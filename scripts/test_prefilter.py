"""Execute SQL extracted from the edited TMDL against deterministic fixtures.

The SQL under test is extracted, not reimplemented. Baseline-date boundary tests
also compare it to an independently frozen copy of the old date SQL. Only the M
parameter-to-predicate helpers are mirrored in Python; this does not execute or
validate the M runtime.
SQLGlot parses Trino and translates to DuckDB. These checks are not live Athena,
ODBC, query-plan, performance, Power BI refresh, or RLS acceptance tests.
"""
from __future__ import annotations

import datetime as dt
import argparse
import calendar
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_packages"))
import duckdb  # noqa: E402
import sqlglot  # noqa: E402

MODEL_NAME = "Project Review - Programme (datalake).SemanticModel"
DEFAULT_MODEL = (ROOT / "after" / MODEL_NAME) if (ROOT / "after").is_dir() else (ROOT / MODEL_NAME)
DEFINITION = Path(os.environ.get("PREFILTER_DEFINITION", str(
    Path(os.environ.get("PREFILTER_MODEL", str(DEFAULT_MODEL))) / "definition"
)))
EXPRESSIONS = DEFINITION / "expressions.tmdl"
TASK = DEFINITION / "tables" / "01 XER_TASK.tmdl"
M_STRING = re.compile(r'"((?:""|[^"])*)"')


def decode_m_literal(literal: str) -> str:
    return literal.replace('""', '"')


def tokens(value: str, *, exclusion: bool = False) -> list[str] | None:
    """Mirror the parameter helpers, not Power Query execution."""
    value = value.strip().upper()
    if exclusion and value in ("", "NONE"):
        return []
    result = sorted({part.strip() for part in value.split(",") if part.strip()})
    if not result and not exclusion:
        raise ValueError("An explicit selection or ALL is required")
    if any(not re.fullmatch(r"[A-Z0-9_]+", part) for part in result):
        raise ValueError("Invalid project code")
    if "ALL" in result:
        if result == ["ALL"] and not exclusion:
            return None
        raise ValueError("ALL must be the sole inclusion token")
    return result


def aliases(codes: list[str] | None) -> list[str] | None:
    if codes is None:
        return None
    result = set(codes)
    for code in codes:
        if re.fullmatch(r"[CJ][0-9]+", code):
            result.add(("J" if code[0] == "C" else "C") + code[1:])
    return sorted(result)


def quoted(values: list[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def scope_sql(selected="ALL", programme="ALL", excluded="NONE", csv_owned=""):
    text = EXPRESSIONS.read_text(encoding="utf-8-sig")
    expression = text.split("expression AthenaScopeSql =", 1)[1].split("\nexpression ", 1)[0]
    programme = programme.strip().upper()
    if programme not in ("C", "T", "ALL"):
        raise ValueError("Invalid programme type")
    project_token = decode_m_literal(re.search(r'ProjectToken = "((?:""|[^"])*)"', expression)[1])
    programme_token = decode_m_literal(re.search(r'ProgrammeToken = "((?:""|[^"])*)"', expression)[1])
    predicate = programme_token + (" IN ('C', 'T')" if programme == "ALL" else " = '" + programme + "'")
    selected_codes = aliases(tokens(selected))
    excluded_codes = aliases(tokens(excluded, exclusion=True))
    csv_codes = aliases(tokens(csv_owned, exclusion=True))
    if selected_codes is not None:
        predicate += " AND " + project_token + " IN (" + quoted(selected_codes) + ")"
    for codes in (excluded_codes, csv_codes):
        if codes:
            predicate += " AND " + project_token + " NOT IN (" + quoted(codes) + ")"
    body = re.search(r"^\s+Sql =\s*\n(.*?)^\s+in\s*$", expression, re.M | re.S)[1]
    fragments = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if "ProgrammeTypeFilter & ProjectFilter & ProjectExclusion & CsvProjectExclusion" in line:
            expected = '"    WHERE " & ProgrammeTypeFilter & ProjectFilter & ProjectExclusion & CsvProjectExclusion & " " &'
            if line != expected:
                raise AssertionError("Unexpected dynamic predicate structure; review extraction")
            fragments.append("    WHERE " + predicate + " ")
        else:
            match = re.fullmatch(r'"((?:""|[^"])*)"\s*&?', line)
            if not match:
                raise AssertionError("Unexpected M SQL expression: " + line)
            fragments.append(decode_m_literal(match[1]))
    return "".join(fragments)


def task_sql(**parameters):
    text = TASK.read_text(encoding="utf-8-sig")
    body = text.split("AthenaScopeSql,", 1)[1].split("\n\t\t\t\t                },", 1)[0]
    fragments = []
    for line in body.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*"((?:""|[^"])*)",?\s*', line)
        if not match:
            raise AssertionError("Unexpected TASK SQL fragment: " + line)
        fragments.append(decode_m_literal(match[1]))
    return scope_sql(**parameters) + " " + " ".join(fragments)


def audit_sql(**parameters):
    text = EXPRESSIONS.read_text(encoding="utf-8-sig")
    expression = text.split("expression AthenaProgrammeSelectionAudit =", 1)[1].split("\nexpression ", 1)[0]
    body = re.search(r"Sql = AthenaScopeSql &\s*\n(.*?)^\s+Result =", expression, re.M | re.S)[1]
    fragments = []
    for line in body.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*"((?:""|[^"])*)"\s*[&,]?\s*', line)
        if not match:
            raise AssertionError("Unexpected audit SQL fragment: " + line)
        fragments.append(decode_m_literal(match[1]))
    return scope_sql(**parameters) + "".join(fragments)


def fn_athena_sql(table_name, projection='t."filename"', **parameters):
    """Extract the real shared native-query wrapper, substituting its inputs."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
        raise ValueError("Invalid fixture table name")
    text = EXPRESSIONS.read_text(encoding="utf-8-sig")
    expression = text.split("expression fnAthenaSource =", 1)[1].split("\nexpression ", 1)[0]
    body = re.search(r"^\s+Sql =\s*\n(.*?)^\s+Result =", expression, re.M | re.S)[1]
    values = {"AthenaScopeSql": scope_sql(**parameters),
              "SelectClause": projection, "SafeTableName": table_name}
    pattern = re.compile(r'\s+|"(?:""|[^"])*"|[A-Za-z_][A-Za-z0-9_]*|[&,]')
    fragments = []
    position = 0
    for match in pattern.finditer(body):
        if match.start() != position:
            raise AssertionError("Unexpected shared native SQL wrapper syntax")
        position = match.end()
        token = match[0]
        if token.isspace() or token in ("&", ","):
            continue
        if token.startswith('"'):
            fragments.append(decode_m_literal(token[1:-1]))
        elif token in values:
            fragments.append(values[token])
        else:
            raise AssertionError("Unexpected shared SQL variable: " + token)
    if position != len(body):
        raise AssertionError("Unparsed shared native SQL wrapper suffix")
    return "".join(fragments)


def duck_sql(sql):
    return sqlglot.parse_one(sql, read="trino").sql(dialect="duckdb")


def task_stage_sql(stage, projection="*", **parameters):
    """Retain actual CTE ASTs through the requested stage, replace final SELECT."""
    parsed = sqlglot.parse_one(task_sql(**parameters), read="trino")
    ctes = []
    for cte in parsed.args["with_"].expressions:
        ctes.append(cte.copy())
        if cte.alias_or_name == stage:
            break
    else:
        raise AssertionError("Unknown TASK stage " + stage)
    result = sqlglot.parse_one("SELECT " + projection + " FROM " + stage, read="trino")
    result.set("with_", sqlglot.exp.With(expressions=ctes))
    return result.sql(dialect="duckdb")


# Frozen pre-optimisation date logic. This is deliberately independent of the
# current TASK CTE extraction, so behavioural changes cannot update both sides.
# The fixture row ID stands in for the old temporary task_row_id; it is not a
# business key and is not introduced into the model SQL under test.
OLD_TASK_DATE_SQL = """
WITH task_named AS (
    SELECT *, fixture_id AS task_row_id FROM boundary_tasks
), non_bl_dates AS (
    SELECT DISTINCT project_group_key, programme_type,
        update_date_filled AS update_date
    FROM task_named
    WHERE is_bl = FALSE AND update_date_filled IS NOT NULL
), update_candidates AS (
    SELECT u.task_row_id,
        CASE WHEN u.update_date_filled IS NULL THEN NULL ELSE
            CAST(date_add('day', -1, date_add('month', 1,
                date_trunc('month', date_add('month', (0 - shift_months),
                    u.update_date_filled)))) AS DATE)
        END AS candidate_update_date,
        ROW_NUMBER() OVER (PARTITION BY u.task_row_id ORDER BY shift_months)
            AS candidate_rank
    FROM task_named u
    CROSS JOIN UNNEST(SEQUENCE(0, CASE WHEN u.is_bl = TRUE
        AND u.update_date_filled IS NOT NULL THEN 240 ELSE 0 END)) AS s(shift_months)
    LEFT JOIN non_bl_dates nbd
        ON nbd.project_group_key = u.project_group_key
        AND nbd.programme_type = u.programme_type
        AND nbd.update_date = CASE WHEN u.update_date_filled IS NULL THEN NULL ELSE
            CAST(date_add('day', -1, date_add('month', 1,
                date_trunc('month', date_add('month', (0 - shift_months),
                    u.update_date_filled)))) AS DATE) END
    WHERE u.is_bl = FALSE OR nbd.update_date IS NULL
), task_prepared AS (
    SELECT u.*, c.candidate_update_date AS update_date
    FROM task_named u
    LEFT JOIN update_candidates c ON c.task_row_id = u.task_row_id
        AND c.candidate_rank = 1
)
SELECT fixture_id, project_group_key, programme_type, filename, is_bl,
    update_date_filled, update_date
FROM task_prepared
ORDER BY fixture_id
"""


def boundary_stage_sql(stage="task_prepared", projection=None):
    """Execute actual date CTEs after substituting typed task_named fixtures.

    This isolates month-collision edge cases from the metadata retention window;
    that window can otherwise hide deliberately colliding fixture snapshots.
    """
    parsed = sqlglot.parse_one(task_sql(), read="trino")
    fixture = sqlglot.parse_one(
        "WITH task_named AS (SELECT * FROM boundary_tasks) SELECT 1", read="trino"
    ).args["with_"].expressions[0]
    ctes = [fixture]
    copying = False
    for cte in parsed.args["with_"].expressions:
        if cte.alias_or_name == "non_bl_dates":
            copying = True
        if copying:
            ctes.append(cte.copy())
        if copying and cte.alias_or_name == stage:
            break
    else:
        raise AssertionError("Actual TASK date stage not found: " + stage)
    if projection is None:
        projection = ("fixture_id, project_group_key, programme_type, filename, "
                      "is_bl, update_date_filled, update_date")
        suffix = " ORDER BY fixture_id"
    else:
        suffix = ""
    result = sqlglot.parse_one("SELECT " + projection + " FROM " + stage + suffix,
                              read="trino")
    result.set("with_", sqlglot.exp.With(expressions=ctes))
    return result.sql(dialect="duckdb")


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(":memory:")
        self.db.execute("CREATE SCHEMA prod_projectcontrols_p6")
        self.db.execute("CREATE SCHEMA prod_projectcontrols_linkedsitereports")
        self.db.execute('CREATE TABLE prod_projectcontrols_p6."02_xer_project" (filename VARCHAR, monthupdate VARCHAR)')
        self.db.execute('CREATE TABLE prod_projectcontrols_linkedsitereports."dbo_project" (projectno VARCHAR, projectname VARCHAR)')
        self.task_columns = sorted(set(re.findall(r't\."([^"]+)"', task_sql())))
        self.db.execute('CREATE TABLE prod_projectcontrols_p6."01_xer_task" (' +
                        ", ".join('"' + col + '" VARCHAR' for col in self.task_columns) + ")")

    def tearDown(self):
        self.db.close()

    def register_project(self, code, name="Registered project"):
        """Insert deliberate registry fixtures, including duplicate/blank rows."""
        self.db.execute('INSERT INTO prod_projectcontrols_linkedsitereports."dbo_project" VALUES (?, ?)',
                        [code, name])

    def add(self, code, tag="2601", month="2026-01-31", programme="C", filename=None,
            register=True):
        filename = filename or f"{code}-{programme}-{tag}_20260101.xer"
        self.db.execute('INSERT INTO prod_projectcontrols_p6."02_xer_project" VALUES (?, ?)', [filename, month])
        if register:
            actual_code = filename.split("-", 1)[0].strip().upper()
            exists = self.db.execute(
                'SELECT COUNT(*) FROM prod_projectcontrols_linkedsitereports."dbo_project" '
                'WHERE projectno = ?', [actual_code]
            ).fetchone()[0]
            if not exists:
                self.register_project(actual_code, "Project " + actual_code)
        return filename

    def keep(self, **parameters):
        return {row[0] for row in self.db.execute(duck_sql(scope_sql(**parameters) + "SELECT filename FROM kept_filenames")).fetchall()}

    def add_task(self, filename, month="2026-01-31", finish="2026-06-01", task_code="A100", **overrides):
        values = {col: None for col in self.task_columns}
        values.update(filename=filename, monthupdate=month, data_date=month,
                      task_code=task_code, task_id_key=filename + "_1", status_code="Not Started",
                      task_type="TT_Task", start="2026-01-01", finish=finish,
                      early_start_date="2026-01-01", early_end_date=finish,
                      late_end_date=finish, remainingduration="10", total_float="0", free_float="0")
        values.update(overrides)
        self.db.execute('INSERT INTO prod_projectcontrols_p6."01_xer_task" VALUES (' +
                        ",".join("?" for _ in self.task_columns) + ")", [values[c] for c in self.task_columns])


class ScopeTests(Fixtures):
    def test_j_whole_history_replaces_c(self):
        self.add("C4017", "2512", "2025-12-31")
        self.add("C4017", "2602", "2026-02-28")
        j1 = self.add("J4017")
        j2 = self.add("J4017", "2603", "2026-03-31")
        self.assertEqual(self.keep(), {j1, j2})

    def test_c_only_retained(self):
        c = self.add("C4017")
        self.assertEqual(self.keep(), {c})

    def test_j_only_retained(self):
        j = self.add("J4017")
        self.assertEqual(self.keep(), {j})

    def test_selected_c_discovers_j(self):
        self.add("C4017")
        j = self.add("J4017")
        self.add("J9999")
        self.assertEqual(self.keep(selected="C4017"), {j})

    def test_selected_j_falls_back_to_c(self):
        c = self.add("C4017")
        self.assertEqual(self.keep(selected="J4017"), {c})

    def test_selected_both_aliases_does_not_duplicate(self):
        self.add("C4017")
        j = self.add("J4017")
        self.assertEqual(self.keep(selected="C4017,J4017,C4017"), {j})

    def test_contract_and_target_are_independent(self):
        j_contract = self.add("J4017", programme="C")
        self.add("C4017", programme="C")
        c_target = self.add("C4017", programme="T")
        self.assertEqual(self.keep(programme="ALL"), {j_contract, c_target})
        self.assertEqual(self.keep(programme="C"), {j_contract})
        self.assertEqual(self.keep(programme="T"), {c_target})

    def test_all_excludes_other_programme_types(self):
        self.add("J4017", programme="X")
        c = self.add("C4017")
        self.assertEqual(self.keep(programme="ALL"), {c})

    def test_excluding_either_alias_excludes_family(self):
        self.add("C4017")
        self.add("J4017")
        other = self.add("C9999")
        for exclusion in ("C4017", "J4017"):
            with self.subTest(exclusion=exclusion):
                self.assertEqual(self.keep(excluded=exclusion), {other})

    def test_csv_ownership_removes_both_aliases(self):
        self.add("C4017")
        self.add("J4017")
        other = self.add("C9999")
        for ownership in ("C4017", "J4017"):
            with self.subTest(ownership=ownership):
                self.assertEqual(self.keep(csv_owned=ownership), {other})

    def test_leading_zeroes_stay_distinct(self):
        self.add("C04017")
        j_zero = self.add("J04017")
        c_plain = self.add("C4017")
        self.assertEqual(self.keep(), {j_zero, c_plain})
        self.assertEqual(self.keep(selected="C04017"), {j_zero})

    def test_numeric_and_nonnumeric_codes_are_exact(self):
        self.add("C4017")
        j = self.add("J4017")
        exact = {self.add(code) for code in ("4017", "X4017", "C4017_OTHER", "J4017_OTHER", "C", "J")}
        self.assertEqual(self.keep(), exact | {j})
        numeric = next(name for name in exact if name.startswith("4017-"))
        self.assertEqual(self.keep(selected="4017"), {numeric})

    def test_case_whitespace_and_original_filename_preserved(self):
        self.add("C4017")
        original = "  j4017 - c -2602_20260201.XER  "
        self.add("unused", month="2026-02-28", filename=original)
        self.assertEqual(self.keep(selected=" c4017 ", programme=" c "), {original})

    def test_revision_precedes_date_and_filename(self):
        self.add("C4017", "BL2-A", "2026-03-31")
        winner = self.add("C4017", "BL2-B", "2026-01-31")
        self.add("C4017", "BL2", "2026-04-30")
        update = self.add("C4017", "2602", "2026-02-28")
        self.assertEqual(self.keep(), {winner, update})

    def test_baseline_number_precedes_revision(self):
        self.add("C4017", "BL9-Z", "2026-02-28")
        winner = self.add("C4017", "BL10", "2026-01-31")
        self.assertEqual(self.keep(), {winner})

    def test_updates_at_or_before_anchor_are_removed(self):
        baseline = self.add("C4017", "BL1", "2026-02-28")
        self.add("C4017", "2601", "2026-01-31")
        self.add("C4017", "2602", "2026-02-28")
        later = self.add("C4017", "2603", "2026-03-31")
        self.assertEqual(self.keep(), {baseline, later})

    def test_underscore_project_code_baseline_revision(self):
        self.add("C_X", "BL1-A", "2026-04-30")
        winner = self.add("C_X", "BL1-B", "2026-01-31")
        self.assertEqual(self.keep(selected="C_X"), {winner})

    def test_null_dates_preserve_existing_keep_policy(self):
        baseline = self.add("C4017", "BL1", "2026-01-31")
        null_update = self.add("C4017", "2602", None)
        invalid_update = self.add("C4017", "2603", "not-a-date")
        self.assertEqual(self.keep(), {baseline, null_update, invalid_update})

    def test_null_anchor_preserves_existing_no_date_filter(self):
        baseline = self.add("C4017", "BL1", None)
        update = self.add("C4017", "2512", "2025-12-31")
        self.assertEqual(self.keep(), {baseline, update})

    def test_duplicate_metadata_does_not_multiply_facts(self):
        name = self.add("J4017")
        self.add("J4017")
        self.add("J4017", month="2026-02-28", filename=name)
        self.add_task(name)
        sql = scope_sql() + 'SELECT t.filename FROM prod_projectcontrols_p6."01_xer_task" t INNER JOIN kept_filenames kf ON t.filename = kf.filename'
        self.assertEqual(self.db.execute(duck_sql(sql)).fetchall(), [(name,)])

    def test_j_older_than_c_still_wins(self):
        self.add("C4017", "2609", "2026-09-30")
        j = self.add("J4017", "2501", "2025-01-31")
        self.assertEqual(self.keep(), {j})

    def test_j_without_baseline_never_reintroduces_c(self):
        self.add("C4017", "BL9", "2026-01-31")
        self.add("C4017", "2603", "2026-03-31")
        j = self.add("J4017", "2602", "2026-02-28")
        self.assertEqual(self.keep(), {j})

    def test_noncanonical_baseline_tag_is_not_baseline(self):
        malformed = self.add("C4017", "BL1FOO", "2026-03-31")
        baseline = self.add("C4017", "BL2", "2026-02-28")
        self.assertEqual(self.keep(), {baseline, malformed})

    def test_empty_scope_has_no_files(self):
        self.add("J4017")
        self.assertEqual(self.keep(selected="C9999"), set())


class ProjectRegistryTests(Fixtures):
    def test_unregistered_example_codes_are_excluded(self):
        self.add("C1046", register=False)
        self.add("C4018B", register=False)
        known = self.add("C4017")
        self.assertEqual(self.keep(), {known})

    def test_blank_null_and_whitespace_names_do_not_register_projects(self):
        for code, name in (("C1001", None), ("C1002", ""), ("C1003", "   ")):
            self.register_project(code, name)
            self.add(code, register=False)
        known = self.add("C4017")
        self.assertEqual(self.keep(), {known})

    def test_c_registry_alias_allows_preferred_j_history(self):
        self.register_project("C4017", "Contract project")
        self.add("C4017", register=False)
        preferred = self.add("J4017", register=False)
        self.assertEqual(self.keep(), {preferred})

    def test_j_registry_alias_allows_c_only_history(self):
        self.register_project("J4017", "Joint venture project")
        c_only = self.add("C4017", register=False)
        self.assertEqual(self.keep(selected="J4017"), {c_only})

    def test_entire_unregistered_cj_family_is_excluded(self):
        self.add("C4017", register=False)
        self.add("J4017", register=False)
        self.assertEqual(self.keep(), set())

    def test_nonnumeric_cj_suffixes_require_exact_registry_codes(self):
        self.register_project("C4018B")
        exact = self.add("C4018B", register=False)
        self.add("J4018B", register=False)
        self.add("C4018", register=False)
        self.assertEqual(self.keep(), {exact})

    def test_registry_identity_preserves_leading_zeroes(self):
        self.register_project("C04017")
        zero_prefixed = self.add("J04017", register=False)
        self.add("J4017", register=False)
        self.assertEqual(self.keep(), {zero_prefixed})

    def test_bare_numeric_registry_code_does_not_register_cj_family(self):
        self.register_project("4017")
        numeric = self.add("4017", register=False)
        self.add("C4017", register=False)
        self.add("J4017", register=False)
        self.assertEqual(self.keep(), {numeric})

    def test_other_prefix_registry_code_is_exact(self):
        self.register_project("X4017")
        exact = self.add("X4017", register=False)
        self.add("C4017", register=False)
        self.assertEqual(self.keep(), {exact})

    def test_filename_case_and_whitespace_match_canonical_registry_key(self):
        self.register_project("C4017", "  Registered name  ")
        original = " j4017 - c -2601_20260101.XER "
        self.add("unused", filename=original, register=False)
        self.add_task(original)
        self.assertEqual(self.keep(), {original})
        self.assertEqual(self.db.execute(task_stage_sql(
            "task_named", "filename, project_name"
        )).fetchall(), [(original, "Registered name")])

    def test_noncanonical_registry_keys_do_not_bypass_exact_metadata_lookup(self):
        self.register_project("c4017", "Lowercase registry key")
        self.register_project(" C4017 ", "Padded registry key")
        self.add("C4017", register=False)
        self.add("J4017", register=False)
        self.assertEqual(self.keep(), set())

    def test_duplicate_registry_rows_do_not_multiply_kept_or_raw_tasks(self):
        self.register_project("C4017", "Name one")
        self.register_project("C4017", "Name one")
        self.register_project("J4017", "Name two")
        name = self.add("J4017", register=False)
        self.add_task(name)
        kept = self.db.execute(duck_sql(scope_sql() +
            "SELECT filename FROM kept_filenames")).fetchall()
        self.assertEqual(kept, [(name,)])
        self.assertEqual(self.db.execute(task_stage_sql(
            "task_raw", "filename"
        )).fetchall(), [(name,)])

    def test_explicit_unregistered_selection_returns_zero(self):
        self.add("C1046", register=False)
        self.add("C4017")
        self.assertEqual(self.keep(selected="C1046"), set())

    def test_audit_preserves_rejected_filename_and_reason(self):
        original = " c1046-C-2601_20260101.XER "
        self.add("unused", filename=original, register=False)
        self.add("J1046", register=False)
        rows = self.db.execute(duck_sql(audit_sql(selected="C1046"))).fetchall()
        self.assertEqual({row[0] for row in rows}, {original, "J1046-C-2601_20260101.xer"})
        self.assertEqual({row[-1] for row in rows}, {"NO_NAMED_PROJECT_MATCH"})
        self.assertEqual({row[5] for row in rows}, {None})

    def test_audit_distinguishes_unregistered_from_existing_selection_reasons(self):
        unknown = self.add("C1046", register=False)
        c = self.add("C4017", "2603", "2026-03-31")
        old = self.add("J4017", "BL1", "2025-01-31")
        baseline = self.add("J4017", "BL2", "2026-01-31")
        update = self.add("J4017", "2602", "2026-02-28")
        rows = self.db.execute(duck_sql(audit_sql())).fetchall()
        self.assertEqual({row[0]: row[-1] for row in rows}, {
            unknown: "NO_NAMED_PROJECT_MATCH", c: "J_HISTORY_PREFERRED",
            old: "OUTSIDE_BASELINE_WINDOW", baseline: "KEPT", update: "KEPT",
        })

    def test_blank_j_name_uses_named_c_alias_without_losing_j_preference(self):
        self.register_project("J4017", "   ")
        self.register_project("C4017", "Named C alias")
        self.add("C4017", register=False)
        preferred = self.add("J4017", register=False)
        self.add_task(preferred)
        self.assertEqual(self.keep(), {preferred})
        self.assertEqual(self.db.execute(task_stage_sql(
            "task_named", "filename, project_name"
        )).fetchall(), [(preferred, "Named C alias")])

    def test_empty_registry_yields_no_contract_or_target_rows(self):
        self.add("C4017", programme="C", register=False)
        self.add("J4017", programme="T", register=False)
        for programme in ("C", "T", "ALL"):
            with self.subTest(programme=programme):
                self.assertEqual(self.keep(programme=programme), set())

    def test_blank_null_registry_codes_do_not_register_other_codes(self):
        self.register_project(None, "Named but missing code")
        self.register_project(" ", "Named but blank code")
        self.add("C1046", register=False)
        self.assertEqual(self.keep(), set())

    def test_all_ten_native_consumers_keep_the_same_registered_snapshots(self):
        shared_tables = set()
        for path in (DEFINITION / "tables").glob("*.tmdl"):
            shared_tables.update(re.findall(r'fnAthenaSource\s*\(\s*"([A-Za-z0-9_]+)"',
                                            path.read_text(encoding="utf-8-sig")))
        self.assertEqual(shared_tables, {
            "02_xer_project", "03_xer_projwbs", "06_xer_predecessor",
            "07_xer_actvtype", "08_xer_actvcode", "09_xer_taskactv",
            "10_xer_calendar", "12_xer_rsrc", "15_xer_resource_distribution",
        })
        old = self.add("C4017", "BL1", "2025-01-31")
        baseline = self.add("C4017", "BL2", "2026-01-31")
        update = self.add("C4017", "2602", "2026-02-28")
        unknown = self.add("C1046", "2603", "2026-03-31", register=False)
        filenames = [old, baseline, update, unknown]
        for table in shared_tables:
            if table != "02_xer_project":
                self.db.execute('CREATE TABLE prod_projectcontrols_p6."' + table + '" (filename VARCHAR)')
                self.db.executemany('INSERT INTO prod_projectcontrols_p6."' + table + '" VALUES (?)',
                                    [(name,) for name in filenames])
            with self.subTest(consumer=table):
                rows = self.db.execute(duck_sql(fn_athena_sql(table))).fetchall()
                self.assertEqual(sorted(rows), sorted([(baseline,), (update,)]))
        for name in filenames:
            self.add_task(name)
        rows = self.db.execute(task_stage_sql("task_raw", "filename")).fetchall()
        self.assertEqual(sorted(rows), sorted([(baseline,), (update,)]))
        self.assertEqual(len(shared_tables) + 1, 10)


class TaskTests(Fixtures):
    def test_complete_task_sql_parses_as_trino(self):
        sql = task_sql()
        parsed = sqlglot.parse_one(sql, read="trino")
        self.assertIsInstance(parsed, sqlglot.exp.Select)
        names = [cte.alias_or_name for cte in parsed.args["with_"].expressions]
        self.assertIn("preferred_projects", names)
        self.assertIn("task_snapshot_prev", names)
        self.assertIn("network_calcs", names)
        self.assertGreater(len(parsed.expressions), 20)

    def test_task_raw_only_preferred_history(self):
        c = self.add("C4017")
        j = self.add("J4017")
        self.add_task(c)
        self.add_task(j)
        self.assertEqual(self.db.execute(task_stage_sql("task_raw", "filename, raw_project_code, project_identity")).fetchall(),
                         [(j, "J4017", "CJ:4017")])

    def test_same_project_name_does_not_merge_baseline_or_previous(self):
        self.db.executemany('INSERT INTO prod_projectcontrols_linkedsitereports."dbo_project" VALUES (?, ?)',
                            [("C1001", "Shared name"), ("C1002", "Shared name")])
        for code, january, february in (("C1001", "2026-04-01", "2026-05-01"),
                                        ("C1002", "2026-08-01", "2026-09-01")):
            one = self.add(code, "2601", "2026-01-31")
            two = self.add(code, "2602", "2026-02-28")
            self.add_task(one, "2026-01-31", january)
            self.add_task(two, "2026-02-28", february)
        rows = self.db.execute(task_stage_sql("task_joined", "project_group_key, update_date, baseline_finish, previous_task_finish")).fetchall()
        feb = {key: (baseline, previous) for key, update, baseline, previous in rows if update == dt.date(2026, 2, 28)}
        self.assertEqual(feb, {
            "CJ:1001:C": (dt.date(2026, 4, 1), dt.date(2026, 4, 1)),
            "CJ:1002:C": (dt.date(2026, 8, 1), dt.date(2026, 8, 1)),
        })

    def test_contract_and_target_task_history_stay_separate(self):
        for programme, finish in (("C", "2026-04-01"), ("T", "2026-08-01")):
            one = self.add("C1001", "2601", "2026-01-31", programme)
            two = self.add("C1001", "2602", "2026-02-28", programme)
            self.add_task(one, "2026-01-31", finish)
            self.add_task(two, "2026-02-28", "2026-10-01")
        rows = self.db.execute(task_stage_sql("task_joined", "project_group_key, update_date, baseline_finish, previous_task_finish")).fetchall()
        feb = {key: (baseline, previous) for key, update, baseline, previous in rows if update == dt.date(2026, 2, 28)}
        self.assertEqual(feb, {
            "CJ:1001:C": (dt.date(2026, 4, 1), dt.date(2026, 4, 1)),
            "CJ:1001:T": (dt.date(2026, 8, 1), dt.date(2026, 8, 1)),
        })

    def test_task_baseline_revision_is_recognised_and_used(self):
        old = self.add("C1001", "BL1-A", "2026-01-31")
        baseline = self.add("C1001", "BL1-B", "2026-01-31")
        update = self.add("C1001", "2602", "2026-02-28")
        self.add_task(old, finish="2026-12-01")
        self.add_task(baseline, finish="2026-04-01")
        self.add_task(update, "2026-02-28", "2026-05-01")
        rows = self.db.execute(task_stage_sql("task_joined", "filename, is_bl, baseline_finish, previous_task_finish")).fetchall()
        self.assertEqual({row[0] for row in rows}, {baseline, update})
        self.assertIn((baseline, True, dt.date(2026, 4, 1), None), rows)
        self.assertIn((update, False, dt.date(2026, 4, 1), dt.date(2026, 4, 1)), rows)

    def test_j_preference_prevents_c_baseline_leak_into_task(self):
        c = self.add("C1001", "BL9", "2026-01-31")
        j = self.add("J1001", "2602", "2026-02-28")
        self.add_task(c, finish="2026-12-01")
        self.add_task(j, "2026-02-28", "2026-04-01")
        rows = self.db.execute(task_stage_sql("task_joined", "filename, baseline_finish, previous_task_finish")).fetchall()
        self.assertEqual(rows, [(j, dt.date(2026, 4, 1), None)])


class BaselineDateBoundaryTests(unittest.TestCase):
    """Compare the new extracted mapping to the old per-row candidate logic."""

    def setUp(self):
        self.db = duckdb.connect(":memory:")
        self.db.execute("""CREATE TABLE boundary_tasks (
            fixture_id INTEGER, project_group_key VARCHAR, programme_type VARCHAR,
            filename VARCHAR, is_bl BOOLEAN, update_date_filled DATE
        )""")
        self.next_fixture_id = 1

    def tearDown(self):
        self.db.close()

    def row(self, date, baseline=True, project="CJ:4017", programme="C",
            filename="same-source.xer", fixture_id=None):
        if fixture_id is None:
            fixture_id = self.next_fixture_id
            self.next_fixture_id += 1
        self.db.execute("INSERT INTO boundary_tasks VALUES (?, ?, ?, ?, ?, ?)",
                        [fixture_id, project + ":" + programme, programme,
                         filename, baseline, date])
        return fixture_id

    def compare_with_old(self):
        old = self.db.execute(duck_sql(OLD_TASK_DATE_SQL)).fetchall()
        actual = self.db.execute(boundary_stage_sql()).fetchall()
        self.assertEqual(actual, old)
        return actual

    def assert_date(self, rows, fixture_id, expected):
        matching = [row[-1] for row in rows if row[0] == fixture_id]
        expected_date = dt.date.fromisoformat(expected) if expected else None
        self.assertTrue(matching, "Fixture row disappeared")
        self.assertEqual(matching, [expected_date] * len(matching))

    @staticmethod
    def month_at_shift(year, month, shift):
        """Build input occupancy fixtures using calendar month ends."""
        absolute_month = year * 12 + month - 1 - shift
        shifted_year, zero_month = divmod(absolute_month, 12)
        shifted_month = zero_month + 1
        return dt.date(shifted_year, shifted_month,
                       calendar.monthrange(shifted_year, shifted_month)[1])

    def test_no_collision_retains_baseline_month(self):
        baseline = self.row("2026-01-31")
        update = self.row("2026-02-28", baseline=False)
        rows = self.compare_with_old()
        self.assert_date(rows, baseline, "2026-01-31")
        self.assert_date(rows, update, "2026-02-28")

    def test_consecutive_occupied_months_choose_first_gap(self):
        baseline = self.row("2026-03-31")
        for month in ("2026-03-31", "2026-02-28", "2026-01-31"):
            self.row(month, baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2025-12-31")

    def test_nonconsecutive_occupied_months_do_not_skip_a_gap(self):
        baseline = self.row("2026-03-31")
        self.row("2026-03-31", baseline=False)
        self.row("2026-01-31", baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2026-02-28")

    def test_leap_year_collision_lands_on_february_29(self):
        baseline = self.row("2024-03-31")
        self.row("2024-03-31", baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2024-02-29")

    def test_year_boundary_collision_lands_on_december_31(self):
        baseline = self.row("2026-01-31")
        self.row("2026-01-31", baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2025-12-31")

    def test_month_length_changes_preserve_month_end(self):
        baseline = self.row("2026-05-31")
        self.row("2026-05-31", baseline=False)
        self.row("2026-04-30", baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2026-03-31")

    def test_all_241_months_occupied_produces_null(self):
        baseline = self.row("2026-01-31")
        for shift in range(241):
            self.row(self.month_at_shift(2026, 1, shift), baseline=False)
        self.assert_date(self.compare_with_old(), baseline, None)

    def test_last_allowed_shift_240_is_available(self):
        baseline = self.row("2026-01-31")
        for shift in range(240):
            self.row(self.month_at_shift(2026, 1, shift), baseline=False)
        self.assert_date(self.compare_with_old(), baseline, "2006-01-31")

    def test_null_dates_stay_null_without_creating_candidates(self):
        baseline = self.row(None)
        update = self.row(None, baseline=False)
        rows = self.compare_with_old()
        self.assert_date(rows, baseline, None)
        self.assert_date(rows, update, None)
        self.assertEqual(self.db.execute(boundary_stage_sql(
            "baseline_date_candidates", "COUNT(*)")).fetchone()[0], 0)

    def test_multiple_dates_in_same_filename_get_distinct_mappings(self):
        january = self.row("2026-01-31")
        february = self.row("2026-02-28")
        self.row("2026-01-31", baseline=False)
        rows = self.compare_with_old()
        self.assert_date(rows, january, "2025-12-31")
        self.assert_date(rows, february, "2026-02-28")

    def test_duplicate_activity_rows_preserve_output_multiplicity(self):
        first = self.row("2026-01-31")
        second = self.row("2026-01-31")
        self.row("2026-01-31", baseline=False)
        rows = self.compare_with_old()
        self.assertEqual(len(rows), 3)
        self.assert_date(rows, first, "2025-12-31")
        self.assert_date(rows, second, "2025-12-31")

    def test_metadata_join_duplicates_with_same_old_id_are_preserved(self):
        baseline = self.row("2026-01-31")
        self.row("2026-01-31", fixture_id=baseline)
        self.row("2026-01-31", baseline=False)
        rows = self.compare_with_old()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row[0] == baseline for row in rows), 2)
        self.assert_date(rows, baseline, "2025-12-31")

    def test_other_project_occupancy_does_not_shift_baseline(self):
        baseline = self.row("2026-01-31", project="CJ:4017")
        self.row("2026-01-31", baseline=False, project="CJ:9999")
        self.assert_date(self.compare_with_old(), baseline, "2026-01-31")

    def test_contract_and_target_occupancy_are_independent(self):
        contract = self.row("2026-01-31", programme="C")
        target = self.row("2026-01-31", programme="T")
        self.row("2026-01-31", baseline=False, programme="C")
        rows = self.compare_with_old()
        self.assert_date(rows, contract, "2025-12-31")
        self.assert_date(rows, target, "2026-01-31")

    def test_no_baselines_leaves_update_dates_unchanged(self):
        first = self.row("2026-01-31", baseline=False)
        second = self.row("2026-02-28", baseline=False)
        rows = self.compare_with_old()
        self.assert_date(rows, first, "2026-01-31")
        self.assert_date(rows, second, "2026-02-28")
        self.assertEqual(self.db.execute(boundary_stage_sql(
            "baseline_date_candidates", "COUNT(*)")).fetchone()[0], 0)

    def test_empty_input_returns_empty_mapping_and_output(self):
        self.assertEqual(self.compare_with_old(), [])
        self.assertEqual(self.db.execute(boundary_stage_sql(
            "baseline_update_dates", "COUNT(*)")).fetchone()[0], 0)

    def test_candidate_count_depends_on_distinct_dates_not_activity_count(self):
        for _ in range(1000):
            self.row("2026-01-31")
        for _ in range(100):
            self.row("2026-02-28", baseline=False)
        self.assertEqual(self.db.execute(boundary_stage_sql(
            "baseline_date_candidates", "COUNT(*)")).fetchone()[0], 241)
        self.row("2026-02-28")
        self.assertEqual(self.db.execute(boundary_stage_sql(
            "baseline_date_candidates", "COUNT(*)")).fetchone()[0], 482)

    def test_actual_date_pipeline_has_no_temporary_row_id_or_row_number(self):
        actual_sql = task_sql()
        self.assertNotRegex(actual_sql, r"\btask_row_id\b")
        parsed = sqlglot.parse_one(actual_sql, read="trino")
        checked = {"task_raw", "baseline_dates", "baseline_date_candidates",
                   "baseline_update_dates", "task_prepared"}
        found = set()
        for cte in parsed.args["with_"].expressions:
            if cte.alias_or_name in checked:
                found.add(cte.alias_or_name)
                self.assertFalse(list(cte.find_all(sqlglot.exp.RowNumber)),
                                 "Unnecessary row-number sort in " + cte.alias_or_name)
        self.assertEqual(found, checked)


class BaselineDateIntegrationTests(Fixtures):
    def test_colliding_baseline_date_and_duplicate_tasks_keep_comparisons(self):
        baseline = self.add("C1001", "BL1", "2026-01-15")
        update = self.add("C1001", "2601", "2026-01-31")
        self.add_task(baseline, "2026-01-15", "2026-04-01")
        self.add_task(baseline, "2026-01-15", "2026-04-01")
        self.add_task(update, "2026-01-31", "2026-05-01")
        rows = self.db.execute(task_stage_sql(
            "task_joined", "filename, update_date, baseline_finish, previous_task_finish"
        )).fetchall()
        expected_baseline = (baseline, dt.date(2025, 12, 31), dt.date(2026, 4, 1), None)
        expected_update = (update, dt.date(2026, 1, 31),
                           dt.date(2026, 4, 1), dt.date(2026, 4, 1))
        self.assertEqual(rows.count(expected_baseline), 2)
        self.assertEqual(rows.count(expected_update), 1)
        self.assertEqual(len(rows), 3)

    def test_kept_filename_tags_make_is_bl_nonnull(self):
        for code, tag in (("C1001", "BL1"), ("C1002", ""),
                          ("C1003", "UNKNOWN"), ("C1004", "2601")):
            name = self.add(code, tag)
            self.add_task(name)
        rows = self.db.execute(task_stage_sql(
            "task_update_parts", "raw_project_code, is_bl"
        )).fetchall()
        self.assertEqual(dict(rows), {
            "C1001": True, "C1002": False, "C1003": False, "C1004": False,
        })


class AuditTests(Fixtures):
    def test_actual_audit_sql_explains_all_three_selection_outcomes(self):
        c = self.add("C4017", "2609", "2026-09-30")
        original = " j4017-C-BL1_20250101.XER "
        old_j = self.add("unused", "BL1", "2025-01-31", filename=original)
        baseline = self.add("J4017", "BL2", "2026-01-31")
        update = self.add("J4017", "2602", "2026-02-28")
        self.add("J9999")
        rows = self.db.execute(duck_sql(audit_sql(selected="C4017", programme="C"))).fetchall()
        self.assertEqual({row[0]: row[-1] for row in rows}, {
            c: "J_HISTORY_PREFERRED",
            old_j: "OUTSIDE_BASELINE_WINDOW",
            baseline: "KEPT",
            update: "KEPT",
        })
        self.assertEqual(len(rows), 4)
        self.assertEqual({row[2] for row in rows}, {"CJ:4017"})
        self.assertEqual({row[3] for row in rows}, {"C"})
        self.assertEqual({row[5] for row in rows}, {"J4017"})


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser(add_help=False)
    argument_parser.add_argument("--definition", type=Path,
                                 help="Path to semantic model definition directory")
    arguments, unittest_arguments = argument_parser.parse_known_args()
    if arguments.definition is not None:
        DEFINITION = arguments.definition
        EXPRESSIONS = DEFINITION / "expressions.tmdl"
        TASK = DEFINITION / "tables" / "01 XER_TASK.tmdl"
    sys.argv = [sys.argv[0], *unittest_arguments]
    unittest.main(verbosity=2)

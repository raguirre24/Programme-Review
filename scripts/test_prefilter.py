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
CALENDAR = DEFINITION / "tables" / "11 XER_CALENDAR_DETAILED.tmdl"
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


def update_limit(value: str) -> int | None:
    """Mirror the LatestUpdateCount validation: ALL, or a whole number from 1 to 999."""
    value = value.strip().upper()
    if value == "ALL":
        return None
    if re.fullmatch(r"[0-9]{1,3}", value) and int(value) >= 1:
        return int(value)
    raise ValueError("LatestUpdateCount must be ALL or a whole number from 1 to 999")


def scope_sql(selected="ALL", programme="ALL", excluded="NONE", csv_owned="", latest_updates="ALL"):
    text = EXPRESSIONS.read_text(encoding="utf-8-sig")
    expression = text.split("expression AthenaScopeSql =", 1)[1].split("\nexpression ", 1)[0]
    programme = programme.strip().upper()
    if programme not in ("C", "T", "ALL"):
        raise ValueError("Invalid programme type")
    project_token = decode_m_literal(re.search(r'ProjectToken = "((?:""|[^"])*)"', expression)[1])
    programme_token = decode_m_literal(re.search(r'ProgrammeToken = "((?:""|[^"])*)"', expression)[1])
    limit = update_limit(latest_updates)
    limit_prefix = decode_m_literal(re.search(
        r'UpdateLimitFilter = if UpdateLimit = null then "TRUE" else "((?:""|[^"])*)" & Text\.From\(UpdateLimit\)',
        expression)[1])
    limit_predicate = "TRUE" if limit is None else limit_prefix + str(limit)
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
        elif "UpdateLimitFilter" in line:
            if line != '"    WHERE " & UpdateLimitFilter & " " &':
                raise AssertionError("Unexpected update-limit predicate structure; review extraction")
            fragments.append("    WHERE " + limit_predicate + " ")
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


def calendar_sql(**parameters):
    """Extract table 11's native SQL (scope CTEs plus the exception-date alignment vote)."""
    text = CALENDAR.read_text(encoding="utf-8-sig")
    body = text.split("AthenaScopeSql,", 1)[1].split("\n\t\t\t\t                },", 1)[0]
    fragments = []
    for line in body.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*"((?:""|[^"])*)",?\s*', line)
        if not match:
            raise AssertionError("Unexpected CALENDAR SQL fragment: " + line)
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

    def test_6012_exception_prefers_c_over_j_when_both_exist(self):
        c = self.add("C6012", "2609", "2026-09-30")
        self.add("J6012", "2609", "2026-09-30")
        self.assertEqual(self.keep(), {c})

    def test_6012_exception_keeps_j_when_only_j_exists(self):
        j = self.add("J6012", "2609", "2026-09-30")
        self.assertEqual(self.keep(), {j})

    def test_6012_exception_keeps_c_when_only_c_exists(self):
        c = self.add("C6012", "2609", "2026-09-30")
        self.assertEqual(self.keep(), {c})

    def test_6012_exception_contract_and_target_are_independent(self):
        c_contract = self.add("C6012", "2609", "2026-09-30", programme="C")
        self.add("J6012", "2609", "2026-09-30", programme="C")
        j_target = self.add("J6012", "2609", "2026-09-30", programme="T")
        self.assertEqual(self.keep(), {c_contract, j_target})


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

    def test_6012_audit_shows_c_history_preferred(self):
        c = self.add("C6012", "2609", "2026-09-30")
        j = self.add("J6012", "2609", "2026-09-30")
        rows = self.db.execute(duck_sql(audit_sql())).fetchall()
        reasons = {row[0]: row[-1] for row in rows}
        self.assertEqual(reasons[c], "KEPT")
        self.assertEqual(reasons[j], "C_HISTORY_PREFERRED")

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

    def test_all_eleven_native_consumers_keep_the_same_registered_snapshots(self):
        shared_tables = set()
        for path in (DEFINITION / "tables").glob("*.tmdl"):
            shared_tables.update(re.findall(r'fnAthenaSource\s*\(\s*"([A-Za-z0-9_]+)"',
                                            path.read_text(encoding="utf-8-sig")))
        self.assertEqual(shared_tables, {
            "02_xer_project", "03_xer_projwbs", "06_xer_predecessor",
            "07_xer_actvtype", "08_xer_actvcode", "09_xer_taskactv",
            "10_xer_calendar", "12_xer_rsrc",
            "15_xer_resource_distribution",
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
        CalendarAlignmentTests.create_calendar_table(self.db)
        for name in filenames:
            CalendarAlignmentTests.insert_calendar(self.db, name, "1", [8] * 5 + [0, 0], {})
        rows = self.db.execute(duck_sql(calendar_sql())).fetchall()
        self.assertEqual({row[7].rsplit(".", 1)[0] for row in rows}, {baseline, update})
        self.assertEqual(len(rows), 14)
        self.assertEqual(len(shared_tables) + 2, 11)


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

    def test_6012_task_named_prefers_c_project_name(self):
        self.register_project("C6012", "Named C6012")
        self.register_project("J6012", "Named J6012")
        c = self.add("C6012", "2609", "2026-09-30", register=False)
        self.add("J6012", "2609", "2026-09-30", register=False)
        self.add_task(c)
        self.assertEqual(self.db.execute(task_stage_sql(
            "task_named", "filename, project_name"
        )).fetchall(), [(c, "Named C6012")])


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


class CalendarAlignmentTests(Fixtures):
    """Table 11's per-file vote on dated-exception alignment (the Athena feed stores them a day early).

    Fixtures write each exception at true date + stored_offset with day_of_week_num derived from the stored date,
    exactly as the faulty feed does, then check the ExceptionDateShiftDays the SQL returns for every row.
    """

    COLUMNS = ("clndr_name", "clndr_type", "date", "day_of_week", "working_day", "work_hours",
               "exception_type", "clndr_id_key", "monthupdate", "day_of_week_num", "working_day_int", "filename")
    DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    FIVE_DAY = [8, 8, 8, 8, 8, 0, 0]

    @classmethod
    def create_calendar_table(cls, db):
        db.execute('CREATE TABLE prod_projectcontrols_p6."11_xer_calendar_detailed" (' +
                   ", ".join('"' + col + '" VARCHAR' for col in cls.COLUMNS) + ")")

    @classmethod
    def insert_calendar(cls, db, filename, calendar_id, week_hours, exceptions, stored_offset=0,
                        duplicate_rules=False):
        """Seven weekday rules plus dated exceptions {true_date: hours}, all values as text like the feed."""
        key = f"{filename}.{calendar_id}"
        rows = []
        for number, hours in enumerate(week_hours, start=1):
            rule = ("Calendar " + calendar_id, "Project", None, cls.DAY_NAMES[number - 1],
                    "Y" if hours else "N", str(float(hours)), "Standard", key, "2026-01-31",
                    str(number), "1" if hours else "0", filename)
            rows.extend([rule, rule] if duplicate_rules else [rule])
        for true_date, hours in exceptions.items():
            stored = true_date + dt.timedelta(days=stored_offset)
            rows.append(("Calendar " + calendar_id, "Project", stored.isoformat(), cls.DAY_NAMES[stored.weekday()],
                         "Y" if hours else "N", str(float(hours)),
                         "Exception - Working" if hours else "Exception - Non-Working", key, "2026-01-31",
                         str(stored.isoweekday()), "1" if hours else "0", filename))
        db.executemany('INSERT INTO prod_projectcontrols_p6."11_xer_calendar_detailed" VALUES (' +
                       ", ".join("?" * len(cls.COLUMNS)) + ")", rows)
        return key

    @staticmethod
    def shutdown(first, last, weekdays=range(5)):
        """Non-working exceptions on the listed weekdays (Monday = 0) between two true dates."""
        days = (last - first).days + 1
        return {first + dt.timedelta(days=i): 0 for i in range(days)
                if (first + dt.timedelta(days=i)).weekday() in weekdays}

    def setUp(self):
        super().setUp()
        self.create_calendar_table(self.db)
        self.winter = self.shutdown(dt.date(2027, 4, 19), dt.date(2027, 10, 1))
        self.winter[dt.date(2027, 3, 26)] = 0  # Good Friday
        self.winter[dt.date(2027, 11, 2)] = 0  # Melbourne Cup (Tuesday)

    def shifts(self):
        rows = self.db.execute(duck_sql(calendar_sql())).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row[7], set()).add(row[12])
        return result, rows

    def test_exceptions_stored_a_day_early_move_a_day_later(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, self.winter, stored_offset=-1)
        shifts, rows = self.shifts()
        self.assertEqual(shifts, {key: {1}})
        self.assertEqual(len(rows), 7 + len(self.winter))
        # The SQL only votes: dates, weekday numbers and names leave Athena unchanged for M to move.
        stored = {row[2] for row in rows if row[2] is not None}
        self.assertEqual(stored, {(d - dt.timedelta(days=1)).isoformat() for d in self.winter})

    def test_aligned_file_keeps_its_dates(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, self.winter)
        self.assertEqual(self.shifts()[0], {key: {0}})

    def test_exceptions_stored_a_day_late_move_a_day_earlier(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, self.winter, stored_offset=1)
        self.assertEqual(self.shifts()[0], {key: {-1}})

    def test_six_day_calendar_with_alternate_saturday_exceptions(self):
        name = self.add("C4017", "2602", "2026-02-28")
        exceptions = self.shutdown(dt.date(2027, 1, 2), dt.date(2027, 12, 31), weekdays={5})
        exceptions = {d: 0 for i, d in enumerate(sorted(exceptions)) if i % 2 == 0}
        exceptions.update(self.winter)
        key = self.insert_calendar(self.db, name, "1007", [8] * 6 + [0], exceptions, stored_offset=-1)
        self.assertEqual(self.shifts()[0], {key: {1}})

    def test_snapshots_vote_independently(self):
        early = self.add("C4017", "2602", "2026-02-28")
        fixed = self.add("C4017", "2603", "2026-03-31")
        early_key = self.insert_calendar(self.db, early, "644", self.FIVE_DAY, self.winter, stored_offset=-1)
        fixed_key = self.insert_calendar(self.db, fixed, "644", self.FIVE_DAY, self.winter)
        self.assertEqual(self.shifts()[0], {early_key: {1}, fixed_key: {0}})

    def test_file_without_evidence_takes_the_scope_vote(self):
        voting = self.add("C4017", "2602", "2026-02-28")
        silent = self.add("C1001", "2602", "2026-02-28")
        voting_key = self.insert_calendar(self.db, voting, "644", self.FIVE_DAY, self.winter, stored_offset=-1)
        # Every day works on a 7-day calendar, so its non-working exceptions never repeat a rule: no evidence.
        silent_key = self.insert_calendar(self.db, silent, "652", [8] * 7, self.winter, stored_offset=-1)
        self.assertEqual(self.shifts()[0], {voting_key: {1}, silent_key: {1}})

    def test_no_evidence_anywhere_keeps_source_dates(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "652", [8] * 7, self.winter, stored_offset=-1)
        self.assertEqual(self.shifts()[0], {key: {0}})

    def test_weak_evidence_is_not_a_clear_winner(self):
        name = self.add("C4017", "2602", "2026-02-28")
        few = {dt.date(2027, 4, 19): 0, dt.date(2027, 4, 26): 0, dt.date(2027, 5, 3): 0}  # three Mondays
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, few, stored_offset=-1)
        self.assertEqual(self.shifts()[0], {key: {0}})

    def test_duplicate_weekday_rules_do_not_vote(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, self.winter, stored_offset=-1,
                                   duplicate_rules=True)
        shifts, rows = self.shifts()
        self.assertEqual(shifts, {key: {0}})
        self.assertEqual(len(rows), 14 + len(self.winter))

    def test_invalid_and_blank_key_rows_are_kept_and_follow_their_file(self):
        name = self.add("C4017", "2602", "2026-02-28")
        key = self.insert_calendar(self.db, name, "644", self.FIVE_DAY, self.winter, stored_offset=-1)
        self.db.executemany('INSERT INTO prod_projectcontrols_p6."11_xer_calendar_detailed" VALUES (' +
                            ", ".join("?" * len(self.COLUMNS)) + ")", [
                                ("Bad", "Project", "2027-06-01", "Tuesday", None, None, "Exception - Invalid",
                                 key, "2026-01-31", "2", None, name),
                                ("Orphan", "Project", "2027-06-02", "Wednesday", "N", "0", "Exception - Non-Working",
                                 "", "2026-01-31", "3", "0", name),
                            ])
        shifts, rows = self.shifts()
        self.assertEqual(shifts, {key: {1}, "": {1}})
        self.assertEqual(len(rows), 9 + len(self.winter))

    def test_unregistered_snapshots_are_excluded(self):
        kept = self.add("C4017", "2602", "2026-02-28")
        dropped = self.add("C1046", "2602", "2026-02-28", register=False)
        kept_key = self.insert_calendar(self.db, kept, "644", self.FIVE_DAY, self.winter, stored_offset=-1)
        self.insert_calendar(self.db, dropped, "644", self.FIVE_DAY, self.winter)
        self.assertEqual(set(self.shifts()[0]), {kept_key})

    def test_vote_thresholds_match_the_csv_m_function(self):
        sql = calendar_sql()
        self.assertIn("best_repeats * 2 <= runner_up_repeats AND runner_up_repeats - best_repeats >= 10", sql)
        m_text = EXPRESSIONS.read_text(encoding="utf-8-sig").split("expression fnXerCalendarDetectExceptionShift =", 1)[1]
        self.assertIn("Decided = Best * 2 <= RunnerUp and RunnerUp - Best >= 10", m_text.split("\nexpression ", 1)[0])


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


class UpdateLimitTests(Fixtures):
    """LatestUpdateCount: the anchor baseline plus the N latest dated updates per project and programme type."""

    def history(self, code="C4017", updates=5, programme="C"):
        """Add a BL1 anchor dated December 2025 and monthly 2026 updates after it, oldest first."""
        baseline = self.add(code, "BL1", "2025-12-31", programme)
        names = []
        for month in range(1, updates + 1):
            day = calendar.monthrange(2026, month)[1]
            names.append(self.add(code, f"26{month:02d}", f"2026-{month:02d}-{day:02d}", programme))
        return baseline, names

    def test_limit_keeps_baseline_and_latest_updates(self):
        baseline, updates = self.history(updates=5)
        self.assertEqual(self.keep(latest_updates="3"), {baseline, *updates[-3:]})
        self.assertEqual(self.keep(latest_updates="1"), {baseline, updates[-1]})

    def test_limit_above_available_history_loads_what_exists(self):
        baseline, updates = self.history(updates=3)
        for value in ("4", "5", "999"):
            with self.subTest(limit=value):
                self.assertEqual(self.keep(latest_updates=value), {baseline, *updates})
        self.assertEqual(self.keep(latest_updates="5"), self.keep())

    def test_all_and_padded_values_are_case_and_whitespace_insensitive(self):
        baseline, updates = self.history(updates=4)
        self.assertEqual(self.keep(latest_updates=" all "), self.keep())
        self.assertEqual(self.keep(latest_updates="ALL"), {baseline, *updates})
        self.assertEqual(self.keep(latest_updates=" 002 "), {baseline, *updates[-2:]})

    def test_limit_is_per_project_and_programme_type(self):
        long_base, long_updates = self.history("C4017", 5, "C")
        short_base, short_updates = self.history("C5001", 2, "C")
        target_base, target_updates = self.history("C4017", 4, "T")
        self.assertEqual(self.keep(latest_updates="3"), {
            long_base, *long_updates[-3:], short_base, *short_updates,
            target_base, *target_updates[-3:],
        })
        self.assertEqual(self.keep(programme="T", latest_updates="3"), {target_base, *target_updates[-3:]})
        self.assertEqual(self.keep(selected="C5001", latest_updates="1"), {short_base, short_updates[-1]})

    def test_updates_before_the_anchor_never_count(self):
        self.add("C4017", "2510", "2025-10-31")
        self.add("C4017", "2511", "2025-11-30")
        baseline, updates = self.history(updates=2)
        self.assertEqual(self.keep(latest_updates="3"), {baseline, *updates})

    def test_project_without_baseline_keeps_latest_updates(self):
        names = [self.add("C4017", f"26{month:02d}", f"2026-{month:02d}-{calendar.monthrange(2026, month)[1]:02d}")
                 for month in range(1, 5)]
        self.assertEqual(self.keep(latest_updates="2"), set(names[-2:]))
        self.assertEqual(self.keep(), set(names))

    def test_limit_drops_undated_files_and_non_anchor_baselines(self):
        baseline = self.add("C4017", "BL1", "2026-01-31")
        null_update = self.add("C4017", "2602", None)
        invalid_update = self.add("C4017", "2603", "not-a-date")
        dated = self.add("C4017", "2604", "2026-04-30")
        self.assertEqual(self.keep(selected="C4017"), {baseline, null_update, invalid_update, dated})
        self.assertEqual(self.keep(selected="C4017", latest_updates="2"), {baseline, dated})
        anchor = self.add("C5001", "BL2", None)
        older_baseline = self.add("C5001", "BL1", "2025-06-30")
        december = self.add("C5001", "2512", "2025-12-31")
        january = self.add("C5001", "2601", "2026-01-31")
        self.assertEqual(self.keep(selected="C5001"), {anchor, older_baseline, december, january})
        self.assertEqual(self.keep(selected="C5001", latest_updates="1"), {anchor, january})

    def test_same_month_files_count_as_one_update(self):
        baseline = self.add("C4017", "BL1", "2025-12-31")
        january = self.add("C4017", "2601", "2026-01-31")
        february = self.add("C4017", "2602", "2026-02-28")
        reissue = self.add("unused", month="2026-02-28", filename="C4017-C-2602_20260305.xer")
        self.assertEqual(self.keep(latest_updates="1"), {baseline, february, reissue})
        self.assertEqual(self.keep(latest_updates="2"), {baseline, january, february, reissue})

    def test_file_with_several_metadata_rows_is_ranked_once(self):
        baseline = self.add("C4017", "BL1", "2025-12-31")
        self.add("C4017", "2601", "2026-01-31")
        february = self.add("C4017", "2602", "2026-02-28")
        march = self.add("C4017", "2603", "2026-03-31")
        self.add("unused", month="2026-04-30", filename=march)
        self.assertEqual(self.keep(latest_updates="2"), {baseline, march, february})

    def test_invalid_limit_values_are_rejected(self):
        self.history(updates=2)
        for value in ("0", "000", "-1", "3.5", "abc", "", " ", "1000", "ALL3", "3,4"):
            with self.subTest(limit=value):
                with self.assertRaises(ValueError):
                    self.keep(latest_updates=value)
        m_text = EXPRESSIONS.read_text(encoding="utf-8-sig").split("expression AthenaScopeSql =", 1)[1].split("\nexpression ", 1)[0]
        for fragment in ('if UpdateCountRaw = "ALL" then null',
                         "Text.Length(UpdateCountRaw) >= 1 and Text.Length(UpdateCountRaw) <= 3",
                         "Text.Length(Text.Remove(UpdateCountRaw, DigitChars)) = 0",
                         'Number.FromText(UpdateCountRaw, "en-US") >= 1',
                         'error "LatestUpdateCount must be ALL or a whole number from 1 to 999."'):
            with self.subTest(m_fragment=fragment):
                self.assertIn(fragment, m_text)

    def test_parameter_is_declared_as_required_text(self):
        # The value is a working setting (Desktop may save any valid value), so only the declaration is checked.
        text = EXPRESSIONS.read_text(encoding="utf-8-sig")
        declaration = re.search(r'^expression LatestUpdateCount = "([^"]*)" meta \[IsParameterQuery=true, '
                                r'Type="Text", IsParameterQueryRequired=true\]$', text, re.M)
        self.assertIsNotNone(declaration)
        update_limit(declaration[1])

    def test_all_eleven_native_consumers_respect_the_limit(self):
        baseline, updates = self.history(updates=3)
        filenames = [baseline, *updates]
        expected = {baseline, *updates[-2:]}
        for table in ("03_xer_projwbs", "06_xer_predecessor", "07_xer_actvtype", "08_xer_actvcode",
                      "09_xer_taskactv", "10_xer_calendar", "12_xer_rsrc", "15_xer_resource_distribution"):
            self.db.execute('CREATE TABLE prod_projectcontrols_p6."' + table + '" (filename VARCHAR)')
            self.db.executemany('INSERT INTO prod_projectcontrols_p6."' + table + '" VALUES (?)',
                                [(name,) for name in filenames])
        for table in ("02_xer_project", "03_xer_projwbs", "06_xer_predecessor", "07_xer_actvtype",
                      "08_xer_actvcode", "09_xer_taskactv", "10_xer_calendar", "12_xer_rsrc",
                      "15_xer_resource_distribution"):
            with self.subTest(consumer=table):
                rows = self.db.execute(duck_sql(fn_athena_sql(table, latest_updates="2"))).fetchall()
                self.assertEqual({row[0] for row in rows}, expected)
                self.assertEqual(len(rows), len(expected))
        for name in filenames:
            self.add_task(name)
        rows = self.db.execute(task_stage_sql("task_raw", "filename", latest_updates="2")).fetchall()
        self.assertEqual(sorted(rows), sorted((name,) for name in expected))
        CalendarAlignmentTests.create_calendar_table(self.db)
        for name in filenames:
            CalendarAlignmentTests.insert_calendar(self.db, name, "1", [8] * 5 + [0, 0], {})
        rows = self.db.execute(duck_sql(calendar_sql(latest_updates="2"))).fetchall()
        self.assertEqual({row[7].rsplit(".", 1)[0] for row in rows}, expected)
        self.assertEqual(len(rows), 7 * len(expected))

    def test_task_previous_values_use_only_loaded_updates(self):
        baseline, (january, february, march) = self.history(updates=3)
        self.add_task(baseline, "2025-12-31", "2026-06-01")
        self.add_task(january, "2026-01-31", "2026-07-01")
        self.add_task(february, "2026-02-28", "2026-08-01")
        self.add_task(march, "2026-03-31", "2026-09-01")
        projection = "filename, previous_task_finish, previous_data_date, baseline_finish"

        def by_file(**parameters):
            return {row[0]: row[1:] for row in self.db.execute(
                task_stage_sql("task_joined", projection, **parameters)).fetchall()}

        full = by_file()
        self.assertEqual(full[february], (dt.date(2026, 7, 1), dt.date(2026, 1, 31), dt.date(2026, 6, 1)))
        limited = by_file(latest_updates="2")
        self.assertEqual(set(limited), {baseline, february, march})
        # The oldest loaded update now compares against the baseline, the snapshot loaded before it.
        self.assertEqual(limited[february], (dt.date(2026, 6, 1), dt.date(2025, 12, 31), dt.date(2026, 6, 1)))
        self.assertEqual(limited[march], full[march])

    def test_audit_reports_files_outside_the_update_limit(self):
        before = self.add("C4017", "2511", "2025-11-30")
        baseline, (january, february, march) = self.history(updates=3)
        rows = self.db.execute(duck_sql(audit_sql(latest_updates="1"))).fetchall()
        self.assertEqual({row[0]: row[-1] for row in rows}, {
            before: "OUTSIDE_BASELINE_WINDOW", baseline: "KEPT",
            january: "OUTSIDE_UPDATE_LIMIT", february: "OUTSIDE_UPDATE_LIMIT", march: "KEPT",
        })
        unlimited = self.db.execute(duck_sql(audit_sql())).fetchall()
        self.assertEqual({row[0]: row[-1] for row in unlimited}, {
            before: "OUTSIDE_BASELINE_WINDOW", baseline: "KEPT",
            january: "KEPT", february: "KEPT", march: "KEPT",
        })


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser(add_help=False)
    argument_parser.add_argument("--definition", type=Path,
                                 help="Path to semantic model definition directory")
    arguments, unittest_arguments = argument_parser.parse_known_args()
    if arguments.definition is not None:
        DEFINITION = arguments.definition
        EXPRESSIONS = DEFINITION / "expressions.tmdl"
        TASK = DEFINITION / "tables" / "01 XER_TASK.tmdl"
        CALENDAR = DEFINITION / "tables" / "11 XER_CALENDAR_DETAILED.tmdl"
    sys.argv = [sys.argv[0], *unittest_arguments]
    unittest.main(verbosity=2)

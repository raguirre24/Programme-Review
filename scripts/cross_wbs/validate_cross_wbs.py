"""Static, TOM round-trip, P6 semantic, WCAG contrast, and PBIR verification for Cross-WBS Analysis.

    python scripts/cross_wbs/validate_cross_wbs.py

Checks:
  1. TOM deserialisation & round-trip of the semantic model, '06 XER_PREDECESSOR' WBS columns, removal of retired
     columns ('PredTaskCodeAndName', 'predecessor_Total Float', 'CriticalLink') across TMDL, en-NZ.tmdl and PBIR,
     all 39 'WBS Measures' expressions, format strings, forbidden DAX variable names, non-summation of floats/lags,
     scope readiness guards, and static PBIR-to-DAX reachability (zero unused measures in 'WBS Measures').
  2. SharePoint CSV schema 5.0 compatibility: verifies XerCsvTableContracts[ModelColumns] coverage across Tables 01,
     02, 03 and 06, fnXerCsvLoadTable + IsCsvSource wiring, Data Lake dual-endpoint link exclusion parity
     (fnXerCsvExcludeFlaggedTasks + XER CSV Refresh Audit), CSV:: compact-key WBS PATH() safety, mixed Athena + CSV
     portfolio KPI isolation, and NOT ISBLANK(...) guards for nullable CSV free_float / total_float values.
  3. Mathematical & P6 scheduling fixture tests: Level 1 root fallback, orphan cross-project predecessor exclusion,
     non-summation of multi-link floats, multi-project KPI interface aggregation, matrix diagonal vs off-diagonal
     rules, and WCAG 2.1 >= 4.5:1 contrast + lightness separation across all matrix & inspector colour pairs.
  4. PBIR contracts on page 'eb4b0a43085cad901574': exact 26 visuals, zero retired visual folders, cleaned project
     menu backdrop, page filters ('Type Validity' = 'Valid', 'Is Unscheduled' = false), 'Update Has Visible Tasks' = 1L
     on CurrentDate, clean slicer filters & defaults, zero visual-level measure filters on analytical visuals, legend
     swatch parity, scoped project-menu bookmarks, interaction matrix, and parity with build_cross_wbs_page.py --check.
Read-only; requires no running Power BI Desktop instance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "rls"))
sys.path.insert(0, str(ROOT / "scripts" / "model_usage"))

import build_cross_wbs_page as builder  # noqa: E402
from find_unused_objects import report_references  # noqa: E402
from validate_rls import VALID_PBIR_FILTER_KEYS, extract_tom_metadata, strip_dax_comments  # noqa: E402

DEFAULT_MODEL = ROOT / "Project Review - Programme (datalake).SemanticModel" / "definition"
DEFAULT_REPORT = ROOT / "Project Review - Programme (datalake).Report" / "definition"

FORBIDDEN_VARS = {"firstdate", "lastdate", "updates", "key", "ordinal"}
RETIRED_PRED_COLUMNS = {"PredTaskCodeAndName", "predecessor_Total Float", "CriticalLink"}

EXPECTED_WBS_MEASURES = {
    "Count of Links",
    "Driving Predecessor Count",
    "Driving Ratio",
    "Predecessor Name",
    "CWBS Scope Ready",
    "CWBS Scope Prompt",
    "CWBS Interface Summary Title",
    "CWBS Matrix Title",
    "CWBS Top Interfaces Title",
    "CWBS Link Inspector Title",
    "CWBS KPI Handoff Links",
    "CWBS KPI Active Interfaces",
    "CWBS KPI Driving Links",
    "CWBS KPI Driving Share",
    "CWBS KPI Critical Handoffs",
    "CWBS KPI Zero Free Float Links",
    "CWBS KPI Distinct Predecessors",
    "CWBS KPI Distinct Successors",
    "CWBS Interface Links",
    "CWBS Interface Driving Links",
    "CWBS Interface Non-Driving Links",
    "CWBS Interface Driving Share",
    "CWBS Interface Critical Links",
    "CWBS Interface Min Free Float",
    "CWBS Matrix Link Count",
    "CWBS Matrix Cell Colour",
    "CWBS Matrix Font Colour",
    "CWBS Link Predecessor Name",
    "CWBS Link Predecessor WBS",
    "CWBS Link Successor Name",
    "CWBS Link Successor WBS",
    "CWBS Link Lag Days",
    "CWBS Link Predecessor Finish",
    "CWBS Link Successor Start",
    "CWBS Link Free Float Days",
    "CWBS Link Successor Total Float",
    "CWBS Link Driving Status",
    "CWBS Link Total Float Colour",
    "CWBS Link Total Float Font Colour",
}

SCOPE_GATED_MEASURES = {
    "CWBS Interface Links",
    "CWBS Interface Driving Links",
    "CWBS Interface Non-Driving Links",
    "CWBS Interface Driving Share",
    "CWBS Interface Critical Links",
    "CWBS Interface Min Free Float",
    "CWBS Matrix Link Count",
    "CWBS Link Predecessor Name",
    "CWBS Link Predecessor WBS",
    "CWBS Link Successor Name",
    "CWBS Link Successor WBS",
    "CWBS Link Lag Days",
    "CWBS Link Predecessor Finish",
    "CWBS Link Successor Start",
    "CWBS Link Free Float Days",
    "CWBS Link Successor Total Float",
    "CWBS Link Driving Status",
}

FLOAT_AND_LAG_MEASURES = {
    "CWBS Interface Min Free Float",
    "CWBS Link Lag Days",
    "CWBS Link Free Float Days",
    "CWBS Link Successor Total Float",
}

MATRIX_PALETTE = {
    "diagonal": ("#E7E6E6", "#595959"),
    "critical_driving": ("#FFC7CE", "#9C0006"),
    "driving_or_near_critical": ("#FFEB9C", "#9C5700"),
    "buffered": ("#DDEBF7", "#1F4E78"),
}


def relative_luminance(hex_code: str) -> float:
    h = hex_code.lstrip("#")
    channels = []
    for idx in (0, 2, 4):
        c = int(h[idx : idx + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def check_wcag_and_fixtures() -> dict:
    # 1. Contrast >= 4.5:1 across all matrix & inspector fill/font pairs, plus lightness separation for Red vs Amber
    ratios = {}
    for state, (fill_hex, font_hex) in MATRIX_PALETTE.items():
        ratio = round(contrast_ratio(fill_hex, font_hex), 2)
        assert ratio >= 4.5, f"Cell state {state} ({fill_hex}/{font_hex}) contrast {ratio}:1 < 4.5:1"
        ratios[state] = ratio
    lum_red = relative_luminance(MATRIX_PALETTE["critical_driving"][0])
    lum_amber = relative_luminance(MATRIX_PALETTE["driving_or_near_critical"][0])
    assert abs(lum_amber - lum_red) >= 0.15, "Critical red and near-critical amber fills must differ in lightness"

    # 2. WBS Level 2 + Level 1 fallback + orphan link exclusion oracle
    def resolve_wbs(level_1: str | None, level_2: str | None) -> str | None:
        if level_2:
            return level_2
        if level_1:
            return f"{level_1} (Level 1)"
        return None

    def classify_link(pred_l1, pred_l2, succ_l1, succ_l2):
        pw = resolve_wbs(pred_l1, pred_l2)
        sw = resolve_wbs(succ_l1, succ_l2)
        if not pw or not sw:
            return None, None
        link_type = "Internal Link" if pw == sw else "Cross-WBS Link"
        return link_type, f"{pw} → {sw}"

    assert classify_link("ProjA", "Design", "ProjA", "Construction") == ("Cross-WBS Link", "Design → Construction")
    assert classify_link("ProjA", "Design", "ProjA", "Design") == ("Internal Link", "Design → Design")
    assert classify_link("ProjA", None, "ProjA", "Construction") == (
        "Cross-WBS Link",
        "ProjA (Level 1) → Construction",
    )
    assert classify_link("ProjA", None, "ProjA", None) == ("Internal Link", "ProjA (Level 1) → ProjA (Level 1)")
    # Orphan external predecessor missing from 01 XER_TASK must never produce a false Cross-WBS Link
    assert classify_link(None, None, "ProjA", "Construction") == (None, None)

    # 3. Float non-summation & multi-project KPI interface aggregation
    incoming_links = [
        {"pred": "D-10", "succ": "C-100", "free_float": 0.0, "succ_tf": 12.0},
        {"pred": "D-20", "succ": "C-100", "free_float": 4.0, "succ_tf": 12.0},
        {"pred": "P-30", "succ": "C-100", "free_float": 9.0, "succ_tf": 12.0},
    ]
    assert min(r["succ_tf"] for r in incoming_links) == 12.0
    assert min(r["free_float"] for r in incoming_links) == 0.0

    portfolio_links = [
        {"project": "CJ:5064", "dir": "Design → Construction", "source": "Athena"},
        {"project": "CJ:5064", "dir": "Design → Construction", "source": "Athena"},
        {"project": "CJ:5068", "dir": "Design → Construction", "source": "Athena"},
        {"project": "EXACT:CNZ01", "dir": "Design → Construction", "source": "CSV"},
    ]
    per_project_distinct = sum(
        len({r["dir"] for r in portfolio_links if r["project"] == pk and r["dir"]})
        for pk in {r["project"] for r in portfolio_links}
    )
    assert per_project_distinct == 3, "Identical WBS direction strings across Athena and CSV projects must count per ProjectKey"

    # 4. CSV schema 5.0 compact-key WBS PATH() & nullable free_float (Historical / FixedEvent / NoFiniteBound) oracle
    def encode_csv_project_token(project_code: str) -> str:
        allowed = set(range(65, 91)) | set(range(97, 123)) | set(range(48, 58)) | {32, 45, 95}
        return "".join(chr(b) if b in allowed else f"%{b:02X}" for b in project_code.encode("utf-8"))

    for sample_code in ("CNZ01", "J5064", "C6012", "PROJ|A::1"):
        tok = encode_csv_project_token(sample_code)
        csv_key = f"CSV::{tok}::C::2610::WBS_20"
        assert "|" not in csv_key, f"CSV:: key {csv_key} must never contain '|' reserved by DAX PATH()"

    csv_wbs_nodes = {
        "CSV::CNZ01::C::2610::W_ROOT": ("CNZ01 Programme", None),
        "CSV::CNZ01::C::2610::W_DES": ("Design", "CSV::CNZ01::C::2610::W_ROOT"),
        "CSV::CNZ01::C::2610::W_DES_STR": ("Structures Design", "CSV::CNZ01::C::2610::W_DES"),
    }

    def dax_path_levels(wbs_id_key: str) -> tuple[str | None, str | None]:
        chain: list[str] = []
        cur: str | None = wbs_id_key
        while cur:
            assert "|" not in cur
            chain.append(cur)
            cur = csv_wbs_nodes[cur][1]
        chain.reverse()
        path_str = "|".join(chain)
        items = path_str.split("|")
        l1 = csv_wbs_nodes[items[0]][0] if len(items) >= 1 else None
        l2 = csv_wbs_nodes[items[1]][0] if len(items) >= 2 else None
        return l1, l2

    assert resolve_wbs(*dax_path_levels("CSV::CNZ01::C::2610::W_DES_STR")) == "Design"
    assert resolve_wbs(*dax_path_levels("CSV::CNZ01::C::2610::W_ROOT")) == "CNZ01 Programme (Level 1)"

    # Nullable CSV free_float: Historical / FixedEvent / RequiresContext rows carry None, never fabricated 0
    csv_task_links = [
        {"pred_key": "CSV::CNZ01::C::2610::T1", "free_float": None},  # Historical completed predecessor
        {"pred_key": "CSV::CNZ01::C::2610::T2", "free_float": 0.0},   # Finite driving predecessor
        {"pred_key": "CSV::CNZ01::C::2610::T3", "free_float": 3.5},   # Finite buffered predecessor
    ]
    numeric_ffs = [r["free_float"] for r in csv_task_links if r["free_float"] is not None]
    min_ff = min(numeric_ffs) if numeric_ffs else None
    driving_flags = [
        "Driving" if (r["free_float"] is not None and r["free_float"] == min_ff) else "Not Driving"
        for r in csv_task_links
    ]
    assert driving_flags == ["Not Driving", "Driving", "Not Driving"], "Blank CSV free_float must never equal 0.0 in Driving check"
    zero_ff_count = sum(1 for r in csv_task_links if r["free_float"] is not None and r["free_float"] <= 0)
    assert zero_ff_count == 1, "Blank CSV free_float must never count as Zero Free Float (DAX BLANK() <= 0 trap)"

    return {"contrast_ratios": ratios, "fixtures": "PASS"}


CSV_REQUIRED_MODEL_COLUMNS = {
    "01_XER_TASK": {
        "task_id_key",
        "wbs_id_key",
        "proj_id_key",
        "task_code",
        "task_name",
        "status_code",
        "task_type",
        "total_float",
        "remaining_duration",
        "early_start_date",
        "early_end_date",
        "act_end_date",
        "data_date",
        "UpdateDate",
        "filename",
        "ProjectCode",
    },
    "02_XER_PROJECT": {"proj_id_key", "ProjectCode"},
    "03_XER_PROJWBS": {"wbs_name", "wbs_id_key", "parent_wbs_id_key", "ProjectCode"},
    "06_XER_PREDECESSOR": {
        "task_id_key",
        "pred_task_id_key",
        "pred_type",
        "task_type",
        "predecessor_task_type",
        "lag",
        "start",
        "finish",
        "predecessor_start",
        "predecessor_finish",
        "free_float",
        "total_float",
        "status_code",
        "predecessor_status_code",
    },
}


def _extract_m_string_list(block: str, field_name: str) -> set[str] | None:
    m = re.search(rf"(?:^|\s){re.escape(field_name)}\s*=\s*\{{([^}}]*)\}}", block, re.DOTALL)
    if not m:
        return None
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def check_csv_bundle_compatibility(model_dir: Path) -> dict:
    expr_text = (model_dir / "expressions.tmdl").read_text(encoding="utf-8-sig")
    contracts_section = expr_text.split("expression XerCsvTableContracts =", 1)[1].split("\nexpression ", 1)[0]

    for retired in RETIRED_PRED_COLUMNS:
        assert retired not in contracts_section, f"Retired DAX column {retired} must not appear in XerCsvTableContracts"

    for table_key, needed_cols in CSV_REQUIRED_MODEL_COLUMNS.items():
        marker = f'#"{table_key}" = ['
        assert marker in contracts_section, f"Missing {table_key} in XerCsvTableContracts"
        sub = contracts_section.split(marker, 1)[1]
        next_tbl = re.search(r'\n\s*#"\d{2}_XER_', sub)
        block = sub[: next_tbl.start()] if next_tbl else sub
        loaded_cols = _extract_m_string_list(block, "ModelColumns") or _extract_m_string_list(block, "Columns")
        assert loaded_cols is not None, f"Could not parse Columns/ModelColumns for {table_key}"
        missing = needed_cols - loaded_cols
        assert not missing, f"CSV contract {table_key} ModelColumns is missing Cross-WBS column(s): {sorted(missing)}"

    # Dual-endpoint Data Lake exclusion parity between CSV (fnXerCsvExcludeFlaggedTasks) and Athena (06 XER_PREDECESSOR)
    exclude_block = expr_text.split("expression fnXerCsvExcludeFlaggedTasks =", 1)[1]
    pred_excl = _extract_m_string_list(exclude_block, '#"06_XER_PREDECESSOR"')
    assert pred_excl == {"task_id_key", "pred_task_id_key"}, (
        f"fnXerCsvExcludeFlaggedTasks must exclude both link endpoints on 06_XER_PREDECESSOR, got {pred_excl}"
    )

    audit_tmdl = (model_dir / "tables" / "XER CSV Refresh Audit.tmdl").read_text(encoding="utf-8-sig")
    assert '"06_XER_PREDECESSOR"' in audit_tmdl and "'06 XER_PREDECESSOR'[IsCsvSource] = TRUE ()" in audit_tmdl

    for tmdl_name, contract_key in (
        ("01 XER_TASK.tmdl", "01_XER_TASK"),
        ("02 XER_PROJECT.tmdl", "02_XER_PROJECT"),
        ("03 XER_PROJWBS.tmdl", "03_XER_PROJWBS"),
        ("06 XER_PREDECESSOR.tmdl", "06_XER_PREDECESSOR"),
    ):
        txt = (model_dir / "tables" / tmdl_name).read_text(encoding="utf-8-sig")
        assert f'fnXerCsvLoadTable("{contract_key}")' in txt, f"{tmdl_name} must union fnXerCsvLoadTable(\"{contract_key}\")"
        assert "column IsCsvSource" in txt, f"{tmdl_name} must preserve hidden IsCsvSource column"

    # Nullable float guards required because CSV schema 5.0 leaves non-Finite/non-Estimated 06.free_float blank (null)
    pred_tmdl = (model_dir / "tables" / "06 XER_PREDECESSOR.tmdl").read_text(encoding="utf-8-sig")
    assert "NOT ISBLANK ( CurrentFreeFloat )" in pred_tmdl, (
        "06 XER_PREDECESSOR[Is Driving Predecessor] must guard NOT ISBLANK(CurrentFreeFloat) for CSV nullable floats"
    )
    wbs_tmdl = (model_dir / "tables" / "WBS Measures.tmdl").read_text(encoding="utf-8-sig")
    assert wbs_tmdl.count("NOT ISBLANK ( '06 XER_PREDECESSOR'[free_float] )") >= 2, (
        "CWBS KPI Zero Free Float Links and CWBS Matrix Cell Colour must guard NOT ISBLANK('06 XER_PREDECESSOR'[free_float])"
    )
    assert "NOT ISBLANK ( TfVal )" in wbs_tmdl, (
        "CWBS Link Total Float Colour must guard NOT ISBLANK(TfVal) for unresolved CSV HPD float rows"
    )

    return {"csv_schema_5_0_contracts": "PASS"}


def check_model_and_measures(model_dir: Path, report_dir: Path, meta: dict) -> dict:
    tables = {t["name"]: t for t in meta["tables"]}
    pred_cols = {c["name"] for c in tables["06 XER_PREDECESSOR"]["columns"]}
    assert not (pred_cols & RETIRED_PRED_COLUMNS), f"Retired columns remain on 06 XER_PREDECESSOR: {pred_cols & RETIRED_PRED_COLUMNS}"
    for required_col in (
        "Predecessor_Level_2",
        "Successor_Level_2",
        "Link_Type",
        "WBS_Link_Direction",
        "Is Driving Predecessor",
        "Type Validity",
        "predecessor_task_code",
        "task_code",
        "pred_type",
        "lag",
        "free_float",
        "total_float",
        "predecessor_finish",
        "start",
    ):
        assert required_col in pred_cols, f"Missing required column 06 XER_PREDECESSOR[{required_col}]"

    # Check en-NZ.tmdl and all PBIR JSONs have zero stale references to retired columns
    en_nz_text = (model_dir / "cultures" / "en-NZ.tmdl").read_text(encoding="utf-8-sig")
    for retired in RETIRED_PRED_COLUMNS:
        assert retired not in en_nz_text, f"Stale reference to {retired} remains in cultures/en-NZ.tmdl"
    for jf in report_dir.rglob("*.json"):
        jtxt = jf.read_text(encoding="utf-8-sig")
        for retired in RETIRED_PRED_COLUMNS:
            assert retired not in jtxt, f"Stale reference to {retired} remains in {jf}"

    # Verify WBS Measures inventory and DAX guardrails
    wbs_tmdl = (model_dir / "tables" / "WBS Measures.tmdl").read_text(encoding="utf-8-sig")
    assert "formatStringDefinition" not in wbs_tmdl, "WBS Measures.tmdl must not combine formatString and formatStringDefinition"

    measures = {m["name"]: m for m in tables["WBS Measures"]["measures"]}
    assert set(measures) == EXPECTED_WBS_MEASURES, (
        f"WBS Measures mismatch.\nMissing: {sorted(EXPECTED_WBS_MEASURES - set(measures))}\n"
        f"Extra:   {sorted(set(measures) - EXPECTED_WBS_MEASURES)}"
    )

    var_re = re.compile(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
    for mname, m in measures.items():
        expr_clean = strip_dax_comments(m["expression"])
        bad_vars = {v.lower() for v in var_re.findall(expr_clean)} & FORBIDDEN_VARS
        assert not bad_vars, f"Forbidden DAX variable name(s) {bad_vars} in WBS Measures[{mname}]"
        if mname in SCOPE_GATED_MEASURES:
            assert "[CWBS Scope Ready]" in expr_clean, f"WBS Measures[{mname}] must check [CWBS Scope Ready]"
        if mname in FLOAT_AND_LAG_MEASURES:
            assert "SUM" not in expr_clean.upper(), f"Float/lag measure WBS Measures[{mname}] must never use SUM"
            assert "MIN" in expr_clean.upper(), f"Float/lag measure WBS Measures[{mname}] must aggregate via MIN"

    assert "DIVIDE" in measures["Driving Ratio"]["expression"].upper(), "Driving Ratio must use DIVIDE"

    # Static PBIR reachability check across WBS Measures so Find-UnusedModelObjects stays 100% clean
    pbir_refs = report_references(report_dir)
    directly_used = {name for kind, tbl, name in pbir_refs if kind == "M" and tbl == "WBS Measures"}
    measure_deps: dict[str, set[str]] = {}
    ref_re = re.compile(r"\[([^\]]+)\]")
    for mname, m in measures.items():
        measure_deps[mname] = {
            cand for cand in ref_re.findall(strip_dax_comments(m["expression"])) if cand in measures and cand != mname
        }
    reached = set(directly_used)
    stack = list(directly_used)
    while stack:
        cur = stack.pop()
        for dep in measure_deps.get(cur, ()):
            if dep not in reached:
                reached.add(dep)
                stack.append(dep)
    unreached = EXPECTED_WBS_MEASURES - reached
    assert not unreached, f"Unreached measures in WBS Measures (would fail Find-UnusedModelObjects): {sorted(unreached)}"

    return {"wbs_measures_verified": len(measures), "wbs_measures_reached": len(reached)}


def check_pbir_page(report_dir: Path) -> dict:
    pages = builder.read(report_dir / "pages" / "pages.json")
    assert builder.PAGE in pages["pageOrder"], f"Page {builder.PAGE} missing from pages.json"

    page_dir = report_dir / "pages" / builder.PAGE
    page = builder.read(page_dir / "page.json")
    assert page["displayName"] == builder.PAGE_NAME

    # Page-level filters: Type Validity = 'Valid' and Is Unscheduled = false
    pfilters = {f["field"]["Column"]["Property"]: f for f in page.get("filterConfig", {}).get("filters", [])}
    assert set(pfilters) == {"Type Validity", "Is Unscheduled"}, f"Unexpected page filters: {sorted(pfilters)}"
    tv_vals = pfilters["Type Validity"]["filter"]["Where"][0]["Condition"]["In"]["Values"]
    assert tv_vals == [[{"Literal": {"Value": "'Valid'"}}]], f"Unexpected Type Validity filter: {tv_vals}"
    unsched_vals = pfilters["Is Unscheduled"]["filter"]["Where"][0]["Condition"]["In"]["Values"]
    assert unsched_vals == [[{"Literal": {"Value": "false"}}]], f"Unexpected Is Unscheduled filter: {unsched_vals}"

    # Visual folders check (no orphan empty folders, no retired folders, exact 26 visuals)
    vis_dirs = {d.name for d in (page_dir / "visuals").iterdir() if d.is_dir()}
    assert not (vis_dirs & set(builder.RETIRED_VISUALS)), f"Retired visual dirs remain: {vis_dirs & set(builder.RETIRED_VISUALS)}"
    assert vis_dirs == builder.EXPECTED_VISUALS, (
        f"Visual folder mismatch.\nMissing: {sorted(builder.EXPECTED_VISUALS - vis_dirs)}\n"
        f"Extra:   {sorted(vis_dirs - builder.EXPECTED_VISUALS)}"
    )
    visuals = {vid: builder.read(page_dir / "visuals" / vid / "visual.json") for vid in sorted(vis_dirs)}

    # Menu backdrop cleaned of 'unique successors', and saved visibility matches closed project menu
    assert "unique successors" not in json.dumps(visuals[builder.MENU_BG]).lower(), "Menu backdrop still contains 'unique successors'"
    for vid, vdata in visuals.items():
        if vid in builder.MENU_VISUALS:
            assert vdata.get("isHidden") is True, f"Project menu visual {vid} must be saved hidden"
        else:
            assert not vdata.get("isHidden"), f"Active page visual {vid} must be saved visible"

    # Unique valid filter names across all visuals on the page, and no hidden Driving filter on slicers
    filter_names: list[str] = []
    for vid, vdata in visuals.items():
        for flt in vdata.get("filterConfig", {}).get("filters", []):
            bad_keys = set(flt) - VALID_PBIR_FILTER_KEYS
            assert not bad_keys, f"Invalid filter keys {bad_keys} in {vid}"
            filter_names.append(flt["name"])
            if vid in builder.SLICERS:
                s_txt = json.dumps(flt)
                assert "'Driving'" not in s_txt, f"Slicer {vid} must not hard-filter 'Driving' in visual filterConfig"
        if vid in builder.DATA_VISUALS:
            for flt in vdata.get("filterConfig", {}).get("filters", []):
                assert "Measure" not in flt.get("field", {}), f"Analytical visual {vid} must not carry a visual-level measure filter"
    assert len(filter_names) == len(set(filter_names)), "Filter names must be unique across Cross-WBS Analysis"

    # Legend swatch parity with MATRIX_PALETTE
    legend_text = json.dumps(visuals[builder.MATRIX_LEGEND]["visual"]["objects"]["general"])
    for state, (fill_hex, _) in MATRIX_PALETTE.items():
        assert fill_hex in legend_text, f"Matrix fill colour {fill_hex} ({state}) missing from legend {builder.MATRIX_LEGEND}"

    # Top 15 bar chart standard orientation & TopN = 15
    bar_objs = visuals[builder.INTERFACES_BAR]["visual"]["objects"]
    assert "invertAxis" not in json.dumps(bar_objs), "Top 15 bar chart must use standard left-to-right axis (no invertAxis)"
    top_flts = [f for f in visuals[builder.INTERFACES_BAR]["filterConfig"]["filters"] if f.get("type") == "TopN"]
    assert len(top_flts) == 1 and top_flts[0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]["Top"] == 15

    # Scoped project-menu bookmarks
    for bm_id in builder.MENU_BOOKMARKS:
        bm = builder.read(report_dir / "bookmarks" / f"{bm_id}.bookmark.json")
        opts = bm["options"]
        assert opts.get("applyOnlyToTargetVisuals") is True, f"Bookmark {bm_id} must set applyOnlyToTargetVisuals: true"
        assert opts.get("suppressData") is True and opts.get("suppressActiveSection") is True
        assert sorted(opts["targetVisualNames"]) == sorted(builder.MENU_VISUALS)
        state = bm["explorationState"]["sections"][builder.PAGE]["visualContainers"]
        assert "filter" not in json.dumps(state).lower(), f"Menu bookmark {bm_id} must not capture filters"

    # Interaction checks
    imap = {(i["source"], i["target"]): i["type"] for i in page["visualInteractions"]}
    for src in builder.DATA_VISUALS:
        for prot in [builder.UPDATE_SLICER] + builder.SLICERS + builder.KPIS:
            assert imap.get((src, prot)) == "NoFilter", f"Data visual {src} must not filter {prot}"
    for ov in (builder.SUMMARY_TABLE, builder.WBS_MATRIX, builder.INTERFACES_BAR):
        assert imap.get((ov, builder.LINK_INSPECTOR)) == "DataFilter", f"{ov} must DataFilter Link Inspector"
        assert imap.get((builder.LINK_INSPECTOR, ov)) == "NoFilter", f"Link Inspector must NoFilter {ov}"

    # Parity with build_cross_wbs_page.py
    orig_def = builder.DEFINITION
    try:
        builder.DEFINITION = report_dir
        expected_files = builder.build()
    finally:
        builder.DEFINITION = orig_def

    diffs = [
        rel.as_posix()
        for rel, val in expected_files.items()
        if (val is None and (report_dir / rel).exists())
        or (val is not None and (not (report_dir / rel).exists() or builder.desktop_neutral(builder.read(report_dir / rel)) != builder.desktop_neutral(val)))
    ]
    assert not diffs, f"build_cross_wbs_page.py parity failed on: {diffs}"

    return {"visuals": len(visuals), "builder_parity": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-definition", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report-definition", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    model_dir = args.model_definition.resolve()
    report_dir = args.report_definition.resolve()

    fixture_summary = check_wcag_and_fixtures()
    csv_summary = check_csv_bundle_compatibility(model_dir)
    meta = extract_tom_metadata(model_dir)
    model_summary = check_model_and_measures(model_dir, report_dir, meta)
    pbir_summary = check_pbir_page(report_dir)

    print(
        json.dumps(
            {
                "status": "PASS",
                "tom_round_trip": meta["roundTrip"],
                "page": builder.PAGE,
                **model_summary,
                **csv_summary,
                **pbir_summary,
                **fixture_summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

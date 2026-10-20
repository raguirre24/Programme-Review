"""Static, TOM round-trip, and mathematical conservation-law verification for Calendar Analysis."""

from __future__ import annotations
import calendar
from datetime import date, timedelta
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MODEL_DEF = ROOT / "Project Review - Programme (datalake).SemanticModel" / "definition"
REPORT_DEF = ROOT / "Project Review - Programme (datalake).Report" / "definition"
PAGE_ID = "ca1da4a175154c398f01"

EXPECTED_CA_MEASURES = [
    "CA Horizon Start Month",
    "CA Horizon End Month",
    "CA Monthly Working Days",
    "CA Monthly Standard Working Days",
    "CA Monthly Exception Delta Days",
    "CA Monthly Non-Working Days",
    "CA Monthly Working Hours",
    "CA Monthly Critical Activities",
    "CA Workweek Signature",
    "CA Future Exception Blackout Days",
    "CA Incomplete Activity Count",
    "CA Critical Activity Count",
    "CA Critical Remaining Working Days",
    "CA Activity Total Float",
    "CA Activity Remaining Working Days",
    "CA Activity Remaining Elapsed Days",
    "CA Activity Standard Non-Working Days",
    "CA Activity Exception Blackout Days",
    "CA Activity Non-Working Stretch Days",
    "CA Activity Stretch Ratio",
    "CA Activity Stretch Diagnosis",
    "CA KPI Active Calendars",
    "CA KPI Critical Exception Blackout Days",
    "CA KPI Max Critical Stretch Days",
]

FORBIDDEN_VARS = {"firstdate", "lastdate", "updates", "key", "ordinal"}


def eval_window_calendar(
    start_dt: date,
    end_dt: date,
    week_hours: dict[int, float],
    exceptions: dict[date, float],
) -> dict[str, float]:
    """Evaluate exact closed-form O(7 + |E|) DAX calendar math and compare against day-by-day truth."""
    span_days = (end_dt - start_dt).days + 1
    start_dow = start_dt.isoweekday()
    full_weeks, extra_days = divmod(span_days, 7)

    std_work_days = 0
    std_work_hours = 0.0
    for rule_dow, hrs in week_hours.items():
        occurrences = full_weeks + (1 if (rule_dow - start_dow) % 7 < extra_days else 0)
        if hrs > 0:
            std_work_days += occurrences
            std_work_hours += occurrences * hrs

    exc_delta_days = 0
    exc_delta_hours = 0.0
    for exc_dt, exc_hrs in exceptions.items():
        if start_dt <= exc_dt <= end_dt:
            norm_hrs = week_hours[exc_dt.isoweekday()]
            exc_delta_days += (1 if exc_hrs > 0 else 0) - (1 if norm_hrs > 0 else 0)
            exc_delta_hours += exc_hrs - norm_hrs

    work_days = max(0, std_work_days + exc_delta_days)
    non_work_days = max(0, span_days - work_days)
    work_hours = max(0.0, std_work_hours + exc_delta_hours)
    std_non_work_days = max(0, span_days - std_work_days)
    exc_blackout_days = -exc_delta_days

    # Day-by-day brute-force reference oracle
    oracle_work_days = 0
    oracle_work_hours = 0.0
    cur = start_dt
    while cur <= end_dt:
        hrs = exceptions.get(cur, week_hours[cur.isoweekday()])
        if hrs > 0:
            oracle_work_days += 1
            oracle_work_hours += hrs
        cur += timedelta(days=1)

    assert work_days == oracle_work_days, f"Closed-form work_days {work_days} != oracle {oracle_work_days}"
    assert abs(work_hours - oracle_work_hours) < 1e-9, f"Closed-form work_hours {work_hours} != oracle {oracle_work_hours}"
    assert work_days + non_work_days == span_days, "Conservation Law 1 violated: Work + NonWork != SpanDays"
    assert std_work_days + exc_delta_days == work_days, "Conservation Law 1b violated: StdWork + ExcDelta != WorkDays"
    assert span_days - work_days == std_non_work_days + exc_blackout_days, "Conservation Law 2 violated"

    return {
        "span_days": span_days,
        "std_work_days": std_work_days,
        "exc_delta_days": exc_delta_days,
        "work_days": work_days,
        "non_work_days": non_work_days,
        "std_non_work_days": std_non_work_days,
        "exc_blackout_days": exc_blackout_days,
        "work_hours": work_hours,
    }


def verify_conservation_laws() -> dict:
    """Verify Monthly Civil Partition and Activity Stretch Decomposition across 5d/6d/7d calendars and blackouts."""
    week_5d = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 8.0, 6: 0.0, 7: 0.0}
    week_6d = {1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0, 5: 10.0, 6: 8.0, 7: 0.0}
    week_7d = {d: 12.0 for d in range(1, 8)}

    # September 2026 blackout: Sept 1 to Sept 15 (11 weekdays turned into 0h non-working exceptions)
    sept_blackout = {
        date(2026, 9, d): 0.0
        for d in range(1, 16)
        if date(2026, 9, d).isoweekday() <= 5
    }
    # Plus one Saturday overtime working exception on 2026-09-26
    sept_with_overtime = dict(sept_blackout)
    sept_with_overtime[date(2026, 9, 26)] = 8.0

    for yr, mo in [(2026, 8), (2026, 9), (2026, 10), (2026, 12), (2028, 2)]:
        last_day = calendar.monthrange(yr, mo)[1]
        m_start = date(yr, mo, 1)
        m_end = date(yr, mo, last_day)
        for wk in (week_5d, week_6d, week_7d):
            eval_window_calendar(m_start, m_end, wk, sept_with_overtime)

    # User prompt canonical scenario:
    # Critical activity with 5 remaining working days starting Fri 28 Aug 2026, hitting the 11-weekday
    # blackout (1 Sep - 15 Sep), finishing Fri 18 Sep 2026.
    aug_sep_task = eval_window_calendar(date(2026, 8, 28), date(2026, 9, 18), week_5d, sept_blackout)
    assert aug_sep_task["span_days"] == 22, f"Expected 22 elapsed days, got {aug_sep_task['span_days']}"
    assert aug_sep_task["work_days"] == 5, f"Expected 5 calendar working days, got {aug_sep_task['work_days']}"
    assert aug_sep_task["std_non_work_days"] == 6, f"Expected 6 weekend days, got {aug_sep_task['std_non_work_days']}"
    assert aug_sep_task["exc_blackout_days"] == 11, f"Expected 11 exception blackout days, got {aug_sep_task['exc_blackout_days']}"
    assert aug_sep_task["non_work_days"] == 17, f"Expected 17 total non-working stretch days, got {aug_sep_task['non_work_days']}"

    return {
        "canonical_aug_sep_stretch_scenario": {
            "remaining_working_days": aug_sep_task["work_days"],
            "remaining_elapsed_days": aug_sep_task["span_days"],
            "standard_weekend_days": aug_sep_task["std_non_work_days"],
            "exception_blackout_days": aug_sep_task["exc_blackout_days"],
            "total_non_working_days": aug_sep_task["non_work_days"],
            "stretch_ratio": round(aug_sep_task["span_days"] / aug_sep_task["work_days"], 2),
        }
    }


def verify_tmdl_measures() -> int:
    tmdl_path = MODEL_DEF / "tables" / "XER Measures.tmdl"
    text = tmdl_path.read_text(encoding="utf-8")

    found_measures = re.findall(r"^\tmeasure '?(CA [^'=\n]+)'? =", text, flags=re.M)
    assert found_measures == EXPECTED_CA_MEASURES, (
        f"CA measure list mismatch.\nExpected: {EXPECTED_CA_MEASURES}\nFound: {found_measures}"
    )

    # Check displayFolder and forbidden variable names inside the CA measures block
    ca_start = text.index("\tmeasure 'CA Horizon Start Month' =")
    ca_block = text[ca_start:]
    folders = re.findall(r"^\t\tdisplayFolder:\s*(.+)$", ca_block, flags=re.M)
    assert len(folders) == len(EXPECTED_CA_MEASURES) and all(f.strip() == "Calendar Analysis" for f in folders), (
        "All CA * measures must have displayFolder: Calendar Analysis"
    )

    var_names = [v.lower() for v in re.findall(r"\bVAR\s+([A-Za-z0-9_]+)\s*=", ca_block)]
    bad_vars = sorted(set(var_names) & FORBIDDEN_VARS)
    assert not bad_vars, f"Forbidden DAX variable names found in CA measures: {bad_vars}"

    # Regression checks:
    # 1. ISINSCOPE('Scenario Calendar'[Calendar]) must guard all 3 Calendar Profile count/duration measures
    #    so out-of-scope calendars (COUNTROWS('Scenario Calendar') = 0) return BLANK() instead of Grand Total.
    assert ca_block.count("ISINSCOPE('Scenario Calendar'[Calendar])") >= 3, (
        "Calendar Profile measures must guard per-calendar rows with ISINSCOPE('Scenario Calendar'[Calendar])"
    )
    # 2. ActiveTasks > 0 / ActiveTaskCount > 0 must guard calendar-grain measures so unused calendars are suppressed.
    assert ca_block.count("ActiveTasks > 0") >= 6 and "ActiveTaskCount > 0" in ca_block, (
        "Calendar-grain measures must require ActiveTasks > 0 to suppress unused calendars"
    )
    # 3. No FORMAT(..., "0.#") or FORMAT(..., "#,0.#") that produces trailing dots like '8.h/d'.
    assert '"0.#"' not in ca_block and '"#,0.#"' not in ca_block, (
        "Do not use FORMAT(..., \"0.#\") in DAX; it leaves a trailing dot on whole numbers"
    )
    # 4. Activity-grain measures must be single-table O(1) over '01 XER_TASK':
    #    - Zero CALCULATETABLE, SELECTCOLUMNS, CROSSFILTER, '11 XER_CALENDAR_DETAILED', 'Scenario Calendar', or 'Scenario Date'
    #    - Zero [CA Activity ...] measure-to-measure macro chaining
    #    - Strict TaskRows > 0 && ISINSCOPE('01 XER_TASK'[task_code]) sparsity guard on all 8 measures
    act_start = ca_block.index("\tmeasure 'CA Activity Total Float' =")
    act_end = ca_block.index("\tmeasure 'CA KPI Active Calendars' =")
    act_block = ca_block[act_start:act_end]
    for forbidden_token in (
        "CALCULATETABLE",
        "SELECTCOLUMNS",
        "CROSSFILTER",
        "11 XER_CALENDAR_DETAILED",
        "Scenario Calendar",
        "Scenario Date",
        "[CA Activity",
    ):
        assert forbidden_token not in act_block, (
            f"Activity-grain CA Activity * measures must not contain '{forbidden_token}' (causes 1024 MB memory spool)"
        )
    assert act_block.count("VAR TaskRows = COUNTROWS('01 XER_TASK')") == 8, (
        "All 8 CA Activity * measures must hoist VAR TaskRows = COUNTROWS('01 XER_TASK') for SE sparsity short-circuiting"
    )
    assert act_block.count("TaskRows > 0 && ISINSCOPE('01 XER_TASK'[task_code])") == 8, (
        "All 8 CA Activity * measures must guard evaluation with TaskRows > 0 && ISINSCOPE('01 XER_TASK'[task_code])"
    )

    return len(found_measures)


def verify_pbir_page() -> dict:
    pages_meta = json.loads((REPORT_DEF / "pages" / "pages.json").read_text(encoding="utf-8"))
    order = pages_meta["pageOrder"]
    assert PAGE_ID in order, f"Page {PAGE_ID} missing from pages.json"
    rc_idx = order.index("4c53a34bba9dcc7f3e8c")
    assert order[rc_idx + 1] == PAGE_ID, "Calendar Analysis must follow Resource Simulator in pageOrder"

    rc_page_json = json.loads((REPORT_DEF / "pages" / "4c53a34bba9dcc7f3e8c" / "page.json").read_text(encoding="utf-8"))
    assert rc_page_json["displayName"] == "Resource Simulator"

    page_dir = REPORT_DEF / "pages" / PAGE_ID
    page_json = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
    assert page_json["displayName"] == "Calendar Analysis"
    assert page_json["width"] == 1920 and page_json["height"] == 1080

    # Check page-level filters (Is Unscheduled = false, TaskType_Classified = 'Activity', status_code, Float Category <= 50)
    filter_props = {
        flt["field"]["Column"]["Property"]
        for flt in page_json.get("filterConfig", {}).get("filters", [])
        if "Column" in flt.get("field", {})
    }
    assert {"Is Unscheduled", "TaskType_Classified", "status_code", "Float Category"} <= filter_props, (
        f"Missing required page-level filters on Calendar Analysis: {filter_props}"
    )

    # Check visuals and bounds
    visual_files = sorted((page_dir / "visuals").glob("*/visual.json"))
    assert len(visual_files) == 24, f"Expected 24 visuals on Calendar Analysis, found {len(visual_files)}"

    sync_groups = set()
    visual_types = {}
    for vf in visual_files:
        vdata = json.loads(vf.read_text(encoding="utf-8"))
        assert vdata["name"] == vf.parent.name
        pos = vdata["position"]
        x, y, w, h = pos["x"], pos["y"], pos["width"], pos["height"]
        assert x >= -1 and y >= -1 and x + w <= 1921 and y + h <= 1081, (
            f"Visual {vf.parent.name} exceeds 1920x1080 bounds: {pos}"
        )
        v = vdata["visual"]
        visual_types[vf.parent.name] = v["visualType"]
        if "syncGroup" in v:
            sync_groups.add(v["syncGroup"]["groupName"])

    assert sync_groups == {"Project", "State", "last_recalc_date", "Level_2"}, (
        f"Expected synced slicer groups {{Project, State, last_recalc_date, Level_2}}, got {sync_groups}"
    )
    assert visual_types["ca21calprof000000021"] == "tableEx"
    assert visual_types["ca22calmatx000000022"] == "pivotTable"
    assert visual_types["ca23actinsp000000023"] == "tableEx"
    assert visual_types["ca24fltslic000000024"] == "slicer"

    # Verify ca24fltslic000000024 uses a valid Power BI RangeSlicer mode ('Before' or 'Between') so it renders a slider, not checkboxes
    flt_vis = json.loads((page_dir / "visuals" / "ca24fltslic000000024" / "visual.json").read_text(encoding="utf-8"))
    flt_mode = flt_vis["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
    assert flt_mode in {"'Before'", "'Between'"}, (
        f"ca24fltslic000000024 must use RangeSlicer mode 'Before' or 'Between' (not {flt_mode}, which falls back to checkboxes)"
    )

    # Verify ca23actinsp000000023 has only 1 unaggregated Column ('01 XER_TASK'[task_code]) to prevent multi-column Auto-Exist Cartesian explosion
    act_vis = json.loads((page_dir / "visuals" / "ca23actinsp000000023" / "visual.json").read_text(encoding="utf-8"))
    act_projs = act_vis["visual"]["query"]["queryState"]["Values"]["projections"]
    unagg_cols = [p["queryRef"] for p in act_projs if "Column" in p["field"]]
    assert unagg_cols == ["01 XER_TASK.task_code"], (
        f"ca23actinsp000000023 must have ONLY '01 XER_TASK.task_code' as an unaggregated Column, got {unagg_cols}"
    )

    # Check bookmarks
    bm_meta = json.loads((REPORT_DEF / "bookmarks" / "bookmarks.json").read_text(encoding="utf-8"))
    bm_names = {item["name"] for item in bm_meta["items"]}
    assert {"ca91openbm0000000091", "ca92closebm000000092"} <= bm_names, "Missing Calendar Analysis bookmarks"

    return {
        "page_id": PAGE_ID,
        "visual_count": len(visual_files),
        "synced_slicer_groups": sorted(sync_groups),
    }


def main() -> None:
    conservation = verify_conservation_laws()
    ca_measure_count = verify_tmdl_measures()
    pbir_summary = verify_pbir_page()

    # Run verify_integration.py (which executes TOM RoundTrip check via extract-model-metadata.ps1)
    proc = subprocess.run(
        ["python", str(ROOT / "scripts" / "resource_playground" / "verify_integration.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    integration_out = json.loads(proc.stdout)
    assert integration_out.get("result") == "PASS"
    assert integration_out.get("metadata_round_trip", {}).get("status") == "PASS"

    print(
        json.dumps(
            {
                "status": "PASS",
                "ca_measures_verified": ca_measure_count,
                "tom_metadata_round_trip": integration_out["metadata_round_trip"]["status"],
                "pbir": pbir_summary,
                "conservation_laws": conservation,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

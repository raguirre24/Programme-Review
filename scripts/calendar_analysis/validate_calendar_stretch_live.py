"""Read-only live checks of the Calendar Stretch columns and measures against the model open in Power BI Desktop.

    python scripts/calendar_analysis/validate_calendar_stretch_live.py --project J2060 --update 2026-02-28 \
        [--expect 26:3:N-C-3131-CPT-1320:168] [--task N-C-3131-CPT-1320] [--define] [--server localhost:<port>]

L1  'Finish Without Exceptions' and 'Calendar Delay Days' equal the Python closed form on every incomplete Activity row.
L3  KPI cards for the project update (page filters, float unrestricted) match --expect (>30 d, >90 d, worst activity, max days).
L4  Top-15 rows: timeline dates and shutdown bands equal the oracle built from the loaded calendar rows.
L5  Cliff chart: every non-blank axis date equals the day-by-day oracle, the window is complete, and the callout text matches.
L6  Query timings (warnings only): bars/Deneb and scatter under 1 s, cliff under 2 s.
L7  At most one incomplete row per (project, update, task_code).
--define injects the TMDL text as query-scoped DEFINE COLUMN/MEASURE (for a model opened before these changes);
the realigned table-11 dates themselves still need a refresh. The P6 reconciliation of the calendar itself is
validate_calendar_live.py.
"""

from __future__ import annotations

import argparse
import collections
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate_calendar_stretch import (  # noqa: E402
    callout_searches, exception_free_finish, need_days, nth_working_day, shutdown_bands,
)

DAY = timedelta(days=1)


def project_key(code: str) -> str:
    code = code.strip().upper()
    return f"CJ:{code[1:]}" if re.fullmatch(r"[CJ][0-9]+", code) else f"EXACT:{code}"


def filters(project: str, update: date) -> str:
    return (
        f'TREATAS({{"{project_key(project)}"}}, Project_Dimension[ProjectKey]), '
        f"TREATAS({{DATE({update.year},{update.month},{update.day})}}, CurrentDate[UpdateDate]), "
        "TREATAS({\"Activity\"}, '01 XER_TASK'[TaskType_Classified]), TREATAS({FALSE}, '01 XER_TASK'[Is Unscheduled]), "
        "TREATAS({\"Not Started\",\"In Progress\"}, '01 XER_TASK'[status_code]), TREATAS({FALSE}, '01 XER_TASK'[IsExcludedFromDataLake])"
    )


def iso(expression: str) -> str:
    return f'VAR __v = {expression} RETURN IF(NOT ISBLANK(__v), FORMAT(__v, "yyyy-MM-dd"))'


def queries(project: str, update: date, task: str | None) -> dict[str, str]:
    scope = filters(project, update)
    delayed = "FILTER(ALL('01 XER_TASK'[Calendar Delay Days]), '01 XER_TASK'[Calendar Delay Days] > 0)"
    top = (f"CALCULATETABLE(TOPN(15, VALUES('01 XER_TASK'[task_code]), CALCULATE(MAX('01 XER_TASK'[Calendar Delay Days])), DESC), "
           f"{scope}, {delayed})")
    cliff_task = f'TREATAS({{"{task}"}}, \'01 XER_TASK\'[task_code]), ' if task else ""
    return {
        "tasks": """EVALUATE SELECTCOLUMNS(
            FILTER('01 XER_TASK', '01 XER_TASK'[status_code] <> "Complete" && '01 XER_TASK'[TaskType_Classified] = "Activity"),
            "project", '01 XER_TASK'[ProjectCode], "programme", '01 XER_TASK'[ProgrammeType],
            "update", FORMAT('01 XER_TASK'[UpdateDate], "yyyy-MM-dd"), "task_code", '01 XER_TASK'[task_code],
            "start", FORMAT('01 XER_TASK'[Start], "yyyy-MM-dd"), "finish", FORMAT('01 XER_TASK'[Finish], "yyyy-MM-dd"),
            "data_date", FORMAT('01 XER_TASK'[data_date], "yyyy-MM-dd"), "remaining", '01 XER_TASK'[remaining_duration],
            "key", '01 XER_TASK'[calendar_id_key], "mask", RELATED('10 XER_CALENDARS'[Workweek Mask]),
            "nwf", FORMAT('01 XER_TASK'[Finish Without Exceptions], "yyyy-MM-dd"), "delay", '01 XER_TASK'[Calendar Delay Days],
            "critical", '01 XER_TASK'[CriticalStatus], "unscheduled", '01 XER_TASK'[Is Unscheduled],
            "excluded", '01 XER_TASK'[IsExcludedFromDataLake])""",
        "calendar": """EVALUATE SELECTCOLUMNS(
            FILTER('11 XER_CALENDAR_DETAILED', NOT ISBLANK('11 XER_CALENDAR_DETAILED'[date])),
            "key", '11 XER_CALENDAR_DETAILED'[clndr_id_key], "date", FORMAT('11 XER_CALENDAR_DETAILED'[date], "yyyy-MM-dd"),
            "hours", '11 XER_CALENDAR_DETAILED'[work_hours], "type", '11 XER_CALENDAR_DETAILED'[exception_type])""",
        "kpis": f"""EVALUATE CALCULATETABLE(ROW(
            "delayed", [CS KPI Delayed Activities], "severe", [CS KPI Severely Delayed Activities],
            "critical_days", [CS KPI Critical Delay Days], "max_days", [CS KPI Max Delay Days],
            "ratio", [CS KPI Worst Stretch Ratio], "default_task", [CS Cliff Task Code]), {scope})""",
        "bars": f"""EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[task_code], TREATAS({top}, '01 XER_TASK'[task_code]), {scope}, {delayed},
            "work", [CA Activity Remaining Working Days], "weekends", [CA Activity Standard Non-Working Days],
            "holidays", [CA Activity Exception Blackout Days], "delay", [CS Activity Calendar Delay Days])""",
        "deneb": f"""EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[task_code], TREATAS({top}, '01 XER_TASK'[task_code]), {scope}, {delayed},
            "name", [CA Activity Name], "delay", [CS Activity Calendar Delay Days],
            "timeline", [CS Activity Timeline Dates], "bands", [CS Activity Shutdown Bands])""",
        "scatter": f"""EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[task_code], '01 XER_TASK'[CriticalStatus], {scope}, {delayed},
            "x", [CA Activity Remaining Working Days], "y", [CS Activity Calendar Delay Days])""",
        "cliff": f"""EVALUATE SELECTCOLUMNS(
            SUMMARIZECOLUMNS('Scenario Date'[Date], {cliff_task}{scope},
                "finish", {iso("[CS Cliff Finish Date]")}, "shift", [CS Cliff Finish Shift Days]),
            "start", FORMAT('Scenario Date'[Date], "yyyy-MM-dd"), "finish", [finish], "shift", [shift])""",
        "callout": f"""EVALUATE CALCULATETABLE(ROW("task", [CS Cliff Task Code], "title", [CS Cliff Title], "callout", [CS Cliff Callout],
            "axis_end", FORMAT(CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date')), "yyyy-MM-dd")), {cliff_task}{scope})""",
    }


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{key.split("[")[-1].strip("]"): value for key, value in row.items()} for row in csv.DictReader(handle)]


def parse(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def number(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--update", required=True, type=date.fromisoformat)
    parser.add_argument("--task", help="Activity for the cliff checks (default: the page's default, the largest delay)")
    parser.add_argument("--expect", help="delayed>30:delayed>90:worst task:max delay days, e.g. 26:3:N-C-3131-CPT-1320:168")
    parser.add_argument("--define", action="store_true", help="Inject TMDL definitions as query-scoped DEFINE statements")
    parser.add_argument("--server")
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        (folder / "queries.json").write_text(json.dumps(queries(arguments.project, arguments.update, arguments.task)), encoding="utf-8")
        command = ["pwsh", "-NoProfile", "-File", str(HERE / "Invoke-ReadOnlyDax.ps1"), "-QueryFile", str(folder / "queries.json"),
                   "-OutputDirectory", str(folder / "out")]
        if arguments.server:
            command += ["-ServerAddress", arguments.server]
        if arguments.define:
            command.append("-DefineFromTmdl")
        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if run.returncode != 0:
            print(json.dumps({"status": "ERROR", "detail": (run.stderr or run.stdout).strip()[-3000:]}, indent=2))
            return 2
        model = json.loads(run.stdout.strip().splitlines()[-1])
        data = {name: read(folder / "out" / f"{name}.csv") for name in ("tasks", "calendar", "kpis", "bars", "deneb", "scatter", "cliff", "callout")}
        timings = json.loads((folder / "out" / "timings.json").read_text(encoding="utf-8-sig"))

    failures: list[str] = []
    warnings: list[str] = []
    exceptions: dict[str, dict[date, float]] = collections.defaultdict(dict)
    for row in data["calendar"]:
        hours = number(row["hours"])
        if hours is not None and row["type"] != "Exception - Invalid":
            exceptions[row["key"]][date.fromisoformat(row["date"])] = hours

    # L1 columns and L7 duplicates.
    checked = mismatched = 0
    seen = collections.Counter()
    for row in data["tasks"]:
        seen[(row["project"], row["update"], row["task_code"])] += 1
        start, data_date, finish = parse(row["start"]), parse(row["data_date"]), parse(row["finish"])
        effective = max(start, data_date) if start and data_date else start
        remaining = number(row["remaining"])
        expected = None
        if effective and finish and remaining is not None and len(row["mask"]) == 7 and need_days(remaining) >= 1:
            expected = exception_free_finish(effective, need_days(remaining), row["mask"])
        expected_delay = max(0, (finish - expected).days) if expected else None
        actual_delay = int(float(row["delay"])) if row["delay"] else None
        checked += 1
        if parse(row["nwf"]) != expected or actual_delay != expected_delay:
            mismatched += 1
            if mismatched <= 5:
                failures.append(f"L1 {row['task_code']} ({row['update']}): Finish Without Exceptions {row['nwf']} / delay {row['delay']}, expected {expected} / {expected_delay}")
    if mismatched > 5:
        failures.append(f"L1 {mismatched} of {checked} rows differ from the closed form")
    duplicates = {key: count for key, count in seen.items() if count > 1}
    if duplicates:
        failures.append(f"L7 {len(duplicates)} (project, update, task_code) keys have several incomplete rows, e.g. {next(iter(duplicates))}")

    # L3 KPIs.
    kpis = data["kpis"][0]
    if arguments.expect:
        delayed, severe, worst, max_days = arguments.expect.split(":")
        actual = (kpis["delayed"], kpis["severe"], kpis["default_task"], kpis["max_days"])
        if (int(float(actual[0])), int(float(actual[1])), actual[2], int(float(actual[3]))) != (int(delayed), int(severe), worst, int(max_days)):
            failures.append(f"L3 KPIs {actual} differ from expected {(delayed, severe, worst, max_days)}")

    # L4 timeline dates and shutdown bands for the Top-15 rows.
    rows_by_code = {(row["project"], row["update"], row["task_code"]): row for row in data["tasks"]}
    project_code = next((row["project"] for row in data["tasks"] if row["project"].upper() == arguments.project.upper()), arguments.project)
    for row in data["deneb"]:
        source = rows_by_code.get((project_code, arguments.update.isoformat(), row["task_code"]))
        if not source:
            failures.append(f"L4 {row['task_code']} not found in the task export")
            continue
        start, data_date, finish = parse(source["start"]), parse(source["data_date"]), parse(source["finish"])
        effective = max(start, data_date)
        expected_dates = "|".join(d.isoformat() for d in (effective, parse(source["nwf"]), finish, data_date))
        expected_bands = ";".join(f"{a.isoformat()}|{b.isoformat()}" for a, b in shutdown_bands(effective, finish, source["mask"], exceptions[source["key"]]))
        if row["timeline"] != expected_dates:
            failures.append(f"L4 {row['task_code']} timeline {row['timeline']} != {expected_dates}")
        if row["bands"] != expected_bands:
            failures.append(f"L4 {row['task_code']} bands {row['bands']!r} != {expected_bands!r}")
    if len(data["bars"]) != len(data["deneb"]) or not data["bars"]:
        failures.append(f"L4 bars returned {len(data['bars'])} rows and Deneb {len(data['deneb'])}")

    # L5 cliff chart and callout.
    callout = data["callout"][0]
    task = arguments.task or callout["task"]
    source = rows_by_code.get((project_code, arguments.update.isoformat(), task))
    cliff_points = 0
    if not source:
        failures.append(f"L5 cliff activity {task!r} not found")
    else:
        start, data_date, finish = parse(source["start"]), parse(source["data_date"]), parse(source["finish"])
        effective, need, mask = max(start, data_date), need_days(float(source["remaining"])), source["mask"]
        axis_end = date.fromisoformat(callout["axis_end"])
        window_start, window_end = max(data_date, effective - 60 * DAY), effective + 60 * DAY
        calendar = exceptions[source["key"]]
        finish_of = lambda day: nth_working_day(day, need, mask, calendar, axis_end)  # noqa: E731
        points = {row["start"]: row for row in data["cliff"] if row["finish"]}
        expected_points = (window_end - window_start).days + 1
        if len(points) != expected_points:
            failures.append(f"L5 cliff returned {len(points)} points, expected {expected_points} ({window_start}..{window_end})")
        for day_text, row in sorted(points.items()):
            day = date.fromisoformat(day_text)
            expected = finish_of(day)
            if parse(row["finish"]) != expected or int(float(row["shift"])) != (expected - finish).days:
                failures.append(f"L5 start {day}: finish {row['finish']} shift {row['shift']}, expected {expected}")
                break
            cliff_points += 1
        model_finish = finish_of(effective)
        recovery, slip = callout_searches(effective, window_start, window_end, finish_of)
        text = lambda day: day.strftime("%d-%b-%y")  # noqa: E731
        parts = []
        if recovery:
            parts.append(f"Start by {text(recovery)} ({(effective - recovery).days:,} days earlier) → finish {text(finish_of(recovery))}, "
                         f"{(model_finish - finish_of(recovery)).days:,} days sooner.")
        if slip:
            parts.append(f"If it starts after {text(slip - DAY)}, the finish jumps to {text(finish_of(slip))} (+{(finish_of(slip) - model_finish).days:,} days).")
        body = " ".join(parts) if parts else "no calendar cliff within 60 days of its remaining start; the finish moves day for day."
        caveat = "" if model_finish == finish else (f" The calendar model finishes on {text(model_finish)}, not the P6 finish {text(finish)}"
                                                      " (resource calendar or part-day duration).")
        expected_callout = f"{task}: {body}{caveat}"
        if callout["callout"] != expected_callout:
            failures.append(f"L5 callout {callout['callout']!r} != {expected_callout!r}")

    # L6 timings.
    for name, budget in (("bars", 1.0), ("deneb", 1.0), ("scatter", 1.0), ("cliff", 2.0), ("callout", 2.0)):
        if timings.get(name, 0) > budget:
            warnings.append(f"L6 {name} query took {timings[name]} s (budget {budget} s)")

    status = "PASS" if not failures else "FAIL"
    print(json.dumps({
        "status": status, "model": model, "rows_checked": checked, "cliff_points": cliff_points,
        "kpis": kpis, "top_rows": [row["task_code"] for row in data["bars"]][:15], "callout": callout.get("callout"),
        "timings_s": timings, "failures": failures, "warnings": warnings,
    }, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

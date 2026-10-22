"""Static, oracle and PBIR verification for the Calendar Stretch page (calendar-driven delay visuals).

Checks the two '01 XER_TASK' columns and the CS measures in TMDL, mirrors their algorithms in Python against
day-by-day brute force (finish without exceptions, shutdown bands, cliff-edge search and its horizon), asserts the canonical
J2060 seasonal-asphalt case, and checks the PBIR page, filters, interactions, bookmarks and the Deneb spec.
Read-only; the DAX itself is exercised against the open model by validate_calendar_stretch_live.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
import json
import math
from pathlib import Path
import random
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate_stretch_page as page_generator  # noqa: E402
import stretch_dax  # noqa: E402
from validate_calendar_analysis import measure_blocks, verify_workweek_mask_formula  # noqa: E402

ROOT = HERE.parents[1]
MODEL_DEF = ROOT / "Project Review - Programme (datalake).SemanticModel" / "definition"
REPORT_DEF = ROOT / "Project Review - Programme (datalake).Report" / "definition"
DAY = timedelta(days=1)

EXPECTED_CS_MEASURES = {
    "CS Activity Calendar Delay Days", "CS Activity Effective Start", "CS Activity Finish Without Exceptions",
    "CS Activity Timeline Dates", "CS Activity Shutdown Bands",
    "CS KPI Delayed Activities", "CS KPI Severely Delayed Activities", "CS KPI Critical Delay Days",
    "CS KPI Max Delay Days", "CS KPI Worst Stretch Ratio", "CS Scope Prompt",
    "CS Cliff Task Code", "CS Cliff Finish Date", "CS Cliff Finish Shift Days", "CS Cliff Title", "CS Cliff Callout",
}
ACTIVITY_MEASURES = {name for name in EXPECTED_CS_MEASURES if name.startswith("CS Activity ")}
KPI_MEASURES = {name for name in EXPECTED_CS_MEASURES if name.startswith("CS KPI ")}
ACTIVITY_GATE = "TaskRows > 0 && ISINSCOPE('01 XER_TASK'[task_code]) && [CA Inspector Scope Ready]"


# ---------------------------------------------------------------------------------------------------------------
# Python mirrors of the DAX (same steps), and brute-force oracles
# ---------------------------------------------------------------------------------------------------------------

def need_days(remaining: float) -> int:
    """DAX INT(CEILING(ROUND(x, 4), 1)); DAX ROUND is half away from zero (not Python's banker's rounding)."""
    rounded = Decimal(str(remaining)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return math.ceil(rounded)


def exception_free_finish(start: date, need: int, mask: str) -> date | None:
    work_days = mask.count("1")
    if len(mask) != 7 or work_days == 0 or need < 1:
        return None
    full_weeks = (need - 1) // work_days
    rank = need - full_weeks * work_days
    week = (mask + mask)[start.isoweekday() - 1:start.isoweekday() - 1 + 7]
    offset = [index for index, flag in enumerate(week, start=1) if flag == "1"][rank - 1]  # FIND("X", SUBSTITUTE(.., r))
    return start + timedelta(days=full_weeks * 7 + offset - 1)


def is_working(day: date, mask: str, exceptions: dict[date, float]) -> bool:
    hours = exceptions.get(day)
    return hours > 0 if hours is not None else mask[day.isoweekday() - 1] == "1"


def nth_working_day(start: date, need: int, mask: str, exceptions: dict[date, float], limit: date) -> date | None:
    day, count = start, 0
    while day <= limit:
        if is_working(day, mask, exceptions):
            count += 1
            if count == need:
                return day
        day += DAY
    return None


def shutdown_bands(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> list[tuple[date, date]]:
    """Mirror of 'CS Activity Shutdown Bands'."""
    fetch_from, fetch_to = effective - 7 * DAY, finish + 7 * DAY
    window = {day: hours for day, hours in exceptions.items() if fetch_from <= day <= fetch_to}
    closed = sorted(day for day, hours in window.items() if hours <= 0)
    opened = sorted(day for day, hours in window.items() if hours > 0)
    off_per_week = mask.count("0")
    double, reverse = mask + mask, mask[::-1]
    heads = []
    for day in closed:
        previous = max((other for other in closed if other < day), default=None)
        if previous is None:
            heads.append(day)
            continue
        gap = (day - previous).days - 1
        start_dow, extra = (previous + DAY).isoweekday(), gap % 7
        gap_off = (gap // 7) * off_per_week + extra - double[start_dow - 1:start_dow - 1 + extra].count("1")
        if gap_off < gap or any(previous < other < day for other in opened):
            heads.append(day)
    bands = []
    for head in heads:
        position = 8 - (head - DAY).isoweekday()
        off_before = ((reverse + reverse)[position - 1:position - 1 + 7] + "1").find("1")
        last_opened = max((other for other in opened if other < head), default=None)
        back = off_before if last_opened is None else min(off_before, (head - last_opened).days - 1)
        start = max(fetch_from, head - back * DAY)
        next_head = min((other for other in heads if other > head), default=None)
        tail = max(other for other in closed if other >= head and (next_head is None or other < next_head))
        dow = (tail + DAY).isoweekday()
        off_after = ((double)[dow - 1:dow - 1 + 7] + "1").find("1")
        next_opened = min((other for other in opened if other > tail), default=None)
        forward = off_after if next_opened is None else min(off_after, (next_opened - tail).days - 1)
        end = min(fetch_to, tail + forward * DAY)
        clipped = (max(start, effective), min(end, finish))
        if (end - start).days + 1 >= 7 and clipped[1] >= clipped[0]:
            bands.append(clipped)
    return sorted(bands)


def brute_bands(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> list[tuple[date, date]]:
    fetch_from, fetch_to = effective - 7 * DAY, finish + 7 * DAY
    runs, run_start, day = [], None, fetch_from
    while day <= fetch_to + DAY:
        non_working = day <= fetch_to and not is_working(day, mask, exceptions)
        if non_working and run_start is None:
            run_start = day
        if not non_working and run_start is not None:
            runs.append((run_start, day - DAY))
            run_start = None
        day += DAY
    return sorted((max(a, effective), min(b, finish)) for a, b in runs
                  if (b - a).days + 1 >= 7 and min(b, finish) >= max(a, effective))


def cliff_finish(candidate: date, need: int, mask: str, exceptions: dict[date, float], search_end: date) -> date | None:
    """Mirror of 'CS Cliff Finish Date': closed form when no exception delta precedes it, else 13-level bisection up to
    SearchEnd = MIN(axis end, scheduled finish + stretch_dax.SEARCH_MARGIN_DAYS)."""
    deltas = sorted((day, (1 if hours > 0 else 0) - (1 if mask[day.isoweekday() - 1] == "1" else 0))
                    for day, hours in exceptions.items() if day >= candidate)
    deltas = [(day, delta) for day, delta in deltas if delta != 0]
    work_days, start_dow, double = mask.count("1"), candidate.isoweekday(), mask + mask

    def through(probe: date) -> int:
        span = (probe - candidate).days + 1
        return (span // 7) * work_days + double[start_dow - 1:start_dow - 1 + span % 7].count("1") + \
            sum(delta for day, delta in deltas if day <= probe)

    normal = exception_free_finish(candidate, need, mask)
    if not any(day <= normal for day, _ in deltas):
        found = normal
    else:
        low, high = candidate - DAY, search_end
        for _ in range(stretch_dax.FINISH_LEVELS):
            middle = low + timedelta(days=(high - low).days // 2)
            if through(middle) >= need:
                high = middle
            else:
                low = middle
        found = high if through(search_end) >= need else None
    return found if found is not None and found <= search_end else None


def search_end(window_end: date, scheduled: date, need: int, mask: str, exceptions: dict[date, float], axis_end: date) -> date:
    """Mirror of the kernel's SearchEnd: scheduled finish + margin when the latest window start completes by then, else the axis end."""
    near = min(axis_end, scheduled + stretch_dax.SEARCH_MARGIN_DAYS * DAY)
    return near if nth_working_day(window_end, need, mask, exceptions, near) is not None else axis_end


def callout_searches(effective: date, window_start: date, window_end: date, finish_of) -> tuple[date | None, date | None]:
    """Mirror of 'CS Cliff Callout': one pass over the window; latest earlier start finishing 7+ days sooner, earliest
    later start finishing 7+ days later."""
    model = finish_of(effective)
    starts = [window_start + timedelta(days=i) for i in range((window_end - window_start).days + 1)]
    finishes = {day: finish_of(day) for day in starts}
    recovery = max((d for d in starts if d < effective and finishes[d] is not None and finishes[d] <= model - 7 * DAY), default=None)
    slip = min((d for d in starts if d > effective and finishes[d] is not None and finishes[d] >= model + 7 * DAY), default=None)
    return recovery, slip


def random_calendar(rng: random.Random) -> tuple[str, dict[date, float]]:
    mask = "0000000"
    while "1" not in mask:
        mask = "".join(rng.choice("1110") for _ in range(7))
    exceptions: dict[date, float] = {}
    origin = date(2026, 1, 1)
    for _ in range(rng.randint(0, 6)):  # shutdown blocks of closed working days
        start = origin + timedelta(days=rng.randint(0, 600))
        for offset in range(rng.randint(3, 160)):
            day = start + timedelta(days=offset)
            if mask[day.isoweekday() - 1] == "1":
                exceptions[day] = 0.0
    for _ in range(rng.randint(0, 25)):  # single holidays, rostered days off, working weekend days, hour-only changes
        day = origin + timedelta(days=rng.randint(0, 760))
        exceptions[day] = rng.choice([0.0, 0.0, 0.0, 8.0, 4.0])
    return mask, exceptions


def verify_oracles() -> dict:
    cases = 0
    for remaining, expected in ((0.4, 1), (1.0, 1), (1.25, 2), (3.99999999, 4), (4.00004, 4), (4.00005, 5)):
        assert need_days(remaining) == expected, f"Need days for {remaining} should be {expected}"
    for bits in range(1, 128):
        mask = format(bits, "07b")
        for start_offset in range(7):
            start = date(2027, 1, 4) + timedelta(days=start_offset)
            for need in range(1, 61):
                assert exception_free_finish(start, need, mask) == nth_working_day(start, need, mask, {}, start + 500 * DAY), (
                    f"Finish without exceptions wrong for mask {mask}, start {start}, need {need}")
                cases += 1
    assert exception_free_finish(date(2027, 4, 16), 4, "0000000") is None

    rng = random.Random(20261022)
    band_cases = cliff_cases = margin_cases = 0
    axis_end = date(2030, 12, 31)
    for _ in range(1500):
        mask, exceptions = random_calendar(rng)
        effective = date(2026, 1, 1) + timedelta(days=rng.randint(0, 500))
        finish = effective + timedelta(days=rng.randint(0, 300))
        assert shutdown_bands(effective, finish, mask, exceptions) == brute_bands(effective, finish, mask, exceptions), (
            f"Shutdown bands differ: mask {mask}, window {effective}..{finish}")
        band_cases += 1
        need = rng.randint(1, 120)
        scheduled = nth_working_day(effective, need, mask, exceptions, axis_end)
        if scheduled is None:
            continue
        horizon = search_end(effective + 60 * DAY, scheduled, need, mask, exceptions, axis_end)
        margin_cases += horizon < axis_end
        for _ in range(10):
            candidate = effective + timedelta(days=rng.randint(-60, 60))
            # Exact: the capped search equals an unlimited day-by-day search for every start in the window.
            assert cliff_finish(candidate, need, mask, exceptions, horizon) == nth_working_day(
                candidate, need, mask, exceptions, axis_end), f"Cliff finish differs: mask {mask}, start {candidate}, need {need}"
            cliff_cases += 1

    # Canonical J2060 Feb-2026 case: N-C-3131-CPT-1320, M80RR 5d Seasonal Asphalt (corrected exception dates).
    mask = "1111100"
    asphalt = {date(2027, 4, 12): 0.0, date(2027, 10, 1): 0.0, date(2027, 10, 11): 0.0, date(2027, 10, 25): 0.0,
               date(2027, 11, 2): 0.0}
    day = date(2027, 4, 19)
    while day <= date(2027, 9, 30):
        if day.isoweekday() <= 5:
            asphalt[day] = 0.0
        day += DAY
    effective, finish = date(2027, 4, 16), date(2027, 10, 6)
    normal = exception_free_finish(effective, need_days(4.0), mask)
    assert normal == date(2027, 4, 21) and (finish - normal).days == 168, "Canonical delay should be 168 days"
    assert shutdown_bands(effective, finish, mask, asphalt) == [(date(2027, 4, 17), date(2027, 10, 3))]
    horizon = search_end(effective + 60 * DAY, finish, 4, mask, asphalt, date(2036, 12, 31))
    assert horizon == finish + stretch_dax.SEARCH_MARGIN_DAYS * DAY, "Canonical case should use the near search horizon"
    finish_of = lambda start: cliff_finish(start, 4, mask, asphalt, horizon)  # noqa: E731
    assert finish_of(date(2027, 4, 13)) == date(2027, 4, 16)
    assert finish_of(date(2027, 4, 14)) == date(2027, 10, 4)
    assert finish_of(effective) == finish
    recovery, slip = callout_searches(effective, effective - 60 * DAY, effective + 60 * DAY, finish_of)
    assert recovery == date(2027, 4, 13) and slip is None, f"Canonical callout should recover from 13-Apr-27, got {recovery}, {slip}"
    assert (finish - finish_of(recovery)).days == 173
    return {"exception_free_finish_cases": cases, "band_cases": band_cases, "cliff_cases": cliff_cases, "search_margin_cases": margin_cases}


# ---------------------------------------------------------------------------------------------------------------
# TMDL contracts
# ---------------------------------------------------------------------------------------------------------------

def column_block(text: str, name: str) -> str:
    header = re.search(rf"^\tcolumn '{re.escape(name)}' =", text, flags=re.M)
    assert header, f"Missing calculated column '01 XER_TASK'[{name}]"
    following = re.search(r"^\t(?:///|column |measure |partition |annotation )", text[header.end():], flags=re.M)
    return text[header.start(): header.end() + (following.start() if following else len(text))]


def verify_tmdl() -> int:
    task = (MODEL_DEF / "tables" / "01 XER_TASK.tmdl").read_text(encoding="utf-8")
    finish = column_block(task, "Finish Without Exceptions")
    for token in ("RELATED('10 XER_CALENDARS'[Workweek Mask])", "INT(CEILING(ROUND(RemWork, 4), 1))",
                  'FIND("X", SUBSTITUTE(WeekFromStart, "1", "X", LastWeekRank))', "MID(WorkweekMask & WorkweekMask, WEEKDAY(EffectiveStart, 2), 7)",
                  "'01 XER_TASK'[status_code] <> \"Complete\"", "'01 XER_TASK'[TaskType_Classified] = \"Activity\""):
        assert token in finish, f"'Finish Without Exceptions' must contain {token}"
    delay = column_block(task, "Calendar Delay Days")
    assert "MAX(0, INT('01 XER_TASK'[Finish] - ExceptionFreeFinish))" in delay
    for block in (finish, delay):
        assert "CALCULATE" not in block, "Calendar Stretch columns must stay row-local (no CALCULATE)"
        assert "displayFolder: Calendar Stretch" in block

    blocks = measure_blocks((MODEL_DEF / "tables" / "XER Measures.tmdl").read_text(encoding="utf-8"))
    cs = {name: body for name, body in blocks.items() if name.startswith("CS ")}
    assert set(cs) == EXPECTED_CS_MEASURES, f"CS measures differ: missing {EXPECTED_CS_MEASURES - set(cs)}, extra {set(cs) - EXPECTED_CS_MEASURES}"
    for name, body in cs.items():
        assert re.findall(r"^\t\tdisplayFolder:\s*(.+)$", body, flags=re.M) == ["Calendar Stretch"], f"{name} folder"
        bad = {v.lower() for v in re.findall(r"\bVAR\s+([A-Za-z0-9_]+)\s*=", body)} & {"firstdate", "lastdate", "updates", "key", "ordinal"}
        assert not bad, f"{name} uses forbidden variable names {bad}"
    for name in ACTIVITY_MEASURES:
        body = cs[name]
        assert body.count("VAR TaskRows = COUNTROWS('01 XER_TASK')") == 1 and body.count(ACTIVITY_GATE) == 1, f"{name} gate"
        assert "MAXX(\n" in body or "MAXX('01 XER_TASK'," in body, f"{name} must compute on row values inside MAXX('01 XER_TASK', ...)"
        for forbidden in ("'Scenario Calendar'", "'Scenario Date'", "CROSSFILTER", "MIN('01 XER_TASK'[Start])",
                          "MAX('01 XER_TASK'[Finish])", "SUM('01 XER_TASK'[remaining_duration])"):
            assert forbidden not in body, f"{name} must not contain {forbidden}"
    assert "'11 XER_CALENDAR_DETAILED'" in cs["CS Activity Shutdown Bands"]
    assert "[Calendar Delay Days] > 0 && LEN(WorkweekMask) = 7" in cs["CS Activity Shutdown Bands"], "Bands only for delayed activities"
    for name in KPI_MEASURES:
        body = cs[name]
        for forbidden in ("'11 XER_CALENDAR_DETAILED'", "'Scenario Date'", "[CA Inspector"):
            assert forbidden not in body, f"{name} must not contain {forbidden}"
        assert "FILTER('01 XER_TASK'" not in body, f"{name} must use column predicates, not FILTER over the fact table"
    for name in ("CS KPI Delayed Activities", "CS KPI Severely Delayed Activities", "CS KPI Worst Stretch Ratio"):
        assert "KEEPFILTERS('01 XER_TASK'[Calendar Delay Days] >" in cs[name], f"{name} must filter the delay column"

    kernel = cs["CS Cliff Finish Date"]
    assert "SELECTEDVALUE('Scenario Date'[Date])" in kernel and "TREATAS({ CalKey }, '11 XER_CALENDAR_DETAILED'[clndr_id_key])" in kernel
    assert kernel.index("CandidateStart >= WindowStart && CandidateStart <= WindowEnd") < kernel.index("CALCULATETABLE(\n"), (
        "The cliff window check must come before any table-11 access")
    for forbidden in ("GENERATESERIES", "CALENDAR(", "CROSSJOIN", "CALENDARAUTO"):
        assert forbidden not in "".join(cs[n] for n in cs if n.startswith("CS Cliff")), f"Cliff measures must not build date series ({forbidden})"
    normalised = {name: body.replace("\r\n", "\n") for name, body in cs.items()}
    assert stretch_dax.finish_search(stretch_dax.FINISH_PAD) in normalised["CS Cliff Finish Date"], "Re-render stretch_dax finish levels"
    assert f"VAR NearEnd = MIN(AxisEnd, ScheduledFinish + {stretch_dax.SEARCH_MARGIN_DAYS})" in kernel, "Kernel must cap the search near the scheduled finish"
    assert "VAR SearchEnd = IF(NearReached, NearEnd, AxisEnd)" in kernel and "TREATAS(WorkingWeekdays, '11 XER_CALENDAR_DETAILED'[day_of_week_num])" in kernel, (
        "The cap must only apply when the latest window start completes by it (exact results)")
    callout = cs["CS Cliff Callout"]
    assert '"__Finish", [CS Cliff Finish Date]' in callout and "'Scenario Date'[Date] >= WindowStart" in callout, (
        "The callout must evaluate the window in one pass over 'Scenario Date'")
    assert "CALCULATE([CS Cliff Finish Date]" not in callout, "The callout must not probe the kernel date by date (each probe repeats its fixed cost)"
    scenario = (MODEL_DEF / "tables" / "Scenario Date.tmdl").read_text(encoding="utf-8")
    assert "YEAR ( TODAY () ) - 1, 1, 1" in scenario and "YEAR ( TODAY () ) + 10, 12, 31" in scenario, "Scenario Date span changed"
    assert stretch_dax.FINISH_LEVELS >= stretch_dax.levels_needed(12 * 366), "Too few bisection levels for the Scenario Date axis"

    tags = re.findall(r"lineageTag: ([0-9a-f-]{36})", "\n".join(
        (MODEL_DEF / "tables" / name).read_text(encoding="utf-8") for name in ("01 XER_TASK.tmdl", "XER Measures.tmdl")))
    assert len(tags) == len(set(tags)), "Duplicate lineageTags"
    return len(cs)


# ---------------------------------------------------------------------------------------------------------------
# PBIR contracts
# ---------------------------------------------------------------------------------------------------------------

DESKTOP_MANAGED_KEYS = {"$schema", "active", "stateManagement", "developer"}


def desktop_neutral(value):
    """Drop what Power BI Desktop and Deneb add or bump when they save a generated visual: the visualContainer $schema
    version, projection 'active' flags, and Deneb's managed state (stateManagement, developer, vega.properties.version)."""
    if isinstance(value, dict):
        result = {key: desktop_neutral(item) for key, item in value.items() if key not in DESKTOP_MANAGED_KEYS}
        for entry in result.get("vega", []) if isinstance(result.get("vega"), list) else []:
            entry.get("properties", {}).pop("version", None)
        return result
    if isinstance(value, list):
        return [desktop_neutral(item) for item in value]
    return value


def verify_pbir() -> dict:
    outputs = page_generator.build(3)
    for relative, value in outputs.items():
        path = REPORT_DEF / relative
        assert path.exists() and desktop_neutral(json.loads(path.read_text(encoding="utf-8-sig"))) == desktop_neutral(value), (
            f"{relative} differs from generate_stretch_page.py beyond Desktop/Deneb round-trip details; run it with --check")

    order = json.loads((REPORT_DEF / "pages" / "pages.json").read_text(encoding="utf-8-sig"))["pageOrder"]
    assert order.index(page_generator.PAGE) == order.index(page_generator.SOURCE_PAGE) + 1, "Calendar Stretch must follow Calendar Analysis"
    page_dir = REPORT_DEF / "pages" / page_generator.PAGE
    page = json.loads((page_dir / "page.json").read_text(encoding="utf-8-sig"))
    assert page["displayName"] == "Calendar Stretch" and page["width"] == 1920 and page["height"] == 1080
    page_filters = {f["field"]["Column"]["Property"]: f for f in page["filterConfig"]["filters"]}
    assert {"Is Unscheduled", "TaskType_Classified", "status_code", "Float Category"} <= set(page_filters)

    visuals = {path.parent.name: json.loads(path.read_text(encoding="utf-8-sig")) for path in (page_dir / "visuals").glob("*/visual.json")}
    assert len(visuals) == 26, f"Expected 26 visuals, found {len(visuals)}"
    types = {name: v["visual"]["visualType"] for name, v in visuals.items()}
    assert types[page_generator.BARS] == "barChart" and types[page_generator.SCATTER] == "scatterChart"
    assert types[page_generator.TIMELINE] == page_generator.DENEB and types[page_generator.CLIFF] == "lineChart"
    assert types[page_generator.CALLOUT] == "card"
    sync = {v["visual"]["syncGroup"]["groupName"] for v in visuals.values() if "syncGroup" in v["visual"]}
    assert sync == {"Project", "State", "last_recalc_date", "Level_2"}, f"Sync groups {sync}"
    slider = visuals["cs24fltslic000000024"]
    assert "filterConfig" not in slider and "numericEnd" not in slider["visual"]["objects"]["data"][0]["properties"], (
        "The Calendar Stretch float slider starts unrestricted")

    filter_names = []
    for name, v in visuals.items():
        filters = v.get("filterConfig", {}).get("filters", [])
        filter_names += [f["name"] for f in filters]
        assert "Measure" not in json.dumps(filters), f"{name} has a measure filter; use column filters only"
        assert "'Scenario Calendar'" not in json.dumps(v) and "Scenario Calendar" not in json.dumps(v.get("visual", {}).get("query", {})), (
            f"{name} must not bind Scenario Calendar (it would change the CA Inspector Selection Match gate)")
        assert '"Property": "Month"' not in json.dumps(v.get("visual", {}).get("query", {})), f"{name} must not bind 'Scenario Date'[Month]"
    assert len(filter_names) == len(set(filter_names)), "Filter names must be unique on the page"
    for name in (page_generator.BARS, page_generator.TIMELINE):
        filters = {f["type"]: f for f in visuals[name]["filterConfig"]["filters"]}
        query = filters["TopN"]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]
        assert query["Top"] == 15 and query["OrderBy"][0]["Direction"] == 2
        aggregation = query["OrderBy"][0]["Expression"]["Aggregation"]
        assert aggregation["Function"] == 4 and aggregation["Expression"]["Column"]["Property"] == "Calendar Delay Days"
    for name in (page_generator.BARS, page_generator.TIMELINE, page_generator.SCATTER):
        advanced = [f for f in visuals[name]["filterConfig"]["filters"] if f["type"] == "Advanced"]
        condition = advanced[0]["filter"]["Where"][0]["Condition"]["Comparison"]
        assert condition["ComparisonKind"] == 1 and condition["Right"]["Literal"]["Value"] == "0L"
    scatter = visuals[page_generator.SCATTER]["visual"]
    assert scatter["objects"]["categoryAxis"][0]["properties"]["logAxisScale"]["expr"]["Literal"]["Value"] == "true"
    cliff = visuals[page_generator.CLIFF]["visual"]
    assert cliff["query"]["queryState"]["Category"]["projections"][0]["queryRef"] == "Scenario Date.Date"
    assert cliff["objects"]["lineStyles"][0]["properties"]["lineChartType"]["expr"]["Literal"]["Value"] == "'step'"

    interactions = {(i["source"], i["target"]): i["type"] for i in page["visualInteractions"]}
    for source in (page_generator.BARS, page_generator.TIMELINE, page_generator.SCATTER):
        for target in (page_generator.CALLOUT, page_generator.CLIFF):
            assert interactions.get((source, target)) == "DataFilter", f"{source} must select the cliff activity"
        for target in page_generator.KPIS:
            assert interactions.get((source, target)) == "NoFilter"
    for target in visuals:
        if target != page_generator.CLIFF:
            assert interactions.get((page_generator.CLIFF, target)) == "NoFilter", f"Cliff chart must not filter {target}"

    report = json.loads((REPORT_DEF / "report.json").read_text(encoding="utf-8-sig"))
    assert page_generator.DENEB in report.get("publicCustomVisuals", []), "Deneb must be registered in report.json"
    deneb = visuals[page_generator.TIMELINE]["visual"]
    vega = deneb["objects"]["vega"][0]["properties"]
    assert vega["provider"]["expr"]["Literal"]["Value"] == "'vegaLite'"
    assert vega["enableSelection"]["expr"]["Literal"]["Value"] == "true"
    literal = vega["jsonSpec"]["expr"]["Literal"]["Value"]
    spec = json.loads(literal[1:-1].replace("''", "'"))
    names = {p["displayName"] for p in deneb["query"]["queryState"]["dataset"]["projections"]}
    derived = set(re.findall(r'"as":\s*"([^"]+)"', json.dumps(spec))) | {"band", "__selected__", "dates"}
    referenced = set(re.findall(r"datum\['([^']+)'\]", json.dumps(spec))) | set(re.findall(r'"field":\s*"([^"]+)"', json.dumps(spec)))
    referenced |= set(re.findall(r"datum\.([A-Za-z_]+)", json.dumps(spec)))
    unknown = referenced - names - derived
    assert not unknown, f"Deneb spec references unknown fields {sorted(unknown)}"
    for name in names:
        assert not set(name) & set(".[]\\\""), f"Deneb field name {name!r} contains characters Deneb rewrites"

    bookmarks = {item["name"] for item in json.loads((REPORT_DEF / "bookmarks" / "bookmarks.json").read_text(encoding="utf-8-sig"))["items"]}
    assert set(page_generator.BOOKMARKS.values()) <= bookmarks
    for bookmark in page_generator.BOOKMARKS.values():
        data = json.loads((REPORT_DEF / "bookmarks" / f"{bookmark}.bookmark.json").read_text(encoding="utf-8-sig"))
        assert data["explorationState"]["activeSection"] == page_generator.PAGE
        assert data["options"]["targetVisualNames"] == ["cs10menubg0000000010", "cs11state00000000011", "cs12proj000000000012", "cs13closebt000000013"]
    return {"page": page_generator.PAGE, "visuals": len(visuals), "deneb_fields": sorted(names)}


def main() -> None:
    mask_cases = verify_workweek_mask_formula()
    oracles = verify_oracles()
    measures = verify_tmdl()
    pbir = verify_pbir()
    print(json.dumps({"status": "PASS", "cs_measures": measures, "workweek_mask_cases": mask_cases,
                      "oracles": oracles, "pbir": pbir}, indent=2))


if __name__ == "__main__":
    main()

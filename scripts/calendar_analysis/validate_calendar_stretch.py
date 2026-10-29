"""Static, oracle and PBIR verification for Calendar Stretch: the calendar-driven delay columns, measures and the Delay
view of the Calendar page.

Checks the two '01 XER_TASK' columns and the CS measures in TMDL, mirrors their algorithms in Python against
day-by-day brute force (finish without exceptions, shutdown bands, cliff-edge search and its horizon), asserts the canonical
J2060 seasonal-asphalt case, and checks the Delay view's visuals, filters, interactions, view bookmarks and the Deneb spec.
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
import generate_stretch_view as view_generator  # noqa: E402
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
    "CS Cliff Task Code", "CS Cliff Start Date", "CS Cliff Shutdown", "CS Cliff Edge Date", "CS Cliff Window Start",
    "CS Cliff Window End", "CS Cliff Finish Date", "CS Cliff Finish Shift Days", "CS Cliff Title", "CS Cliff Callout",
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


def shutdown_runs(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> list[tuple[date, date]]:
    """Runs of 'CS Activity Shutdown Bands' and 'CS Cliff Shutdown' (any length), clipped to the fetch window."""
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
    runs = []
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
        runs.append((start, min(fetch_to, tail + forward * DAY)))
    return runs


def shutdown_bands(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> list[tuple[date, date]]:
    """Mirror of 'CS Activity Shutdown Bands'."""
    bands = []
    for start, end in shutdown_runs(effective, finish, mask, exceptions):
        clipped = (max(start, effective), min(end, finish))
        if (end - start).days + 1 >= 7 and clipped[1] >= clipped[0]:
            bands.append(clipped)
    return sorted(bands)


def cliff_shutdown(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> tuple[date, date] | None:
    """Mirror of 'CS Cliff Shutdown': the first 7+ day run starting after the remaining start and by the finish."""
    if len(mask) != 7 or finish <= effective:
        return None
    hits = [(start, end) for start, end in shutdown_runs(effective, finish, mask, exceptions)
            if (end - start).days + 1 >= 7 and effective < start <= finish]
    return min(hits) if hits else None


def brute_cliff_shutdown(effective: date, finish: date, mask: str, exceptions: dict[date, float]) -> tuple[date, date] | None:
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
    hits = [(a, b) for a, b in runs if (b - a).days + 1 >= 7 and effective < a <= finish]
    return min(hits) if hits else None


def edge_date(data_date: date, last_day: date, need: int, mask: str, exceptions: dict[date, float]) -> date | None:
    """Mirror of 'CS Cliff Edge Date': latest start in [data_date, last_day] with at least `need` working days through
    last_day (the day before the shutdown), by closed-form counts plus deltas and a 13-level backward bisection."""
    if last_day < data_date or need < 1 or "1" not in mask:
        return None
    deltas = [(day, (1 if hours > 0 else 0) - (1 if mask[day.isoweekday() - 1] == "1" else 0))
              for day, hours in exceptions.items() if data_date <= day <= last_day]
    deltas = [(day, delta) for day, delta in deltas if delta != 0]
    work_days, double = mask.count("1"), mask + mask

    def back(probe: date) -> int:
        span = (last_day - probe).days + 1
        dow = probe.isoweekday()
        return (span // 7) * work_days + double[dow - 1:dow - 1 + span % 7].count("1") + \
            sum(delta for day, delta in deltas if day >= probe)

    if back(data_date) < need:
        return None
    low, high = data_date, last_day + DAY
    for _ in range(stretch_dax.FINISH_LEVELS):
        middle = low + timedelta(days=(high - low).days // 2)
        if back(middle) >= need:
            low = middle
        else:
            high = middle
    return low


def brute_edge(data_date: date, last_day: date, need: int, mask: str, exceptions: dict[date, float]) -> date | None:
    count, day = 0, last_day
    while day >= data_date:
        count += is_working(day, mask, exceptions)
        if count >= need:
            return day
        day -= DAY
    return None


def cliff_window(data_date: date, effective: date, edge: date | None, shutdown_start: date | None) -> tuple[date, date]:
    """Mirror of 'CS Cliff Window Start' / 'CS Cliff Window End'."""
    sd = stretch_dax
    if edge is not None:
        wanted = max(edge - sd.WINDOW_BEFORE_EDGE * DAY, effective - sd.WINDOW_MAX_BEFORE * DAY)
    else:
        wanted = effective - sd.WINDOW_DEFAULT * DAY
    if shutdown_start is not None:
        end = min(effective + sd.WINDOW_MAX_AFTER * DAY, shutdown_start + sd.WINDOW_AFTER_SHUTDOWN * DAY)
    else:
        end = effective + sd.WINDOW_DEFAULT * DAY
    return max(data_date, wanted), end


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
    """Mirror of 'CS Cliff Callout' without a shutdown: one pass over the window; latest earlier start saving 7+ net
    calendar days, earliest later start adding 7+ net calendar days."""
    model = finish_of(effective)
    starts = [window_start + timedelta(days=i) for i in range((window_end - window_start).days + 1)]
    finishes = {day: finish_of(day) for day in starts}
    recovery = max((d for d in starts if d < effective and finishes[d] is not None
                    and (model - finishes[d]).days - (effective - d).days >= 7), default=None)
    slip = min((d for d in starts if d > effective and finishes[d] is not None
                and (finishes[d] - model).days - (d - effective).days >= 7), default=None)
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
    band_cases = cliff_cases = margin_cases = edge_cases = 0
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
        shutdown = cliff_shutdown(effective, scheduled, mask, exceptions)
        assert shutdown == brute_cliff_shutdown(effective, scheduled, mask, exceptions), (
            f"Cliff shutdown differs: mask {mask}, window {effective}..{scheduled}")
        data_date = effective - timedelta(days=rng.randint(0, 400))
        if shutdown:
            edge = edge_date(data_date, shutdown[0] - DAY, need, mask, exceptions)
            assert edge == brute_edge(data_date, shutdown[0] - DAY, need, mask, exceptions), (
                f"Edge differs: mask {mask}, shutdown {shutdown}, need {need}")
            if edge:  # the edge is the last start that finishes before the shutdown
                assert nth_working_day(edge, need, mask, exceptions, axis_end) < shutdown[0]
                assert nth_working_day(edge + DAY, need, mask, exceptions, axis_end) > shutdown[1]
                assert edge < effective
            edge_cases += 1
        horizon = search_end(effective + stretch_dax.WINDOW_MAX_AFTER * DAY, scheduled, need, mask, exceptions, axis_end)
        margin_cases += horizon < axis_end
        for _ in range(10):
            candidate = effective + timedelta(days=rng.randint(-stretch_dax.WINDOW_MAX_BEFORE, stretch_dax.WINDOW_MAX_AFTER))
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
    shutdown = cliff_shutdown(effective, finish, mask, asphalt)
    assert shutdown == (date(2027, 4, 17), date(2027, 10, 3)), f"Canonical shutdown {shutdown}"
    edge = edge_date(date(2026, 2, 28), shutdown[0] - DAY, 4, mask, asphalt)
    assert edge == date(2027, 4, 13), f"Canonical edge {edge}"
    assert cliff_window(date(2026, 2, 28), effective, edge, shutdown[0]) == (date(2027, 3, 30), date(2027, 5, 1))
    horizon = search_end(effective + stretch_dax.WINDOW_MAX_AFTER * DAY, finish, 4, mask, asphalt, date(2036, 12, 31))
    assert horizon == finish + stretch_dax.SEARCH_MARGIN_DAYS * DAY, "Canonical case should use the near search horizon"
    finish_of = lambda start: cliff_finish(start, 4, mask, asphalt, horizon)  # noqa: E731
    assert finish_of(date(2027, 4, 13)) == date(2027, 4, 16)
    assert finish_of(date(2027, 4, 14)) == date(2027, 10, 4)
    assert finish_of(effective) == finish
    recovery, slip = callout_searches(effective, effective - 60 * DAY, effective + 60 * DAY, finish_of)
    assert recovery == date(2027, 4, 13) and slip is None, f"Canonical callout should recover from 13-Apr-27, got {recovery}, {slip}"
    assert (finish - finish_of(recovery)).days == 173

    # C6036 Sep-2026 case: C-Z4B-BEW-C-0360 (25 days, W2T 5d Earth/Pave wet Wednesdays, Easter, winter shutdown from 1-May-28).
    wet = {date(2028, 4, 14): 0.0, date(2028, 4, 17): 0.0, date(2028, 4, 27): 0.0}
    day = date(2028, 3, 1)
    while day <= date(2028, 9, 29):
        if day.isoweekday() == 3 or (day >= date(2028, 5, 1) and day.isoweekday() <= 5):
            wet[day] = 0.0
        day += DAY
    effective, data_date = date(2028, 3, 27), date(2026, 9, 30)
    scheduled = nth_working_day(effective, 25, mask, wet, date(2029, 12, 31))
    shutdown = cliff_shutdown(effective, scheduled, mask, wet)
    assert shutdown == (date(2028, 4, 29), date(2028, 10, 1)), f"C6036 shutdown {shutdown}"
    edge = edge_date(data_date, shutdown[0] - DAY, 25, mask, wet)
    assert edge == date(2028, 3, 13) and nth_working_day(edge, 25, mask, wet, scheduled) == date(2028, 4, 28), f"C6036 edge {edge}"
    assert nth_working_day(edge + DAY, 25, mask, wet, scheduled) == date(2028, 10, 2)
    assert cliff_window(data_date, effective, edge, shutdown[0]) == (date(2028, 2, 28), date(2028, 5, 13))
    return {"exception_free_finish_cases": cases, "band_cases": band_cases, "cliff_cases": cliff_cases,
            "search_margin_cases": margin_cases, "edge_cases": edge_cases}


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
    assert stretch_dax.edge_search(stretch_dax.EDGE_PAD) in normalised["CS Cliff Edge Date"], "Re-render stretch_dax edge levels"
    sd = stretch_dax
    # The kernel's data range stays a pure function of the row: the window measures cost about 25 ms an evaluation, so per
    # axis date they took 10 s. They are read once per visual (X-axis range, constant line, callout) instead.
    kernel_code = "\n".join(line for line in kernel.splitlines() if not line.strip().startswith("//"))
    assert "[CS Cliff Window" not in kernel_code and "[CS Cliff Edge Date]" not in kernel_code and "[CS Cliff Shutdown]" not in kernel_code
    assert (f"VAR WindowStart = MAX(DataDate, EffectiveStart - {sd.WINDOW_MAX_BEFORE})" in kernel
            and f"VAR WindowEnd = EffectiveStart + {sd.WINDOW_MAX_AFTER}" in kernel), "Kernel data range must follow stretch_dax"
    assert (f"MAX(Edge - {sd.WINDOW_BEFORE_EDGE}, EffectiveStart - {sd.WINDOW_MAX_BEFORE}), EffectiveStart - {sd.WINDOW_DEFAULT})"
            in cs["CS Cliff Window Start"]), "Window start must follow stretch_dax"
    assert "MAX(DataDate, Wanted)" in cs["CS Cliff Window Start"], "The window must never start before the data date"
    assert f"MIN(EffectiveStart + {sd.WINDOW_MAX_AFTER}," in cs["CS Cliff Window End"] and f"+ {sd.WINDOW_AFTER_SHUTDOWN})" in cs["CS Cliff Window End"]
    assert "INT([__End] - [__Start]) + 1 >= 7 && [__Start] > EffectiveStart && [__Start] <= FinishDate" in cs["CS Cliff Shutdown"]
    callout = cs["CS Cliff Callout"]
    assert "[CS Cliff Window Start]" in callout and "[CS Cliff Edge Date]" in callout, "The callout must share the chart's window and edge"
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

DESKTOP_MANAGED_KEYS = {"$schema", "z", "tabOrder", "active", "stateManagement", "developer"}


def desktop_neutral(value):
    """Drop what Power BI Desktop and Deneb add or bump when they save a generated visual: the visualContainer $schema
    version, stacking and tab order (z, tabOrder), projection 'active' flags, and Deneb's managed state (stateManagement,
    developer, vega.properties.version)."""
    if isinstance(value, dict):
        result = {key: desktop_neutral(item) for key, item in value.items() if key not in DESKTOP_MANAGED_KEYS}
        if "filterConfig" in result and isinstance(result["filterConfig"], dict):
            active_filters = [f for f in result["filterConfig"].get("filters", []) if isinstance(f, dict) and "filter" in f]
            if active_filters:
                result["filterConfig"] = {**result["filterConfig"], "filters": active_filters}
            else:
                result.pop("filterConfig", None)
        for entry in result.get("vega", []) if isinstance(result.get("vega"), list) else []:
            entry.get("properties", {}).pop("version", None)
        return result
    if isinstance(value, list):
        return [desktop_neutral(item) for item in value]
    return value


def verify_pbir() -> dict:
    gen = view_generator
    outputs = gen.build()
    page_dir = REPORT_DEF / "pages" / gen.PAGE
    # Files the generator owns must match it; Desktop/Deneb round-trip details aside.
    owned = [Path("pages") / gen.PAGE / "visuals" / name / "visual.json" for name in gen.DELAY_VIEW + [gen.NAVIGATOR]]
    owned += [Path("bookmarks") / f"{name}.bookmark.json" for name in (gen.CALENDARS_BOOKMARK, gen.DELAY_BOOKMARK)]
    for relative in owned:
        path = REPORT_DEF / relative
        assert path.exists() and desktop_neutral(json.loads(path.read_text(encoding="utf-8-sig"))) == desktop_neutral(outputs[relative]), (
            f"{relative} differs from generate_stretch_view.py beyond Desktop/Deneb round-trip details; run it with --check")

    # The separate Calendar Stretch page and its project-menu bookmarks are gone.
    order = json.loads((REPORT_DEF / "pages" / "pages.json").read_text(encoding="utf-8-sig"))["pageOrder"]
    assert gen.FORMER_PAGE not in order and not (REPORT_DEF / "pages" / gen.FORMER_PAGE).exists(), "The Calendar Stretch page must be removed"
    assert gen.PAGE in order
    for name in gen.FORMER_BOOKMARKS:
        assert not (REPORT_DEF / "bookmarks" / f"{name}.bookmark.json").exists(), f"Bookmark {name} of the removed page remains"
    page = json.loads((page_dir / "page.json").read_text(encoding="utf-8-sig"))
    assert page["displayName"] == "Calendar" and page["width"] == 1920 and page["height"] == 1080
    page_filters = {f["field"]["Column"]["Property"]: f for f in page["filterConfig"]["filters"]}
    assert {"Is Unscheduled", "TaskType_Classified", "status_code", "Float Category"} <= set(page_filters)

    visuals = {path.parent.name: json.loads(path.read_text(encoding="utf-8-sig")) for path in (page_dir / "visuals").glob("*/visual.json")}
    delay = {name: visuals[name] for name in gen.DELAY_VIEW}
    types = {name: v["visual"]["visualType"] for name, v in visuals.items()}
    assert types[gen.BARS] == "barChart" and types[gen.SCATTER] == "scatterChart"
    assert types[gen.TIMELINE] == gen.DENEB and types[gen.CLIFF] == "lineChart"
    assert types[gen.CALLOUT] == "card" and types[gen.NAVIGATOR] == "bookmarkNavigator"
    # Calendars is the saved view: its visuals show, the Delay visuals wait for the Delay bookmark.
    assert all(v.get("isHidden") is True for v in delay.values()), "Delay visuals must be hidden in the saved (Calendars) view"
    assert not any(visuals[name].get("isHidden") for name in gen.CALENDARS_VIEW + [gen.NAVIGATOR]), "Calendars view must be visible by default"

    filter_names = [f["name"] for v in visuals.values() for f in v.get("filterConfig", {}).get("filters", [])]
    assert len(filter_names) == len(set(filter_names)), "Filter names must be unique on the page"
    for name, v in delay.items():
        filters = [f for f in v.get("filterConfig", {}).get("filters", []) if "filter" in f]
        non_topn = [f for f in filters if f.get("type") != "TopN"]
        assert "Measure" not in json.dumps(non_topn), f"{name} has a measure filter; use column filters only"
        assert "'Scenario Calendar'" not in json.dumps(v) and "Scenario Calendar" not in json.dumps(v.get("visual", {}).get("query", {})), (
            f"{name} must not bind Scenario Calendar (it would change the CA Inspector Selection Match gate)")
        assert '"Property": "Month"' not in json.dumps(v.get("visual", {}).get("query", {})), f"{name} must not bind 'Scenario Date'[Month]"
    for name in (gen.BARS, gen.TIMELINE):
        filters = {f["type"]: f for f in visuals[name]["filterConfig"]["filters"] if "filter" in f}
        query = filters["TopN"]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]
        assert query["Top"] == 15 and query["OrderBy"][0]["Direction"] == 2
        measure_expr = query["OrderBy"][0]["Expression"]["Measure"]
        assert measure_expr["Property"] == "CA Activity Stretch Ratio"
    bars_sort = visuals[gen.BARS]["visual"]["query"]["sortDefinition"]["sort"][0]
    assert bars_sort["field"]["Measure"]["Property"] == "CA Activity Stretch Ratio" and bars_sort["direction"] == "Descending"
    for name in (gen.BARS, gen.TIMELINE, gen.SCATTER):
        advanced = [f for f in visuals[name]["filterConfig"]["filters"] if f["type"] == "Advanced" and "filter" in f]
        condition = advanced[0]["filter"]["Where"][0]["Condition"]["Comparison"]
        assert condition["ComparisonKind"] == 1 and condition["Right"]["Literal"]["Value"] == "0L"
    scatter = visuals[gen.SCATTER]["visual"]
    assert scatter["objects"]["categoryAxis"][0]["properties"]["logAxisScale"]["expr"]["Literal"]["Value"] == "true"
    cliff = visuals[gen.CLIFF]["visual"]
    assert cliff["query"]["queryState"]["Category"]["projections"][0]["queryRef"] == "Scenario Date.Date"
    assert cliff["objects"]["lineStyles"][0]["properties"]["lineChartType"]["expr"]["Literal"]["Value"] == "'step'"
    x_lines = {line["selector"]["id"]: line["properties"]["value"]["expr"]["Measure"]["Property"] for line in cliff["objects"]["xAxisReferenceLine"]}
    assert x_lines == {"1": "CS Cliff Start Date", "2": "CS Cliff Edge Date"}, f"Cliff X-axis constant lines {x_lines}"
    axis = cliff["objects"]["categoryAxis"][0]["properties"]
    assert (axis["start"]["expr"]["Measure"]["Property"], axis["end"]["expr"]["Measure"]["Property"]) == (
        "CS Cliff Window Start", "CS Cliff Window End"), "The cliff chart's X axis must be zoomed to the window measures"
    y_axis = cliff["objects"]["valueAxis"][0]["properties"]
    assert y_axis["titleText"]["expr"]["Literal"]["Value"] == "'Finish change vs scheduled (days)'"
    y_line = cliff["objects"]["y1AxisReferenceLine"][0]["properties"]
    assert y_line["displayName"]["expr"]["Literal"]["Value"] == "'No finish change (0 d)'" and y_line["value"]["expr"]["Literal"]["Value"] == "0D"

    interactions = {(i["source"], i["target"]): i["type"] for i in page["visualInteractions"]}
    for source in (gen.BARS, gen.TIMELINE, gen.SCATTER):
        for target in (gen.CALLOUT, gen.CLIFF):
            assert interactions.get((source, target)) == "DataFilter", f"{source} must select the cliff activity"
        for target in gen.KPIS:
            assert interactions.get((source, target)) == "NoFilter"
    for target in visuals:
        if target != gen.CLIFF:
            assert interactions.get((gen.CLIFF, target)) == "NoFilter", f"Cliff chart must not filter {target}"
    for calendars_visual in gen.CALENDARS_VIEW:
        for delay_visual in gen.DELAY_VIEW:
            assert interactions.get((calendars_visual, delay_visual)) == interactions.get((delay_visual, calendars_visual)) == "NoFilter", (
                f"Views must not filter each other ({calendars_visual} / {delay_visual})")

    report = json.loads((REPORT_DEF / "report.json").read_text(encoding="utf-8-sig"))
    assert gen.DENEB in report.get("publicCustomVisuals", []), "Deneb must be registered in report.json"
    deneb = visuals[gen.TIMELINE]["visual"]
    vega = deneb["objects"]["vega"][0]["properties"]
    assert vega["provider"]["expr"]["Literal"]["Value"] == "'vegaLite'"
    assert vega["enableSelection"]["expr"]["Literal"]["Value"] == "true"
    literal = vega["jsonSpec"]["expr"]["Literal"]["Value"]
    spec = json.loads(literal[1:-1].replace("''", "'"))
    assert spec["encoding"]["y"]["sort"] == {"field": "Stretch Ratio", "op": "max", "order": "descending"}, (
        "Deneb timeline must sort activities from highest to lowest Stretch Ratio")
    names = {p["displayName"] for p in deneb["query"]["queryState"]["dataset"]["projections"]}
    derived = set(re.findall(r'"as":\s*"([^"]+)"', json.dumps(spec))) | {"band", "__selected__", "dates"}
    referenced = set(re.findall(r"datum\['([^']+)'\]", json.dumps(spec))) | set(re.findall(r'"field":\s*"([^"]+)"', json.dumps(spec)))
    referenced |= set(re.findall(r"datum\.([A-Za-z_]+)", json.dumps(spec)))
    unknown = referenced - names - derived
    assert not unknown, f"Deneb spec references unknown fields {sorted(unknown)}"
    for name in names:
        assert not set(name) & set(".[]\\\""), f"Deneb field name {name!r} contains characters Deneb rewrites"

    metadata = json.loads((REPORT_DEF / "bookmarks" / "bookmarks.json").read_text(encoding="utf-8-sig"))["items"]
    groups = [item for item in metadata if item.get("name") == gen.VIEW_GROUP]
    assert groups and groups[0].get("children") == [gen.CALENDARS_BOOKMARK, gen.DELAY_BOOKMARK], "View group must hold Calendars, Delay"
    assert not {item.get("name") for item in metadata} & set(gen.FORMER_BOOKMARKS)
    navigator = visuals[gen.NAVIGATOR]["visual"]["objects"]["bookmarks"][0]["properties"]
    assert navigator["selectedBookmark"]["expr"]["Literal"]["Value"] == f"'{gen.CALENDARS_BOOKMARK}'", "The navigator must start on Calendars"
    for bookmark in gen.MENU_BOOKMARKS:
        options = json.loads((REPORT_DEF / "bookmarks" / f"{bookmark}.bookmark.json").read_text(encoding="utf-8-sig"))["options"]
        assert options.get("applyOnlyToTargetVisuals") is True, f"{bookmark} must not reset the selected view"
        assert options["targetVisualNames"] == ["ca10menubg0000000010", "ca11state00000000011", "ca12proj000000000012", "ca13closebt000000013"]
    return {"page": gen.PAGE, "delay_visuals": len(delay), "page_visuals": len(visuals), "deneb_fields": sorted(names)}


def main() -> None:
    mask_cases = verify_workweek_mask_formula()
    oracles = verify_oracles()
    measures = verify_tmdl()
    pbir = verify_pbir()
    print(json.dumps({"status": "PASS", "cs_measures": measures, "workweek_mask_cases": mask_cases,
                      "oracles": oracles, "pbir": pbir}, indent=2))


if __name__ == "__main__":
    main()

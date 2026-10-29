"""Render the unrolled bisection DAX used by the Calendar Stretch cliff-edge kernel ('CS Cliff Finish Date', forwards)
and the shutdown edge ('CS Cliff Edge Date', backwards).

DAX has no loops, so the search is written out level by level. This module is the single source for that text:
validate_calendar_stretch.py re-renders it and checks the TMDL still contains the same block.
"""

from __future__ import annotations

import math

# The search runs from the candidate start to SearchEnd = MIN(axis end, scheduled finish + SEARCH_MARGIN_DAYS), but only
# when the latest window start (60 days after the remaining start) still completes by then; otherwise it runs to
# the axis end. The margin keeps the exception deltas (and the cost) small without changing any result.
SEARCH_MARGIN_DAYS = 400
# 'Scenario Date' spans at most 12 years (4,384 days), so 13 halvings (8,192) always narrow the search to one day.
FINISH_LEVELS = 13
INDENT = "\t\t\t"
# Indentation of the rendered blocks inside 'CS Cliff Finish Date' and 'CS Cliff Edge Date' (TMDL expression lines).
FINISH_PAD = INDENT + " " * 32
EDGE_PAD = INDENT + " " * 24
# Cliff-edge chart window (see 'CS Cliff Window Start' / 'CS Cliff Window End'), never before the data date. The kernel
# evaluates its cheap data range (60 days either side of the remaining start) and the window measures, evaluated once per
# visual, zoom the X axis inside it: evaluating them per axis date cost about 25 ms a date (10 s per chart).
WINDOW_BEFORE_EDGE = 14       # days shown before the last start that beats the shutdown
WINDOW_AFTER_SHUTDOWN = 14    # days shown after the shutdown starts (the finish flattens there)
WINDOW_MAX_BEFORE = 60        # the data range: never more than this many days before the remaining start
WINDOW_MAX_AFTER = 60         # the data range: never more than this many days after the remaining start
WINDOW_DEFAULT = 30           # +/- days around the remaining start when the work runs into no shutdown


def working_days_through(probe: str) -> str:
    """Working days from CandidateStart through probe: closed-form weekday counts plus dated exception deltas."""
    span = f"INT({probe} - CandidateStart) + 1"
    return (
        f"QUOTIENT({span}, 7) * WorkDays"
        f" + LEN(SUBSTITUTE(MID(DoubleMask, StartDow, MOD({span}, 7)), \"0\", \"\"))"
        f" + SUMX(FILTER(Deltas, [__Date] <= {probe}), [__Delta])"
    )


def finish_search(pad: str) -> str:
    """Smallest date P up to SearchEnd with at least NeedDays working days in [CandidateStart, P] (invariant: Lo fails, Hi passes)."""
    lines = [f"{pad}VAR Lo00 = CandidateStart - 1", f"{pad}VAR Hi00 = SearchEnd"]
    for level in range(1, FINISH_LEVELS + 1):
        before, now = f"{level - 1:02d}", f"{level:02d}"
        lines += [
            f"{pad}VAR Mid{now} = Lo{before} + QUOTIENT(INT(Hi{before} - Lo{before}), 2)",
            f"{pad}VAR Ok{now} = {working_days_through('Mid' + now)} >= NeedDays",
            f"{pad}VAR Lo{now} = IF(Ok{now}, Lo{before}, Mid{now})",
            f"{pad}VAR Hi{now} = IF(Ok{now}, Mid{now}, Hi{before})",
        ]
    lines.append(f"{pad}RETURN IF({working_days_through('SearchEnd')} >= NeedDays, Hi{FINISH_LEVELS:02d})")
    return "\n".join(lines)


def working_days_back(probe: str) -> str:
    """Working days from probe through LastDay (the day before the shutdown): closed-form weekday counts plus deltas."""
    span = f"INT(LastDay - {probe}) + 1"
    return (
        f"QUOTIENT({span}, 7) * WorkDays"
        f" + LEN(SUBSTITUTE(MID(DoubleMask, WEEKDAY({probe}, 2), MOD({span}, 7)), \"0\", \"\"))"
        f" + SUMX(FILTER(Deltas, [__Date] >= {probe}), [__Delta])"
    )


def edge_search(pad: str) -> str:
    """Latest start E in [DataDate, LastDay] with at least NeedDays working days in [E, LastDay] (invariant: Lo passes,
    Hi fails); blank when even the data date fails. Used by 'CS Cliff Edge Date'."""
    lines = [f"{pad}VAR Lo00 = DataDate", f"{pad}VAR Hi00 = LastDay + 1"]
    for level in range(1, FINISH_LEVELS + 1):
        before, now = f"{level - 1:02d}", f"{level:02d}"
        lines += [
            f"{pad}VAR Mid{now} = Lo{before} + QUOTIENT(INT(Hi{before} - Lo{before}), 2)",
            f"{pad}VAR Ok{now} = {working_days_back('Mid' + now)} >= NeedDays",
            f"{pad}VAR Lo{now} = IF(Ok{now}, Mid{now}, Lo{before})",
            f"{pad}VAR Hi{now} = IF(Ok{now}, Hi{before}, Mid{now})",
        ]
    lines.append(f"{pad}RETURN IF({working_days_back('DataDate')} >= NeedDays, Lo{FINISH_LEVELS:02d})")
    return "\n".join(lines)


def levels_needed(span_days: int) -> int:
    return math.ceil(math.log2(span_days + 1))

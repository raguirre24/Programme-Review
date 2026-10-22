"""Render the unrolled bisection DAX used by the Calendar Stretch cliff-edge kernel ('CS Cliff Finish Date').

DAX has no loops, so the search is written out level by level. This module is the single source for that text:
validate_calendar_stretch.py re-renders it and checks the TMDL still contains the same block.
"""

from __future__ import annotations

import math

# The search runs from the candidate start to SearchEnd = MIN(axis end, scheduled finish + SEARCH_MARGIN_DAYS).
# A start at most 60 days after the remaining start cannot push the finish more than about a year past the scheduled
# finish, so the margin keeps the exception deltas (and the cost) small without changing any result.
SEARCH_MARGIN_DAYS = 400
# 'Scenario Date' spans at most 12 years (4,384 days), so 13 halvings (8,192) always narrow the search to one day.
FINISH_LEVELS = 13
INDENT = "\t\t\t"
# Indentation of the rendered block inside 'CS Cliff Finish Date' (TMDL expression lines).
FINISH_PAD = INDENT + " " * 32


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


def levels_needed(span_days: int) -> int:
    return math.ceil(math.log2(span_days + 1))

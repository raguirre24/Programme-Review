"""Independent arithmetic validation for a rule-based Resource Playground.

Uses synthetic calendars, not project data. Compares a seven-weekday plus
exception-correction algorithm with a direct daily oracle. This is not a DAX,
Power BI host, performance or native-P6 verification.
"""

from __future__ import annotations

import argparse
import calendar as month_calendar
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction as F
import json
from pathlib import Path
import random


DAY = timedelta(days=1)


@dataclass
class Calendar:
    week: tuple[F | None, ...]
    exceptions: list[tuple[date, F | None]]
    undated_invalid: bool = False

    def validate(self) -> None:
        if self.undated_invalid:
            raise ValueError("unknown_exception_coverage")
        if len(self.week) != 7 or any(h is None or h < 0 for h in self.week):
            raise ValueError("invalid_week")
        if len({d for d, _ in self.exceptions}) != len(self.exceptions):
            raise ValueError("duplicate_exception")
        if any(h is not None and h < 0 for _, h in self.exceptions):
            raise ValueError("invalid_exception_hours")


def capacity(hours: F, rate: F, cap: F | None, mode: str) -> F:
    value = F(0) if hours == 0 else rate if mode == "daily" else rate * hours
    return value if cap is None else min(value, cap)


def prefix(cal: Calendar, start: date, end: date, rate: F,
           cap: F | None, mode: str) -> F:
    """Inclusive capacity using 7 counts plus corrections, without date expansion."""
    if end < start:
        return F(0)
    n = (end - start).days + 1
    weeks, remainder = divmod(n, 7)
    base_caps = [capacity(h, rate, cap, mode) for h in cal.week]
    result = sum(
        (weeks + int((weekday - start.weekday()) % 7 < remainder)) * base_caps[weekday]
        for weekday in range(7)
    )
    for when, hours in cal.exceptions:
        if start <= when <= end:
            if hours is None:
                raise ValueError("unknown_date")
            result += capacity(hours, rate, cap, mode) - base_caps[when.weekday()]
    return result


def rule_finish(cal: Calendar, start: date, end: date, qty: F,
                rate: F, cap: F | None, mode: str) -> tuple[date | None, str, int]:
    cal.validate()
    if qty == 0:
        return None, "no_work", 0
    unknown = [d for d, h in cal.exceptions if h is None and start <= d <= end]
    safe_end = min(unknown) - DAY if unknown else end
    if safe_end < start:
        return None, "unknown_availability", 0
    cursor = start
    probes = 0
    while cursor <= safe_end:
        month_end = date(cursor.year, cursor.month,
                         month_calendar.monthrange(cursor.year, cursor.month)[1])
        probe_end = min(month_end, safe_end)
        probes += 1
        if prefix(cal, start, probe_end, rate, cap, mode) >= qty:
            candidate = cursor
            while candidate <= probe_end:
                probes += 1
                if prefix(cal, start, candidate, rate, cap, mode) >= qty:
                    return candidate, "complete", probes
                candidate += DAY
            raise AssertionError("crossing month had no crossing date")
        cursor = probe_end + DAY
    return None, "unknown_availability" if unknown else "outside_horizon", probes


def allocated_through(cal: Calendar, start: date, end: date, qty: F,
                      rate: F, cap: F | None, mode: str) -> F | None:
    """Known allocation can stay at Q after a later unknown capacity date."""
    if end < start or qty == 0:
        return F(0)
    unknown = [d for d, h in cal.exceptions if h is None and start <= d <= end]
    safe_end = min(unknown) - DAY if unknown else end
    known_capacity = prefix(cal, start, safe_end, rate, cap, mode)
    if unknown and known_capacity < qty:
        return None
    return min(qty, known_capacity)


def daily_oracle(cal: Calendar, start: date, end: date, qty: F,
                 rate: F, cap: F | None, mode: str):
    """Daily reference intentionally enumerates dates and applies replacements."""
    cal.validate()
    overrides = dict(cal.exceptions)
    running = F(0)
    remaining = qty
    finish = None
    first_unknown = None
    rows = []
    d = start
    while d <= end:
        hours = overrides[d] if d in overrides else cal.week[d.weekday()]
        if hours is None:
            first_unknown = d
            break
        available = F(0)
        if hours > 0:
            available = rate if mode == "daily" else rate * hours
            if cap is not None and available > cap:
                available = cap
        allocated = min(remaining, available)
        remaining -= allocated
        running += available
        rows.append((d, available, running, allocated))
        if finish is None and qty > 0 and remaining == 0:
            finish = d
        d += DAY
    status = ("no_work" if qty == 0 else "complete" if finish is not None
              else "unknown_availability" if first_unknown else "outside_horizon")
    return finish, status, rows


def check(cal, start, end, qty, rate, cap, mode, rng):
    finish, status, rows = daily_oracle(cal, start, end, qty, rate, cap, mode)
    actual_finish, actual_status, probes = rule_finish(cal, start, end, qty, rate, cap, mode)
    assert (actual_finish, actual_status) == (finish, status), (
        cal, start, end, qty, rate, cap, mode,
        (actual_finish, actual_status), (finish, status))
    assert probes <= ((end.year - start.year) * 12 + end.month - start.month + 1) + 31
    assert prefix(cal, start, start - DAY, rate, cap, mode) == 0
    if rows:
        choices = {0, len(rows) - 1, rng.randrange(len(rows))}
        for index in choices:
            d, available, cumulative, allocated = rows[index]
            p = prefix(cal, start, d, rate, cap, mode)
            prev = prefix(cal, start, d - DAY, rate, cap, mode)
            assert p == cumulative
            assert p - prev == available
            assert min(qty, p) - min(qty, prev) == allocated
        a = rng.randrange(len(rows))
        b = rng.randrange(a, len(rows))
        by_boundaries = (min(qty, prefix(cal, start, rows[b][0], rate, cap, mode))
                         - min(qty, prefix(cal, start, rows[a][0] - DAY, rate, cap, mode)))
        assert by_boundaries == sum(row[3] for row in rows[a:b + 1])
        # Monthly bars must equal the reference sum, even in partial months.
        months = sorted({(row[0].year, row[0].month) for row in rows})
        allocated_sum = F(0)
        for year, month in months:
            a_date = date(year, month, 1)
            b_date = min(date(year, month, month_calendar.monthrange(year, month)[1]), rows[-1][0])
            bar = min(qty, prefix(cal, start, b_date, rate, cap, mode)) - min(
                qty, prefix(cal, start, a_date - DAY, rate, cap, mode))
            expected = sum(row[3] for row in rows if (row[0].year, row[0].month) == (year, month))
            assert bar == expected
            allocated_sum += bar
        assert allocated_sum == sum(row[3] for row in rows)
    # Actual plotted endpoints can extend past unknown calendar availability.
    # If the oracle finished earlier, the allocation is nevertheless exactly Q.
    expected_end = qty if finish is not None else (
        None if status == "unknown_availability" else sum(row[3] for row in rows))
    assert allocated_through(cal, start, end, qty, rate, cap, mode) == expected_end
    if rows and finish is not None:
        first = date(finish.year, finish.month, 1)
        last = min(end, date(finish.year, finish.month,
                             month_calendar.monthrange(finish.year, finish.month)[1]))
        through_last = allocated_through(cal, start, last, qty, rate, cap, mode)
        through_before = allocated_through(cal, start, first - DAY, qty, rate, cap, mode)
        assert through_last - through_before == sum(
            row[3] for row in rows if first <= row[0] <= last)
    return probes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=3000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rng = random.Random(20260911)
    five = (F(8),) * 5 + (F(0),) * 2
    starts = date(2026, 9, 14)
    fixtures = [
        (Calendar(five, []), starts, date(2026, 10, 31), F(1050), F(120), F(100), "daily"),
        (Calendar(five, [(date(2026, 9, 21), F(0))]), starts, date(2026, 10, 31), F(1050), F(120), F(100), "daily"),
        (Calendar(five, [(date(2026, 9, 19), F(4))]), starts, date(2026, 10, 31), F(650), F(20), F(100), "hourly"),
        (Calendar(five, [(date(2026, 9, 25), None)]), starts, date(2026, 9, 30), F(200), F(100), None, "daily"),
        (Calendar(five, [(date(2026, 9, 25), None)]), starts, date(2026, 9, 30), F(2000), F(100), None, "daily"),
        (Calendar((F(0),) * 7, [(date(2028, 2, 29), F(3))]), date(2028, 2, 20), date(2028, 3, 3), F(15), F(5), None, "hourly"),
        (Calendar(five, []), date(2028, 2, 27), date(2028, 3, 2), F(1), F(0), None, "hourly"),
        (Calendar(five, []), starts, starts, F(0), F(1), None, "daily"),
        (Calendar(five, []), starts, starts, F(1), F(1), F(0), "daily"),
        (Calendar(five, [(starts, None)]), starts, starts + DAY, F(1), F(1), None, "daily"),
    ]
    probes = [check(*fixture, rng) for fixture in fixtures]
    assert rule_finish(*fixtures[0])[0] == date(2026, 9, 28)
    assert rule_finish(*fixtures[1])[0] == date(2026, 9, 29)
    assert rule_finish(*fixtures[3])[0] == date(2026, 9, 15)
    assert allocated_through(*fixtures[3]) == 200
    assert allocated_through(*fixtures[4]) is None
    # Applying the cap after aggregation is demonstrably incorrect.
    sample = Calendar((F(8), F(2), F(0), F(0), F(0), F(0), F(0)), [])
    assert prefix(sample, starts, starts + DAY, F(10), F(60), "hourly") == 80
    assert min(F(10) * (8 + 2), F(60) * 2) == 100
    invalids = [Calendar((None,) + five[1:], []), Calendar(five, [], True),
                Calendar(five, [(starts, F(1)), (starts, F(2))])]
    for cal in invalids:
        try:
            cal.validate()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid calendar was accepted")
    hours = [F(0), F(2), F(4), F(15, 2), F(8), F(10), F(12), F(24)]
    for _ in range(args.cases):
        start = date(2020, 1, 1) + timedelta(days=rng.randrange(5500))
        span = rng.randrange(1, 750)
        end = start + timedelta(days=span - 1)
        offsets = rng.sample(range(-20, span + 20), min(rng.randrange(36), span + 40))
        exceptions = [(start + timedelta(days=o), rng.choice(hours)) for o in offsets]
        if rng.random() < 0.12:
            d = start + timedelta(days=rng.randrange(span))
            exceptions = [(when, h) for when, h in exceptions if when != d] + [(d, None)]
        cal = Calendar(tuple(rng.choice(hours) for _ in range(7)), exceptions)
        mode = rng.choice(["daily", "hourly"])
        rate = F(rng.randrange(0, 101), rng.choice([1, 2, 4]))
        cap = None if rng.random() < 0.3 else F(rng.randrange(0, 501), 2)
        qty = F(rng.randrange(0, max(1, span * 350)), 2)
        probes.append(check(cal, start, end, qty, rate, cap, mode, rng))
    report = {
        "result": "PASS",
        "seed": 20260911,
        "deterministic_scenarios": len(fixtures),
        "random_scenarios": args.cases,
        "invalid_calendar_checks": len(invalids),
        "checks": ["prefix capacity", "exact earliest finish", "daily allocation",
                   "arbitrary interval allocation", "monthly reconciliation", "partial last day",
                   "daily cap before aggregation", "unknown-date safe horizon", "month search bound",
                   "completed monthly allocation beyond later unknown calendar date"],
        "maximum_prefix_probes_observed": max(probes),
        "arithmetic": "exact rational",
        "scope": "Synthetic mathematical validation only; no DAX, Power BI host, native-P6 or performance proof."
    }
    rendered = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

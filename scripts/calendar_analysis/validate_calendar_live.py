"""Read-only live checks of table 11 dated-exception alignment against the model open in Power BI Desktop.

Run after refreshing the report so '11 XER_CALENDAR_DETAILED'[ExceptionDateShiftDays] exists:
    python scripts/calendar_analysis/validate_calendar_live.py [--server localhost:<port>]

Checks, per source file and per project update:
1. Every dated row's day_of_week_num matches its (realigned) date.
2. Re-running the alignment vote on the loaded rows finds nothing left to move (no file still votes +1/-1).
3. P6 reconciliation: for not-started activities with whole-day remaining durations, the working days between
   Start and Finish on the loaded calendar equal remaining_duration for at least --min-match of activities.
"""

from __future__ import annotations

import argparse
import collections
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{key.strip("[]"): value for key, value in row.items()} for row in csv.DictReader(handle)]


def to_number(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def vote(rules: dict[int, float], exceptions: list[tuple[int, float]]) -> list[int]:
    """Repeats of the weekday rule's hours as loaded, moved a day later and moved a day earlier (same as the SQL/M vote)."""
    counts = [0, 0, 0]
    for weekday, hours in exceptions:
        for slot, offset in enumerate((0, 1, -1)):
            rule = rules.get((weekday - 1 + offset) % 7 + 1)
            if rule is not None and abs(rule - hours) < 0.0001:
                counts[slot] += 1
    return counts


def decided_shift(counts: list[int]) -> int:
    ranked = sorted(counts)
    if ranked[0] * 2 <= ranked[1] and ranked[1] - ranked[0] >= 10:
        return (0, 1, -1)[counts.index(ranked[0])]
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", help="Power BI Desktop Analysis Services address, e.g. localhost:53666")
    parser.add_argument("--min-match", type=float, default=0.99, help="Minimum P6 reconciliation rate per project update")
    parser.add_argument("--input-dir", type=Path, help="Check calendar.csv/activities.csv already exported by Export-CalendarLiveData.ps1")
    arguments = parser.parse_args()

    if arguments.input_dir:
        connection = {"input_dir": str(arguments.input_dir)}
        calendar_rows = read_csv(arguments.input_dir / "calendar.csv")
        activity_rows = read_csv(arguments.input_dir / "activities.csv")
    else:
        with tempfile.TemporaryDirectory() as temporary:
            command = ["pwsh", "-NoProfile", "-File", str(HERE / "Export-CalendarLiveData.ps1"), "-OutputDirectory", temporary]
            if arguments.server:
                command += ["-ServerAddress", arguments.server]
            exported = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            if exported.returncode != 0:
                print(json.dumps({"status": "ERROR", "detail": exported.stderr.strip() or exported.stdout.strip()}, indent=2))
                return 2
            connection = json.loads(exported.stdout.strip().splitlines()[-1])
            calendar_rows = read_csv(Path(temporary) / "calendar.csv")
            activity_rows = read_csv(Path(temporary) / "activities.csv")

    rules: dict[str, dict[int, float]] = collections.defaultdict(dict)
    rule_counts: collections.Counter = collections.Counter()
    exceptions: dict[str, dict[date, float]] = collections.defaultdict(dict)
    file_exceptions: dict[str, list[tuple[str, int, float]]] = collections.defaultdict(list)
    shifts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    weekday_mismatches = []
    for row in calendar_rows:
        key, hours, weekday = row["key"], to_number(row["hours"]), to_number(row["weekday"])
        source_file = key.rsplit("::" if "::" in key else ".", 1)[0]
        shifts[source_file][int(to_number(row["shift"]) or 0)] += 1
        if not row["date"]:
            if row["type"] == "Standard" and hours is not None and weekday is not None:
                rules[key][int(weekday)] = hours
                rule_counts[(key, int(weekday))] += 1
            continue
        day = date.fromisoformat(row["date"])
        if weekday is not None and int(weekday) != day.isoweekday():
            weekday_mismatches.append((key, row["date"], int(weekday)))
        if hours is not None and row["type"] != "Exception - Invalid":
            exceptions[key][day] = hours
            if weekday is not None:
                file_exceptions[source_file].append((key, int(weekday), hours))
    for (key, weekday), count in rule_counts.items():
        if count != 1:
            rules[key].pop(weekday, None)

    still_shifted = {}
    for source_file, items in file_exceptions.items():
        counts = [0, 0, 0]
        by_key = collections.defaultdict(list)
        for key, weekday, hours in items:
            by_key[key].append((weekday, hours))
        for key, pairs in by_key.items():
            counts = [a + b for a, b in zip(counts, vote(rules[key], pairs))]
        if decided_shift(counts) != 0:
            still_shifted[source_file] = counts

    reconciliation: dict[tuple[str, str], list[int]] = collections.defaultdict(lambda: [0, 0])
    examples = []
    for row in activity_rows:
        remaining = to_number(row["remaining"])
        week = rules.get(row["key"])
        if remaining is None or remaining <= 0 or abs(remaining - round(remaining)) > 1e-6 or not week or len(week) != 7:
            continue
        start, finish = date.fromisoformat(row["start"]), date.fromisoformat(row["finish"])
        dated = exceptions[row["key"]]
        working = sum(
            1 for offset in range((finish - start).days + 1)
            if dated.get(start + timedelta(days=offset), week[(start + timedelta(days=offset)).isoweekday()]) > 0
        )
        bucket = reconciliation[(row["project"], row["update"])]
        bucket[1] += 1
        if working == round(remaining):
            bucket[0] += 1
        elif len(examples) < 5:
            examples.append({"task_code": row["task_code"], "update": row["update"], "start": row["start"],
                             "finish": row["finish"], "remaining_duration": remaining, "calendar_working_days": working})

    rates = {f"{project} {update}": round(ok / total, 4) for (project, update), (ok, total) in sorted(reconciliation.items()) if total}
    low = {name: rate for name, rate in rates.items() if rate < arguments.min_match}
    status = "PASS" if not weekday_mismatches and not still_shifted and not low and rates else "FAIL"
    print(json.dumps({
        "status": status,
        "model": connection,
        "source_files": len(shifts),
        "exception_date_shift_by_file": {name: dict(counter) for name, counter in sorted(shifts.items())},
        "weekday_mismatches": len(weekday_mismatches),
        "files_still_voting_for_a_shift": still_shifted,
        "p6_reconciliation_rate_by_update": rates,
        "updates_below_min_match": low,
        "reconciliation_examples": examples,
    }, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

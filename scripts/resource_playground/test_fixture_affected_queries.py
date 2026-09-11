"""Prepare a targeted regression set after the inverse-capacity correction."""
from __future__ import annotations

import datetime as dt
import json

from test_build_fixture import DEFAULT, MARKER, js
from test_fixture_cases import OUTPUTS, filters, oracle, query, scenario


def build():
    source = json.loads((DEFAULT.parent / "fixture_cases.json").read_text())
    names = {
        "inverse_precision_probe", "forward_daily_cap_partial_final", "hourly_cap_applied_per_date",
        "inverse_daily", "inverse_daily_infeasible_cap", "inverse_hourly", "inverse_hourly_capped_unavailable",
        "unknown_before_completion", "unknown_day_blanks", "completed_before_later_unknown", "inverse_target_before_start",
        "sparse_dates_do_not_fill_gap", "disjoint_months_exclude_october", "grand_total_matches_quantity", "ambiguous_period_chart_only_guard",
    }
    tests = [t for t in source["tests"] if t["name"] in names or t["name"].startswith("all_")]
    for name, values in {
        "inverse_zero_quantity": scenario(mode="Meet target date", quantity=0, cap=None),
        "inverse_zero_hour_calendar": scenario(mode="Meet target date", calendar="zero", cap=None),
        "inverse_unknown_calendar": scenario(mode="Meet target date", calendar="unknown", cap=None),
        "inverse_inclusive_one_day_target": scenario(mode="Meet target date", target=dt.date(2026, 9, 7), cap=None),
    }.items():
        f = filters(values)
        columns = {label: "[" + measure + "]" for label, measure in OUTPUTS.items()}
        tests.append({"name": name, "dax": query(columns, f), "expect": oracle(values), "contains": {}, "role": None, "maxRows": 1,
                      "fragments": [{"name": label, "dax": query({label: expression}, f)} for label, expression in columns.items()]})
    for date, capacity in [(dt.date(2026, 9, 7), 1050 / 18), (dt.date(2026, 9, 30), 1050), (dt.date(2026, 10, 5), 1225)]:
        f = filters(scenario(mode="Meet target date", cap=None, axis=date))
        tests.append({"name": "inverse_rate_axis_independence_" + date.isoformat(),
                      "dax": query({"Required": "[Scenario Required Rate]", "Applied": "[Scenario Applied Rate]", "Capacity": "[Scenario Capacity Through]"}, f),
                      "expect": {"Required": 1050 / 18, "Applied": 1050 / 18, "Capacity": capacity}, "contains": {}, "role": None, "maxRows": 1})
    tests.append({"name": "rls_cannot_inverse_forecast_p2", "dax": query({"Finish": "[Scenario Finish Date]", "Calendars": "COUNTROWS('Scenario Calendar')", "Required": "[Scenario Required Rate]"}, filters(scenario(project="P2", mode="Meet target date", cap=None))),
                  "expect": {"Finish": None, "Calendars": None, "Required": None}, "contains": {}, "role": "Fixture Project P1", "maxRows": 1})
    output = DEFAULT.parent / "fixture_affected_cases.json"
    js(output, {"marker": MARKER, "testCount": len(tests), "tests": tests})
    print(json.dumps({"output": str(output), "tests": len(tests)}, indent=2))


if __name__ == "__main__":
    build()

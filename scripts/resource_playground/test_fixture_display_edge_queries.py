"""Boundary and sparse-context assertions for the fused display measures."""
from __future__ import annotations

import datetime as dt
import json

from test_build_fixture import DEFAULT, MARKER, js
from test_fixture_cases import filters, oracle, query, scenario


def build():
    tests = []
    def add(name, f, expected, role=None):
        tests.append({"name": name, "dax": query({"Allocated": "[Scenario Chart Quantity]", "Cumulative": "[Scenario Chart Cumulative Quantity]"}, f),
                      "expect": expected, "contains": {}, "role": role, "maxRows": 1})
    for name, values in {
        "chart_fractional_final_day": scenario(quantity=12345, scale=0.01, rate=12.3, cap=None, axis=dt.date(2026, 9, 21)),
        "chart_tolerance_final_day": scenario(quantity=3, scale=0.1, rate=0.1, cap=None, axis=dt.date(2026, 9, 9)),
        "chart_zero_rate": scenario(rate=0, cap=None),
        "chart_zero_cap": scenario(cap=0),
        "chart_zero_hour_calendar": scenario(calendar="zero", cap=None),
        "chart_unequal_hourly_capped": scenario(calendar="unequal", basis="Per working hour", rate=10, cap=50, axis=dt.date(2026, 9, 9)),
        "chart_working_weekend": scenario(calendar="holiday", axis=dt.date(2026, 9, 12)),
        "chart_holiday": scenario(calendar="holiday", axis=dt.date(2026, 9, 8)),
        "chart_unknown_before_completion": scenario(calendar="unknown", quantity=1000, axis=dt.date(2026, 9, 8)),
        "chart_unknown_day": scenario(calendar="unknown", quantity=1000, axis=dt.date(2026, 9, 9)),
        "chart_after_completion_before_unknown": scenario(calendar="unknown", quantity=100, axis=dt.date(2026, 9, 8)),
        "chart_inverse_precision_final_day": scenario(mode="Meet target date", cap=None, axis=dt.date(2026, 9, 30)),
        "chart_final_horizon_date": scenario(quantity=100000, scale=1000000, rate=1, cap=None, axis=dt.date(2036, 12, 31)),
    }.items():
        result = oracle(values)
        allocated, cumulative = result["DailyQuantity"], result["Cumulative"]
        # Display rows finish after completion even though the public cumulative
        # scalar intentionally continues to report the completed quantity.
        if allocated is None:
            cumulative = None
        add(name, filters(values), {"Allocated": allocated, "Cumulative": cumulative})
    add("chart_zero_quantity", filters(scenario(quantity=0)), {"Allocated": None, "Cumulative": None})
    for calendar in ["duplicate_week", "invalid_week", "undated_unknown"]:
        add("chart_invalid_" + calendar, filters(scenario(calendar=calendar)), {"Allocated": None, "Cumulative": None})
    add("chart_rls_denied", filters(scenario(project="P2")), {"Allocated": None, "Cumulative": None}, "Fixture Project P1")
    f = filters(scenario(calendar="unknown", start=dt.date(2026, 9, 9)))
    f["axis"] = "TREATAS({DATE(2026,9,1)},'Scenario Date'[Month])"
    add("chart_unknown_on_start_month", f, {"Allocated": None, "Cumulative": None})
    f = filters(scenario())
    f["axis"] = "TREATAS({DATE(2026,9,7),DATE(2026,9,9)},'Scenario Date'[Date])"
    add("chart_sparse_selected_dates", f, {"Allocated": 200, "Cumulative": 300})
    f = filters(scenario(quantity=100000, rate=100, cap=None))
    f["axis"] = "TREATAS({DATE(2026,9,1),DATE(2026,11,1)},'Scenario Date'[Month])"
    add("chart_disjoint_selected_months", f, {"Allocated": 3900, "Cumulative": 6100})
    output = DEFAULT.parent / "fixture_display_edge_cases.json"
    js(output, {"marker": MARKER, "testCount": len(tests), "tests": tests})
    print(json.dumps({"output": str(output), "tests": len(tests)}, indent=2))


if __name__ == "__main__":
    build()

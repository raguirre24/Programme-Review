"""Daily audit table queries retaining Desktop's measure-filter query shape."""
from __future__ import annotations

import datetime as dt
import argparse
import copy
import json

from test_build_fixture import DEFAULT, MARKER, SOURCE, js
from test_fixture_cases import filters, oracle, scenario


def build(report_bindings=False):
    tests = []
    columns = ["Scenario Daily Hours", "Scenario Daily Capacity", "Scenario Period Quantity", "Scenario Cumulative Quantity", "Scenario Daily Remaining"]
    if report_bindings:
        visual_path = SOURCE.parent.parent / "Project Review - Programme (datalake).Report" / "definition/pages/4c53a34bba9dcc7f3e8c/visuals/c4762ffe207ce780fc4d/visual.json"
        visual = json.loads(visual_path.read_text(encoding="utf-8-sig"))
        columns = [p["field"]["Measure"]["Property"] for p in visual["visual"]["query"]["queryState"]["Values"]["projections"][1:]]
        if len(columns) != 5 or any(f.get("field", {}).get("Measure", {}).get("Property") == "Scenario Show Daily Row" for f in visual.get("filterConfig", {}).get("filters", [])):
            raise ValueError("Final daily display bindings require five measures and no Show Daily Row visual filter.")
    for name, values in [
        ("native_audit_forward", scenario()),
        ("native_audit_inverse_daily", scenario(mode="Meet target date", cap=None)),
        ("native_audit_inverse_hourly", scenario(mode="Meet target date", basis="Per working hour", calendar="unequal", cap=None)),
    ]:
        f = filters(values)
        f.pop("axis")
        variables = "\n".join(f"VAR __Filter{i} = {expression}" for i, expression in enumerate(f.values()))
        arguments = ",\n".join(f"__Filter{i}" for i in range(len(f)))
        fields = '\n'.join(f',"{label}",[{measure}]' for label, measure in zip(["DailyHours", "DailyCapacity", "Allocated", "Cumulative", "DailyRemaining"], columns))
        statement = f"""DEFINE
{variables}
VAR __ValueFilterDM0 = FILTER(KEEPFILTERS(SUMMARIZECOLUMNS(
    'Scenario Date'[Date], {arguments}
    {fields}, "Scenario_Show_Daily_Row", IGNORE([Scenario Show Daily Row])
)), [Scenario_Show_Daily_Row] = 1)
VAR __DS0Core = SUMMARIZECOLUMNS('Scenario Date'[Date], {arguments}, __ValueFilterDM0 {fields})
VAR __DS0PrimaryWindowed = TOPN(501, __DS0Core, 'Scenario Date'[Date], 1)
EVALUATE __DS0PrimaryWindowed
ORDER BY 'Scenario Date'[Date]
"""
        if report_bindings:
            name = name.replace("native_audit_", "native_display_")
            statement = f"""DEFINE
{variables}
VAR __DS0Core = SUMMARIZECOLUMNS('Scenario Date'[Date], {arguments} {fields})
VAR __DS0PrimaryWindowed = TOPN(501, __DS0Core, 'Scenario Date'[Date], 1)
EVALUATE __DS0PrimaryWindowed
ORDER BY 'Scenario Date'[Date]
"""
        result = oracle(values)
        finish = dt.date.fromisoformat(result["Finish"])
        expected_rows = []
        for offset in range((finish - values["start"]).days + 1):
            day = values["start"] + dt.timedelta(days=offset)
            row = oracle(dict(values, axis=day))
            expected_rows.append({"Scenario Date[Date]": day.isoformat(), "DailyHours": row["DailyHours"], "DailyCapacity": row["DailyCapacity"],
                                  "Allocated": row["DailyQuantity"], "Cumulative": row["Cumulative"], "DailyRemaining": row["DailyRemaining"]})
        tests.append({"name": name, "dax": statement, "expect": {"Buckets": len(expected_rows), "Quantity": 1050, "FinalCumulative": 1050},
                      "contains": {}, "role": None, "maxRows": 365, "aggregateRows": True, "axisColumn": "Scenario Date[Date]", "expectedNativeRows": expected_rows})
    if report_bindings:
        for suffix, period_expression in [("cleared", None), ("multiple", "TREATAS({0,1},'Scenario Period'[Period Order])"), ("unmatched", "TREATAS({99},'Scenario Period'[Period Order])")]:
            period_test = copy.deepcopy(tests[0])
            period_test["name"] = "native_display_period_" + suffix
            if period_expression is None:
                period_test["dax"] = period_test["dax"].replace(",\n__Filter13", "")
            else:
                period_test["dax"] = period_test["dax"].replace("VAR __Filter13 = TREATAS({2},'Scenario Period'[Period Order])", "VAR __Filter13 = " + period_expression)
            tests.append(period_test)
        extra_cases = [
            ("native_display_zero_quantity", scenario(quantity=0), None, 0, 0, None),
            ("native_display_invalid_calendar", scenario(calendar="duplicate_week"), None, 0, 0, None),
            ("native_display_unknown_on_start", scenario(calendar="unknown", start=dt.date(2026, 9, 9)), None, 0, 0, None),
            ("native_display_rls_denied", scenario(project="P2"), "Fixture Project P1", 0, 0, None),
            ("native_display_365_day_boundary", scenario(quantity=100000, rate=1, cap=None), None, 365, 261, 261),
        ]
        for name, values, role, row_count, quantity, cumulative in extra_cases:
            f = filters(values)
            f.pop("axis")
            arguments = ",\n".join(f.values())
            statement = f"EVALUATE TOPN(501,SUMMARIZECOLUMNS('Scenario Date'[Date],{arguments} {fields}),'Scenario Date'[Date],1) ORDER BY 'Scenario Date'[Date]"
            tests.append({"name": name, "dax": statement, "expect": {"Buckets": row_count, "Quantity": quantity, "FinalCumulative": cumulative},
                          "contains": {}, "role": role, "maxRows": 365, "aggregateRows": True, "axisColumn": "Scenario Date[Date]"})
    output = DEFAULT.parent / ("fixture_daily_display_cases.json" if report_bindings else "fixture_daily_audit_cases.json")
    js(output, {"marker": MARKER, "testCount": len(tests), "tests": tests})
    print(json.dumps({"output": str(output), "tests": len(tests)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-bindings", action="store_true", help="Use the final PBIR's five bounded measure bindings with no visual measure filter.")
    build(parser.parse_args().report_bindings)

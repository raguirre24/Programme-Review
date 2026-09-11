"""Native grouped Day/Week/Month regression queries for the synthetic fixture."""
from __future__ import annotations

import json

from test_build_fixture import DEFAULT, MARKER, js
from test_fixture_cases import filters, scenario


def build():
    tests = []
    def add(name, values, period, count, quantity):
        f = filters(values)
        f.pop("axis")
        f["period"] = f"TREATAS({{{period}}},'Scenario Period'[Period Order])"
        f["range"] = "FILTER(ALL('Scenario Date'[Date]),'Scenario Date'[Date]>=DATE(2026,9,1)&&'Scenario Date'[Date]<=DATE(2026,10,31))"
        field = ["Date", "Week", "Month"][period]
        native = f"SUMMARIZECOLUMNS('Scenario Date'[{field}]," + ",\n".join(f.values()) + ',"Allocated",[Scenario Chart Quantity],"Cumulative",[Scenario Chart Cumulative Quantity])'
        query = 'EVALUATE ' + native
        tests.append({"name": name, "dax": query, "expect": {"Buckets": count, "Quantity": quantity, "FinalCumulative": quantity}, "contains": {}, "role": None, "maxRows": 100, "aggregateRows": True})
    for period, count in [(0, 15), (1, 3), (2, 1)]:
        add(["native_forward_day", "native_forward_week", "native_forward_month"][period], scenario(), period, count, 1050)
    add("native_inverse_daily_day", scenario(mode="Meet target date", cap=None), 0, 24, 1050)
    add("native_inverse_hourly_day", scenario(mode="Meet target date", basis="Per working hour", calendar="unequal", cap=None), 0, 24, 1050)
    add("native_inverse_capped_week", scenario(mode="Meet target date", cap=50), 1, 5, 1050)
    add("native_unknown_partial_month", scenario(calendar="unknown", quantity=1000), 2, 1, 200)
    add("native_completion_before_unknown", scenario(calendar="unknown", quantity=100), 2, 1, 100)
    output = DEFAULT.parent / "fixture_native_cases.json"
    js(output, {"marker": MARKER, "testCount": len(tests), "tests": tests})
    print(json.dumps({"output": str(output), "tests": len(tests)}, indent=2))


if __name__ == "__main__":
    build()

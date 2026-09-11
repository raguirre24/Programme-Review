"""Generate actual-DAX assertions using an independent daily calendar oracle."""
from __future__ import annotations

import argparse
import datetime as dt
from fractions import Fraction
import json
from pathlib import Path
import random
import re

from test_build_fixture import DEFAULT, MARKER, SOURCE, START, calendar_rows, dax, js

END = dt.date(2036, 12, 31)
SPECS = calendar_rows()[1]
MEASURES = re.findall(r"^\s*measure '([^']+)'", (SOURCE / "tables" / "Resource Scenario Measures.tmdl").read_text(encoding="utf-8-sig"), re.M)


def number(v):
    return None if v is None else float(v)


def scenario(**overrides):
    result = dict(calendar="base", project="P1", quantity=1050, scale=1, rate=120, cap=100,
                  start=START, target=dt.date(2026, 9, 30), axis=START, basis="Per working day", mode="Find finish date")
    result.update(overrides)
    return result


def filters(s):
    return {
        "calendar": f"TREATAS({{{dax(s['project'] + '|' + s['calendar'])}}},'Scenario Calendar'[clndr_id_key])",
        "project": f"TREATAS({{{dax(s['project'])}}},'Scenario Calendar'[ProjectKey])",
        "source": f"TREATAS({{{dax(s['calendar'] == 'base_csv')}}},'Scenario Calendar'[IsCsvSource])",
        "quantity": f"TREATAS({{{s['quantity']}}},'Scenario Quantity'[Value])",
        "scale": f"TREATAS({{{s['scale']}}},'Scenario Quantity Scale'[Multiplier])",
        "rate": f"TREATAS({{{s['rate']}}},'Scenario Rate'[Value])",
        "limit": f"TREATAS({{{s['cap'] if s['cap'] is not None else 100}}},'Scenario Limit'[Value])",
        "limitmode": f"TREATAS({{{dax('No limit' if s['cap'] is None else 'Daily limit')}}},'Scenario Limit Mode'[Mode])",
        "start": f"TREATAS({{{dax(s['start'].isoformat())}}},'Scenario Start'[Date Input])",
        "target": f"TREATAS({{{dax(s['target'].isoformat())}}},'Scenario Target'[Date Input])",
        "mode": f"TREATAS({{{dax(s['mode'])}}},'Scenario Mode'[Mode])",
        "basis": f"TREATAS({{{dax(s['basis'])}}},'Scenario Rate Basis'[Basis])",
        "unit": 'TREATAS({"items"},\'Scenario Unit\'[Unit])',
        "period": "TREATAS({2},'Scenario Period'[Period Order])",
        "axis": f"TREATAS({{{dax(s['axis'])}}},'Scenario Date'[Date])",
    }


def query(columns, f):
    row = "ROW(" + ",\n".join(dax(label) + "," + expr for label, expr in columns.items()) + ")"
    return "EVALUATE " + ("CALCULATETABLE(" + row + ",\n" + ",\n".join(f.values()) + ")" if f else row)


def oracle(s):
    week, exceptions = SPECS.get(s["calendar"], SPECS["base"])
    q = Fraction(str(s["quantity"])) * Fraction(str(s["scale"]))
    unknowns = [dt.date.fromisoformat(date) for date, hours in exceptions.items() if hours is None and dt.date.fromisoformat(date) >= s["start"]]
    unknown = min(unknowns) if unknowns else None
    safe = min(END, unknown - dt.timedelta(days=1)) if unknown else END

    def hours(date):
        return exceptions.get(date.isoformat(), week[date.weekday()])

    def dates(until):
        for offset in range(max(0, (until - s["start"]).days + 1)):
            yield s["start"] + dt.timedelta(days=offset)

    target_hours = sum(Fraction(str(hours(date))) for date in dates(s["target"])) if s["target"] <= safe else None
    target_days = sum(hours(date) > 0 for date in dates(s["target"])) if s["target"] <= safe else None
    required = None
    if not (s["basis"] == "Per working hour" and s["cap"] is not None):
        work = target_hours if s["basis"] == "Per working hour" else target_days
        required = Fraction(0) if q == 0 else q / work if work else None
    rate = required if s["mode"] == "Meet target date" else Fraction(str(s["rate"]))

    def capacity(date):
        h = hours(date)
        if h is None or rate is None:
            return None
        raw = (rate * Fraction(str(h)) if s["basis"] == "Per working hour" else rate) if h > 0 else Fraction(0)
        return min(raw, Fraction(str(s["cap"]))) if s["cap"] is not None else raw

    accumulated = Fraction(0)
    finish = None
    first = None
    working_used = 0
    through = {}
    for date in dates(safe):
        if hours(date) > 0 and first is None:
            first = date
        if finish is None and hours(date) > 0:
            working_used += 1
        cap = capacity(date)
        if cap is not None:
            accumulated += cap
        through[date] = accumulated if cap is not None else None
        if q > 0 and accumulated >= q and finish is None:
            finish = date

    def allocated(endpoint):
        if q == 0 or endpoint < s["start"]:
            return Fraction(0)
        amount = through.get(min(endpoint, safe))
        if amount is None:
            return None
        if amount >= q:
            return q
        return None if endpoint > safe else amount

    target = allocated(s["target"])
    horizon = allocated(safe)
    axis = s["axis"]
    allocated_axis = allocated(axis)
    before = allocated(axis - dt.timedelta(days=1))
    daily_hours = hours(axis) if s["start"] <= axis <= safe else None
    daily_capacity = capacity(axis) if daily_hours is not None else None
    daily_quantity = None if axis < s["start"] or axis > safe or allocated_axis is None or before is None or before >= q else allocated_axis - before
    cumulative = allocated(min(axis, safe))
    if axis < s["start"] or (axis > safe and cumulative != q):
        cumulative = None
    return {"Finish": finish.isoformat() if finish else None, "EffectiveStart": first.isoformat() if first and q > 0 else None,
            "WorkingDays": working_used if finish else None, "ElapsedDays": (finish - s["start"]).days + 1 if finish else None,
            "RequiredRate": number(required), "AppliedRate": number(rate), "Quantity": number(q),
            "TargetQuantity": number(target), "TargetRemaining": number(q - target) if target is not None else None,
            "HorizonRemaining": number(q - horizon) if horizon is not None else None,
            "DailyHours": number(daily_hours), "DailyCapacity": number(daily_capacity), "DailyQuantity": number(daily_quantity),
            "Cumulative": number(cumulative), "DailyRemaining": number(q - allocated_axis) if allocated_axis is not None else None,
            "FirstUnknown": unknown.isoformat() if unknown else None,
            "SafeThrough": safe.isoformat()}


OUTPUTS = {"Finish": "Scenario Finish Date", "EffectiveStart": "Scenario Effective Start", "WorkingDays": "Scenario Working Days",
           "ElapsedDays": "Scenario Elapsed Days", "RequiredRate": "Scenario Required Rate", "AppliedRate": "Scenario Applied Rate",
           "Quantity": "Scenario Selected Quantity", "TargetQuantity": "Scenario Target Quantity", "TargetRemaining": "Scenario Target Remaining",
           "HorizonRemaining": "Scenario Horizon Remaining", "DailyHours": "Scenario Daily Hours", "DailyCapacity": "Scenario Daily Capacity",
           "DailyQuantity": "Scenario Period Quantity", "Cumulative": "Scenario Cumulative Quantity", "DailyRemaining": "Scenario Daily Remaining",
           "FirstUnknown": "Scenario First Unknown Date", "SafeThrough": "Scenario Safe Through"}


def build(output):
    tests = []
    def add(name, columns, f, expect=None, contains=None, role=None):
        test = {"name": name, "dax": query(columns, f), "expect": expect or {}, "contains": contains or {}, "role": role, "maxRows": 1}
        if len(columns) > 6:
            # Diagnostics should not construct a much larger expression bundle
            # than the actual visual. Run each scalar independently, then merge
            # the results for the same immutable scenario assertion.
            test["fragments"] = [{"name": label, "dax": query({label: expr}, f)} for label, expr in columns.items()]
        tests.append(test)
    base = scenario()
    f = filters(base)
    add(f"all_{len(MEASURES)}_measures_compile_and_execute", {measure: "[" + measure + "]" for measure in MEASURES}, f)
    add("inverse_precision_probe", {"RateDouble": "CONVERT([Scenario Required Rate],DOUBLE)", "RateText": 'FORMAT([Scenario Required Rate],"0.000000000000000")', "TargetDeficit": "CONVERT([Scenario Selected Quantity]-[Scenario Required Rate]*18,DOUBLE)"}, f, {"RateDouble": 1050 / 18, "TargetDeficit": 0})
    add("fixture_counts", {"Calendars": "COUNTROWS('Scenario Calendar')", "Projects": "COUNTROWS(Project_Dimension)", "RuleRows": "COUNTROWS('11 XER_CALENDAR_DETAILED')", "Dates": "COUNTROWS('Scenario Date')"}, {}, {"Calendars": 12, "Projects": 2, "RuleRows": 93, "Dates": 4383})
    examples = {
        "forward_daily_cap_partial_final": base,
        "forward_uncapped": scenario(cap=None),
        "holiday_and_working_weekend": scenario(calendar="holiday", axis=dt.date(2026, 9, 12)),
        "holiday_nonworking_override": scenario(calendar="holiday", axis=dt.date(2026, 9, 8)),
        "unequal_day_capacity": scenario(calendar="unequal", axis=dt.date(2026, 9, 8), cap=None),
        "unequal_hour_capacity": scenario(calendar="unequal", axis=dt.date(2026, 9, 8), basis="Per working hour", rate=10, cap=None),
        "hourly_cap_applied_per_date": scenario(calendar="unequal", basis="Per working hour", rate=10, cap=50, axis=dt.date(2026, 9, 9)),
        "fractional_quantity": scenario(quantity=12345, scale=0.01, rate=12.3, cap=None),
        "decimal_tolerance_final_day": scenario(quantity=3, scale=0.1, rate=0.1, cap=None, axis=dt.date(2026, 9, 9)),
        "zero_quantity": scenario(quantity=0),
        "zero_rate": scenario(rate=0, cap=None),
        "zero_cap": scenario(cap=0),
        "zero_hour_calendar": scenario(calendar="zero", cap=None),
        "weekend_requested_start": scenario(start=dt.date(2026, 9, 12), axis=dt.date(2026, 9, 12), cap=None),
        "inverse_daily": scenario(mode="Meet target date", cap=None),
        "inverse_daily_infeasible_cap": scenario(mode="Meet target date", cap=50),
        "inverse_hourly": scenario(mode="Meet target date", basis="Per working hour", calendar="unequal", cap=None),
        "inverse_hourly_capped_unavailable": scenario(mode="Meet target date", basis="Per working hour"),
        "unknown_before_completion": scenario(calendar="unknown", quantity=1000, axis=dt.date(2026, 9, 8)),
        "unknown_day_blanks": scenario(calendar="unknown", quantity=1000, axis=dt.date(2026, 9, 9)),
        "completed_before_later_unknown": scenario(calendar="unknown", quantity=100, axis=dt.date(2026, 10, 1)),
        "inherited_csv_identity": scenario(calendar="base_csv"),
        "same_name_other_project": scenario(project="P2"),
        "beyond_horizon_quantity": scenario(quantity=100000, scale=1000000, rate=1, cap=None),
    }
    rng = random.Random(20260911)
    for i in range(12):
        examples[f"oracle_random_{i:02}"] = scenario(calendar=rng.choice(["base", "holiday", "unequal"]), quantity=rng.randint(1, 30000), scale=rng.choice([0.01, 0.1, 1]), rate=rng.randint(1, 2000) / 10, cap=rng.choice([None, 50, 100]), basis=rng.choice(["Per working day", "Per working hour"]), axis=START + dt.timedelta(days=rng.randint(0, 35)))
    for name, s in examples.items():
        # Match a native scalar card exactly; normalise XMLA date serials in
        # the harness instead of duplicating expensive measure references.
        columns = {key: "[" + measure + "]" for key, measure in OUTPUTS.items()}
        add(name, columns, filters(s), oracle(s))
    defaults = {key: value for key, value in f.items() if key in {"calendar", "project", "source", "axis"}}
    add("cleared_inputs_use_explicit_defaults", {"Quantity": "[Scenario Selected Quantity]", "Rate": "[Scenario Selected Rate]", "LimitMode": "[Scenario Selected Limit Mode]", "Unit": "[Scenario Selected Unit]", "StartToday": "[Scenario Selected Start]=TODAY()", "TargetThirtyDays": "[Scenario Selected Target]=TODAY()+30"}, defaults,
        {"Quantity": 1000, "Rate": 100, "LimitMode": "No limit", "Unit": "items", "StartToday": True, "TargetThirtyDays": True})
    bad_cases = [
        ("invalid_quantity_no_match", "quantity", "TREATAS({100001},'Scenario Quantity'[Value])", "quantity"),
        ("ambiguous_quantity", "quantity", "TREATAS({1000,1001},'Scenario Quantity'[Value])", "quantity"),
        ("invalid_rate_step", "rate", "TREATAS({120.05},'Scenario Rate'[Value])", "production rate"),
        ("invalid_iso_start", "start", "TREATAS({\"2026-02-30\"},'Scenario Start'[Date Input])", "start date"),
    ]
    for name, key, replacement, message in bad_cases:
        ff = dict(f); ff[key] = replacement
        add(name, {"Finish": "[Scenario Finish Date]", "Status": "[Scenario Status]"}, ff, {"Finish": None}, {"Status": message})
    for calendar, message in [("undated_unknown", "unresolved date"), ("duplicate_week", "seven unique"), ("invalid_week", "weekday hours"), ("duplicate_exception", "unknown from")]:
        add("calendar_" + calendar, {"Finish": "[Scenario Finish Date]", "Status": "[Scenario Status]"}, filters(scenario(calendar=calendar)), {"Finish": None}, {"Status": message})
    ff = dict(f); ff.pop("calendar"); ff.pop("project"); ff.pop("source")
    add("no_calendar_selection", {"Finish": "[Scenario Finish Date]", "Status": "[Scenario Status]"}, ff, {"Finish": None}, {"Status": "Select one authorised"})
    ff = dict(f); ff["target"] = "TREATAS({\"not-a-date\"},'Scenario Target'[Date Input])"
    add("invalid_optional_target_preserves_forward", {"Finish": "[Scenario Finish Date]", "Target": "[Scenario Target Quantity]", "Status": "[Scenario Status]"}, ff, {"Finish": "2026-09-21", "Target": None}, {"Status": "Target comparison unavailable"})
    ff = dict(f); ff["target"] = "TREATAS({\"2026-09-01\"},'Scenario Target'[Date Input])"; ff["mode"] = "TREATAS({\"Meet target date\"},'Scenario Mode'[Mode])"
    add("inverse_target_before_start", {"Finish": "[Scenario Finish Date]", "Status": "[Scenario Status]"}, ff, {"Finish": None}, {"Status": "before the start date"})
    ff = dict(f); ff["axis"] = "TREATAS({DATE(2026,9,7),DATE(2026,9,9)},'Scenario Date'[Date])"
    add("sparse_dates_do_not_fill_gap", {"Allocated": "[Scenario Period Quantity]", "Cumulative": "[Scenario Cumulative Quantity]"}, ff, {"Allocated": 200, "Cumulative": 300})
    ff = filters(scenario(quantity=100000, cap=None, rate=100)); ff.pop("axis"); ff["months"] = "TREATAS({DATE(2026,9,1),DATE(2026,11,1)},'Scenario Date'[Month])"
    add("disjoint_months_exclude_october", {"Allocated": "[Scenario Period Quantity]"}, ff, {"Allocated": 3900})
    ff = dict(f); ff.pop("axis")
    add("grand_total_matches_quantity", {"Allocated": "[Scenario Period Quantity]", "Cumulative": "[Scenario Cumulative Quantity]"}, ff, {"Allocated": 1050, "Cumulative": 1050})
    ff = dict(f); ff.pop("period")
    add("ambiguous_period_chart_only_guard", {"Chart": "[Scenario Chart Quantity]", "Line": "[Scenario Chart Cumulative Quantity]", "Title": "[Scenario Chart Title]", "Finish": "[Scenario Finish Date]"}, ff, {"Chart": None, "Line": None, "Finish": "2026-09-21"}, {"Title": "Select one display period"})
    for name, selector, count in [("project_filter", "TREATAS({\"P1\"},Project_Dimension[ProjectKey])", 11), ("project_filter_p2", "TREATAS({\"P2\"},Project_Dimension[ProjectKey])", 1)]:
        add(name, {"Calendars": "COUNTROWS('Scenario Calendar')"}, {"scope": selector}, {"Calendars": count})
    ff = dict(f); ff["scope"] = "TREATAS({\"P2\"},Project_Dimension[ProjectKey])"
    add("conflicting_project_selection_no_leak", {"Calendars": "COUNTROWS('Scenario Calendar')", "Finish": "[Scenario Finish Date]"}, ff, {"Calendars": None, "Finish": None})
    add("rls_p1_selector_scope", {"Calendars": "COUNTROWS('Scenario Calendar')", "Projects": "COUNTROWS(Project_Dimension)", "HiddenP2": "CALCULATE(COUNTROWS('Scenario Calendar'),TREATAS({\"P2\"},'Scenario Calendar'[ProjectKey]))"}, {}, {"Calendars": 11, "Projects": 1, "HiddenP2": None}, role="Fixture Project P1")
    add("rls_cannot_forecast_p2", {"Finish": "[Scenario Finish Date]", "Calendars": "COUNTROWS('Scenario Calendar')"}, filters(scenario(project="P2")), {"Finish": None, "Calendars": None}, role="Fixture Project P1")
    js(output, {"marker": MARKER, "measureCount": len(MEASURES), "testCount": len(tests), "oracle": "Independent day-by-day exact Fraction arithmetic; production DAX is executed unchanged.", "tests": tests})
    print(json.dumps({"output": str(output), "tests": len(tests), "allMeasures": len(MEASURES)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT.parent / "fixture_cases.json")
    build(parser.parse_args().output)

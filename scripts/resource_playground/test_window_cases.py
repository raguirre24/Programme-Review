"""Independent exact-arithmetic assertions for the rolling-window revision."""
from __future__ import annotations

import datetime as dt
from fractions import Fraction
import json
import re
import sys

sys.dont_write_bytecode = True
from test_build_window_fixture import ARTIFACTS, OUTPUT, SOURCE, MARKER, edate
from test_build_fixture import dax, js

manifest = json.loads((OUTPUT / "fixture-marker.json").read_text(encoding="utf-8-sig")) if (OUTPUT / "fixture-marker.json").exists() else None


def scenario(**changes):
    start = dt.date.fromisoformat(manifest["start"])
    values = dict(calendar="base", quantity=1050, scale=1, rate=120, cap=100, start=start, target=start + dt.timedelta(days=23), axis=start,
                  mode="Find finish date", basis="Per working day")
    values.update(changes)
    return values


def filters(s):
    spec = manifest["calendars"][s["calendar"]]
    return {
        "project": f"TREATAS({{{dax('Project one' if spec['project'] == 'P1' else 'Project two')}}},Project_Dimension[Project])",
        "update": f"TREATAS({{{dax(dt.date.fromisoformat(spec['update']))}}},CurrentDate[UpdateDate])",
        "calendar": f"TREATAS({{{dax(spec['key'])}}},'Scenario Calendar'[clndr_id_key])",
        "source": f"TREATAS({{{dax(spec['csv'])}}},'Scenario Calendar'[IsCsvSource])",
        "quantity": f"TREATAS({{{s['quantity']}}},'Scenario Quantity'[Value])",
        "scale": f"TREATAS({{{s['scale']}}},'Scenario Quantity Scale'[Multiplier])",
        "rate": f"TREATAS({{{s['rate']}}},'Scenario Rate'[Value])",
        "limit": f"TREATAS({{{s['cap'] if s['cap'] is not None else 100}}},'Scenario Limit'[Value])",
        "limitmode": f"TREATAS({{{dax('No limit' if s['cap'] is None else 'Daily limit')}}},'Scenario Limit Mode'[Mode])",
        "start": f"TREATAS({{{dax(s['start'].strftime('%d-%m-%Y'))}}},'Scenario Start'[Date Input])",
        "target": f"TREATAS({{{dax(s['target'].strftime('%d-%m-%Y'))}}},'Scenario Target'[Date Input])",
        "mode": f"TREATAS({{{dax(s['mode'])}}},'Scenario Mode'[Mode])",
        "basis": f"TREATAS({{{dax(s['basis'])}}},'Scenario Rate Basis'[Basis])",
        "unit": 'TREATAS({"items"},\'Scenario Unit\'[Unit])',
        "period": "TREATAS({2},'Scenario Period'[Period Order])",
        "axis": f"TREATAS({{{dax(s['axis'])}}},'Scenario Date'[Date])",
    }


def query(columns, f):
    row = "ROW(" + ",".join(dax(k) + "," + v for k, v in columns.items()) + ")"
    return "EVALUATE " + ("CALCULATETABLE(" + row + "," + ",".join(f.values()) + ")" if f else row)


def oracle(s):
    today, end = (dt.date.fromisoformat(manifest[k]) for k in ["today", "windowEnd"])
    spec = manifest["calendars"][s["calendar"]]
    q = Fraction(str(s["quantity"])) * Fraction(str(s["scale"]))
    unknowns = [dt.date.fromisoformat(d) for d, h in spec["exceptions"].items() if h is None and dt.date.fromisoformat(d) >= s["start"]]
    unknown = min(unknowns) if unknowns else None
    safe = min(end, unknown - dt.timedelta(days=1)) if unknown else end
    def hours(date):
        return spec["exceptions"].get(date.isoformat(), spec["week"][date.weekday()])
    def days(until):
        return [s["start"] + dt.timedelta(days=i) for i in range(max(0, (until - s["start"]).days + 1))]
    target_hours = sum(Fraction(str(hours(d))) for d in days(s["target"])) if s["target"] <= safe else None
    target_days = sum(hours(d) > 0 for d in days(s["target"])) if s["target"] <= safe else None
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
    through, finish, first = {}, None, None
    working = 0
    for date in days(safe):
        h = hours(date)
        if h > 0 and first is None:
            first = date
        if finish is None and h > 0:
            working += 1
        cap = capacity(date)
        if cap is not None:
            accumulated += cap
        through[date] = accumulated if cap is not None else None
        if q > 0 and accumulated >= q and finish is None:
            finish = date
    def allocated(date):
        if date > end:
            return None
        if q == 0 or date < s["start"]:
            return Fraction(0)
        total = through.get(min(date, safe))
        if total is None:
            return None
        if total >= q:
            return q
        return None if date > safe else total
    axis = s["axis"]
    axis_valid = today <= axis <= end and axis >= s["start"]
    current = allocated(axis) if axis_valid else None
    before = allocated(axis - dt.timedelta(days=1))
    daily = None if not axis_valid or axis > safe or current is None or before is None or before >= q else current - before
    target, horizon = allocated(s["target"]), allocated(safe)
    number = lambda value: None if value is None else float(value)
    return {"Finish": finish.isoformat() if finish else None, "RequiredRate": number(required), "AppliedRate": number(rate),
            "TargetQuantity": number(target), "TargetRemaining": number(q - target) if target is not None else None,
            "HorizonRemaining": number(q - horizon) if horizon is not None else None,
            "DailyHours": number(hours(axis)) if axis_valid and axis <= safe else None,
            "DailyCapacity": number(capacity(axis)) if axis_valid and axis <= safe else None,
            "DailyQuantity": number(daily), "Cumulative": number(current), "DailyRemaining": number(q - current) if current is not None else None}


NUMERIC = {"Finish": "Scenario Finish Date", "RequiredRate": "Scenario Required Rate", "AppliedRate": "Scenario Applied Rate", "TargetQuantity": "Scenario Target Quantity",
           "TargetRemaining": "Scenario Target Remaining", "HorizonRemaining": "Scenario Horizon Remaining", "DailyHours": "Scenario Daily Hours", "DailyCapacity": "Scenario Daily Capacity",
           "DailyQuantity": "Scenario Period Quantity", "Cumulative": "Scenario Cumulative Quantity", "DailyRemaining": "Scenario Daily Remaining"}
BLANK_OUTPUTS = {"Finish": "[Scenario Finish Date]", "Target": "[Scenario Target Quantity]", "TargetRemaining": "[Scenario Target Remaining]", "HorizonRemaining": "[Scenario Horizon Remaining]",
                 "Chart": "[Scenario Chart Quantity]", "Daily": "[Scenario Daily Display Quantity]"}


def build():
    if manifest is None:
        raise ValueError("Build the final-source window fixture first")
    today, end = (dt.date.fromisoformat(manifest[k]) for k in ["today", "windowEnd"])
    start = dt.date.fromisoformat(manifest["start"])
    tests = []
    def add(name, columns, f, expected=None, contains=None, role=None, split=False):
        test = {"name": name, "dax": query(columns, f), "expect": expected or {}, "contains": contains or {}, "role": role, "maxRows": 1}
        if split:
            test["fragments"] = [{"name": name, "dax": query({name: expression}, f)} for name, expression in columns.items()]
        tests.append(test)
    measures = re.findall(r"^\s*measure '([^']+)'", (SOURCE / "tables/Resource Scenario Measures.tmdl").read_text(encoding="utf-8-sig"), re.M)
    add("all_current_measures_execute", {name: "[" + name + "]" for name in measures}, filters(scenario()), split=True)
    examples = {
        "forward_capped_partial": scenario(), "forward_hourly_unequal": scenario(calendar="unequal", basis="Per working hour", rate=10, cap=None, axis=start + dt.timedelta(days=1)),
        "hourly_cap_per_date": scenario(calendar="unequal", basis="Per working hour", rate=10, cap=50, axis=start + dt.timedelta(days=2)),
        "holiday": scenario(calendar="holiday", axis=start + dt.timedelta(days=1)), "working_weekend": scenario(calendar="holiday", axis=start + dt.timedelta(days=5)),
        "fractional_final": scenario(quantity=12345, scale=0.01, rate=12.3, cap=None, axis=start + dt.timedelta(days=14)),
        "tolerance_final": scenario(quantity=3, scale=0.1, rate=0.1, cap=None, axis=start + dt.timedelta(days=2)),
        "inverse_daily_precision": scenario(mode="Meet target date", cap=None, axis=start + dt.timedelta(days=23)),
        "inverse_daily_cap": scenario(mode="Meet target date", cap=50),
        "inverse_hourly": scenario(mode="Meet target date", calendar="unequal", basis="Per working hour", cap=None),
        "inverse_hourly_cap_unsupported": scenario(mode="Meet target date", calendar="unequal", basis="Per working hour", cap=50),
        "zero_quantity": scenario(quantity=0), "zero_rate": scenario(rate=0, cap=None), "zero_cap": scenario(cap=0), "zero_calendar": scenario(calendar="zero"),
        "unknown_before_finish": scenario(calendar="unknown", axis=start + dt.timedelta(days=1)),
        "completed_before_unknown": scenario(calendar="unknown", quantity=100, axis=start + dt.timedelta(days=1)),
        "finish_on_window_end": scenario(calendar="always", start=end, target=end, axis=end, quantity=50, rate=50, cap=None),
        "cannot_finish_past_window": scenario(calendar="always", start=end, target=end, axis=end, quantity=51, rate=50, cap=None),
        "full_window_insufficient": scenario(calendar="always", start=today, target=end, axis=end, quantity=100000, rate=1, cap=None),
        "today_valid": scenario(calendar="always", start=today, target=today, axis=today, quantity=10, cap=None),
        "tomorrow_valid": scenario(calendar="always", start=today + dt.timedelta(days=1), target=today + dt.timedelta(days=1), axis=today + dt.timedelta(days=1), quantity=10, cap=None),
    }
    for name, values in examples.items():
        add(name, {label: "[" + measure + "]" for label, measure in NUMERIC.items()}, filters(values), oracle(values), split=True)
    for mode in ["Find finish date", "Meet target date"]:
        for name, key, value in [("start_yesterday", "start", today - dt.timedelta(days=1)), ("start_after_window", "start", end + dt.timedelta(days=1)),
                                 ("target_yesterday", "target", today - dt.timedelta(days=1)), ("target_after_window", "target", end + dt.timedelta(days=1)),
                                 ("target_before_start", "target", today)]:
            values = scenario(mode=mode, **{key: value})
            add(mode + "_" + name, BLANK_OUTPUTS, filters(values), dict.fromkeys(BLANK_OUTPUTS))
    for name, key, text in [("target_us_month13", "target", "09-13-2026"), ("target_invalid_day", "target", "31-02-2027"), ("target_iso_rejected", "target", "2026-10-31"), ("start_unpadded_rejected", "start", "3-4-2027")]:
        f = filters(scenario())
        table = "Scenario Start" if key == "start" else "Scenario Target"
        f[key] = f"TREATAS({{{dax(text)}}},'{table}'[Date Input])"
        add(name, BLANK_OUTPUTS, f, dict.fromkeys(BLANK_OUTPUTS))
    for text, date in [("13-09-2026", dt.date(2026, 9, 13)), ("03-04-2027", dt.date(2027, 4, 3))]:
        f = filters(scenario())
        f["start"] = f"TREATAS({{{dax(text)}}},'Scenario Start'[Date Input])"
        add("ddmm_exact_" + text, {"Start": "[Scenario Selected Start]"}, f, {"Start": date.isoformat()})
    for date in [today, end - dt.timedelta(days=10), end]:
        f = filters(scenario(calendar="always", start=date, target=end, axis=date))
        f.pop("target")
        add("cleared_target_" + date.isoformat(), {"Target": "[Scenario Selected Target]", "Validation": "[Scenario Target Validation]"}, f,
            {"Target": min(date + dt.timedelta(days=30), end).isoformat(), "Validation": ""})
    f = filters(scenario()); f.pop("start"); f.pop("target")
    add("cleared_dates_defaults", {"Start": "[Scenario Selected Start]", "Target": "[Scenario Selected Target]"}, f, {"Start": today.isoformat(), "Target": min(today + dt.timedelta(days=30), end).isoformat()})
    for date in [today - dt.timedelta(days=1), end + dt.timedelta(days=1)]:
        f = filters(scenario(calendar="always", start=today, target=end, axis=date, quantity=100000, rate=1, cap=None))
        columns = {name: "[" + name + "]" for name in ["Scenario Daily Hours", "Scenario Daily Capacity", "Scenario Period Quantity", "Scenario Cumulative Quantity", "Scenario Daily Remaining", "Scenario Chart Quantity", "Scenario Chart Cumulative Quantity", "Scenario Daily Display Quantity"]}
        add("axis_outside_" + date.isoformat(), columns, f, dict.fromkeys(columns), split=True)
    for selection in ["0", "1,2", "99"]:
        f = filters(scenario()); f["period"] = f"TREATAS({{{selection}}},'Scenario Period'[Period Order])"
        add("invalid_period_" + selection, {"Chart": "[Scenario Chart Quantity]", "Line": "[Scenario Chart Cumulative Quantity]", "Daily": "[Scenario Daily Display Quantity]"}, f,
            {"Chart": None, "Line": None, "Daily": 100})
    add("leap_rollover_contract", {"End": "EDATE(DATE(2028,2,29),12)", "LeapWindowDays": "COUNTROWS(CALENDAR(DATE(2027,3,1),EDATE(DATE(2027,3,1),12)))"}, {}, {"End": "2029-02-28", "LeapWindowDays": 367})
    add("period_domain", {"Rows": "COUNTROWS('Scenario Period')", "Min": "MIN('Scenario Period'[Period Order])", "Max": "MAX('Scenario Period'[Period Order])"}, {}, {"Rows": 2, "Min": 1, "Max": 2})
    f = filters(scenario(calendar="always", start=today, target=end, quantity=100000, rate=1, cap=None))
    selected = [today - dt.timedelta(days=1), today, today + dt.timedelta(days=1), end, end + dt.timedelta(days=1)]
    f["axis"] = "TREATAS({" + ",".join(dax(date) for date in selected) + "},'Scenario Date'[Date])"
    add("sparse_dates_clip_window", {"Quantity": "[Scenario Chart Quantity]", "RawQuantity": "[Scenario Period Quantity]", "Cumulative": "[Scenario Chart Cumulative Quantity]"}, f,
        {"Quantity": 3, "RawQuantity": 3, "Cumulative": (end - today).days + 1})
    first_month = edate(today.replace(day=1), 4)
    second_month = edate(first_month, 2)
    after_second = edate(second_month, 1)
    f = filters(scenario(calendar="always", start=today, target=end, quantity=100000, rate=1, cap=None)); f.pop("axis")
    f["months"] = f"TREATAS({{{dax(first_month)},{dax(second_month)}}},'Scenario Date'[Month])"
    selected_count = (edate(first_month, 1) - first_month).days + (after_second - second_month).days
    add("disjoint_months_only_selected_allocation", {"Quantity": "[Scenario Chart Quantity]", "RawQuantity": "[Scenario Period Quantity]", "Cumulative": "[Scenario Chart Cumulative Quantity]"}, f,
        {"Quantity": selected_count, "RawQuantity": selected_count, "Cumulative": (after_second - today).days})
    js(ARTIFACTS / "fixture_cases.json", {"marker": MARKER, "today": manifest["today"], "windowEnd": manifest["windowEnd"], "measureCount": len(measures), "tests": tests})
    print(json.dumps({"tests": len(tests), "measures": len(measures), "output": str(ARTIFACTS / 'fixture_cases.json')}, indent=2))


if __name__ == "__main__":
    build()

"""Build current-date comparison queries with an independent daily Fraction oracle.

This generates evidence inputs only. A separately guarded runner must execute
them against the marked source-free fixture and compare every expected row.
"""
from __future__ import annotations

import argparse
import datetime as dt
from fractions import Fraction as F
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from test_build_fixture import dax, js
from test_build_comparison_fixture import MARKER

CT = "'Scenario Comparison Calendar'"


def daily_oracle(spec, start, target, end, quantity=1050, rate=120, cap=100, basis="Per working day", mode="Find finish date"):
    """Enumerate resolved civil dates; do not reuse production prefix arithmetic."""
    if spec["defect"] or any(h is None or h < 0 for h in spec["week"]):
        return {"rows": [], "finish": None, "required": None, "targetRemaining": None}
    q = F(str(quantity))
    def hours(day):
        return spec["exceptions"].get(day.isoformat(), spec["week"][day.weekday()])
    def dates(until):
        return [start + dt.timedelta(days=i) for i in range(max(0, (until - start).days + 1))]
    unknown = [dt.date.fromisoformat(d) for d, h in spec["exceptions"].items() if h is None and dt.date.fromisoformat(d) >= start]
    safe = min(end, min(unknown) - dt.timedelta(days=1)) if unknown else end
    required = None
    if target <= safe and not (basis == "Per working hour" and cap is not None):
        work = sum(F(str(hours(d))) if basis == "Per working hour" else F(int(hours(d) > 0)) for d in dates(target))
        required = q / work if work else None
    applied = required if mode == "Meet target date" else F(str(rate))
    if applied is None:
        return {"rows": [], "finish": None, "required": required, "targetRemaining": None}
    allocated, rows, finish = F(0), [], None
    for day in dates(safe):
        if allocated >= q:
            break
        h = F(str(hours(day)))
        capacity = (applied * h if basis == "Per working hour" else applied) if h > 0 else F(0)
        if cap is not None:
            capacity = min(capacity, F(str(cap)))
        amount = min(capacity, q - allocated)
        allocated += amount
        rows.append((day, amount, allocated))
        if allocated >= q:
            finish = day
    by_target = sum(amount for day, amount, _ in rows if day <= target)
    remaining = q - by_target if target <= safe or finish and finish <= target else None
    return {"rows": rows, "finish": finish, "required": required, "targetRemaining": remaining}


def build(output: Path):
    manifest = json.loads((output / "fixture-marker.json").read_text(encoding="utf-8-sig"))
    if manifest["marker"] != MARKER:
        raise ValueError("Unexpected fixture marker")
    today, start, end = (dt.date.fromisoformat(manifest[k]) for k in ("today", "start", "windowEnd"))
    specs = manifest["calendars"]
    update = dt.date.fromisoformat(specs["base"]["update"])
    target = start + dt.timedelta(days=23)
    tests = []
    def filters(tags=None, project="P1", selected_update=update, **s):
        f = [f"TREATAS({{{dax(project)}}},Project_Dimension[ProjectKey])", f"TREATAS({{{dax(selected_update)}}},CurrentDate[UpdateDate])"]
        values = [("Scenario Quantity", "Value", s.get("quantity", 1050)), ("Scenario Quantity Scale", "Multiplier", 1),
                  ("Scenario Rate", "Value", s.get("rate", 120)), ("Scenario Limit", "Value", s.get("cap", 100) if s.get("cap", 100) is not None else 100),
                  ("Scenario Limit Mode", "Mode", "Daily limit" if s.get("cap", 100) is not None else "No limit"),
                  ("Scenario Mode", "Mode", s.get("mode", "Find finish date")), ("Scenario Rate Basis", "Basis", s.get("basis", "Per working day")),
                  ("Scenario Unit", "Unit", "items"), ("Scenario Start", "Date", s.get("start", start)), ("Scenario Target", "Date", s.get("target", target)),
                  ("Scenario Period", "Period Order", 2)]
        f += [f"TREATAS({{{dax(v)}}},'{t}'[{c}])" for t, c, v in values]
        if tags is not None:
            f += ["TREATAS({" + ",".join(dax(specs[tag]["key"]) for tag in tags) + "}," + CT + "[clndr_id_key])"]
        return f
    def scalar(name, expressions, f, expect=None, contains=None, role=None, split=False):
        def statement(fields):
            return "EVALUATE CALCULATETABLE(ROW(" + ",".join(dax(k) + "," + v for k, v in fields.items()) + ")," + ",".join(f) + ")"
        case = {"name": name, "dax": statement(expressions), "expect": expect or {}, "contains": contains or {}, "role": role}
        if split:
            case["fragments"] = [{"name": k, "dax": statement({k: v})} for k, v in expressions.items()]
        tests.append(case)
    def oracle(tag, s):
        return daily_oracle(specs[tag], s.get("start", start), s.get("target", target), end,
                            **{k: v for k, v in s.items() if k not in {"start", "target"}})
    def identity(tag):
        spec = specs[tag]
        return f"Project: {spec['project']} | Calendar key: {spec['key']} | Source: {'CSV' if spec['csv'] else 'Athena'}"
    def grouped(name, tags, field="Week", **s):
        f = filters(tags, **s)
        f = [x for x in f if "'Scenario Period'" not in x] + [f"TREATAS({{{1 if field == 'Week' else 2}}},'Scenario Period'[Period Order])"]
        core = "SUMMARIZECOLUMNS(" + CT + "[Calendar]," + CT + "[clndr_id_key],'Scenario Date'[" + field + "]," + ",".join(f) + ',"Allocated",[Comparison Chart Quantity],"Identity",[Comparison Calendar Identity])'
        statement = 'EVALUATE SELECTCOLUMNS(' + core + ',"Calendar",' + CT + '[clndr_id_key],"Period",\'Scenario Date\'[' + field + '],"Allocated",[Allocated],"Identity",[Identity])'
        eligible = tags if tags is not None else [k for k, spec in specs.items() if spec["project"] == "P1" and spec["update"] == update.isoformat()]
        expected = []
        for tag in eligible:
            buckets = {}
            for date, allocated, _ in oracle(tag, s)["rows"]:
                period = date - dt.timedelta(days=date.weekday()) if field == "Week" else date.replace(day=1)
                buckets[period] = buckets.get(period, F(0)) + allocated
            expected += [{"Calendar": specs[tag]["key"], "Period": period.isoformat(), "Allocated": float(amount), "Identity": identity(tag)} for period, amount in buckets.items()]
        tests.append({"name": name, "dax": statement, "expectedRows": expected, "keyColumns": ["Calendar", "Period"]})

    eligible = [k for k, spec in specs.items() if spec["project"] == "P1" and spec["update"] == update.isoformat()]
    scalar("default_all_project_update_scope", {"Calendars": "COUNTROWS(" + CT + ")", "Labels": "DISTINCTCOUNT(" + CT + "[Calendar])", "SelectionSummary": "[Comparison Selection Summary]"}, filters(), {"Calendars": len(eligible), "Labels": len(eligible)}, contains={"SelectionSummary": f"{len(eligible)} of {len(eligible)}"})
    scalar("duplicate_names_have_distinct_labels", {"Rows": "COUNTROWS(" + CT + ")", "Labels": "DISTINCTCOUNT(" + CT + "[Calendar])"}, filters(["duplicate_name_a", "duplicate_name_b"]), {"Rows": 2, "Labels": 2})
    scalar("different_sources_have_distinct_labels", {"Rows": "COUNTROWS(" + CT + ")", "Labels": "DISTINCTCOUNT(" + CT + "[Calendar])"}, filters(["source_athena", "source_csv"]), {"Rows": 2, "Labels": 2})
    collision_tags = ["label_collision_a", "label_collision_b", "label_collision_literal", "label_collision_nested"]
    collision_keys = ",".join(dax(specs[tag]["key"]) for tag in collision_tags)
    scalar("generated_and_literal_label_collisions", {"Rows": "COUNTROWS(" + CT + ")", "Labels": "DISTINCTCOUNT(" + CT + "[Calendar])",
           "OriginalLabels": "CALCULATE(DISTINCTCOUNT('Scenario Calendar'[Calendar]),TREATAS({" + collision_keys + "},'Scenario Calendar'[clndr_id_key]))"},
           filters(collision_tags), {"Rows": 4, "Labels": 4, "OriginalLabels": 4})
    scalar("case_insensitive_names_stay_distinct", {"Rows": "COUNTROWS(" + CT + ")", "Labels": "DISTINCTCOUNT(" + CT + "[Calendar])"}, filters(["label_case_a", "label_case_b"]), {"Rows": 2, "Labels": 2})
    scalar("prior_update_scope", {"Rows": "COUNTROWS(" + CT + ")"}, filters(selected_update=dt.date.fromisoformat(specs["base_previous"]["update"])), {"Rows": 2})
    scalar("P2_scope", {"Rows": "COUNTROWS(" + CT + ")"}, filters(project="P2"), {"Rows": 1})
    scalar("unaffected_scope_keeps_original_name", {"Label": "SELECTEDVALUE(" + CT + "[Calendar])"}, filters(["base_p2"], project="P2"), {"Label": specs["base_p2"]["name"]})
    scalar("RLS_denies_P2", {"Rows": "COALESCE(COUNTROWS(" + CT + "),0)", "Quantity": "[Comparison Chart Quantity]", "Identity": "[Comparison Calendar Identity]"}, filters(["base_p2"], project="P2"), {"Rows": 0, "Quantity": None, "Identity": None}, role="Fixture Project P1")
    scalar("no_aggregate_of_alternatives", {"Quantity": "[Comparison Chart Quantity]", "Rate": "[Comparison Required Rate]", "Remaining": "[Comparison Target Remaining]", "Finish": "[Comparison Finish Date]", "Identity": "[Comparison Calendar Identity]"}, filters(["base", "always"]), {"Quantity": None, "Rate": None, "Remaining": None, "Finish": None, "Identity": None}, split=True)
    scalar("selector_alone_does_not_run_finish", {"Finish": "[Comparison Finish Date]", "Status": "[Comparison Status]"}, filters(["base"]), {"Finish": None}, contains={"Status": "Select one calendar row"})
    scalar("cleared_selection_does_not_run_finish", {"Finish": "[Comparison Finish Date]"}, filters(), {"Finish": None})
    for tag in ["base", "holiday", "unequal", "base_csv", "duplicate_name_a", "duplicate_name_b", "unknown", "invalid_week"]:
        result = oracle(tag, {})
        f = filters([tag])
        scalar("single_" + tag, {"Quantity": "[Comparison Chart Quantity]", "Required": "[Comparison Required Rate]", "Remaining": "[Comparison Target Remaining]", "Identity": "[Comparison Calendar Identity]"}, f,
               {"Quantity": float(sum(r[1] for r in result["rows"])) if result["rows"] else None,
                "Required": None if result["required"] is None else float(result["required"]), "Remaining": None if result["targetRemaining"] is None else float(result["targetRemaining"]), "Identity": identity(tag) if result["rows"] else None}, split=True)
    first_allocation = next(day for day, amount, _ in oracle("base", {})["rows"] if amount > 0)
    after_allocation = oracle("base", {})["finish"] + dt.timedelta(days=45)
    for name, day, expected in [("tooltip_allocated_point", first_allocation, identity("base")), ("tooltip_outside_allocation", after_allocation, None)]:
        scalar(name, {"Identity": "[Comparison Calendar Identity]"}, filters(["base"]) + ["TREATAS({" + dax(day) + "},'Scenario Date'[Date])"], {"Identity": expected})
    scalar("tooltip_zero_quantity", {"Quantity": "[Comparison Chart Quantity]", "Identity": "[Comparison Calendar Identity]"}, filters(["base"], quantity=0), {"Quantity": None, "Identity": None})
    # An unrelated original single selector must not contaminate comparison rows.
    f = filters(["base"]) + ["TREATAS({" + dax(specs["holiday"]["key"]) + "},'Scenario Calendar'[clndr_id_key])"]
    scalar("comparison_ignores_original_selector", {"Quantity": "[Comparison Chart Quantity]"}, f, {"Quantity": 1050})
    # Inspection filtering is explicit and independent of the chart/slicer field.
    # Resolve the inspection label by identity: the rare scope-wide uniqueness
    # fallback may suffix even an otherwise unique name in an affected scope.
    inspected_label = "CALCULATETABLE(VALUES(" + CT + "[Inspection Calendar]),TREATAS({" + dax(specs["base"]["key"]) + "}," + CT + "[clndr_id_key]))"
    inspect = filters(["base", "always"]) + ["TREATAS(" + inspected_label + "," + CT + "[Inspection Calendar])"]
    scalar("inspected_row_finish", {"Finish": "[Comparison Finish Date]", "Status": "[Comparison Status]"}, inspect, {"Finish": oracle("base", {})["finish"].isoformat()}, contains={"Status": "working days"}, split=True)
    scalar("invalid_row_explained", {"Issue": "[Comparison Validation]"}, filters(["invalid_week"]), contains={"Issue": "weekday"})
    scalar("completed_before_unknown_retained", {"Remaining": "[Comparison Target Remaining]", "Issue": "[Comparison Validation]"}, filters(["unknown"], quantity=100), {"Remaining": 0}, contains={"Issue": "complete before unknown"}, split=True)
    unknown_date = min(dt.date.fromisoformat(day) for day, hours in specs["unknown"]["exceptions"].items() if hours is None)
    warning = "Calendar data is unknown from " + unknown_date.strftime("%d-%m-%Y") + "; select row for completion details."
    completed = "Quantity complete before unknown data; select row for finish."
    ready = "Ready; select this row for completion details."
    unknown_label = "CALCULATETABLE(VALUES(" + CT + "[Inspection Calendar]),TREATAS({" + dax(specs["unknown"]["key"]) + "}," + CT + "[clndr_id_key]))"
    unknown_cases = [
        ("unknown_after_target_forward_partial", {"quantity": 1050, "target": start + dt.timedelta(days=1)}, warning),
        ("unknown_after_target_forward_complete", {"quantity": 100, "target": start + dt.timedelta(days=1)}, completed),
        ("unknown_after_target_forward_later_finish", {"quantity": 150, "target": start}, warning),
        ("unknown_after_target_inverse_complete", {"quantity": 1050, "target": start + dt.timedelta(days=1), "mode": "Meet target date", "cap": None}, ready),
    ]
    for name, settings, issue in unknown_cases:
        result = oracle("unknown", settings)
        scoped = filters(["unknown"], **settings) + ["TREATAS(" + unknown_label + "," + CT + "[Inspection Calendar])"]
        scalar(name, {"Quantity": "[Comparison Chart Quantity]", "Required": "[Comparison Required Rate]", "Remaining": "[Comparison Target Remaining]", "Finish": "[Comparison Finish Date]", "Issue": "[Comparison Validation]"}, scoped,
               {"Quantity": float(sum(row[1] for row in result["rows"])), "Required": float(result["required"]), "Remaining": float(result["targetRemaining"]), "Finish": result["finish"].isoformat() if result["finish"] else None, "Issue": issue}, split=True)
    summary_settings = {"target": start + dt.timedelta(days=1)}
    summary_core = "SUMMARIZECOLUMNS(" + CT + "[Inspection Calendar]," + CT + "[clndr_id_key]," + ",".join(filters(["base", "unknown"], **summary_settings)) + ',"Required",[Comparison Required Rate],"Remaining",[Comparison Target Remaining],"Issue",[Comparison Validation])'
    summary_query = 'EVALUATE SELECTCOLUMNS(' + summary_core + ',"Calendar",' + CT + '[clndr_id_key],"Required",[Required],"Remaining",[Remaining],"Issue",[Issue])'
    summary_expected = []
    for tag, issue in [("base", ready), ("unknown", warning)]:
        result = oracle(tag, summary_settings)
        summary_expected.append({"Calendar": specs[tag]["key"], "Required": float(result["required"]), "Remaining": float(result["targetRemaining"]), "Issue": issue})
    tests.append({"name": "unknown_after_target_grouped_summary", "dax": summary_query, "expectedRows": summary_expected, "keyColumns": ["Calendar"]})
    for field in ["Week", "Month"]:
        grouped("default_all_" + field, None, field)
        grouped("subset_" + field, ["base", "holiday", "unequal", "base_csv"], field)
        grouped("isolated_base_" + field, ["base"], field)
        grouped("invalid_isolation_" + field, ["base", "invalid_week", "unknown"], field)
        grouped("duplicate_names_" + field, ["duplicate_name_a", "duplicate_name_b"], field)
        grouped("generated_label_collision_" + field, collision_tags, field)
        grouped("case_insensitive_names_" + field, ["label_case_a", "label_case_b"], field)
        grouped("hourly_daily_cap_" + field, ["base", "unequal"], field, basis="Per working hour", rate=10, cap=60)
        grouped("inverse_daily_" + field, ["base", "always", "unequal"], field, mode="Meet target date", cap=None)
        grouped("inverse_capped_" + field, ["base", "always"], field, mode="Meet target date", cap=50)
        grouped("inverse_hourly_" + field, ["base", "unequal"], field, mode="Meet target date", basis="Per working hour", cap=None)
        grouped("unsupported_inverse_hourly_cap_" + field, ["base", "unequal"], field, mode="Meet target date", basis="Per working hour", cap=50)
    js(output / "comparison_cases.json", {"marker": MARKER, "today": today.isoformat(), "fixtureDefinition": manifest["definition"], "tests": tests})
    print(json.dumps({"cases": len(tests), "groupedCases": sum("expectedRows" in t for t in tests), "chartCases": sum(t.get("keyColumns") == ["Calendar", "Period"] for t in tests), "summaryCases": sum(t.get("keyColumns") == ["Calendar"] for t in tests), "output": str(output / "comparison_cases.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    build(parser.parse_args().output_dir.resolve())

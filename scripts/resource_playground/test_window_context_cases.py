"""Context, secured identity and exact source-update mapping regressions."""
import datetime as dt
import json
import sys

sys.dont_write_bytecode = True
from test_window_cases import manifest, scenario, filters, query, BLANK_OUTPUTS
from test_build_fixture import dax, js
from test_build_window_fixture import ARTIFACTS, MARKER


def build():
    tests = []
    def add(name, columns, f, expect, contains=None, role=None):
        tests.append(dict(name=name, dax=query(columns, f), expect=expect, contains=contains or {}, role=role, maxRows=1))
    def by_name(tag):
        f = filters(scenario(calendar=tag)); f.pop("source")
        f["calendar"] = f"TREATAS({{{dax(manifest['calendars'][tag]['name'])}}},'Scenario Calendar'[Calendar])"
        return f
    columns = {"Rows": "COUNTROWS('Scenario Calendar')", "Key": "SELECTEDVALUE('Scenario Calendar'[clndr_id_key])",
               "Label": "SELECTEDVALUE('Scenario Calendar'[Calendar])", "Update": "SELECTEDVALUE('Scenario Calendar'[Report Update Date])",
               "Hours": "[Scenario Daily Hours]", "Validation": "[Scenario Calendar Validation]"}
    for tag, hours in [("base", 8), ("base_previous", 4), ("base_p2", 12), ("base_csv", 6), ("unused", 8), ("prior_only", 8)]:
        spec = manifest["calendars"][tag]
        add("context_name_" + tag, columns, by_name(tag), {"Rows": 1, "Key": spec["key"], "Label": spec["name"], "Update": spec["update"], "Hours": hours, "Validation": ""})
    f = by_name("prior_only"); f["update"] = filters(scenario())["update"]
    add("context_stale_name_new_update", dict(columns, **BLANK_OUTPUTS), f,
        dict.fromkeys(["Rows", "Key", "Label", "Update", "Hours"] + list(BLANK_OUTPUTS)), {"Validation": "available for the selected project and update"})
    for tag in ["duplicate_name_a", "source_athena"]:
        add("context_ambiguous_" + tag, {"Rows": columns["Rows"], "Validation": columns["Validation"], **BLANK_OUTPUTS}, by_name(tag),
            {"Rows": 2, **dict.fromkeys(BLANK_OUTPUTS)}, {"Validation": "more than one calendar"})
    for label, key in [("project_required", "project"), ("update_required", "update")]:
        f = by_name("base"); f.pop(key)
        add(label, {"Validation": columns["Validation"], **BLANK_OUTPUTS}, f, dict.fromkeys(BLANK_OUTPUTS),
            {"Validation": "Select one project" if key == "project" else "Select one report update month"})
    f = by_name("base"); f["update"] = "TREATAS({BLANK()},CurrentDate[UpdateDate])"
    add("context_blank_update", {"Validation": columns["Validation"], **BLANK_OUTPUTS}, f, dict.fromkeys(BLANK_OUTPUTS), {"Validation": "Select one report update month"})
    f = by_name("base"); f["update"] = f"TREATAS({{{dax(dt.date.fromisoformat(manifest['calendars']['base']['update']).replace(day=1))}}},CurrentDate[UpdateDate])"
    add("context_table11_month_is_not_report_update", {"Rows": columns["Rows"], **BLANK_OUTPUTS}, f, dict.fromkeys(["Rows"] + list(BLANK_OUTPUTS)))
    for tag, role in [("base", "Fixture Project P1"), ("base_p2", "Fixture Project P1")]:
        expected = {"Hours": 8, "CalendarRows": 1} if tag == "base" else {"Hours": None, "CalendarRows": None}
        add("rls_" + tag, {"Hours": "[Scenario Daily Hours]", "CalendarRows": "COUNTROWS('Scenario Calendar')"}, by_name(tag), expected, role=role)
    add("mapping_identity_cardinality", {"Rows": "COUNTROWS('Scenario Calendar')", "MissingDates": "COUNTROWS(FILTER('Scenario Calendar',ISBLANK('Scenario Calendar'[Report Update Date])))",
                                            "NonNameLabels": "COUNTROWS(FILTER('Scenario Calendar','Scenario Calendar'[Calendar]<>'Scenario Calendar'[Calendar Name]))",
                                            "TaskRows": "COUNTROWS('01 XER_TASK')", "CalendarRuleRows": "COUNTROWS('11 XER_CALENDAR_DETAILED')"}, {},
        {"Rows": 18, "MissingDates": None, "NonNameLabels": None, "TaskRows": 8, "CalendarRuleRows": 132})
    for tag in ["invalid_week", "duplicate_week"]:
        add("invalid_calendar_" + tag, BLANK_OUTPUTS, by_name(tag), dict.fromkeys(BLANK_OUTPUTS))
    output = ARTIFACTS / "fixture_context_cases.json"
    js(output, {"marker": MARKER, "tests": tests})
    print(json.dumps({"tests": len(tests), "output": str(output)}, indent=2))


if __name__ == "__main__":
    build()

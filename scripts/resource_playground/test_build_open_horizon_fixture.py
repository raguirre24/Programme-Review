"""Build the revised source-free fixture without changing production expressions."""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
import test_build_fixture as support

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "Project Review - Programme (datalake).SemanticModel/definition"
ARTIFACTS = REPO.parent / "resource_playground_review/open_horizon_20260911"
OUTPUT = ARTIFACTS / "ResourcePlaygroundOpenHorizonFixture"
MARKER = "resource-playground-open-horizon-20260911"
support.MARKER = MARKER
LITERALS = ["11 XER_CALENDAR_DETAILED", "Project_Dimension", "01 XER_TASK", "03 XER_PROJWBS", "Fixture Identity"]
CURRENT_DATE_DAX = "DISTINCT('01 XER_TASK'[UpdateDate])"


def edate(date, months):
    total = date.year * 12 + date.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    return dt.date(year, month, min(date.day, calendar.monthrange(year, month)[1]))


def fixture_data(today):
    start = today + dt.timedelta(days=(-today.weekday()) % 7)
    current_update = today - dt.timedelta(days=3)
    prior_update = edate(today, -1).replace(day=15)
    sources = [
        ("P1", "fixtureP1current.xer", False, current_update),
        ("P1", "fixtureP1previous.xer", False, prior_update),
        ("P2", "fixtureP2current.xer", False, current_update),
        ("P1", "csv::fixture::P1::" + today.strftime("%y%m"), True, current_update),
    ]
    specs = {}
    base = [8, 8, 8, 8, 8, 0, 0]
    def add(tag, source_index, native_id, name, week=None, exceptions=None, defect=None):
        project, namespace, csv, update = sources[source_index]
        key = namespace + ("::" if csv else ".") + str(native_id)
        specs[tag] = {"key": key, "project": project, "csv": csv, "name": name, "update": update.isoformat(),
                      "week": week if week is not None else base, "exceptions": exceptions or {}, "defect": defect}
    add("base", 0, 1, "Common calendar")
    add("base_previous", 1, 1, "Common calendar", [4, 4, 4, 4, 4, 0, 0])
    add("base_p2", 2, 1, "Common calendar", [12, 12, 12, 12, 12, 0, 0])
    add("base_csv", 3, 1, "CSV calendar", [6, 6, 6, 6, 6, 0, 0])
    add("holiday", 0, 2, "Holiday calendar", exceptions={(start + dt.timedelta(days=1)).isoformat(): 0, (start + dt.timedelta(days=5)).isoformat(): 4})
    add("unequal", 0, 3, "Unequal hours", [8, 4, 10, 0, 6, 0, 0], {(start + dt.timedelta(days=1)).isoformat(): 2})
    add("always", 0, 4, "Every day", [8] * 7)
    add("zero", 0, 5, "Zero hours", [0] * 7)
    add("unknown", 0, 6, "Unknown date", exceptions={(start + dt.timedelta(days=2)).isoformat(): None})
    add("unknown_on_start", 0, 7, "Unknown on start", exceptions={today.isoformat(): None})
    add("invalid_week", 0, 8, "Invalid weekday", [None, 8, 8, 8, 8, 0, 0])
    add("duplicate_week", 0, 9, "Duplicate weekday", defect="duplicate_week")
    add("unused", 0, 10, "Unused calendar")
    add("duplicate_name_a", 0, 11, "Duplicate name")
    add("duplicate_name_b", 0, 12, "Duplicate name", [4, 4, 4, 4, 4, 0, 0])
    add("prior_only", 1, 13, "Prior only")
    add("source_athena", 0, 14, "Source clash")
    add("source_csv", 3, 14, "Source clash", [6, 6, 6, 6, 6, 0, 0])
    rows = []
    for spec in specs.values():
        def row(dow, hours, date=None, kind="Standard"):
            valid = hours is not None
            return [spec["project"], spec["key"], spec["csv"], spec["name"], "Project", dt.date.fromisoformat(spec["update"]).replace(day=1), date,
                    calendar.day_name[dow - 1], dow, ("Y" if hours > 0 else "N") if valid else None,
                    (1 if hours > 0 else 0) if valid else None, hours, kind]
        rows.extend(row(dow, hours) for dow, hours in enumerate(spec["week"], 1))
        for text, hours in spec["exceptions"].items():
            date = dt.date.fromisoformat(text)
            rows.append(row(date.isoweekday(), hours, date, "Exception - Invalid" if hours is None else "Exception - Working" if hours > 0 else "Exception - Non-Working"))
        if spec["defect"] == "duplicate_week":
            rows.append(row(1, 8))
    tasks = []
    wbs = []
    for project, namespace, csv, update in sources:
        separator = "::" if csv else "."
        wbs_key = namespace + separator + "900"
        wbs.append([wbs_key, project])
        for identifier in [1001, 1002]:
            tasks.append([namespace, project, csv, update, namespace + separator + str(identifier), wbs_key])
    return rows, specs, tasks, wbs, sorted({source[3] for source in sources}), start


def build():
    clock = json.loads((ARTIFACTS / "engine_clock.json").read_text(encoding="utf-8-sig"))
    today = dt.date.fromisoformat(clock["today"])
    if dt.date.fromisoformat(clock["windowEnd"]) <= today:
        raise ValueError("Existing axis end must be later than the current engine date")
    if OUTPUT.exists() and any(OUTPUT.iterdir()) and not (OUTPUT / "fixture-marker.json").exists():
        raise ValueError("Refusing to reuse an unmarked fixture output")
    definition = OUTPUT / "ResourcePlaygroundOpenHorizonFixture.SemanticModel/definition"
    copied = []
    for source in sorted((SOURCE / "tables").glob("*.tmdl")):
        if source.stem.startswith("Scenario ") or source.stem == "Resource Scenario Measures":
            target = definition / "tables" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({"name": source.stem, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    if len(copied) != 14:
        raise ValueError("Expected precisely 14 production Scenario tables")
    rows, specs, tasks, wbs, updates, start = fixture_data(today)
    literal_data = [
        ("11 XER_CALENDAR_DETAILED", support.NAMES, support.TYPES, rows),
        ("Project_Dimension", ["ProjectKey", "Project"], ["string", "string"], [["P1", "Project one"], ["P2", "Project two"]]),
        ("01 XER_TASK", ["filename", "ProjectCode", "IsCsvSource", "UpdateDate", "task_id_key", "wbs_id_key"], ["string", "string", "boolean", "dateTime", "string", "string"], tasks),
        ("03 XER_PROJWBS", ["wbs_id_key", "ProjectKey"], ["string", "string"], wbs),
        ("Fixture Identity", ["Marker", "AnchorDate"], ["string", "dateTime"], [[MARKER, today]]),
    ]
    for name, columns, types, values in literal_data:
        support.write(definition / "tables" / (name + ".tmdl"), support.table(name, columns, types, values))
    shutil.copyfile(SOURCE / "tables/CurrentDate.tmdl", definition / "tables/CurrentDate.tmdl")
    names = LITERALS + ["CurrentDate"] + [entry["name"] for entry in copied]
    model = "model Model\n\tculture: en-NZ\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-NZ\n\nannotation ResourcePlaygroundFixture = " + MARKER + "\n\nannotation __PBI_TimeIntelligenceEnabled = 0\n\n"
    model += "\n".join("ref table '" + name + "'" for name in names) + "\n\nref role 'Fixture Project P1'\n"
    support.write(definition / "model.tmdl", model)
    support.write(definition / "database.tmdl", "database\n\tcompatibilityLevel: 1606\n")
    relationships = []
    for ft, fc, tt, tc, both in [
        ("03 XER_PROJWBS", "ProjectKey", "Project_Dimension", "ProjectKey", False),
        ("01 XER_TASK", "wbs_id_key", "03 XER_PROJWBS", "wbs_id_key", True),
        ("01 XER_TASK", "UpdateDate", "CurrentDate", "UpdateDate", True),
        ("11 XER_CALENDAR_DETAILED", "ProjectKey", "Project_Dimension", "ProjectKey", False),
        ("Scenario Calendar", "ProjectKey", "Project_Dimension", "ProjectKey", False),
        ("Scenario Calendar", "Report Update Date", "CurrentDate", "UpdateDate", False),
    ]:
        relationships.append(f"relationship {uuid.uuid5(uuid.NAMESPACE_URL, MARKER + ft + fc)}\n" + ("\tcrossFilteringBehavior: bothDirections\n" if both else "") + f"\tfromColumn: '{ft}'.'{fc}'\n\ttoColumn: '{tt}'.'{tc}'\n")
    support.write(definition / "relationships.tmdl", "\n".join(relationships))
    support.write(definition / "roles/Fixture Project P1.tmdl", "role 'Fixture Project P1'\n\tmodelPermission: read\n\n\ttablePermission Project_Dimension = 'Project_Dimension'[ProjectKey] = \"P1\"\n")
    manifest = {"marker": MARKER, "today": today.isoformat(), "windowEnd": clock["windowEnd"], "start": start.isoformat(), "tables": names,
                "literalTables": LITERALS, "currentDateExpression": CURRENT_DATE_DAX, "sourceTables": copied, "calendars": specs, "table11Rows": len(rows), "taskRows": len(tasks), "updates": [d.isoformat() for d in updates]}
    support.js(OUTPUT / "fixture-marker.json", manifest)
    print(json.dumps({"definition": str(definition), "tables": len(names), "calendarIdentities": len(specs), "table11Rows": len(rows), "today": today.isoformat()}, indent=2))


if __name__ == "__main__":
    build()

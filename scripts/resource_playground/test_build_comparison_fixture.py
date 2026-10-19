"""Create a marked, source-free comparison fixture; never connect to an engine.

The explicit date must be obtained from the target engine's TODAY(). All source
expressions are copied unchanged. Only synthetic data is supplied. Output must
be outside the production PBIP folders, and existing outputs require our marker.
"""
from __future__ import annotations

import argparse
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
from test_build_open_horizon_fixture import fixture_data as historical_fixture_data

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "Project Review - Programme (datalake).SemanticModel/definition"
MARKER = "resource-playground-comparison-20261017"
LITERALS = ["11 XER_CALENDAR_DETAILED", "Project_Dimension", "01 XER_TASK", "03 XER_PROJWBS", "Fixture Identity"]


def fixture_data(today):
    rows, specs, tasks, wbs, updates, start = historical_fixture_data(today)
    prototype = specs["base"]
    namespace = prototype["key"].rsplit(".", 1)[0]
    additions = [
        ("label_collision_a", 21, "Shift", [8, 8, 8, 8, 8, 0, 0]),
        ("label_collision_b", 22, "Shift", [4, 4, 4, 4, 4, 0, 0]),
        ("label_collision_literal", 23, "Shift [21]", [12, 12, 12, 12, 12, 0, 0]),
        # A second fixed suffix pass must not merely move the same collision.
        ("label_collision_nested", 24, f"Shift [{namespace}.21 | Athena]", [8] * 7),
        ("label_case_a", 25, "Case", [8, 8, 8, 0, 0, 0, 0]),
        ("label_case_b", 26, "case", [8, 8, 0, 0, 0, 0, 0]),
    ]
    for tag, native_id, name, week in additions:
        spec = dict(prototype, key=f"{namespace}.{native_id}", name=name, week=week, exceptions={}, defect=None)
        specs[tag] = spec
        for dow, hours in enumerate(week, 1):
            rows.append([spec["project"], spec["key"], spec["csv"], name, "Project", dt.date.fromisoformat(spec["update"]).replace(day=1), None,
                         calendar.day_name[dow - 1], dow, "Y" if hours else "N", int(hours > 0), hours, "Standard"])
    return rows, specs, tasks, wbs, updates, start


def build(output: Path, today: dt.date):
    output = output.resolve()
    if output == REPO or REPO in output.parents:
        raise ValueError("Keep fixture output outside the production repository, for example its sibling resource_playground_review folder.")
    marker_file = output / "fixture-marker.json"
    if output.exists() and any(output.iterdir()):
        if not marker_file.exists() or json.loads(marker_file.read_text(encoding="utf-8-sig"))["marker"] != MARKER:
            raise ValueError("Refusing to reuse an unmarked fixture output.")
    support.MARKER = MARKER
    definition = output / "ResourcePlaygroundComparisonFixture.SemanticModel/definition"
    sources = [source for source in sorted((SOURCE / "tables").glob("*.tmdl"))
               if source.stem.startswith("Scenario ") or source.stem == "Resource Scenario Measures"]
    if len(sources) != 15 or not any(source.stem == "Scenario Comparison Calendar" for source in sources):
        raise ValueError("Expected the final 15 production Scenario tables.")
    copied = []
    for source in sources:
        target = definition / "tables" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append({"name": source.stem, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    rows, specs, tasks, wbs, updates, start = fixture_data(today)
    literal_data = [
        ("11 XER_CALENDAR_DETAILED", support.NAMES, support.TYPES, rows),
        ("Project_Dimension", ["ProjectKey", "Project"], ["string", "string"], [["P1", "Project one"], ["P2", "Project two"]]),
        ("01 XER_TASK", ["filename", "ProjectCode", "IsCsvSource", "UpdateDate", "task_id_key", "wbs_id_key", "data_date"], ["string", "string", "boolean", "dateTime", "string", "string", "dateTime"], tasks),
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
    edges = [
        ("03 XER_PROJWBS", "ProjectKey", "Project_Dimension", "ProjectKey", False),
        ("01 XER_TASK", "wbs_id_key", "03 XER_PROJWBS", "wbs_id_key", True),
        ("01 XER_TASK", "UpdateDate", "CurrentDate", "UpdateDate", True),
        ("11 XER_CALENDAR_DETAILED", "ProjectKey", "Project_Dimension", "ProjectKey", False),
    ]
    for selector in ["Scenario Calendar", "Scenario Comparison Calendar"]:
        edges.extend([(selector, "ProjectKey", "Project_Dimension", "ProjectKey", False),
                      (selector, "Report Update Date", "CurrentDate", "UpdateDate", False)])
    relationships = []
    for ft, fc, tt, tc, both in edges:
        relationships.append(f"relationship {uuid.uuid5(uuid.NAMESPACE_URL, MARKER + ft + fc)}\n" + ("\tcrossFilteringBehavior: bothDirections\n" if both else "") + f"\tfromColumn: '{ft}'.'{fc}'\n\ttoColumn: '{tt}'.'{tc}'\n")
    support.write(definition / "relationships.tmdl", "\n".join(relationships))
    support.write(definition / "roles/Fixture Project P1.tmdl", "role 'Fixture Project P1'\n\tmodelPermission: read\n\n\ttablePermission Project_Dimension = 'Project_Dimension'[ProjectKey] = \"P1\"\n")
    # This is the existing shared-axis expression's refresh-year contract.
    manifest = {"marker": MARKER, "today": today.isoformat(), "windowEnd": dt.date(today.year + 10, 12, 31).isoformat(), "start": start.isoformat(), "tables": names,
                "literalTables": LITERALS, "currentDateExpression": "DISTINCT('01 XER_TASK'[UpdateDate])", "sourceTables": copied,
                "calendars": specs, "table11Rows": len(rows), "taskRows": len(tasks), "updates": [d.isoformat() for d in updates], "definition": str(definition)}
    support.js(marker_file, manifest)
    print(json.dumps({"definition": str(definition), "tables": len(names), "calendarIdentities": len(specs), "today": today.isoformat(), "marker": MARKER}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--today", required=True, type=dt.date.fromisoformat)
    args = parser.parse_args()
    build(args.output_dir, args.today)

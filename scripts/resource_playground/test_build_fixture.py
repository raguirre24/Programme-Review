"""Build an isolated, source-free PBIP for execution of the production scenario DAX.

The builder writes only its explicit fixture directory. It copies the current
production scenario definitions, rather than implementing a second DAX engine.
Never point its output at a production report directory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import uuid

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "Project Review - Programme (datalake).SemanticModel" / "definition"
MARKER = "resource-playground-repair-20260911"
DEFAULT = REPO.parent / "resource_playground_review" / "repair_20260911" / "ResourcePlaygroundFixture"
NAMES = ["ProjectKey", "clndr_id_key", "IsCsvSource", "clndr_name", "clndr_type", "MonthUpdate", "date", "day_of_week", "day_of_week_num", "working_day", "working_day_int", "work_hours", "exception_type"]
TYPES = ["string", "string", "boolean", "string", "string", "dateTime", "dateTime", "string", "int64", "string", "int64", "double", "string"]
START = dt.date(2026, 9, 7)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def js(path, data):
    write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def dax(v):
    if v is None:
        return "BLANK()"
    if isinstance(v, bool):
        return "TRUE()" if v else "FALSE()"
    if isinstance(v, dt.date):
        return f"DATE({v.year},{v.month},{v.day})"
    if isinstance(v, str):
        return '"' + v.replace('"', '""') + '"'
    return str(v)


def table(name, columns, types, rows):
    text = f"table '{name}'\n\tlineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, MARKER + name)}\n"
    for col, typ in zip(columns, types):
        text += f"\n\tcolumn '{col}'\n\t\tdataType: {typ}\n\t\tsummarizeBy: none\n\t\tsourceColumn: [{col}]\n"
    expressions = ["ROW(" + ",".join(dax(col) + "," + dax(val) for col, val in zip(columns, row)) + ")" for row in rows]
    expression = expressions[0] if len(expressions) == 1 else "UNION(\n" + ",\n".join(expressions) + "\n)"
    text += f"\n\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource =\n" + "\n".join("\t\t\t" + line for line in expression.splitlines()) + "\n"
    return text


def calendar_rows():
    rows = []
    specs = {
        "base": ([8, 8, 8, 8, 8, 0, 0], {}),
        "holiday": ([8, 8, 8, 8, 8, 0, 0], {"2026-09-08": 0, "2026-09-12": 4}),
        "unequal": ([8, 4, 10, 0, 6, 0, 0], {"2026-09-08": 2}),
        "zero": ([0] * 7, {}),
        "unknown": ([8, 8, 8, 8, 8, 0, 0], {"2026-09-09": None}),
        "unknown_after": ([8, 8, 8, 8, 8, 0, 0], {"2026-09-21": None}),
        "undated_unknown": ([8, 8, 8, 8, 8, 0, 0], {}),
        "duplicate_week": ([8, 8, 8, 8, 8, 0, 0], {}),
        "invalid_week": ([None, 8, 8, 8, 8, 0, 0], {}),
        "duplicate_exception": ([8, 8, 8, 8, 8, 0, 0], {"2026-09-09": 4}),
    }
    for project, key, csv in [("P1", key, False) for key in specs] + [("P2", "base", False), ("P1", "base_csv", True)]:
        week, exceptions = specs.get(key, specs["base"])
        def row(dow, hours, date=None, kind="Standard"):
            valid = hours is not None
            return [project, project + "|" + key, csv, "Common calendar" if key in {"base", "base_csv"} else key,
                    "Project", dt.date(2026, 9, 1), date, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dow - 1],
                    dow, ("Y" if hours > 0 else "N") if valid else None,
                    (1 if hours > 0 else 0) if valid else None, hours, kind]
        for dow, hours in enumerate(week, 1):
            rows.append(row(dow, hours))
        for text, hours in exceptions.items():
            date = dt.date.fromisoformat(text)
            kind = "Exception - Invalid" if hours is None else "Exception - Working" if hours > 0 else "Exception - Non-Working"
            rows.append(row(date.isoweekday(), hours, date, kind))
        if key == "undated_unknown":
            rows.append(row(1, None, None, "Exception - Invalid"))
        if key == "duplicate_week":
            rows.append(row(1, 8))
        if key == "duplicate_exception":
            rows.append(row(3, 4, dt.date(2026, 9, 9), "Exception - Working"))
    return rows, specs


def build(output):
    output = output.resolve()
    if output == REPO or SOURCE in output.parents or output in SOURCE.parents:
        raise ValueError("Fixture output must not contain or be inside the production semantic model")
    marker_file = output / "fixture-marker.json"
    if output.exists() and any(output.iterdir()) and not marker_file.exists():
        raise ValueError("Refusing to reuse a non-fixture directory")
    definition = output / "ResourcePlaygroundFixture.SemanticModel" / "definition"
    copied = []
    for source in sorted((SOURCE / "tables").glob("*.tmdl")):
        if source.stem.startswith("Scenario ") or source.stem == "Resource Scenario Measures":
            target = definition / "tables" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({"name": source.stem, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    if len(copied) != 14:
        raise ValueError(f"Expected 14 production scenario tables, got {len(copied)}")
    rows, specs = calendar_rows()
    write(definition / "tables" / "11 XER_CALENDAR_DETAILED.tmdl", table("11 XER_CALENDAR_DETAILED", NAMES, TYPES, rows))
    write(definition / "tables" / "Project_Dimension.tmdl", table("Project_Dimension", ["ProjectKey"], ["string"], [["P1"], ["P2"]]))
    write(definition / "tables" / "Fixture Identity.tmdl", table("Fixture Identity", ["Marker"], ["string"], [[MARKER]]))
    tables = ["11 XER_CALENDAR_DETAILED", "Project_Dimension", "Fixture Identity"] + [item["name"] for item in copied]
    model = "model Model\n\tculture: en-NZ\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-NZ\n\nannotation ResourcePlaygroundFixture = " + MARKER + "\n\nannotation __PBI_TimeIntelligenceEnabled = 0\n\n"
    model += "\n".join("ref table '" + name + "'" for name in tables) + "\n\nref role 'Fixture Project P1'\n"
    write(definition / "model.tmdl", model)
    write(definition / "database.tmdl", "database\n\tcompatibilityLevel: 1606\n")
    relations = ""
    for source in ["11 XER_CALENDAR_DETAILED", "Scenario Calendar"]:
        relations += f"relationship {uuid.uuid5(uuid.NAMESPACE_URL, MARKER + source)}\n\tfromColumn: '{source}'.ProjectKey\n\ttoColumn: Project_Dimension.ProjectKey\n\n"
    write(definition / "relationships.tmdl", relations)
    write(definition / "roles" / "Fixture Project P1.tmdl", "role 'Fixture Project P1'\n\tmodelPermission: read\n\n\ttablePermission Project_Dimension = 'Project_Dimension'[ProjectKey] = \"P1\"\n")
    js(output / "ResourcePlaygroundFixture.SemanticModel" / "definition.pbism", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {}})
    report = output / "ResourcePlaygroundFixture.Report"
    js(report / "definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": "../ResourcePlaygroundFixture.SemanticModel"}}})
    js(report / "definition" / "report.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json", "themeCollection": {"baseTheme": {"name": "CY23SU08", "reportVersionAtImport": {"visual": "1.8.84", "report": "2.0.84", "page": "1.3.84"}, "type": "SharedResources"}}})
    js(report / "definition" / "pages" / "pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json", "pageOrder": ["fixtureproof000000001"], "activePageName": "fixtureproof000000001"})
    js(report / "definition" / "pages" / "fixtureproof000000001" / "page.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json", "name": "fixtureproof000000001", "displayName": "Isolated DAX fixture", "displayOption": "FitToPage", "height": 720, "width": 1280})
    js(output / "ResourcePlaygroundFixture.pbip", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0", "artifacts": [{"report": {"path": "ResourcePlaygroundFixture.Report"}}], "settings": {"enableAutoRecovery": False}})
    manifest = {"marker": MARKER, "generatedUtc": dt.datetime.now(dt.timezone.utc).isoformat(), "fixtureRows": len(rows), "calendarIdentities": 12, "sourceTables": copied, "start": START.isoformat(), "calendars": specs}
    js(marker_file, manifest)
    print(json.dumps({"pbip": str(output / "ResourcePlaygroundFixture.pbip"), "model": str(definition), "marker": MARKER, "fixtureRows": len(rows), "productionTablesCopied": len(copied)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT)
    build(parser.parse_args().output)

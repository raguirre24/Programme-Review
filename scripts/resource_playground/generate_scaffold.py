"""Generate a new Resource Playground scaffold or explicit review-only drafts.

Calendar rules stay in table 11. There is deliberately no calendar/date crossjoin.
An existing Desktop-saved scaffold is never regenerated in place. Use
--output-dir to create draft table definitions for TOM semantic comparison;
draft generation does not change production registrations or relationships.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "Project Review - Programme (datalake).SemanticModel" / "definition"
TABLES = DEFINITION / "tables"
MARKER = "ResourcePlaygroundScaffold"


def identity(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "programme-review/resource-playground/" + name))


def quoted(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def column(table, name, dtype, source=None, fmt=None, hidden=False, extras=()):
    lines = [f"\tcolumn {quoted(name)}", f"\t\tdataType: {dtype}"]
    if hidden:
        lines.append("\t\tisHidden")
    if fmt:
        lines.append(f"\t\tformatString: {fmt}")
    lines += [f"\t\tlineageTag: {identity(table + '/' + name)}",
              "\t\tsummarizeBy: none", f"\t\tsourceColumn: [{source or name}]"]
    lines += list(extras)
    lines += ["", "\t\tannotation SummarizationSetBy = Automatic"]
    if dtype == "dateTime":
        lines += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    return "\n".join(lines)


def table(name, description, columns, expression):
    parts = ["/// " + description, f"table {quoted(name)}",
             f"\tlineageTag: {identity(name)}", "", "\n\n".join(columns), "",
             f"\tpartition {quoted(name)} = calculated", "\t\tmode: import",
             "\t\tsource = ```"]
    parts += ["\t\t\t" + line for line in expression.strip().splitlines()]
    parts += ["\t\t\t```", "", f"\tannotation {MARKER} = 1",
              f"\tannotation PBI_Id = {identity(name + '/pbi').replace('-', '')}", ""]
    text = "\n".join(parts)
    path = TABLES / (name + ".tmdl")
    if path.exists() and MARKER not in path.read_text(encoding="utf-8-sig"):
        raise RuntimeError(f"Refusing to replace an unowned table: {path}")
    path.write_text(text, encoding="utf-8", newline="\n")
    return name


def single(name, field, values, dtype="string", dax_type="STRING", fmt=None):
    literals = [json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v) for v in values]
    rows = ",\n".join("    { " + v + " }" for v in literals)
    return table(name, "Disconnected Resource Playground input; one value per scenario.",
                 [column(name, field, dtype, fmt=fmt)],
                 f'DATATABLE ( "{field}", {dax_type}, {{\n{rows}\n}} )')


def extend(path: Path, transform):
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    updated = transform(text)
    if updated != text:
        path.write_bytes(updated.replace("\n", newline).encode("utf-8"))


def main(output_dir: Path | None = None):
    global TABLES
    production_tables = DEFINITION / "tables"
    is_draft = output_dir is not None
    if is_draft:
        TABLES = output_dir.resolve()
        if TABLES == production_tables.resolve():
            raise RuntimeError("--output-dir must differ from the production tables directory.")
        TABLES.mkdir(parents=True, exist_ok=True)
    else:
        TABLES = production_tables
        existing = sorted(TABLES.glob("Scenario *.tmdl"))
        if existing:
            raise RuntimeError(
                "Refusing to overwrite an existing Desktop-saved scaffold. "
                "Use --output-dir for review-only drafts and compare them with TOM."
            )
    names = []
    name = "Scenario Date"
    names.append(table(name, "One shared display-date axis providing finite forecast coverage; measures require starts on or after today.",
        [column(name, "Date", "dateTime", fmt="dd-MM-yyyy"),
         column(name, "Week", "dateTime", fmt="dd-MM-yyyy"),
         column(name, "Month", "dateTime", fmt="MMM yyyy")],
        '''VAR __ScenarioAxisStart = DATE ( YEAR ( TODAY () ) - 1, 1, 1 )
VAR __ScenarioAxisEnd = DATE ( YEAR ( TODAY () ) + 10, 12, 31 )
RETURN
    ADDCOLUMNS (
        CALENDAR ( __ScenarioAxisStart, __ScenarioAxisEnd ),
        "Week", [Date] - WEEKDAY ( [Date], 2 ) + 1,
        "Month", DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 )
    )'''))
    for name in ["Scenario Start", "Scenario Target"]:
        names.append(table(name, "DD-MM-YYYY date input over the shared axis; measures enforce today's minimum and available date coverage.",
            [column(name, "Date", "dateTime", fmt="dd-MM-yyyy"),
             column(name, "Date Input", "string")],
            '''SELECTCOLUMNS (
    'Scenario Date',
    "Date", 'Scenario Date'[Date],
    "Date Input", FORMAT ( 'Scenario Date'[Date], "dd-MM-yyyy" )
)'''))
    name = "Scenario Calendar"
    names.append(table(name, "One row per governed calendar identity; explicitly secured by Project_Dimension.",
        [column(name, "ProjectKey", "string", hidden=True),
         column(name, "clndr_id_key", "string", hidden=True),
         column(name, "IsCsvSource", "boolean", hidden=True),
         column(name, "Calendar Name", "string", hidden=True),
         column(name, "MonthUpdate", "dateTime", fmt="dd-MM-yyyy"),
         column(name, "Report Update Date", "dateTime", fmt="dd-MM-yyyy", hidden=True),
         column(name, "Calendar", "string")],
        '''VAR SourceRows =
    FILTER (
        '11 XER_CALENDAR_DETAILED',
        NOT ISBLANK ( '11 XER_CALENDAR_DETAILED'[ProjectKey] )
            && '11 XER_CALENDAR_DETAILED'[ProjectKey] <> ""
            && NOT ISBLANK ( '11 XER_CALENDAR_DETAILED'[clndr_id_key] )
            && '11 XER_CALENDAR_DETAILED'[clndr_id_key] <> ""
    )
VAR Identities =
    SUMMARIZE (
        SourceRows,
        '11 XER_CALENDAR_DETAILED'[ProjectKey],
        '11 XER_CALENDAR_DETAILED'[clndr_id_key],
        '11 XER_CALENDAR_DETAILED'[IsCsvSource]
    )
VAR TaskSourceGroups =
    SUMMARIZE (
        '01 XER_TASK',
        '01 XER_TASK'[filename],
        '01 XER_TASK'[ProjectCode],
        '01 XER_TASK'[IsCsvSource],
        '01 XER_TASK'[UpdateDate],
        "__TaskMinimumKey", MIN ( '01 XER_TASK'[task_id_key] ),
        "__TaskMaximumKey", MAX ( '01 XER_TASK'[task_id_key] )
    )
VAR TaskSourceNamespaces =
    ADDCOLUMNS (
        TaskSourceGroups,
        "__MinimumNamespace",
            VAR TaskKey = [__TaskMinimumKey]
            VAR Delimiter = IF ( '01 XER_TASK'[IsCsvSource], "::", "." )
            VAR Tail = PATHITEMREVERSE ( SUBSTITUTE ( TaskKey, Delimiter, "|" ), 1 )
            RETURN IF ( NOT ISBLANK ( TaskKey ) && CONTAINSSTRING ( TaskKey, Delimiter ),
                LEFT ( TaskKey, LEN ( TaskKey ) - LEN ( Tail ) - LEN ( Delimiter ) ) ),
        "__MaximumNamespace",
            VAR TaskKey = [__TaskMaximumKey]
            VAR Delimiter = IF ( '01 XER_TASK'[IsCsvSource], "::", "." )
            VAR Tail = PATHITEMREVERSE ( SUBSTITUTE ( TaskKey, Delimiter, "|" ), 1 )
            RETURN IF ( NOT ISBLANK ( TaskKey ) && CONTAINSSTRING ( TaskKey, Delimiter ),
                LEFT ( TaskKey, LEN ( TaskKey ) - LEN ( Tail ) - LEN ( Delimiter ) ) )
    )
VAR WithMetadata =
    ADDCOLUMNS (
        Identities,
        "Calendar Name",
            VAR CalendarKey = '11 XER_CALENDAR_DETAILED'[clndr_id_key]
            VAR ProjectKey = '11 XER_CALENDAR_DETAILED'[ProjectKey]
            VAR CsvSource = '11 XER_CALENDAR_DETAILED'[IsCsvSource]
            VAR MatchingRows = FILTER ( SourceRows,
                '11 XER_CALENDAR_DETAILED'[clndr_id_key] = CalendarKey
                    && '11 XER_CALENDAR_DETAILED'[ProjectKey] = ProjectKey
                    && '11 XER_CALENDAR_DETAILED'[IsCsvSource] = CsvSource )
            VAR Names = DISTINCT ( SELECTCOLUMNS ( MatchingRows, "Name", '11 XER_CALENDAR_DETAILED'[clndr_name] ) )
            RETURN IF ( COUNTROWS ( Names ) = 1, MAXX ( Names, [Name] ), "Conflicting calendar names" ),
        "MonthUpdate",
            VAR CalendarKey = '11 XER_CALENDAR_DETAILED'[clndr_id_key]
            VAR ProjectKey = '11 XER_CALENDAR_DETAILED'[ProjectKey]
            VAR CsvSource = '11 XER_CALENDAR_DETAILED'[IsCsvSource]
            VAR MatchingRows = FILTER ( SourceRows,
                '11 XER_CALENDAR_DETAILED'[clndr_id_key] = CalendarKey
                    && '11 XER_CALENDAR_DETAILED'[ProjectKey] = ProjectKey
                    && '11 XER_CALENDAR_DETAILED'[IsCsvSource] = CsvSource )
            VAR __ScenarioUpdateValues = DISTINCT ( SELECTCOLUMNS ( MatchingRows, "Update", '11 XER_CALENDAR_DETAILED'[MonthUpdate] ) )
            RETURN IF ( COUNTROWS ( __ScenarioUpdateValues ) = 1, MAXX ( __ScenarioUpdateValues, [Update] ) ),
        "Report Update Date",
            VAR CalendarKey = '11 XER_CALENDAR_DETAILED'[clndr_id_key]
            VAR CsvSource = '11 XER_CALENDAR_DETAILED'[IsCsvSource]
            VAR Delimiter = IF ( CsvSource, "::", "." )
            VAR Tail = PATHITEMREVERSE ( SUBSTITUTE ( CalendarKey, Delimiter, "|" ), 1 )
            VAR Namespace = IF ( CONTAINSSTRING ( CalendarKey, Delimiter ),
                LEFT ( CalendarKey, LEN ( CalendarKey ) - LEN ( Tail ) - LEN ( Delimiter ) ) )
            VAR MatchingGroups = FILTER ( TaskSourceNamespaces,
                '01 XER_TASK'[IsCsvSource] == CsvSource
                    && ( [__MinimumNamespace] == Namespace || [__MaximumNamespace] == Namespace ) )
            VAR ConflictingNamespaces = COUNTROWS ( FILTER ( MatchingGroups,
                ISBLANK ( [__MinimumNamespace] ) || ISBLANK ( [__MaximumNamespace] )
                    || [__MinimumNamespace] <> [__MaximumNamespace] ) )
            VAR UpdateDates = DISTINCT ( SELECTCOLUMNS ( MatchingGroups, "__ReportDate", '01 XER_TASK'[UpdateDate] ) )
            VAR ReportDate = MAXX ( UpdateDates, [__ReportDate] )
            RETURN IF ( NOT ISBLANK ( Namespace ) && ConflictingNamespaces = 0
                && COUNTROWS ( UpdateDates ) = 1 && NOT ISBLANK ( ReportDate ), ReportDate )
    )
VAR __ScenarioWithLabel =
    ADDCOLUMNS (
        WithMetadata,
        "Calendar", COALESCE ( [Calendar Name], "Unnamed calendar" )
    )
RETURN
    SELECTCOLUMNS (
        __ScenarioWithLabel,
        "ProjectKey", [ProjectKey],
        "clndr_id_key", [clndr_id_key],
        "IsCsvSource", [IsCsvSource],
        "Calendar Name", [Calendar Name],
        "MonthUpdate", [MonthUpdate],
        "Report Update Date", [Report Update Date],
        "Calendar", [Calendar]
    )'''))
    for name, maximum, divisor in [("Scenario Quantity", 100000, 1),
                                    ("Scenario Rate", 100000, 10),
                                    ("Scenario Limit", 100000, 10)]:
        names.append(table(name,
            "Bounded exact numeric input. No what-if parameter sampling metadata is applied.",
            [column(name, "Value", "int64" if divisor == 1 else "decimal",
                    fmt="#,0" if divisor == 1 else "#,0.0")],
            f'SELECTCOLUMNS ( GENERATESERIES ( 0, {maximum}, 1 ), "Value", '
            + ('[Value]' if divisor == 1 else f'CURRENCY ( DIVIDE ( [Value], {divisor} ) )') + ' )'))
    names.append(single("Scenario Quantity Scale", "Multiplier", [0.01, 0.1, 1, 1000, 1000000],
                        "decimal", "CURRENCY", "#,0.##"))
    names.append(single("Scenario Limit Mode", "Mode", ["No limit", "Daily limit"]))
    names.append(single("Scenario Mode", "Mode", ["Find finish date", "Meet target date"]))
    names.append(single("Scenario Rate Basis", "Basis", ["Per working day", "Per working hour"]))
    names.append(single("Scenario Unit", "Unit", ["labour-hours", "tonnes", "m³", "metres", "items"]))
    name = "Scenario Period"
    names.append(table(name, "Native field parameter switching the shared chart axis between week and month.",
        [column(name, "Period", "string", source="Value1", extras=[
            "\t\tsortByColumn: 'Period Order'", "", "\t\trelatedColumnDetails",
            "\t\t\tgroupByColumn: 'Period Fields'"]),
         column(name, "Period Fields", "string", source="Value2", hidden=True, extras=[
            "\t\tsortByColumn: 'Period Order'", "", "\t\textendedProperty ParameterMetadata =",
            '\t\t\t\t{ "version": 3, "kind": 2 }']),
         column(name, "Period Order", "int64", source="Value3", hidden=True, fmt="0")],
        '''{
    ( "Week", NAMEOF ( 'Scenario Date'[Week] ), 1 ),
    ( "Month", NAMEOF ( 'Scenario Date'[Month] ), 2 )
}'''))

    if is_draft:
        print(json.dumps({"tables": names, "outputDirectory": str(TABLES),
                          "productionRegistrationsChanged": False,
                          "numericInputRows": 300003, "calendarDateCrossJoin": False}, indent=2))
        return

    def model(text):
        registrations = names + ["Resource Scenario Measures"]
        insertion = "".join("ref table " + quoted(n) + "\n" for n in registrations
                            if "ref table " + quoted(n) + "\n" not in text)
        if insertion:
            position = text.index("ref role ")
            text = text[:position] + insertion + "\n" + text[position:]
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("annotation PBI_QueryOrder = "):
                order = json.loads(line.split(" = ", 1)[1])
                order += [n for n in registrations if n not in order]
                lines[i] = "annotation PBI_QueryOrder = " + json.dumps(order, ensure_ascii=False, separators=(",", ":"))
        return "\n".join(lines) + "\n"

    extend(DEFINITION / "model.tmdl", model)
    relation_id = identity("project-selector-relationship")
    update_relation_id = identity("update-selector-relationship")
    def relationships(text):
        if f"relationship {relation_id}" not in text:
            text = text.rstrip() + f"\n\nrelationship {relation_id}\n" + (
                "\tfromColumn: 'Scenario Calendar'.ProjectKey\n"
                "\ttoColumn: Project_Dimension.ProjectKey\n")
        if f"relationship {update_relation_id}" not in text:
            text = text.rstrip() + f"\n\nrelationship {update_relation_id}\n" + (
                "\tfromColumn: 'Scenario Calendar'.'Report Update Date'\n"
                "\ttoColumn: CurrentDate.UpdateDate\n")
        return text
    extend(DEFINITION / "relationships.tmdl", relationships)
    print(json.dumps({"tables": names, "selectorRelationship": relation_id, "updateSelectorRelationship": update_relation_id,
                      "numericInputRows": 300003, "calendarDateCrossJoin": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Write review-only table drafts here without changing production model files.")
    main(parser.parse_args().output_dir)

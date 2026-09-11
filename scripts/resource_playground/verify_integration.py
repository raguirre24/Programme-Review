"""Check playground integration and preservation; this does not execute DAX."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "Project Review - Programme (datalake).SemanticModel/definition"
REPORT = ROOT / "Project Review - Programme (datalake).Report/definition"
# Confirmed by the installed engine; this is not a complete DAX keyword list.
KNOWN_REJECTED_VARIABLES = {"firstdate", "lastdate", "updates", "key"}
DAILY_VISUAL_ID = "c4762ffe207ce780fc4d"
CHART_VISUAL_ID = "fa2eaf106e8ead20b935"
EXPECTED_SCENARIO_MEASURES = 48
PERIOD_VISUAL_ID = "5f5e832a845f69b11b99"
RESET_BOOKMARK_ID = "e899bf3a9c2d243f33bf"
CALENDAR_VISUAL_ID = "16643c36a5f294a63a18"
RESET_TARGET_IDS = {
    "a47a28f5f6803a0bd238", CALENDAR_VISUAL_ID, "76632dab0ff8b86a8c55", "342b3372b9f35b4d628c",
    "f0c4beaebbd1f349d8fa", "34ac98823f173c5173e2", "179c68eefe44759dc6a6", "7c85a4199efc0955fcf9",
    "c3f32af88a59421d9975", "5b3c0db966d719181dd4", "cf0eeaddb7f90594dee2", PERIOD_VISUAL_ID,
}
CONTEXT_GROUPS = {
    "Project": ("Project_Dimension", "Project"),
    "State": ("Project_Dimension", "State"),
    "last_recalc_date": ("CurrentDate", "UpdateDate"),
}
DAILY_FIELDS = [
    ("Column", "Scenario Date", "Date"),
    ("Measure", "Resource Scenario Measures", "Scenario Daily Display Hours"),
    ("Measure", "Resource Scenario Measures", "Scenario Daily Display Capacity"),
    ("Measure", "Resource Scenario Measures", "Scenario Daily Display Quantity"),
    ("Measure", "Resource Scenario Measures", "Scenario Daily Display Cumulative"),
    ("Measure", "Resource Scenario Measures", "Scenario Daily Display Remaining"),
]


def validate_daily_projections(visual):
    projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
    assert len(projections) == 6, ("daily detail requires exactly six fields", len(projections))
    fields = []
    for projection in projections:
        assert projection.get("active") is True, ("inactive daily detail field", projection.get("queryRef"))
        field = projection["field"]
        assert len(field) == 1, ("unexpected daily field expression", field)
        kind, definition = next(iter(field.items()))
        fields.append((kind, definition["Expression"]["SourceRef"]["Entity"], definition["Property"]))
    assert fields == DAILY_FIELDS, ("daily detail field contract", fields)
    assert "Scenario Show Daily Row" not in json.dumps(visual.get("filterConfig", {})), \
        "Daily detail must use bounded display measures without the native row measure filter."
    totals = visual["visual"]["objects"]["total"][0]["properties"]["totals"]
    assert totals == {"expr": {"Literal": {"Value": "false"}}}, "Daily detail totals must remain disabled."


def validate_chart_projections(visual):
    query = visual["visual"]["query"]["queryState"]
    for role, name in (("Y", "Scenario Chart Quantity"), ("Y2", "Scenario Chart Cumulative Quantity")):
        projections = query[role]["projections"]
        assert len(projections) == 1, ("chart display field count", role)
        field = projections[0]["field"]["Measure"]
        assert field["Expression"]["SourceRef"]["Entity"] == "Resource Scenario Measures", ("chart measure table", role)
        assert field["Property"] == name, ("chart must use its display wrapper", role, field["Property"])
    assert "Scenario Show Period Row" not in json.dumps(visual.get("filterConfig", {})), \
        "The chart row measure filter exceeded the native query memory budget; use the display wrappers."


def validate_period_reset(bookmark):
    state = bookmark["explorationState"]["sections"]["4c53a34bba9dcc7f3e8c"]["visualContainers"][PERIOD_VISUAL_ID]
    reset_filter = state["singleVisual"]["objects"]["merge"]["general"][0]["properties"]["filter"]["filter"]
    where = reset_filter["Where"]
    assert len(where) == 1, "Reset must select exactly one display period."
    condition = where[0]["Condition"]["In"]
    assert condition["Expressions"][0]["Column"]["Property"] == "Period Fields", \
        "Field-parameter Reset must filter its identity field, not the display label."
    literal = "'''Scenario Date''[Month]'"
    assert condition["Values"] == [[{"Literal": {"Value": literal}}]], "Reset must select the Month field key."
    metadata = where[0]["Annotations"]["filterExpressionMetadata"]
    assert metadata["expressions"][0]["Column"]["Property"] == "Period", "Reset display metadata must refer to Period."
    identities = metadata["decomposedIdentities"]
    assert identities["columns"][0]["value"]["Column"]["Property"] == "Period Fields"
    assert identities["values"] == [[{"0": [{"Literal": {"Value": literal}}]}]], "Reset identity metadata must agree with its filter."
    assert metadata["valueMap"] == [{"0": "Month"}], "Reset must display Month for its field key."


def validate_calendar_reset(bookmark, calendar_visual):
    options = bookmark["options"]
    assert options.get("applyOnlyToTargetVisuals") is True, \
        "Target IDs are ignored without applyOnlyToTargetVisuals; Reset could clear report/page filters."
    assert len(options["targetVisualNames"]) == 12 and set(options["targetVisualNames"]) == RESET_TARGET_IDS
    state = bookmark["explorationState"]
    assert set(state) == {"version", "activeSection", "sections"}, "Reset must not capture report filter state."
    assert set(state["sections"]) == {"4c53a34bba9dcc7f3e8c"}
    section = state["sections"]["4c53a34bba9dcc7f3e8c"]
    assert set(section) == {"visualContainers"}, "Reset must not capture page filter state."
    assert set(section["visualContainers"]) == RESET_TARGET_IDS
    calendar_state = section["visualContainers"][CALENDAR_VISUAL_ID]
    for objects in (calendar_visual["visual"]["objects"], calendar_state["singleVisual"]["objects"]["merge"]):
        selection = objects["selection"][0]["properties"]
        assert selection["strictSingleSelect"]["expr"]["Literal"]["Value"] == "false", \
            "Calendar must allow an empty selection for Clear and Reset."
        # Desktop omits the ordinary singleSelect=true default when saving.
        ordinary = selection.get("singleSelect", {"expr": {"Literal": {"Value": "true"}}})
        assert ordinary["expr"]["Literal"]["Value"] == "true"
    filters = calendar_state["filters"]["byExpr"]
    assert len(filters) == 1 and "filter" not in filters[0], "Calendar Reset must capture an unselected native filter identity."
    entry = filters[0]
    assert entry["type"] == "Categorical" and entry["howCreated"] == 0
    expression = {"Column": {"Expression": {"SourceRef": {"Entity": "Scenario Calendar"}}, "Property": "Calendar"}}
    assert entry["expression"] == expression
    native_filters = calendar_visual["filterConfig"]["filters"]
    assert any(item["name"] == entry["name"] and item.get("field") == expression for item in native_filters), \
        "Calendar Reset filter identity must match its visual."
    general = calendar_state["singleVisual"]["objects"]["merge"].get("general", [])
    assert all("filter" not in item.get("properties", {}) for item in general), "Calendar Reset must not retain a selected value."


def validate_window_and_calendar_contract(tables, measures):
    period = tables["Scenario Period"]["calculatedPartitions"][0]["expression"]
    period_labels = re.findall(r'\(\s*"([^"]+)"\s*,\s*NAMEOF\s*\(', period, re.I)
    assert period_labels == ["Week", "Month"], ("display-period contract", period_labels)
    assert "NAMEOF ( 'Scenario Date'[Date] )" not in period
    for table in ("Scenario Start", "Scenario Target"):
        source = tables[table]["calculatedPartitions"][0]["expression"]
        assert re.search(r'FORMAT\s*\([^,]+,\s*"dd-MM-yyyy"\s*\)', source, re.I), \
            ("date input must use DD-MM-YYYY", table)
    validate_open_horizon_contract(measures)
    calendar = tables["Scenario Calendar"]
    columns = {column["name"]: column for column in calendar["columns"]}
    assert columns["Report Update Date"]["dataType"].lower() == "datetime"
    source = calendar["calculatedPartitions"][0]["expression"]
    assert "'01 XER_TASK'[UpdateDate]" in source, "Calendar update context must reuse the report's resolved snapshot dates."
    assert not re.search(r"\bEOMONTH\s*\(", dax_code(source), re.I), "Calendar source dates cannot approximate report update dates."
    assert not re.search(r"\bSELECTCOLUMNS\s*\(\s*'01 XER_TASK'\s*,", source, re.I), \
        "Group source snapshots before parsing key namespaces; do not parse every activity key."
    assert '& " | "' not in source, "Calendar choices must show calendar names without appended source identities."


def validate_open_horizon_contract(measures):
    axis_end = "calculate(max('scenariodate'[date]),removefilters('scenariodate'))"
    horizon_measures = ["Scenario Input Validation", "Scenario Target Validation", "Scenario Selected Target",
                        "Scenario Safe Through", "Scenario Hours Through", "Scenario Working Days Through",
                        "Scenario Capacity Through", "Scenario Allocated Through", "Scenario Period Quantity",
                        "Scenario Cumulative Quantity", "Scenario Chart Quantity", "Scenario Chart Cumulative Quantity",
                        "Scenario Evaluation Window", "Scenario Required Rate", "Scenario Status", "Scenario Chart Title",
                        "Scenario Input Summary", "Scenario Show Daily Row", "Scenario Show Period Row"]
    daily_measures = [field[2] for field in DAILY_FIELDS if field[0] == "Measure"]
    for name in horizon_measures + daily_measures:
        compact = re.sub(r"\s+", "", dax_code(measures[name])).casefold()
        assert axis_end in compact, ("coverage end must clear Date, Week and Month filters from the entire date axis", name)
    lower_bound_measures = ["Scenario Input Validation", "Scenario Target Validation", "Scenario Hours Through",
                            "Scenario Working Days Through", "Scenario Capacity Through", "Scenario Chart Quantity",
                            "Scenario Chart Cumulative Quantity", "Scenario Evaluation Window"] + daily_measures
    for name in lower_bound_measures:
        assert re.search(r"\bTODAY\s*\(\s*\)", dax_code(measures[name]), re.I), ("today remains the earliest scenario date", name)
    for name, expression in measures.items():
        if not name.startswith("Scenario "):
            continue
        code = dax_code(expression)
        assert not re.search(r"\bEDATE\s*\(", code, re.I), ("obsolete fixed-month scenario cap", name)
        assert not re.search(r"\+\s*365\b", code), ("obsolete fixed daily-detail cutoff", name)


def dax_code(expression):
    """Strip comments/string literals for static checks, not DAX compilation."""
    return re.sub(r'/\*.*?\*/|//[^\r\n]*|--[^\r\n]*|"(?:[^"]|"")*"',
                  " ", expression, flags=re.S)


def validate_qualified_dax_references(expressions, tables):
    """Check model field names in expressions; this is not DAX compilation."""
    model_fields = {
        table_name.casefold(): {field["name"].casefold()
                                for field in table["columns"] + table["measures"]}
        for table_name, table in tables.items()
    }
    pattern = re.compile(r"(?:'(?P<quoted>(?:[^']|'')+)'|(?P<bare>\b[A-Za-z_]\w*))"
                         r"\s*\[(?P<field>(?:[^\]]|\]\])+)\]")
    references = 0
    for name, source in expressions:
        for match in pattern.finditer(dax_code(source)):
            table = (match["quoted"] or match["bare"]).replace("''", "'")
            field = match["field"].replace("]]", "]")
            assert table.casefold() in model_fields, ("unknown qualified DAX table", name, table)
            assert field.casefold() in model_fields[table.casefold()], ("unknown qualified DAX field", name, table, field)
            references += 1
    return references


def validate_dax_variables(expressions, tables):
    table_names = {name.casefold() for name in tables}
    checks = 0
    for name, source in expressions:
        for variable in re.findall(r"\bVAR\s+(\w+)\s*=", dax_code(source), re.I):
            assert variable.casefold() not in table_names, ("variable shadows table", name, variable)
            assert variable.casefold() not in KNOWN_REJECTED_VARIABLES, ("known engine-rejected variable", name, variable)
            checks += 1
    return checks


def read_metadata(model_root, tom_directory=None):
    powershell = shutil.which("pwsh")
    assert powershell, "PowerShell 7 is required for the TOM metadata extractor."
    command = [powershell, "-NoProfile", "-File",
               str(Path(__file__).with_name("extract-model-metadata.ps1")),
               "-ModelRoot", str(model_root), "-CheckRoundTrip"]
    if tom_directory:
        command += ["-TomDirectory", str(tom_directory)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.lstrip("\ufeff"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--model-root", type=Path, default=MODEL)
    parser.add_argument("--report-root", type=Path, default=REPORT,
                        help="Report definition directory, including pages; accepts a generator draft.")
    parser.add_argument("--tom-directory", type=Path)
    args = parser.parse_args()
    metadata = read_metadata(args.model_root, args.tom_directory)
    tables = {table["name"]: table for table in metadata["tables"]}
    measures = {}
    for table in tables.values():
        for measure in table["measures"]:
            assert measure["name"] not in measures, ("ambiguous measure", measure["name"])
            measures[measure["name"]] = measure["expression"]
    added = [name for name in tables if name.startswith("Scenario ") or name == "Resource Scenario Measures"]
    assert len(added) == 14, ("scenario table coverage", len(added))
    scenario_measures = tables["Resource Scenario Measures"]["measures"]
    assert len(scenario_measures) == EXPECTED_SCENARIO_MEASURES, ("scenario measure coverage", len(scenario_measures))
    calculated_tables = [name for name in added if tables[name]["calculatedPartitions"]]
    assert len(calculated_tables) == 13, ("calculated table coverage", len(calculated_tables))
    expressions = [(f"{table_name}/{partition['name']}", partition["expression"])
                   for table_name in added for partition in tables[table_name]["calculatedPartitions"]]
    assert len(expressions) == 13, ("calculated partition coverage", len(expressions))
    expressions += [(measure["name"], measure["expression"]) for measure in scenario_measures]
    assert len(expressions) == 13 + EXPECTED_SCENARIO_MEASURES, ("DAX expression coverage", len(expressions))
    qualified_references = validate_qualified_dax_references(expressions, tables)
    validate_window_and_calendar_contract(tables, measures)
    model = (args.model_root / "model.tmdl").read_text(encoding="utf-8-sig")
    for name in added:
        assert model.count("ref table '" + name + "'\n") == 1, ("registration", name)
    relations = (args.model_root / "relationships.tmdl").read_text(encoding="utf-8-sig")
    scenario_relations = [block for block in relations.split("\nrelationship ") if "'Scenario " in block]
    assert len(scenario_relations) == 2, "Scenario calendars require project and report-update filter paths."
    project_paths = [block for block in scenario_relations if "fromColumn: 'Scenario Calendar'.ProjectKey" in block]
    update_paths = [block for block in scenario_relations if "fromColumn: 'Scenario Calendar'.'Report Update Date'" in block]
    assert len(project_paths) == len(update_paths) == 1
    assert "toColumn: Project_Dimension.ProjectKey" in project_paths[0]
    assert "toColumn: CurrentDate.UpdateDate" in update_paths[0]
    for block in scenario_relations:
        assert "bothDirections" not in block and not re.search(r"isActive:\s*false", block), \
            "Both scenario context relationships must be active and single direction."
    assert not any(re.search(r"\bCROSSJOIN\s*\(", dax_code(source), re.I) for _, source in expressions)
    assert "'Scenario Date'" not in tables["Scenario Calendar"]["calculatedPartitions"][0]["expression"]
    variable_checks = validate_dax_variables(expressions, tables)
    graph = {name: set(re.findall(r"(?<![\w'\]])\[([^\]]+)\]", dax_code(source))) & measures.keys()
             for name, source in measures.items()}
    completed = set()
    def visit(name, stack):
        assert name not in stack, ("measure cycle", stack, name)
        if name not in completed:
            for child in graph[name]:
                visit(child, stack + [name])
            completed.add(name)
    for name in graph:
        visit(name, [])
    page = args.report_root / "pages/4c53a34bba9dcc7f3e8c"
    page_data = json.loads((page / "page.json").read_text(encoding="utf-8-sig"))
    visuals = []
    calendar_visual = None
    context_visuals = {}
    for path in (page / "visuals").glob("*/visual.json"):
        visual = json.loads(path.read_text(encoding="utf-8-sig"))
        if visual["name"] == DAILY_VISUAL_ID:
            validate_daily_projections(visual)
        if visual["name"] == CHART_VISUAL_ID:
            validate_chart_projections(visual)
        if visual["name"] == CALENDAR_VISUAL_ID:
            calendar_visual = visual
        sync = visual["visual"].get("syncGroup")
        if sync:
            group = sync["groupName"]
            assert group in CONTEXT_GROUPS and group not in context_visuals, ("unexpected or repeated shared context group", group)
            assert sync.get("fieldChanges") is True and sync.get("filterChanges") is True
            projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
            assert len(projections) == 1
            column = projections[0]["field"]["Column"]
            assert (column["Expression"]["SourceRef"]["Entity"], column["Property"]) == CONTEXT_GROUPS[group]
            assert visual["name"] not in RESET_TARGET_IDS, "Shared project/update controls must remain outside scenario Reset."
            assert bool(visual.get("isHidden")) == (group == "State"), "Project/update context must be visible; State remains synchronised and hidden."
            context_visuals[group] = visual["name"]
        position = visual["position"]
        assert position["x"] >= 0 and position["y"] >= 0
        assert position["x"] + position["width"] <= page_data["width"]
        assert position["y"] + position["height"] <= page_data["height"]
        def inspect(value):
            if isinstance(value, dict):
                for kind in ("Measure", "Column"):
                    if kind in value and isinstance(value[kind], dict):
                        field = value[kind]
                        entity = field.get("Expression", {}).get("SourceRef", {}).get("Entity")
                        if entity:
                            assert entity in tables, (path, entity)
                            if kind == "Measure":
                                assert field["Property"] in {m["name"] for m in tables[entity]["measures"]}, (path, field)
                            else:
                                assert field["Property"] in {c["name"] for c in tables[entity]["columns"]}, (path, field)
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(visual)
        visuals.append(visual["name"])
    assert len(visuals) == len(set(visuals))
    assert len(visuals) == 35, ("playground visual coverage including shared context", len(visuals))
    assert set(context_visuals) == set(CONTEXT_GROUPS), "All three existing shared context groups must reach the playground."
    assert visuals.count(DAILY_VISUAL_ID) == 1, "The daily detail visual is missing or duplicated."
    assert visuals.count(CHART_VISUAL_ID) == 1, "The distribution chart is missing or duplicated."
    reset_bookmark = json.loads((args.report_root / "bookmarks" / (RESET_BOOKMARK_ID + ".bookmark.json")).read_text(encoding="utf-8-sig"))
    validate_period_reset(reset_bookmark)
    assert calendar_visual is not None, "The calendar input visual is missing."
    validate_calendar_reset(reset_bookmark, calendar_visual)
    preserved = []
    if args.baseline:
        for entry in json.loads((args.baseline / "files.json").read_text(encoding="utf-8-sig")):
            relative = entry["path"]
            if Path(relative).name in {"ARCHITECTURE.md", "model.tmdl", "relationships.tmdl", "pages.json"}:
                continue
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            assert digest.lower() == entry["sha256"].lower(), ("unrelated file changed", relative)
            preserved.append(relative)
    result = {"result": "PASS", "new_tables": len(added),
              "scenario_measures": len(scenario_measures),
              "calculated_tables": len(calculated_tables), "dax_expressions_checked": len(expressions),
              "qualified_dax_references_checked": qualified_references,
              "dax_variable_names_checked": variable_checks,
              "metadata_round_trip": metadata["roundTrip"],
              "engine": {"status": "NOT_RUN", "scope": "No DAX compilation, execution or table processing."},
              "page_visuals": len(visuals), "preserved_baseline_files": preserved,
              "active_daily_fields": 6,
              "reset_period": "Month (canonical field-parameter identity)",
              "reset_scope": "12 input visuals only; report/page filters excluded",
              "reset_calendar": "Cleared native filter identity; ordinary single selection allows empty",
              "shared_context_groups": context_visuals,
              "display_periods": ["Week", "Month"],
              "date_input_format": "DD-MM-YYYY",
              "evaluation_window": "TODAY() through the full existing Scenario Date maximum; all axis filters removed from coverage lookup",
              "checks": ["table registrations", "governed project and report-update selector relationships", "no calendar date cross join",
                         "complete TOM expression coverage", "known rejected VAR identifiers (static regression list)",
                         "DAX variable table-name collisions", "qualified DAX field references", "measure dependency cycles", "report field references",
                         "six active daily detail fields without native row measure filter or totals",
                         "chart display measures without native row measure filter",
                         "canonical Month reset identity and display metadata", "calendar clear-state and 12-target Reset scope",
                         "three shared context groups outside Reset",
                         "Week/Month periods, DD-MM-YYYY date inputs, today lower bound and full axis coverage independent of bucket filters",
                         "calendar-name labels and compact resolved snapshot-date mapping",
                         "page geometry", "unique visual identifiers"],
              "scope": "Static integration checks only. Does not compile or execute DAX, test RLS in a host, or render the page."}
    rendered = json.dumps(result, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

"""Generate the isolated Resource Playground PBIR page.

Native Input slicer schema was checked against the installed Power BI Desktop
2.157.1354.0 textSlicer capabilities and filter implementation. It filters a
bounded disconnected column; it does not create an arbitrary DAX variable.
Existing Resources visuals supply the native chart, table and navigator styling.
Run from any directory with --output-dir to generate review-only page drafts.
Existing Desktop-saved production pages are never overwritten by this script.
"""

from __future__ import annotations

import copy
import argparse
import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEFINITION = REPO / "Project Review - Programme (datalake).Report" / "definition"
RESOURCES = "099895b98057d0135349"
MEASURES = "Resource Scenario Measures"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"


def identifier(label: str) -> str:
    return hashlib.sha256(("resource-playground-v1:" + label).encode()).hexdigest()[:20]


PAGE = identifier("page")
RESET = identifier("reset")
VISUALS: dict[str, dict] = {}
INPUTS: list[str] = []


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def expr(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def string(value: str) -> dict:
    return expr("'" + value.replace("'", "''") + "'")


def colour(index: int, percent: float = 0) -> dict:
    return {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": index, "Percent": percent}}}}}


def props(**values: dict) -> list[dict]:
    return [{"properties": values}]


def field(table: str, column: str, kind: str = "Column", *, source: bool = False) -> dict:
    return {kind: {"Expression": {"SourceRef": {"Source" if source else "Entity": table}}, "Property": column}}


def projection(table: str, column: str, kind: str = "Column", label: str | None = None) -> dict:
    item = {"field": field(table, column, kind), "queryRef": f"{table}.{column}",
            "nativeQueryRef": label or column, "active": True}
    if label:
        item["displayName"] = label
    return item


def measure(column: str, label: str | None = None) -> dict:
    return projection(MEASURES, column, "Measure", label)


def default_filter(table: str, column: str, literal: str, *, numeric: bool = False) -> dict:
    target = field("s", column, source=True)
    condition = ({"Comparison": {"ComparisonKind": 0, "Left": target, "Right": {"Literal": {"Value": literal}}}}
                 if numeric else {"In": {"Expressions": [target], "Values": [[{"Literal": {"Value": literal}}]]}})
    return {"filter": {"Version": 2, "From": [{"Name": "s", "Entity": table, "Type": 0}], "Where": [{"Condition": condition}]}}


def empty_filter(table: str) -> dict:
    """An explicit unrestricted state makes Reset replace a previously entered filter."""
    return {"filter": {"Version": 2, "From": [{"Name": "s", "Entity": table, "Type": 0}], "Where": []}}


def period_filter(period: str) -> dict:
    """Match Desktop's field-parameter identity filter, including display metadata."""
    column = {"Day": "Date", "Week": "Week", "Month": "Month"}[period]
    field_key = f"'Scenario Date'[{column}]"
    literal = "'" + field_key.replace("'", "''") + "'"
    result = default_filter("Scenario Period", "Period Fields", literal)
    result["filter"]["Where"][0]["Annotations"] = {"filterExpressionMetadata": {
        "expressions": [field("Scenario Period", "Period")],
        "decomposedIdentities": {
            "values": [[{"0": [{"Literal": {"Value": literal}}]}]],
            "columns": [{"value": field("Scenario Period", "Period Fields")}],
        },
        "valueMap": [{"0": period}],
    }}
    return result


def container(label: str, visual_type: str, x: float, y: float, width: float, height: float, order: int) -> dict:
    item = {"$schema": SCHEMA + "visualContainer/2.12.0/schema.json", "name": identifier(label),
            "position": {"x": x, "y": y, "z": order * 1000, "height": height, "width": width, "tabOrder": order},
            "visual": {"visualType": visual_type, "objects": {}, "visualContainerObjects": {
                "background": props(show=expr("false")),
                "padding": props(top=expr("4D"), bottom=expr("4D"), left=expr("4D"), right=expr("4D")),
                "general": props(altText=string(label.replace("-", " "))),
            }, "drillFilterOtherVisuals": True}}
    VISUALS[label] = item
    return item


def title(item: dict, value: str, *, dynamic: bool = False, size: int = 12) -> None:
    item["visual"]["visualContainerObjects"]["title"] = props(
        show=expr("true"), text={"expr": field(MEASURES, value, "Measure")} if dynamic else string(value),
        fontSize=expr(f"{size}D"), fontColor=colour(1), bold=expr("false"), titleWrap=expr("true"))


def textbox(label: str, text: str, x: int, y: int, width: int, height: int, *, size: int = 12, bold: bool = False) -> None:
    item = container(label, "textbox", x, y, width, height, 0)
    item["visual"]["objects"] = {"general": props(paragraphs=[{"textRuns": [{"value": text,
        "textStyle": {"fontSize": f"{size}pt", "fontWeight": "bold" if bold else "normal", "fontFamily": "Segoe UI"}}]}])}


def input_slicer(label: str, table: str, column: str, caption: str, x: int, y: int, width: int, height: int,
                 order: int, *, default: str | float | int | None = None, numeric: bool = False,
                 placeholder: str = "") -> dict:
    item = container(label, "textSlicer", x, y, width, height, order)
    v = item["visual"]
    v["query"] = {"queryState": {"Values": {"projections": [projection(table, column)]}}}
    v["objects"] = {
        "slicerSettings": props(multiselect=expr("false"), numericInputOnly=expr("true" if numeric else "false")),
        "dropdown": props(filterMode=string("Filter_Is_Any")),
        "filterOperator": props(showText=expr("false")),
        "inputText": props(placeholder=string(placeholder), fontSize=expr("12D"), fontColor=colour(1)),
    }
    if default is not None:
        # Desktop saves exact numeric Input-slicer comparisons with M literals,
        # including the whole-number quantity column.
        literal = f"{default}M" if numeric else "'" + str(default).replace("'", "''") + "'"
        v["objects"]["general"] = props(filter=default_filter(table, column, literal, numeric=numeric))
    else:
        v["objects"]["general"] = props(filter=empty_filter(table))
    title(item, caption)
    INPUTS.append(label)
    return item


def dropdown(label: str, table: str, column: str, caption: str, x: int, y: int, width: int, height: int,
             order: int, default: str | int | None = None, *, numeric: bool = False, allow_empty: bool = False) -> dict:
    item = container(label, "slicer", x, y, width, height, order)
    v = item["visual"]
    v["query"] = {"queryState": {"Values": {"projections": [projection(table, column)]}},
                  "sortDefinition": {"sort": [{"field": field(table, column), "direction": "Ascending"}]}}
    v["objects"] = {"data": props(mode=string("Dropdown")), "selection": props(strictSingleSelect=expr("true")),
                    "header": props(show=expr("false")), "items": props(textSize=expr("12D"), fontColor=colour(1)),
                    "general": props(selfFilterEnabled=expr("true"))}
    if allow_empty:
        # Native strict single selection prevents Clear and restores a selected
        # item. Ordinary selection permits clearing; DAX enforces one calendar.
        v["objects"]["selection"] = props(strictSingleSelect=expr("false"), singleSelect=expr("true"))
        item["filterConfig"] = {"filters": [{"name": identifier(label + "-selection-filter"),
            "field": field(table, column), "type": "Categorical"}]}
    if default is not None:
        literal = f"{default}L" if numeric else "'" + str(default).replace("'", "''") + "'"
        v["objects"]["general"][0]["properties"]["filter"] = default_filter(table, column, literal)
    elif not allow_empty:
        v["objects"]["general"][0]["properties"]["filter"] = empty_filter(table)
    title(item, caption)
    INPUTS.append(label)
    return item


def card(label: str, output: str, caption: str, x: int, y: int, width: int, height: int, *, size: int = 25) -> None:
    item = container(label, "card", x, y, width, height, 30)
    item["visual"]["query"] = {"queryState": {"Values": {"projections": [measure(output, caption)]}}}
    item["visual"]["objects"] = {"categoryLabels": props(show=expr("false")),
        "labels": props(fontSize=expr(f"{size}D"), color=colour(1), labelDisplayUnits=expr("1D")),
        "wordWrap": props(show=expr("true"))}
    title(item, caption)


def show_measure_filter(output: str, label: str) -> dict:
    return {"filters": [{"name": identifier(label), "field": field(MEASURES, output, "Measure"), "type": "Advanced",
        "filter": {"Version": 2, "From": [{"Name": "r", "Entity": MEASURES, "Type": 0}], "Where": [{"Condition": {
            "Comparison": {"ComparisonKind": 0, "Left": field("r", output, "Measure", source=True),
                           "Right": {"Literal": {"Value": "1L"}}}}}]}, "howCreated": "User"}]}


def context_slicers() -> None:
    """Reuse the report's existing synced context without including it in Reset."""
    source = DEFINITION / "pages" / RESOURCES / "visuals"
    for label, old_id, caption, x, width in [
        ("context-project", "a4265e6358b19cd956ac", "Project", 422, 810),
        ("context-update", "720a90a0d00b39375588", "Monthly update", 1244, 518),
    ]:
        item = read(source / old_id / "visual.json")
        item["name"] = identifier(label)
        item.pop("isHidden", None)
        item.pop("parentGroupName", None)
        item["position"] = {"x": x, "y": 112, "z": 500, "width": width, "height": 68,
                            "tabOrder": 0 if label == "context-project" else 1}
        v = item["visual"]
        general = copy.deepcopy(v["objects"].get("general", props()))
        v["visualType"] = "slicer"
        v["objects"] = {
            "general": general, "data": props(mode=string("Dropdown")),
            "selection": props(strictSingleSelect=expr("false"), singleSelect=expr("true")),
            "header": props(show=expr("false")),
            "items": props(textSize=expr("12D"), fontColor=colour(1)),
        }
        for p in v["query"]["queryState"]["Values"]["projections"]:
            p["active"] = True
        title(item, caption)
        for f in item.get("filterConfig", {}).get("filters", []):
            f["name"] = identifier(label + "-filter-" + f["name"])
        VISUALS[label] = item
    state = read(source / "59f0493f357917eb627a" / "visual.json")
    state["name"] = identifier("context-state")
    state["isHidden"] = True
    state.pop("parentGroupName", None)
    state["position"] = {"x": 0, "y": 0, "z": 0, "width": 100, "height": 60, "tabOrder": 0}
    for f in state.get("filterConfig", {}).get("filters", []):
        f["name"] = identifier("context-state-filter-" + f["name"])
    VISUALS["context-state"] = state


def build_page(output_dir: Path | None = None) -> None:
    if output_dir is not None:
        output_definition = output_dir.resolve()
        production_report = DEFINITION.parent.resolve()
        if output_definition == production_report or production_report in output_definition.parents:
            raise RuntimeError("--output-dir must be outside the production report directory.")
    else:
        output_definition = DEFINITION
        if (DEFINITION / "pages" / PAGE).exists() or (DEFINITION / "bookmarks" / (RESET + ".bookmark.json")).exists():
            raise RuntimeError("Refusing to overwrite the existing Desktop-saved Resource Playground. Use --output-dir for review-only drafts.")
    VISUALS.clear()
    INPUTS.clear()
    textbox("heading", "Resource Playground", 0, 0, 1500, 70, size=25, bold=True)
    heading = VISUALS["heading"]["visual"]
    heading["objects"]["general"][0]["properties"]["paragraphs"][0]["textRuns"][0]["textStyle"]["color"] = "#FFFFFF"
    heading["visualContainerObjects"]["background"] = props(
        show=expr("true"), color={"solid": {"color": string("#D40000")}}, transparency=expr("0D"))
    heading["visualContainerObjects"]["padding"] = props(
        left=expr("24D"), right=expr("4D"), top=expr("8D"), bottom=expr("4D"))
    card("introduction", "Scenario Evaluation Window", "Planning window", 24, 78, 1744, 30, size=13)
    VISUALS["introduction"]["visual"]["visualContainerObjects"]["title"] = props(show=expr("false"))
    context_slicers()

    # Scenario parameters are page-local. The three context controls above reuse
    # the report's Project, State and monthly-update sync groups.
    dropdown("mode", "Scenario Mode", "Mode", "Calculation mode", 24, 110, 368, 76, 1, "Find finish date")
    dropdown("calendar", "Scenario Calendar", "Calendar", "Calendar", 24, 192, 368, 90, 2, allow_empty=True)
    input_slicer("quantity", "Scenario Quantity", "Value", "Quantity · 0–100,000", 24, 292, 224, 80, 3,
                 default=1050, numeric=True, placeholder="Whole quantity")
    dropdown("quantity-scale", "Scenario Quantity Scale", "Multiplier", "Multiply by", 260, 292, 132, 80, 4, 1, numeric=True)
    dropdown("unit", "Scenario Unit", "Unit", "Unit", 24, 382, 368, 68, 5, "m³")
    input_slicer("rate", "Scenario Rate", "Value", "Production · 0–10,000, step 0.1", 24, 460, 368, 80, 6,
                 default=120, numeric=True, placeholder="Production rate")
    dropdown("rate-basis", "Scenario Rate Basis", "Basis", "Production basis", 24, 550, 368, 68, 7, "Per working day")
    dropdown("limit-mode", "Scenario Limit Mode", "Mode", "Daily upper limit", 24, 628, 224, 68, 8, "Daily limit")
    input_slicer("limit", "Scenario Limit", "Value", "Limit · step 0.1", 260, 628, 132, 80, 9,
                 default=100, numeric=True, placeholder="0–10,000")
    input_slicer("start", "Scenario Start", "Date Input", "Start date · DD-MM-YYYY", 24, 724, 368, 80, 10,
                 placeholder="Clear uses today's date")
    input_slicer("target", "Scenario Target", "Date Input", "Target finish · DD-MM-YYYY", 24, 814, 368, 80, 11,
                 placeholder="Clear uses start + 30 days, within window")
    textbox("input-help", "Type one exact value and press Enter. Quantity × multiplier gives the total. Rate and limit use the selected unit.",
            24, 910, 368, 65, size=11)

    for index, (output, caption) in enumerate([
        ("Scenario Finish Date", "Potential finish"), ("Scenario Effective Start", "First working date"),
        ("Scenario Working Days", "Working dates used"), ("Scenario Elapsed Days", "Elapsed days"),
        ("Scenario Required Rate", "Required production"),
    ]):
        card("result-" + str(index), output, caption, 422 + index * 270, 196, 260, 100)
    card("status", "Scenario Status", "Scenario status", 422, 302, 1340, 68, size=15)
    card("input-summary", "Scenario Input Summary", "Evaluated inputs", 422, 376, 1340, 80, size=12)
    card("target-quantity", "Scenario Target Quantity", "Quantity by target", 422, 462, 300, 66, size=20)
    card("target-remaining", "Scenario Target Remaining", "Remaining at target", 748, 462, 300, 66, size=20)
    card("horizon-remaining", "Scenario Horizon Remaining", "Remaining at last known date", 1074, 462, 300, 66, size=20)
    period = dropdown("period", "Scenario Period", "Period", "Display period", 1492, 462, 270, 66, 12, "Month")
    period["visual"]["objects"]["general"][0]["properties"]["filter"] = period_filter("Month")

    source = DEFINITION / "pages" / RESOURCES / "visuals"
    chart = read(source / "bb2e46e5dbae497008e6" / "visual.json")
    chart["name"] = identifier("distribution-chart")
    chart["position"] = {"x": 422, "y": 536, "z": 31000, "height": 242, "width": 1340, "tabOrder": 31}
    v = chart["visual"]
    v["query"] = {"queryState": {
        "Category": {"projections": [projection("Scenario Date", "Month")], "fieldParameters": [{
            "parameterExpr": field("Scenario Period", "Period Fields"), "index": 0, "length": 1, "sortDirection": "Ascending"}]},
        "Y": {"projections": [measure("Scenario Chart Quantity", "Allocated quantity")]},
        "Y2": {"projections": [measure("Scenario Chart Cumulative Quantity", "Cumulative quantity")]},
    }, "sortDefinition": {"sort": [{"field": field("Scenario Date", "Month"), "direction": "Ascending"}], "isDefaultSort": True}}
    # Retain compatible native axis styling; remove old series, error bars and source-specific selectors.
    v["objects"] = {k: val for k, val in v["objects"].items() if k in {"categoryAxis", "valueAxis", "legend"}}
    v["objects"]["categoryAxis"][0]["properties"]["axisType"] = string("Categorical")
    v["objects"]["dataPoint"] = [
        {"properties": {"fill": colour(9)}, "selector": {"metadata": MEASURES + ".Scenario Chart Quantity"}},
        {"properties": {"fill": colour(1)}, "selector": {"metadata": MEASURES + ".Scenario Chart Cumulative Quantity"}},
    ]
    title(chart, "Scenario Chart Title", dynamic=True, size=16)
    # The native measure-filter query exceeded its 1 GB request budget. Display
    # wrappers return blank outside visible buckets without that filter phase.
    chart.pop("filterConfig", None)
    VISUALS["distribution-chart"] = chart

    textbox("daily-heading", "Daily detail · selected scenario", 422, 794, 1340, 32, size=13, bold=True)
    table = read(source / "224fd832199fc5bc1ac1" / "visual.json")
    table["name"] = identifier("daily-detail")
    table["position"] = {"x": 422, "y": 830, "z": 32000, "height": 188, "width": 1340, "tabOrder": 32}
    v = table["visual"]
    columns = [projection("Scenario Date", "Date"), measure("Scenario Daily Display Hours", "Working hours"),
        measure("Scenario Daily Display Capacity", "Capacity"), measure("Scenario Daily Display Quantity", "Allocated"),
        measure("Scenario Daily Display Cumulative", "Cumulative"), measure("Scenario Daily Display Remaining", "Remaining")]
    v["query"] = {"queryState": {"Values": {"projections": columns}}, "sortDefinition": {
        "sort": [{"field": field("Scenario Date", "Date"), "direction": "Ascending"}], "isDefaultSort": True}}
    v.pop("expansionStates", None)
    v["objects"]["columnWidth"] = [{"properties": {"value": expr(f"{210 if i else 180}D")},
                                   "selector": {"metadata": p["queryRef"]}} for i, p in enumerate(columns)]
    v["objects"]["columnHeaders"][0]["properties"]["fontSize"] = expr("12D")
    v["objects"]["values"][0]["properties"]["fontSize"] = expr("12D")
    # A sum of cumulative quantities or capacities is not a meaningful scenario total.
    v["objects"]["total"] = props(totals=expr("false"))
    v["visualContainerObjects"]["title"][0]["properties"]["text"] = string("Daily resource detail")
    # Display measures bound the daily dates and blank unknown rows within the
    # value query, avoiding the expensive native measure-filter query phase.
    table.pop("filterConfig", None)
    VISUALS["daily-detail"] = table

    textbox("calendar-basis", "Calendar basis: weekly rules and dated exceptions in the selected update. Future holidays are included only when present in that calendar.",
            422, 1026, 1340, 42, size=11)
    reset = read(source / "422b7d5c5696862377d2" / "visual.json")
    reset["name"] = identifier("reset-button")
    reset["position"] = {"x": 24, "y": 990, "z": 13000, "height": 44, "width": 368, "tabOrder": 13}
    reset.pop("isHidden", None)
    reset["visual"]["objects"]["text"][1]["properties"]["text"] = string("Reset scenario")
    reset["visual"]["visualContainerObjects"]["visualLink"][0]["properties"]["bookmark"] = string(RESET)
    VISUALS["reset-button"] = reset

    # Both automatic page navigators retain their existing show/hide policy.
    for label, old in [("home-navigation", "fb6dc1ae9a97dc777817"), ("page-navigation", "139185c162e95a768ece")]:
        item = read(source / old / "visual.json")
        item["name"] = identifier(label)
        item["position"]["tabOrder"] = 40 if label == "home-navigation" else 41
        VISUALS[label] = item

    # Source selections and chart clicks cannot alter scenario inputs or completion cards.
    interactions = []
    for source_label in ["distribution-chart", "daily-detail"]:
        for target_label in INPUTS + ["context-project", "context-update", "context-state", "status", "input-summary", "target-quantity", "target-remaining", "horizon-remaining"] + ["result-" + str(i) for i in range(5)]:
            interactions.append({"source": identifier(source_label), "target": identifier(target_label), "type": "NoFilter"})
    # Keep chart and daily audit unfiltered by clicking each other; use period control to change grouping.
    for a, b in [("distribution-chart", "daily-detail"), ("daily-detail", "distribution-chart")]:
        interactions.append({"source": identifier(a), "target": identifier(b), "type": "NoFilter"})
    page = {"$schema": SCHEMA + "page/2.1.0/schema.json", "name": PAGE, "displayName": "Resource Playground",
            "displayOption": "FitToPage", "height": 1080, "width": 1920, "visualInteractions": interactions}
    write(output_definition / "pages" / PAGE / "page.json", page)
    for item in VISUALS.values():
        write(output_definition / "pages" / PAGE / "visuals" / item["name"] / "visual.json", item)

    metadata_path = DEFINITION / "pages" / "pages.json"
    metadata = read(metadata_path)
    order = [p for p in metadata["pageOrder"] if p != PAGE]
    order.insert(order.index(RESOURCES) + 1, PAGE)
    metadata["pageOrder"] = order
    write(output_definition / "pages" / "pages.json", metadata)

    states = {}
    for label in INPUTS:
        item = VISUALS[label]
        objects = copy.deepcopy(item["visual"]["objects"])
        states[item["name"]] = {"singleVisual": {"visualType": item["visual"]["visualType"], "objects": {"merge": objects},
            "activeProjections": {"Values": [item["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]]}}}
        if label == "calendar":
            # Match the native unselected slicer bookmark captured in Desktop:
            # byExpr records the filter identity without a selection predicate.
            calendar_filter = item["filterConfig"]["filters"][0]
            states[item["name"]]["filters"] = {"byExpr": [{"name": calendar_filter["name"],
                "type": "Categorical", "expression": copy.deepcopy(calendar_filter["field"]), "howCreated": 0}]}
            states[item["name"]]["singleVisual"]["objects"]["merge"] = {
                "data": objects["data"], "selection": objects["selection"]}
    bookmark = {"$schema": SCHEMA + "bookmark/2.1.0/schema.json", "displayName": "Reset Resource Playground", "name": RESET,
        "options": {"applyOnlyToTargetVisuals": True, "targetVisualNames": [identifier(label) for label in INPUTS], "suppressActiveSection": True, "suppressDisplay": True},
        "explorationState": {"version": "1.0", "activeSection": PAGE, "sections": {PAGE: {"visualContainers": states}}}}
    write(output_definition / "bookmarks" / (RESET + ".bookmark.json"), bookmark)
    bookmark_metadata_path = DEFINITION / "bookmarks" / "bookmarks.json"
    bookmark_metadata = read(bookmark_metadata_path)
    if not any(item["name"] == RESET for item in bookmark_metadata["items"]):
        bookmark_metadata["items"].append({"name": RESET})
    write(output_definition / "bookmarks" / "bookmarks.json", bookmark_metadata)
    print(f"Generated Resource Playground {PAGE}: {len(VISUALS)} visuals, {len(INPUTS)} isolated inputs; reset {RESET}; output {output_definition}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Write review-only report definition drafts here without changing the production report.")
    build_page(parser.parse_args().output_dir)

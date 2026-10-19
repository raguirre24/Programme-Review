"""Add the calendar-comparison view without regenerating the saved Playground.

No existing visual file is written. The patch adds eight visuals, two display-only
bookmarks, their bookmark group, scoped interactions, and two Reset targets.
Run with --check for a read-only parity check, --output-dir for a review draft,
or --apply to apply the explicitly authorised comparison patch.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from generate_page import colour, expr, field, measure, projection, props, string


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "Project Review - Programme (datalake).Report/definition"
PAGE = "4c53a34bba9dcc7f3e8c"
RESET = "e899bf3a9c2d243f33bf"
CALENDAR = "Scenario Comparison Calendar"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"


def identifier(label: str) -> str:
    return hashlib.sha256(("resource-playground-comparison-v1:" + label).encode()).hexdigest()[:20]


IDS = {label: identifier(label) for label in (
    "selector", "selection-summary", "results", "finish", "status", "chart", "help", "view-navigation",
    "single-bookmark", "compare-bookmark", "bookmark-group", "selector-filter",
)}
SINGLE_VISUALS = {
    "16643c36a5f294a63a18",  # Calendar selector.
    "03410ac18c0fb7b35af1", "b8131dcaa0d2fd84ea2c", "f1268db2c25979d9b9c3",
    "f62b2a2433a4e7baa768", "6989681937a36a7c31bf",  # Five result cards.
    "dfe45a9f6ada77e1e968", "d0ef1452175fcccbadc7",  # Status and input summary.
    "dea161918df8bfd0fc62", "f138b12e316741ce70dd", "72af6b2274a8e97ddc2e",
    "fa2eaf106e8ead20b935", "d5725d830dac62d285ce", "c4762ffe207ce780fc4d",
}
COMPARISON_LABELS = ("selector", "selection-summary", "results", "finish", "status", "chart", "help")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def title(visual: dict, text: str, *, size: int = 12, show: bool = True) -> None:
    visual["visual"].setdefault("visualContainerObjects", {})["title"] = props(
        show=expr(str(show).lower()), text=string(text), fontSize=expr(f"{size}D"),
        fontColor=colour(1), bold=expr("false"), titleWrap=expr("true"))


def positioned(template: dict, label: str, x: int, y: int, width: int, height: int, order: int) -> dict:
    item = copy.deepcopy(template)
    item["name"] = IDS[label]
    item["position"] = {"x": x, "y": y, "width": width, "height": height,
                        "z": order * 1000, "tabOrder": order * 1000}
    item["isHidden"] = label != "view-navigation"
    for key in ("parentGroupName", "filterConfig", "howCreated"):
        item.pop(key, None)
    item["visual"].pop("syncGroup", None)
    objects = item["visual"].setdefault("visualContainerObjects", {})
    objects["general"] = props(altText=string("Calendar comparison " + label.replace("-", " ")))
    return item


def build() -> dict[Path, dict]:
    page_path = Path("pages") / PAGE / "page.json"
    visual_root = DEFINITION / "pages" / PAGE / "visuals"
    existing = {p.parent.name: read(p) for p in sorted(visual_root.glob("*/visual.json"))}
    missing = SINGLE_VISUALS - set(existing)
    if missing:
        raise ValueError(f"Saved single-calendar visual identities are missing: {sorted(missing)}")
    original = {key: value for key, value in existing.items() if key not in set(IDS.values())}
    visuals: dict[str, dict] = {}

    selector = positioned(existing["16643c36a5f294a63a18"], "selector", 24, 192, 368, 90, 36)
    selector["visual"]["query"] = {"queryState": {"Values": {
        "projections": [projection(CALENDAR, "Calendar")]}}, "sortDefinition": {"sort": [
            {"field": field(CALENDAR, "Calendar"), "direction": "Ascending"}]}}
    selector["visual"]["objects"]["selection"] = props(
        strictSingleSelect=expr("false"), singleSelect=expr("false"), selectAllCheckboxEnabled=expr("true"))
    selector["visual"]["objects"]["general"] = props(selfFilterEnabled=expr("true"))
    selector["filterConfig"] = {"filters": [{"name": IDS["selector-filter"],
        "field": field(CALENDAR, "Calendar"), "type": "Categorical"}]}
    title(selector, "Compare calendars · clear for all")
    visuals["selector"] = selector

    for label, output, caption, x, y, width, height, size in (
        ("selection-summary", "Comparison Selection Summary", "Comparison selection", 422, 196, 1340, 48, 13),
        ("finish", "Comparison Finish Date Display", "Inspected calendar finish", 422, 462, 260, 66, 20),
        ("status", "Comparison Status", "Inspected calendar status", 692, 462, 786, 66, 12),
    ):
        card = positioned(existing["03410ac18c0fb7b35af1"], label, x, y, width, height, 37 + len(visuals))
        card["visual"]["query"] = {"queryState": {"Values": {"projections": [measure(output, caption)]}}}
        card["visual"]["objects"]["labels"][0]["properties"]["fontSize"] = expr(f"{size}D")
        title(card, caption, show=label != "selection-summary")
        visuals[label] = card

    table = positioned(existing["c4762ffe207ce780fc4d"], "results", 422, 250, 1340, 200, 41)
    columns = [projection(CALENDAR, "Inspection Calendar", label="Calendar"),
               measure("Comparison Required Rate", "Required rate"),
               measure("Comparison Target Remaining", "Remaining at target"),
               measure("Comparison Validation", "Calculation status")]
    table["visual"]["query"] = {"queryState": {"Values": {"projections": columns}},
        "sortDefinition": {"sort": [{"field": field(CALENDAR, "Inspection Calendar"), "direction": "Ascending"}],
                           "isDefaultSort": True}}
    table["visual"].pop("expansionStates", None)
    table["visual"]["objects"]["columnWidth"] = [
        {"properties": {"value": expr(f"{width}D")}, "selector": {"metadata": column["queryRef"]}}
        for column, width in zip(columns, (440, 170, 190, 510))]
    table["visual"]["objects"]["columnHeaders"][0]["properties"]["autoSizeColumnWidth"] = expr("false")
    table["visual"]["objects"]["total"] = props(totals=expr("false"))
    title(table, "Calendar alternatives · select one row to inspect finish and status")
    visuals["results"] = table

    chart = positioned(existing["fa2eaf106e8ead20b935"], "chart", 422, 536, 1340, 456, 42)
    chart["visual"]["visualType"] = "clusteredColumnChart"
    chart["visual"]["query"] = {"queryState": {
        "Category": copy.deepcopy(existing["fa2eaf106e8ead20b935"]["visual"]["query"]["queryState"]["Category"]),
        "Series": {"projections": [projection(CALENDAR, "Calendar")]},
        "Y": {"projections": [measure("Comparison Chart Quantity", "Allocated quantity")]},
        "Tooltips": {"projections": [measure("Comparison Calendar Identity", "Calendar source identity")]},
    }, "sortDefinition": {"sort": [{"field": field("Scenario Date", "Month"), "direction": "Ascending"}],
                          "isDefaultSort": True}}
    chart["visual"]["objects"] = {key: copy.deepcopy(value) for key, value in chart["visual"]["objects"].items()
                                    if key in {"categoryAxis", "valueAxis", "legend"}}
    # alignZeros belongs to the original combo chart's two-axis configuration.
    for value_axis in chart["visual"]["objects"].get("valueAxis", []):
        value_axis.get("properties", {}).pop("alignZeros", None)
    chart["visual"]["objects"]["legend"] = props(show=expr("true"), fontSize=expr("11D"),
        position=string("Top"), showTitle=expr("false"))
    title(chart, "Calendar alternatives · the full quantity is allocated separately to each calendar", size=15)
    visuals["chart"] = chart

    help_text = positioned(existing["d5725d830dac62d285ce"], "help", 422, 998, 1340, 26, 43)
    help_text["visual"]["objects"]["general"] = props(paragraphs=[{"textRuns": [{
        "value": "Each colour is an alternative scenario. Calendar quantities are not added together. Select a table row to inspect its finish and status.",
        "textStyle": {"fontSize": "11pt", "fontFamily": "Segoe UI", "fontWeight": "normal"}}]}])
    title(help_text, "Comparison guidance", show=False)
    visuals["help"] = help_text

    navigator_template = read(DEFINITION / "pages/1351c9e89c045d35e160/visuals/9e0f36670d147185628d/visual.json")
    navigator = positioned(navigator_template, "view-navigation", 1508, 20, 254, 44, 44)
    navigator["visual"]["objects"]["bookmarks"] = props(bookmarkGroup=string(IDS["bookmark-group"]),
        allowDeselectionBookmark=expr("false"), selectedBookmark=string(IDS["single-bookmark"]))
    title(navigator, "Resource Playground view", show=False)
    visuals["view-navigation"] = navigator

    outputs = {Path("pages") / PAGE / "visuals" / value["name"] / "visual.json": value for value in visuals.values()}
    all_visuals = {**original, **{value["name"]: value for value in visuals.values()}}
    page = read(DEFINITION / page_path)
    # Preserve every pre-existing interaction. Rebuild only pairs involving the
    # comparison controls, so a second application is byte-identical.
    new_ids = {value["name"] for value in visuals.values()}
    interactions = {(item["source"], item["target"]): item["type"] for item in page.get("visualInteractions", [])
                    if item["source"] not in new_ids and item["target"] not in new_ids}
    for source in (IDS["results"], IDS["chart"]):
        for target in all_visuals:
            if source != target:
                interactions[(source, target)] = ("DataFilter" if source == IDS["results"]
                    and target in {IDS["finish"], IDS["status"]} else "NoFilter")
    for source in ("fa2eaf106e8ead20b935", "c4762ffe207ce780fc4d", "16643c36a5f294a63a18"):
        for target in sorted(new_ids):
            interactions[(source, target)] = "NoFilter"
    # The separate comparison selector never changes the single-calendar view
    # or the common inputs/context. Shared input controls still filter the new
    # outputs through their normal native DataFilter behaviour.
    for target in original:
        interactions[(IDS["selector"], target)] = "NoFilter"
    page["visualInteractions"] = [{"source": source, "target": target, "type": kind}
                                  for (source, target), kind in interactions.items()]
    outputs[page_path] = page

    compare_ids = {IDS[label] for label in COMPARISON_LABELS}
    targets = sorted(SINGLE_VISUALS | compare_ids)
    for label, caption, comparison in (("single-bookmark", "Single", False), ("compare-bookmark", "Compare", True)):
        states = {}
        for visual_id in targets:
            visible = (visual_id in compare_ids) == comparison
            single = {"visualType": all_visuals[visual_id]["visual"]["visualType"], "objects": {}}
            if not visible:
                single["display"] = {"mode": "hidden"}
            states[visual_id] = {"singleVisual": single}
        outputs[Path("bookmarks") / (IDS[label] + ".bookmark.json")] = {
            "$schema": SCHEMA + "bookmark/2.1.0/schema.json", "name": IDS[label], "displayName": caption,
            "options": {"targetVisualNames": targets, "suppressData": True, "suppressActiveSection": True,
                        "applyOnlyToTargetVisuals": True},
            "explorationState": {"version": "1.0", "activeSection": PAGE,
                                 "sections": {PAGE: {"visualContainers": states}}}}

    reset_path = Path("bookmarks") / (RESET + ".bookmark.json")
    reset = read(DEFINITION / reset_path)
    reset_targets = reset["options"]["targetVisualNames"]
    for visual_id in (IDS["selector"], IDS["results"]):
        if visual_id not in reset_targets:
            reset_targets.append(visual_id)
    states = reset["explorationState"]["sections"][PAGE]["visualContainers"]
    states[IDS["selector"]] = {"filters": {"byExpr": [{"name": IDS["selector-filter"], "type": "Categorical",
        "expression": field(CALENDAR, "Calendar"), "howCreated": 0}]}, "singleVisual": {
            "visualType": "slicer", "objects": {"merge": {"data": selector["visual"]["objects"]["data"],
                "selection": selector["visual"]["objects"]["selection"]}},
            "activeProjections": {"Values": [field(CALENDAR, "Calendar")]}}}
    # Bookmark schema HighlightState.selection=[] explicitly clears row selection
    # while suppressDisplay keeps the user's current Single/Compare view.
    states[IDS["results"]] = {"singleVisual": {"visualType": "tableEx", "objects": {}},
                              "highlight": {"selection": []}}
    outputs[reset_path] = reset

    metadata_path = Path("bookmarks/bookmarks.json")
    metadata = read(DEFINITION / metadata_path)
    group = {"name": IDS["bookmark-group"], "displayName": "Resource Playground view",
             "children": [IDS["single-bookmark"], IDS["compare-bookmark"]]}
    groups = [index for index, item in enumerate(metadata["items"]) if item["name"] == IDS["bookmark-group"]]
    if groups:
        metadata["items"][groups[0]] = group
    else:
        metadata["items"].append(group)
    outputs[metadata_path] = metadata
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    outputs = build()
    destination = args.output_dir.resolve() if args.output_dir else DEFINITION
    if args.output_dir and (destination == DEFINITION.parent or DEFINITION.parent in destination.parents):
        raise ValueError("Review drafts must be outside the production report folder; use --apply for the approved patch.")
    changed = []
    for relative, value in outputs.items():
        path = destination / relative
        text = rendered(value)
        if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
            changed.append(str(relative))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print(json.dumps({"result": "FAIL" if args.check and changed else "PASS", "changed": changed,
                      "newVisuals": 8, "existingVisualFilesWritten": 0, "ids": IDS}, indent=2))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

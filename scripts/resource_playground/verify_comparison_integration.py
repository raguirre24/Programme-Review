"""Strict static checks for additive calendar comparison. Does not execute DAX."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import verify_integration as base
import merge_resources_page as merge

PAGE = "4c53a34bba9dcc7f3e8c"
TABLE = "Scenario Comparison Calendar"
IDS = {name: hashlib.sha256(("resource-playground-comparison-v1:" + name).encode()).hexdigest()[:20]
       for name in ["selector", "results", "finish", "status", "chart", "help", "view-navigation"]}
HEADER_NAV_VISUALS = {
    "0205468805ab90499de6", "03fe0bf469cf674fcd83", "42028c831190ced43922",
    "8176899626f3b56a69c1", "a12fa8f42142c61203d5", "ad7400649f94db2c6276",
    "bf2c5a9d2aaf3cf456d7", "c3fd436b960b0d6d8f8c", "d80c22aa4fc16a4ee9d2",
    "f07b62160a6bcaded91e", "fa323b6b39cecca295b5",
}
# Histogram (former Resources page), Simulator (single calendar) and Compare views of the merged Resources page.
BOOKMARKS = list(merge.VIEWS)


def canonical(expression):
    return "".join(re.findall(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'|\S', expression))


def extract_measures(text):
    measures = {}
    for match in re.finditer(r"^\tmeasure '([^']+)'\s*=\s*(.*?)(?=^\t\tformatString:)", text, re.M | re.S):
        expression = match[2].strip()
        if expression.startswith("```") and expression.endswith("```"):
            expression = expression[3:-3].strip()
        measures[match[1]] = expression
    return measures


def validate_model(tables):
    measures = {m["name"]: m["expression"] for m in tables["Resource Scenario Measures"]["measures"]}
    assert len(measures) == 66 and {n for n in measures if n.startswith("Comparison ")} == base.COMPARISON_MEASURES
    import tempfile, generate_measures
    with tempfile.TemporaryDirectory() as tmp:
        generate_measures.generate(Path(tmp))
        generated = (Path(tmp) / "Resource Scenario Measures.tmdl").read_text(encoding="utf-8")
    original_measures = {n: e for n, e in extract_measures(generated).items() if n.startswith("Scenario ")}
    assert len(original_measures) == 57, "Original single-calendar measure inventory changed."
    assert all(canonical(measures[n]) == canonical(e) for n, e in original_measures.items()), "Existing single-calendar expressions drifted from generator."
    expected_columns = {"ProjectKey", "clndr_id_key", "IsCsvSource", "Calendar Name", "MonthUpdate", "Report Update Date", "Calendar", "Inspection Calendar"}
    assert {c["name"] for c in tables[TABLE]["columns"]} == expected_columns
    assert len(tables[TABLE]["calculatedPartitions"]) == 1
    source = tables[TABLE]["calculatedPartitions"][0]["expression"]
    assert "'Scenario Calendar'" in source and "'Scenario Date'" not in source and not re.search(r"\bCROSSJOIN\s*\(", source, re.I)
    for name in base.COMPARISON_MEASURES - {"Comparison Selection Summary", "Comparison Finish Date Display"}:
        expression = measures[name]
        compact = canonical(expression)
        assert "COUNTROWS('Scenario Comparison Calendar')=1" in compact, (name, "one independent identity required")
        assert "HASONEVALUE('Project_Dimension'[ProjectKey])" in compact and "HASONEVALUE('CurrentDate'[UpdateDate])" in compact
        if name != "Comparison Calendar Identity":
            for column in ["ProjectKey", "clndr_id_key", "IsCsvSource"]:
                assert "'Scenario Calendar'[" + column + "]" in expression, (name, column)
        assert not re.search(r"REMOVEFILTERS\s*\(\s*'(Project_Dimension|CurrentDate)'", expression, re.I), (name, "must preserve secured scope")
        assert not re.search(r"\bSUMX?\s*\(", base.dax_code(expression), re.I), (name, "alternatives must not be added")
    for name in ["Comparison Finish Date", "Comparison Status"]:
        assert canonical("ISFILTERED('Scenario Comparison Calendar'[Inspection Calendar])") in canonical(measures[name])
    assert canonical("[Comparison Finish Date]") in canonical(measures["Comparison Finish Date Display"])
    bounded = measures["Comparison Validation"]
    assert "[Scenario Finish Date]" not in bounded and "[Scenario Status]" not in bounded
    summary = measures["Comparison Selection Summary"]
    assert "COUNTROWS('Scenario Comparison Calendar')" in canonical(summary)
    assert "[Inspection Calendar]" in summary and "[Calendar]" in summary
    identity = canonical(measures["Comparison Calendar Identity"])
    assert canonical("NOT ISBLANK([Comparison Chart Quantity])") in identity, "Text tooltips must not add invalid series or empty chart periods."
    assert canonical("IF(Eligible && NOT UnsupportedMode, IF(NOT ISBLANK([Comparison Chart Quantity])") in identity, "Unsupported inverse-hourly-cap mode must exit before the tooltip evaluates chart quantity."
    for expression in ['[Scenario Selected Mode] = "Meet target date"', '[Scenario Selected Basis] = "Per working hour"', '[Scenario Selected Limit Mode] = "Daily limit"']:
        assert canonical(expression) in identity
    for column in ["ProjectKey", "clndr_id_key", "IsCsvSource"]:
        assert "SELECTEDVALUE('Scenario Comparison Calendar'[" + column + "])" in identity
    return {"measures": 66, "preserved_base_measures": 57, "comparison_measures": 9}


def projections(visual, role):
    return [p["field"] for p in visual["visual"]["query"]["queryState"][role]["projections"]]


def field_name(field):
    kind, data = next(iter(field.items()))
    return kind, data["Expression"]["SourceRef"]["Entity"], data["Property"]


def validate_report(report_root):
    page_root = report_root / "pages" / PAGE
    visuals = {p.parent.name: json.loads(p.read_text(encoding="utf-8-sig")) for p in (page_root / "visuals").glob("*/visual.json")}
    assert len(visuals) == 58 and set(IDS.values()) <= visuals.keys(), (
        "Exact 58 visuals (Playground, comparison, the 8 Histogram visuals and header/navigation visuals) required.")
    selector, chart, results = (visuals[IDS[n]] for n in ["selector", "chart", "results"])
    assert [field_name(f) for f in projections(selector, "Values")] == [("Column", TABLE, "Calendar")]
    selection = selector["visual"]["objects"]["selection"][0]["properties"]
    for prop in ["singleSelect", "strictSingleSelect"]:
        assert selection[prop]["expr"]["Literal"]["Value"] == "false", "Comparison selector must allow multiple or cleared selections."
    assert chart["visual"]["visualType"] == "clusteredColumnChart"
    assert [field_name(f) for f in projections(chart, "Series")] == [("Column", TABLE, "Calendar")]
    assert [field_name(f) for f in projections(chart, "Y")] == [("Measure", "Resource Scenario Measures", "Comparison Chart Quantity")]
    assert [field_name(f) for f in projections(chart, "Tooltips")] == [("Measure", "Resource Scenario Measures", "Comparison Calendar Identity")], "The measure-only tooltip role must expose the guarded full calendar identity."
    assert chart["visual"]["query"]["queryState"]["Category"]["fieldParameters"] == visuals[base.CHART_VISUAL_ID]["visual"]["query"]["queryState"]["Category"]["fieldParameters"]
    assert [field_name(f) for f in projections(results, "Values")] == [
        ("Column", TABLE, "Inspection Calendar"),
        *(('Measure', 'Resource Scenario Measures', 'Comparison ' + suffix) for suffix in ['Required Rate', 'Target Remaining', 'Validation'])]
    assert results["visual"]["objects"]["total"][0]["properties"]["totals"]["expr"]["Literal"]["Value"] == "false"
    page = json.loads((page_root / "page.json").read_text(encoding="utf-8-sig"))
    interactions = {(r["source"], r["target"]): r["type"] for r in page["visualInteractions"]}
    for target in visuals.keys() - {IDS["results"]} - HEADER_NAV_VISUALS:
        expected = "DataFilter" if target in {IDS["finish"], IDS["status"]} else "NoFilter"
        assert interactions.get((IDS["results"], target)) == expected, ("inspection row interaction", target)
    for target in visuals.keys() - {IDS["chart"]} - HEADER_NAV_VISUALS:
        assert interactions.get((IDS["chart"], target)) == "NoFilter", ("comparison chart interaction", target)
    states = []
    for bookmark_id in BOOKMARKS:
        bookmark = json.loads((report_root / "bookmarks" / (bookmark_id + ".bookmark.json")).read_text(encoding="utf-8-sig"))
        options = bookmark["options"]
        assert options.get("suppressData") is True and options.get("suppressActiveSection") is True and options.get("applyOnlyToTargetVisuals") is True
        state = bookmark["explorationState"]["sections"][PAGE]
        assert set(state) == {"visualContainers"}
        assert all(set(v) <= {"singleVisual", "isHidden"} for v in state["visualContainers"].values()), "Display bookmarks must not capture filters or highlight selections."
        assert "filter" not in json.dumps(state).lower()
        caption, shown = merge.VIEWS[bookmark_id]
        assert bookmark["displayName"] == caption and sorted(options["targetVisualNames"]) == sorted(merge.TOGGLED), (
            f"View bookmark {caption} must target exactly the 43 toggled visuals")
        visible = {name for name, value in state["visualContainers"].items() if value["singleVisual"].get("display", {}).get("mode") != "hidden"}
        assert visible == set(shown), (f"View bookmark {caption} shows the wrong visuals", sorted(visible ^ set(shown)))
        states.append(state)
    assert len({json.dumps(state, sort_keys=True) for state in states}) == len(states), "Histogram, Simulator and Compare must differ."
    metadata = json.loads((report_root / "bookmarks" / "bookmarks.json").read_text(encoding="utf-8-sig"))["items"]
    groups = [item for item in metadata if item.get("name") == merge.VIEW_GROUP]
    assert groups and groups[0].get("children") == BOOKMARKS, "The Resources view group must hold Histogram, Simulator, Compare."
    navigator = visuals[IDS["view-navigation"]]["visual"]["objects"]["bookmarks"][0]["properties"]
    assert navigator["selectedBookmark"]["expr"]["Literal"]["Value"] == f"'{merge.HISTOGRAM_BOOKMARK}'", "Resources must open on Histogram."
    # Saved view: Histogram visible, Simulator and Compare hidden.
    assert all(not visuals[name].get("isHidden") for name in merge.HISTOGRAM_VIEW)
    assert all(visuals[name].get("isHidden") is True for name in merge.SIMULATOR_SIDE)
    for histogram_visual in merge.HISTOGRAM_VIEW:
        for simulator_visual in merge.SIMULATOR_SIDE:
            assert interactions.get((histogram_visual, simulator_visual)) == interactions.get((simulator_visual, histogram_visual)) == "NoFilter", (
                "Histogram and Simulator/Compare visuals must not filter each other", histogram_visual, simulator_visual)
    page_index = json.loads((report_root / "pages" / "pages.json").read_text(encoding="utf-8-sig"))
    assert merge.FORMER_PAGE not in page_index["pageOrder"] and not (report_root / "pages" / merge.FORMER_PAGE).exists(), (
        "The former Resources page must be removed.")
    assert page["displayName"] == merge.PAGE_NAME
    reset = json.loads((report_root / "bookmarks" / (base.RESET_BOOKMARK_ID + ".bookmark.json")).read_text(encoding="utf-8-sig"))
    expected_targets = base.RESET_TARGET_IDS | {IDS["selector"], IDS["results"]}
    assert set(reset["options"]["targetVisualNames"]) == expected_targets and len(reset["options"]["targetVisualNames"]) == 14
    reset_states = reset["explorationState"]["sections"][PAGE]["visualContainers"]
    assert reset_states[IDS["results"]]["highlight"] == {"selection": []}
    filters = reset_states[IDS["selector"]]["filters"]["byExpr"]
    assert len(filters) == 1 and "filter" not in filters[0]
    assert filters[0]["expression"]["Column"]["Property"] == "Calendar"
    return {"visuals": len(visuals), "selector": IDS["selector"], "results": IDS["results"], "display_bookmarks": len(BOOKMARKS), "reset_targets": 14}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=base.MODEL)
    parser.add_argument("--report-root", type=Path, default=base.REPORT)
    parser.add_argument("--tom-directory")
    args = parser.parse_args()
    metadata = base.read_metadata(args.model_root, args.tom_directory)
    result = validate_model({table["name"]: table for table in metadata["tables"]})
    result.update(validate_report(args.report_root))
    print(json.dumps({"result": "PASS", **result, "scope": "Static source/report checks; no DAX execution, rendering or runtime RLS."}, indent=2))


if __name__ == "__main__":
    main()

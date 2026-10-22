"""Generate the Calendar Stretch report page (calendar-driven delay) next to Calendar Analysis.

The page clones the Calendar Analysis header, slicers and project menu (same sync groups), then adds four KPI
cards, a stacked 'work vs wait' bar chart, a Deneb delay timeline, an outlier scatter, and a cliff-edge line
chart with its callout. Only these files are written: the new page folder, its two project-menu bookmarks,
pages.json (page order), bookmarks.json and report.json (Deneb in publicCustomVisuals). No other page is touched.

Modes: --check compares the generated files with the report (exit 1 on difference), --output-dir writes a review
copy outside the report, --apply writes them into the report. --phase limits the content: 1 = native visuals,
2 = + Deneb timeline, 3 = + cliff-edge chart (default).
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "resource_playground"))
from generate_page import colour, expr, field, props, string  # noqa: E402

DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
SOURCE_PAGE = "ca1da4a175154c398f01"
PAGE = "csstretchpage0000001"
PAGE_NAME = "Calendar Stretch"
DENEB = "deneb7E15AEF80B9E4D4F8E12924291ECE89A"
TASK = "01 XER_TASK"
XER = "XER Measures"
SPEC = Path(__file__).with_name("calendar_stretch_timeline.vl.json")

# Calendar Analysis furniture cloned as-is (ids "ca.." become "cs.."): header, navigators, project menu, slicers.
CLONED = [
    "ca01logo000000000001", "ca02title00000000002", "ca03update0000000003", "ca04selttl0000000004",
    "ca05ddttl00000000005", "ca06selfil0000000006", "ca07openbtn000000007", "ca08navhome000000008",
    "ca09navpage000000009", "ca10menubg0000000010", "ca11state00000000011", "ca12proj000000000012",
    "ca13closebt000000013", "ca14wbsslic000000014", "ca15critslc000000015", "ca16drivslc000000016",
    "ca24fltslic000000024",
]
BOOKMARKS = {"ca91openbm0000000091": "cs91openbm0000000091", "ca92closebm000000092": "cs92closebm000000092"}
KPIS = ["cs17kpi1dly000000017", "cs18kpi2crt000000018", "cs19kpi3max000000019", "cs20kpi4rat000000020"]
BARS, TIMELINE, SCATTER = "cs21workbar000000021", "cs22timeline00000022", "cs23scatter000000023"
CALLOUT, CLIFF = "cs25cliffco000000025", "cs26cliffch000000026"
PAGE_FILTER_NAMES = {
    "TaskType_Classified": "cs00tasktypefilter01", "Is Unscheduled": "cs00unscheduledflt02",
    "status_code": "cs00statusfilter0003", "Float Category": "cs00floatcategory004",
}


def cs(name: str) -> str:
    return "cs" + name[2:]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def hex_colour(value: str) -> dict:
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{value}'"}}}}}


def measure(name: str, label: str) -> dict:
    return {"field": field(XER, name, "Measure"), "queryRef": f"{XER}.{name}", "nativeQueryRef": label, "displayName": label}


def column(table: str, name: str, label: str) -> dict:
    return {"field": field(table, name), "queryRef": f"{table}.{name}", "nativeQueryRef": label, "active": True, "displayName": label}


def container(name: str, visual_type: str, x: int, y: int, width: int, height: int, order: int) -> dict:
    return {
        "$schema": SCHEMA + "visualContainer/2.13.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": order * 1000, "height": height, "width": width, "tabOrder": order * 1000},
        "visual": {"visualType": visual_type, "objects": {}, "visualContainerObjects": {}, "drillFilterOtherVisuals": True},
    }


def titles(item: dict, title: str | dict, alt_text: str, *, subtitle: bool = True) -> None:
    text = title if isinstance(title, dict) else string(title)
    vco = item["visual"]["visualContainerObjects"]
    vco["title"] = props(show=expr("true"), text=text, fontSize=expr("12D"), fontColor=colour(1), bold=expr("true"),
                         titleWrap=expr("true"))
    if subtitle:
        vco["subTitle"] = props(show=expr("true"), text={"expr": {"Measure": field(XER, "CS Scope Prompt", "Measure")["Measure"]}},
                                fontSize=expr("9D"), fontColor=colour(1, 0.4), titleWrap=expr("true"))
    vco["general"] = props(altText=string(alt_text))


def series_colours(colours: dict[str, str]) -> list[dict]:
    return [{"properties": {"fill": hex_colour(value)}, "selector": {"metadata": f"{XER}.{name}"}} for name, value in colours.items()]


def column_ref(source: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": source}}, "Property": name}}


def top_delay_filter(name: str) -> dict:
    """Top 15 activities by MAX('01 XER_TASK'[Calendar Delay Days]): a column aggregate, never a measure filter."""
    return {
        "name": name,
        "field": field(TASK, "task_code"),
        "type": "TopN",
        "filter": {
            "Version": 2,
            "From": [
                {"Name": "subquery", "Expression": {"Subquery": {"Query": {
                    "Version": 2,
                    "From": [{"Name": "t", "Entity": TASK, "Type": 0}],
                    "Select": [{**column_ref("t", "task_code"), "Name": "field"}],
                    "OrderBy": [{"Direction": 2, "Expression": {"Aggregation": {
                        "Expression": column_ref("t", "Calendar Delay Days"), "Function": 4}}}],
                    "Top": 15,
                }}}, "Type": 2},
                {"Name": "t", "Entity": TASK, "Type": 0},
            ],
            "Where": [{"Condition": {"In": {"Expressions": [column_ref("t", "task_code")],
                                            "Table": {"SourceRef": {"Source": "subquery"}}}}}],
        },
        "howCreated": "User",
    }


def delayed_filter(name: str) -> dict:
    """Only activities the calendar delays: '01 XER_TASK'[Calendar Delay Days] > 0 (column filter)."""
    return {
        "name": name,
        "field": field(TASK, "Calendar Delay Days"),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": TASK, "Type": 0}],
            "Where": [{"Condition": {"Comparison": {"ComparisonKind": 1, "Left": column_ref("t", "Calendar Delay Days"),
                                                    "Right": {"Literal": {"Value": "0L"}}}}}],
        },
        "howCreated": "User",
    }


def clone_furniture(source_dir: Path) -> dict[str, dict]:
    visuals = {}
    for name in CLONED:
        text = (source_dir / name / "visual.json").read_text(encoding="utf-8-sig")
        for old, new in BOOKMARKS.items():
            text = text.replace(old, new)
        item = json.loads(text)
        item["name"] = cs(name)
        # Filter names must stay unique across the report, so each cloned slicer filter gets its own.
        for index, visual_filter in enumerate(item.get("filterConfig", {}).get("filters", []), start=1):
            visual_filter["name"] = (cs(name)[:16] + f"flt{index}")[:20]
        if name == "ca02title00000000002":
            for entry in item["visual"]["objects"]["text"]:
                if "text" in entry.get("properties", {}):
                    entry["properties"]["text"] = string(PAGE_NAME)
        if name == "ca24fltslic000000024":
            # Same float slider without Calendar Analysis' <= 50 default, so long-float activities stay visible.
            item.pop("filterConfig", None)
            objects = item["visual"]["objects"]
            objects["data"][0]["properties"].pop("numericEnd", None)
            objects.pop("general", None)
            objects["header"][0]["properties"]["text"] = string("Max Total Float")
            projection = item["visual"]["query"]["queryState"]["Values"]["projections"][0]
            projection["nativeQueryRef"] = projection["displayName"] = "Total Float"
        visuals[item["name"]] = item
    return visuals


def kpi_cards(template: dict) -> dict[str, dict]:
    specs = [
        (KPIS[0], 12, [("CS KPI Delayed Activities", "Delayed > 30 days"), ("CS KPI Severely Delayed Activities", "Delayed > 90 days")],
         "Activities the calendar delays"),
        (KPIS[1], 456, [("CS KPI Critical Delay Days", "Delay days on critical & near-critical")], "Calendar delay on critical work"),
        (KPIS[2], 900, [("CS KPI Max Delay Days", "Largest calendar-driven delay (days)")], "Largest calendar-driven delay"),
        (KPIS[3], 1344, [("CS KPI Worst Stretch Ratio", "Worst calendar vs working ratio")], "Worst calendar vs working ratio"),
    ]
    cards = {}
    for order, (name, x, measures, alt_text) in enumerate(specs, start=9):
        item = copy.deepcopy(template)
        item["name"] = name
        item["position"] = {"x": x, "y": 148, "z": order * 1000, "height": 70, "width": 432, "tabOrder": order * 1000}
        item["visual"]["query"]["queryState"]["Data"]["projections"] = [measure(m, label) for m, label in measures]
        item["visual"]["query"]["sortDefinition"]["sort"][0]["field"] = field(XER, measures[0][0], "Measure")
        vco = item["visual"]["visualContainerObjects"]
        vco["general"] = props(altText=string(alt_text))
        vco["title"][0]["properties"]["text"] = string(alt_text)
        cards[name] = item
    return cards


def work_vs_wait_bars() -> dict:
    item = container(BARS, "barChart", 12, 226, 620, 420, 13)
    visual = item["visual"]
    stack = {
        "CA Activity Remaining Working Days": ("Working days", "#404040"),
        "CA Activity Standard Non-Working Days": ("Weekends / off-days", "#BFBFBF"),
        "CA Activity Exception Blackout Days": ("Holidays / shutdowns", "#C00000"),
    }
    visual["query"] = {
        "queryState": {
            "Category": {"projections": [column(TASK, "task_code", "Activity")]},
            "Y": {"projections": [measure(name, label) for name, (label, _) in stack.items()]},
            "Tooltips": {"projections": [
                measure("CS Activity Calendar Delay Days", "Calendar-driven delay (days)"),
                measure("CA Activity Name", "Activity name"),
                measure("CA Activity Calendar", "Calendar"),
                measure("CA Activity Stretch Ratio", "Calendar vs working ratio"),
                measure("CA Activity Total Float", "Total float (working days)"),
            ]},
        },
        "sortDefinition": {"sort": [{"field": field(XER, "CS Activity Calendar Delay Days", "Measure"), "direction": "Descending"}]},
    }
    visual["objects"] = {
        "dataPoint": series_colours({name: hex_value for name, (_, hex_value) in stack.items()}),
        "legend": props(show=expr("true"), position=string("Top")),
        "totals": props(show=expr("true")),
        "valueAxis": props(showAxisTitle=expr("true"), titleText=string("Remaining calendar days")),
        "categoryAxis": props(showAxisTitle=expr("false")),
    }
    titles(item, "Work vs wait · top 15 activities by calendar-driven delay",
           "Remaining calendar days split into working days, weekends and holidays or shutdowns")
    item["filterConfig"] = {"filters": [top_delay_filter("cs21topdelayfilter01"), delayed_filter("cs21delayedfilter002")]}
    return item


def deneb_timeline() -> dict:
    item = container(TIMELINE, DENEB, 644, 226, 1132, 420, 14)
    visual = item["visual"]
    visual["query"] = {"queryState": {"dataset": {"projections": [
        column(TASK, "task_code", "Activity"),
        measure("CA Activity Name", "Name"),
        measure("CA Activity Calendar", "Calendar"),
        measure("CS Activity Calendar Delay Days", "Delay Days"),
        measure("CS Activity Timeline Dates", "Timeline Dates"),
        measure("CS Activity Shutdown Bands", "Shutdown Bands"),
        measure("CA Activity Total Float", "Total Float"),
    ]}}}
    spec = json.dumps(json.loads(SPEC.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    config = json.dumps({"autosize": {"type": "fit", "contains": "padding"}, "view": {"stroke": None},
                         "font": "Segoe UI", "padding": 5}, separators=(",", ":"))
    visual["objects"] = {"vega": props(
        jsonSpec=string(spec), jsonConfig=string(config), provider=string("vegaLite"), renderMode=string("svg"),
        enableTooltips=expr("true"), enableContextMenu=expr("true"), enableSelection=expr("true"),
        enableHighlight=expr("false"), selectionMode=string("simple"),
    )}
    titles(item, "Delay timeline · dark: finish without calendar exceptions · red: delay they add · dashed: shutdowns",
           "Timeline of each delayed activity from its remaining start to its finish, with shutdown periods drawn over the bars")
    item["filterConfig"] = {"filters": [top_delay_filter("cs22topdelayfilter01"), delayed_filter("cs22delayedfilter002")]}
    return item


def outlier_scatter() -> dict:
    item = container(SCATTER, "scatterChart", 12, 658, 620, 410, 15)
    visual = item["visual"]
    visual["query"] = {"queryState": {
        "Category": {"projections": [column(TASK, "task_code", "Activity")]},
        "Series": {"projections": [column(TASK, "CriticalStatus", "Critical status")]},
        "X": {"projections": [measure("CA Activity Remaining Working Days", "Remaining working days")]},
        "Y": {"projections": [measure("CS Activity Calendar Delay Days", "Calendar-driven delay (days)")]},
        "Tooltips": {"projections": [
            measure("CA Activity Name", "Activity name"),
            measure("CA Activity Calendar", "Calendar"),
            measure("CA Activity Remaining Elapsed Days", "Remaining calendar days"),
            measure("CA Activity Stretch Ratio", "Calendar vs working ratio"),
            measure("CA Activity Total Float", "Total float (working days)"),
        ]},
    }}
    status_colours = {"Critical": "#D40000", "Near Critical": "#F28C28", "Non-Critical": "#7F7F7F"}
    visual["objects"] = {
        "dataPoint": [
            {"properties": {"fill": hex_colour(value)}, "selector": {"data": [{"scopeId": {"Comparison": {
                "ComparisonKind": 0, "Left": {"Column": field(TASK, "CriticalStatus")["Column"]},
                "Right": {"Literal": {"Value": f"'{status}'"}}}}}]}}
            for status, value in status_colours.items()
        ],
        "categoryAxis": props(logAxisScale=expr("true"), showAxisTitle=expr("true"), titleText=string("Remaining working days (log scale)")),
        "valueAxis": props(showAxisTitle=expr("true"), titleText=string("Calendar-driven delay (days)")),
        "legend": props(show=expr("true"), position=string("Top")),
    }
    titles(item, "Outlier finder · calendar-driven delay against remaining work",
           "Each delayed activity plotted by remaining working days and calendar-driven delay, coloured by critical status")
    item["filterConfig"] = {"filters": [delayed_filter("cs23delayedfilter001")]}
    return item


def cliff_callout() -> dict:
    item = container(CALLOUT, "card", 644, 658, 1132, 62, 16)
    visual = item["visual"]
    visual["query"] = {"queryState": {"Values": {"projections": [measure("CS Cliff Callout", "Cliff edge")]}}}
    visual["objects"] = {
        "labels": props(fontSize=expr("11D"), color=colour(1)),
        "categoryLabels": props(show=expr("false")),
        "wordWrap": props(show=expr("true")),
    }
    vco = visual["visualContainerObjects"]
    vco["title"] = props(show=expr("false"))
    vco["general"] = props(altText=string("Cliff-edge callout: how far an earlier start recovers, or a later start delays, the finish"))
    return item


def cliff_chart() -> dict:
    item = container(CLIFF, "lineChart", 644, 728, 1132, 340, 17)
    visual = item["visual"]
    visual["query"] = {"queryState": {
        "Category": {"projections": [column("Scenario Date", "Date", "Possible start")]},
        "Y": {"projections": [measure("CS Cliff Finish Shift Days", "Finish change vs scheduled (days)")]},
        "Tooltips": {"projections": [measure("CS Cliff Finish Date", "Finish if started that day")]},
    }}
    visual["objects"] = {
        "lineStyles": props(lineChartType=string("step"), showMarker=expr("false"), strokeWidth=expr("3D")),
        "categoryAxis": props(axisType=string("Scalar"), showAxisTitle=expr("true"), titleText=string("Possible start of the remaining work")),
        "valueAxis": props(showAxisTitle=expr("true"), titleText=string("Finish change vs scheduled (calendar days)")),
        "dataPoint": series_colours({"CS Cliff Finish Shift Days": "#C00000"}),
        "y1AxisReferenceLine": [{"properties": {
            "show": expr("true"), "displayName": string("Scheduled finish"), "value": expr("0D"),
            "lineColor": hex_colour("#404040"), "style": string("dashed"),
            "dataLabelShow": expr("true"), "dataLabelText": string("Name"),
        }, "selector": {"id": "1"}}],
    }
    titles(item, {"expr": {"Measure": field(XER, "CS Cliff Title", "Measure")["Measure"]}},
           "Step chart of how the finish moves if the remaining work started on each possible date")
    return item


def interactions(source_page: dict, present: set[str]) -> list[dict]:
    result = []
    for entry in source_page.get("visualInteractions", []):
        if entry["source"] in CLONED and entry["target"] in CLONED:
            result.append({"source": cs(entry["source"]), "target": cs(entry["target"]), "type": entry["type"]})
    charts = [name for name in (BARS, TIMELINE, SCATTER) if name in present]
    cliff = [name for name in (CALLOUT, CLIFF) if name in present]
    for source in charts:
        # A click selects one activity for the cliff edge; the ranked charts and KPIs keep their full context.
        result += [{"source": source, "target": target, "type": "DataFilter"} for target in cliff]
        result += [{"source": source, "target": target, "type": "NoFilter"} for target in charts + KPIS if target != source]
    if CLIFF in present:
        # The cliff axis is 'Scenario Date'; never let it filter anything else (it would reach the CA gate).
        result += [{"source": CLIFF, "target": target, "type": "NoFilter"} for target in sorted(present) if target != CLIFF]
    return result


def build(phase: int) -> dict[Path, dict]:
    source_dir = DEFINITION / "pages" / SOURCE_PAGE
    source_page = read(source_dir / "page.json")
    visuals = clone_furniture(source_dir / "visuals")
    visuals.update(kpi_cards(read(source_dir / "visuals" / "ca17kpi1cal000000017" / "visual.json")))
    visuals[BARS] = work_vs_wait_bars()
    visuals[SCATTER] = outlier_scatter()
    if phase >= 2:
        visuals[TIMELINE] = deneb_timeline()
    if phase >= 3:
        visuals[CALLOUT] = cliff_callout()
        visuals[CLIFF] = cliff_chart()

    page = copy.deepcopy(source_page)
    page["name"], page["displayName"] = PAGE, PAGE_NAME
    for page_filter in page["filterConfig"]["filters"]:
        page_filter["name"] = PAGE_FILTER_NAMES[page_filter["field"]["Column"]["Property"]]
    page["visualInteractions"] = interactions(source_page, set(visuals))

    outputs: dict[Path, dict] = {Path("pages") / PAGE / "page.json": page}
    for name, item in visuals.items():
        outputs[Path("pages") / PAGE / "visuals" / name / "visual.json"] = item

    for old, new in BOOKMARKS.items():
        text = (DEFINITION / "bookmarks" / f"{old}.bookmark.json").read_text(encoding="utf-8-sig")
        for source_name in CLONED:
            text = text.replace(source_name, cs(source_name))
        bookmark = json.loads(text.replace(SOURCE_PAGE, PAGE).replace(old, new))
        bookmark["displayName"] = bookmark["displayName"].replace("Calendar Analysis", PAGE_NAME)
        outputs[Path("bookmarks") / f"{new}.bookmark.json"] = bookmark

    metadata = read(DEFINITION / "bookmarks" / "bookmarks.json")
    names = [item.get("name") for item in metadata["items"]]
    for new in BOOKMARKS.values():
        if new not in names:
            metadata["items"].append({"name": new})
    outputs[Path("bookmarks") / "bookmarks.json"] = metadata

    pages = read(DEFINITION / "pages" / "pages.json")
    if PAGE not in pages["pageOrder"]:
        pages["pageOrder"].insert(pages["pageOrder"].index(SOURCE_PAGE) + 1, PAGE)
    outputs[Path("pages") / "pages.json"] = pages

    report = read(DEFINITION / "report.json")
    if phase >= 2 and DENEB not in report.get("publicCustomVisuals", []):
        report["publicCustomVisuals"] = report.get("publicCustomVisuals", []) + [DENEB]
    outputs[Path("report.json")] = report
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-dir", type=Path)
    parser.add_argument("--phase", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    outputs = build(args.phase)
    destination = args.output_dir.resolve() if args.output_dir else DEFINITION
    if args.output_dir and (destination == DEFINITION.parent or DEFINITION.parent in destination.parents):
        raise ValueError("Review drafts must be outside the production report folder; use --apply to write the page.")
    changed = []
    for relative, value in outputs.items():
        path = destination / relative
        text = rendered(value)
        if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
            changed.append(str(relative))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print(json.dumps({"result": "FAIL" if args.check and changed else "PASS", "phase": args.phase, "page": PAGE,
                      "visuals": sum(1 for path in outputs if path.name == "visual.json"), "changed": changed}, indent=2))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

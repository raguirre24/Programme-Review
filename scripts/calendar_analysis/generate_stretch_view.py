"""Generate the Delay view of the Calendar page (calendar-driven delay), switched with its Calendars view.

The Delay view adds four KPI cards, a stacked 'work vs wait' bar chart, a Deneb delay timeline, an outlier scatter, and a
cliff-edge line chart with its callout to the Calendar page. They stay hidden until the 'Delay' button of the
view navigator in the page header is pressed; 'Calendars' shows the KPIs, summary, matrix with its Monthly | Weekly
switch, legend and inspector again.
Both views share the header, slicers (including the Max Total Float slider) and project menu, and neither view filters
the other. Written files: the nine Delay visuals and the navigator, the page's interactions, the 'Calendars' and 'Delay'
bookmarks and their group, the scope of the project-menu bookmarks, bookmarks.json, pages.json, and report.json when
Deneb is not yet in publicCustomVisuals. It also removes the former Calendar Stretch page and its two project-menu bookmarks. No other
visual is written.

Modes: --check compares the generated files' content with the report, ignoring what Desktop rewrites on save (exit 1
on difference), --output-dir writes a review copy
outside the report, --apply writes them into the report (close Power BI Desktop without saving first).
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "resource_playground"))
from generate_page import colour, expr, field, props, string  # noqa: E402

DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
PAGE = "ca1da4a175154c398f01"
# The separate Calendar Stretch page and its project-menu bookmarks, replaced by the Delay view.
FORMER_PAGE = "csstretchpage0000001"
FORMER_BOOKMARKS = ("cs91openbm0000000091", "cs92closebm000000092")
MENU_BOOKMARKS = ("ca91openbm0000000091", "ca92closebm000000092")
DENEB = "deneb7E15AEF80B9E4D4F8E12924291ECE89A"
TASK = "01 XER_TASK"
XER = "XER Measures"
SPEC = Path(__file__).with_name("calendar_stretch_timeline.vl.json")

KPIS = ["cs17kpi1dly000000017", "cs18kpi2crt000000018", "cs19kpi3max000000019", "cs20kpi4rat000000020"]
BARS, TIMELINE, SCATTER = "cs21workbar000000021", "cs22timeline00000022", "cs23scatter000000023"
CALLOUT, CLIFF = "cs25cliffco000000025", "cs26cliffch000000026"
DELAY_VIEW = KPIS + [BARS, TIMELINE, SCATTER, CALLOUT, CLIFF]
CALENDARS_VIEW = [
    "ca17kpi1cal000000017", "ca18kpi2crt000000018", "ca19kpi3blk000000019", "ca20kpi4str000000020",
    "ca21calprof000000021", "ca22calmatx000000022", "ca23actinsp000000023", "ca25matxleg000000025",
    "ca27periodslc0000027",
]
NAVIGATOR = "ca26viewnav000000026"
CALENDARS_BOOKMARK, DELAY_BOOKMARK, VIEW_GROUP = "ca93calview000000093", "ca94delayvw000000094", "ca95viewgrp000000095"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


# What Power BI Desktop rewrites when it saves, so --check and --apply compare content rather than formatting: the
# visualContainer $schema version, stacking and tab order (z, tabOrder), projection 'active' flags and Deneb's state.
DESKTOP_MANAGED_KEYS = {"$schema", "z", "tabOrder", "active", "stateManagement", "developer"}


def desktop_neutral(value):
    if isinstance(value, dict):
        result = {key: desktop_neutral(item) for key, item in value.items() if key not in DESKTOP_MANAGED_KEYS}
        for entry in result.get("vega", []) if isinstance(result.get("vega"), list) else []:
            entry.get("properties", {}).pop("version", None)
        return result
    if isinstance(value, list):
        return [desktop_neutral(item) for item in value]
    return value


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
        if name != KPIS[3]:
            # Desktop saves a per-value display-units entry on the whole-number cards (not the 0.0x ratio).
            item["visual"]["objects"]["value"] += [{"properties": {"labelDisplayUnits": expr("1D")}, "selector": {"metadata": f"{XER}.{m}"}}
                                                   for m, _ in measures]
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
        "valueAxis": props(showAxisTitle=expr("true"), titleText=string("Finish change vs scheduled")),
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


def view_navigator() -> dict:
    """Header buttons 'Calendars' | 'Delay' (bookmark group VIEW_GROUP), in the free space right of the logo."""
    item = container(NAVIGATOR, "bookmarkNavigator", 200, 20, 320, 44, 24)
    item["visual"]["objects"] = {
        "bookmarks": props(bookmarkGroup=string(VIEW_GROUP), allowDeselectionBookmark=expr("false"),
                           selectedBookmark=string(CALENDARS_BOOKMARK)),
        "fill": [{"properties": {"fillColor": colour(9)}, "selector": {"id": "selected"}}],
        "layout": props(cellPadding=expr("2L")),
        "text": [{"properties": {"bold": expr("true")}, "selector": {"id": "default"}}],
    }
    vco = item["visual"]["visualContainerObjects"]
    vco["title"] = props(show=expr("false"), text=string("Calendar Analysis view"))
    vco["background"] = props(show=expr("false"))
    vco["visualHeader"] = props(show=expr("false"))
    vco["general"] = props(altText=string(
        "Calendar Analysis view: Calendars (summary, monthly or weekly matrix and activities) or Delay (calendar-driven delay charts)"))
    return item


def view_bookmark(name: str, caption: str, shown: list[str], visual_types: dict[str, str]) -> dict:
    """Display-only: shows one view's visuals and hides the other's, without touching data, filters or other visuals."""
    targets = sorted(CALENDARS_VIEW + DELAY_VIEW)
    states = {}
    for visual_id in targets:
        single = {"visualType": visual_types[visual_id], "objects": {}}
        if visual_id not in shown:
            single["display"] = {"mode": "hidden"}
        states[visual_id] = {"singleVisual": single}
    return {
        "$schema": SCHEMA + "bookmark/2.1.0/schema.json", "displayName": caption, "name": name,
        "options": {"applyOnlyToTargetVisuals": True, "targetVisualNames": targets, "suppressActiveSection": True,
                    "suppressData": True},
        "explorationState": {"version": "1.0", "activeSection": PAGE, "sections": {PAGE: {"visualContainers": states}}},
    }


def interactions(page: dict, visual_names: set[str]) -> list[dict]:
    """Keep the Calendars view's pairs, add the Delay view's rules, and keep the two views from filtering each other."""
    managed = set(DELAY_VIEW) | {NAVIGATOR}
    pairs = {(entry["source"], entry["target"]): entry["type"] for entry in page.get("visualInteractions", [])
             if entry["source"] not in managed and entry["target"] not in managed}
    charts = [BARS, TIMELINE, SCATTER]
    for source in charts:
        # A click selects one activity for the cliff edge; the ranked charts and KPIs keep their full context.
        pairs.update({(source, target): "DataFilter" for target in (CALLOUT, CLIFF)})
        pairs.update({(source, target): "NoFilter" for target in charts + KPIS if target != source})
    # The cliff axis is 'Scenario Date'; never let it filter anything (it would reach the CA Inspector Selection Match gate).
    pairs.update({(CLIFF, target): "NoFilter" for target in sorted(visual_names) if target != CLIFF})
    # A hidden view keeps its selections, so neither view may filter the other.
    for calendars_visual in CALENDARS_VIEW:
        for delay_visual in DELAY_VIEW:
            pairs[(calendars_visual, delay_visual)] = pairs[(delay_visual, calendars_visual)] = "NoFilter"
    return [{"source": source, "target": target, "type": kind} for (source, target), kind in pairs.items()]


def build() -> dict[Path, dict | None]:
    """Every file the view owns or changes; None removes a file or folder of the former Calendar Stretch page."""
    page_dir = DEFINITION / "pages" / PAGE
    existing = {path.parent.name: read(path) for path in sorted((page_dir / "visuals").glob("*/visual.json"))}
    missing = set(CALENDARS_VIEW) - set(existing)
    if missing:
        raise ValueError(f"Calendar Analysis visuals are missing: {sorted(missing)}")
    delay = kpi_cards(existing["ca17kpi1cal000000017"])
    for item in (work_vs_wait_bars(), deneb_timeline(), outlier_scatter(), cliff_callout(), cliff_chart()):
        delay[item["name"]] = item
    for item in delay.values():
        # Calendars is the saved view; the Delay bookmark shows these.
        item["isHidden"] = True
    navigator = view_navigator()
    if NAVIGATOR in existing:
        # Once placed, the buttons' position is the report author's: keep a navigator moved in Desktop where it is.
        navigator["position"] = existing[NAVIGATOR]["position"]

    outputs: dict[Path, dict | None] = {}
    for item in [*delay.values(), navigator]:
        outputs[Path("pages") / PAGE / "visuals" / item["name"] / "visual.json"] = item
    page = read(page_dir / "page.json")
    page["visualInteractions"] = interactions(page, set(existing) | set(delay) | {NAVIGATOR})
    outputs[Path("pages") / PAGE / "page.json"] = page

    visual_types = {name: existing[name]["visual"]["visualType"] for name in CALENDARS_VIEW}
    visual_types.update({name: item["visual"]["visualType"] for name, item in delay.items()})
    outputs[Path("bookmarks") / f"{CALENDARS_BOOKMARK}.bookmark.json"] = view_bookmark(CALENDARS_BOOKMARK, "Calendars", CALENDARS_VIEW, visual_types)
    outputs[Path("bookmarks") / f"{DELAY_BOOKMARK}.bookmark.json"] = view_bookmark(DELAY_BOOKMARK, "Delay", DELAY_VIEW, visual_types)
    for name in MENU_BOOKMARKS:
        # Opening or closing the project menu must leave the selected view alone.
        path = Path("bookmarks") / f"{name}.bookmark.json"
        bookmark = read(DEFINITION / path)
        bookmark["options"] = {"applyOnlyToTargetVisuals": True,
                               **{key: value for key, value in bookmark["options"].items() if key != "applyOnlyToTargetVisuals"}}
        outputs[path] = bookmark

    metadata = read(DEFINITION / "bookmarks" / "bookmarks.json")
    metadata["items"] = [entry for entry in metadata["items"] if entry.get("name") not in FORMER_BOOKMARKS]
    group = {"name": VIEW_GROUP, "displayName": "Calendar Analysis view", "children": [CALENDARS_BOOKMARK, DELAY_BOOKMARK]}
    positions = [index for index, entry in enumerate(metadata["items"]) if entry.get("name") == VIEW_GROUP]
    if positions:
        metadata["items"][positions[0]] = group
    else:
        metadata["items"].append(group)
    outputs[Path("bookmarks") / "bookmarks.json"] = metadata
    for name in FORMER_BOOKMARKS:
        outputs[Path("bookmarks") / f"{name}.bookmark.json"] = None
    outputs[Path("pages") / FORMER_PAGE] = None

    pages = read(DEFINITION / "pages" / "pages.json")
    pages["pageOrder"] = [name for name in pages["pageOrder"] if name != FORMER_PAGE]
    if pages.get("activePageName") == FORMER_PAGE:
        pages["activePageName"] = PAGE
    outputs[Path("pages") / "pages.json"] = pages

    report = read(DEFINITION / "report.json")
    if DENEB not in report.get("publicCustomVisuals", []):
        # Written only to register Deneb, so an unchanged report.json keeps Desktop's formatting.
        report["publicCustomVisuals"] = report.get("publicCustomVisuals", []) + [DENEB]
        outputs[Path("report.json")] = report
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    outputs = build()
    destination = args.output_dir.resolve() if args.output_dir else DEFINITION
    if args.output_dir and (destination == DEFINITION.parent or DEFINITION.parent in destination.parents):
        raise ValueError("Review drafts must be outside the production report folder; use --apply to write the view.")
    changed = []
    for relative, value in outputs.items():
        path = destination / relative
        if value is None:
            if path.exists():
                changed.append(relative.as_posix() + " (removed)")
                if not args.check:
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            continue
        text = rendered(value)
        if not path.exists() or desktop_neutral(json.loads(path.read_text(encoding="utf-8-sig"))) != desktop_neutral(value):
            changed.append(relative.as_posix())
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print(json.dumps({"result": "FAIL" if args.check and changed else "PASS", "page": PAGE,
                      "visuals": sum(1 for path, value in outputs.items() if path.name == "visual.json" and value is not None),
                      "changed": changed}, indent=2))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

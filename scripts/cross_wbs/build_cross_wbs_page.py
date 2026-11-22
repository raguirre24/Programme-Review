"""Build and verify the Cross-WBS Analysis PBIR page (eb4b0a43085cad901574) and its project-menu bookmarks.

This generator owns the layout, slicers, KPI strip, analytical visuals, legend, visual interactions,
and project-menu bookmark scoping for 'Cross-WBS Analysis':
  - Cleans the hidden Project Menu backdrop ('f7d730a81623609efa7f') and aligns the header UpdateDate dropdown
    ('20a217eb520400e1b9b8') while preserving its syncGroup and 'Update Has Visible Tasks' = 1L RLS filter.
  - Builds the 4 titled filter-bar slicers (y = 86, h = 54): Link Scope, Successor Status, Successor Criticality,
    and Driving Relationship.
  - Builds the 4 portfolio-safe KPI cards (y = 148, h = 70): Handoff Links & WBS Interfaces, Driving Links & Share,
    Critical & Zero-Free-Float Handoffs, and Unique Predecessors & Unique Successors.
  - Builds the WBS Interface Summary table, Risk-Coloured WBS-to-WBS Matrix + Cell Colour Legend, Top 15 WBS Handoff
    Interfaces stacked bar chart, and Unified Handoff Link Inspector table.
  - Removes the 6 retired prototype visuals ('c25ab916ac9a587450df', 'c5b3da7b948b79624521', '564019b5e64b29ba8e29',
    'bc3556dbcc6daf4a1bd6', '2bb8296a8a98ae9e2685', '77a062a0a61423c22251').
  - Scopes project-menu bookmarks '4811b33dc17bc4c98b1b' and '577b6b2c226d54c39e00' with applyOnlyToTargetVisuals
    and suppressActiveSection.

Modes:
  --check       Compare generated content against the report, ignoring Desktop-managed formatting keys (exit 1 on diff).
  --output-dir  Write a full review copy outside the production report directory without touching the report.
  --apply       Write changes into the report definition (ensure Power BI Desktop is closed first).
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "resource_playground"))
from generate_page import colour, expr, field, props, string  # noqa: E402

DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
PAGE = "eb4b0a43085cad901574"
PAGE_NAME = "Cross-WBS Analysis"
CALENDAR_PAGE = "ca1da4a175154c398f01"

PRED = "06 XER_PREDECESSOR"
TASK = "01 XER_TASK"
WBS_MEASURES = "WBS Measures"
STATUS_FILTER_TABLE = "Filter_Activity_Status"
CRIT_FILTER_TABLE = "Filter_Critical_Status"

# Preserved chrome & project-menu visual IDs
LOGO = "b28b1f271cb925756fc2"
PAGE_TITLE_SHAPE = "f48dbc7f27139d1e5861"
UPDATE_SLICER = "20a217eb520400e1b9b8"
SELECTED_TITLE = "1f1ce611c0cd31041cd7"
DATA_DATE_TITLE = "2901bcdf949a3ac8c590"
SELECTED_FILE = "76e42b25c0170b790e00"
OPEN_MENU_BTN = "868fe50f0be7e3d59f79"
HOME_NAV = "612b3664c4a0011ddadb"
PAGE_NAV = "a70586e08033a1060c0e"
MENU_BG = "f7d730a81623609efa7f"
STATE_SLICER = "b5b9e58ac61e23e6960f"
PROJECT_SLICER = "a080ddcc97529e047055"
CLOSE_MENU_BTN = "0b8551c19458f13c9d1f"

MENU_VISUALS = [MENU_BG, STATE_SLICER, PROJECT_SLICER, CLOSE_MENU_BTN]
MENU_BOOKMARKS = ("4811b33dc17bc4c98b1b", "577b6b2c226d54c39e00")

UNTOUCHED_CHROME = [
    LOGO,
    PAGE_TITLE_SHAPE,
    SELECTED_TITLE,
    DATA_DATE_TITLE,
    SELECTED_FILE,
    OPEN_MENU_BTN,
    HOME_NAV,
    PAGE_NAV,
    STATE_SLICER,
    PROJECT_SLICER,
    CLOSE_MENU_BTN,
]

# Filter control strip (y = 86, h = 54)
LINK_SCOPE_SLICER = "77166234f588ee948bbb"
STATUS_SLICER = "cwbs14statslc0000014"
CRITICALITY_SLICER = "cwbs15critslc0000015"
DRIVING_SLICER = "c422a8a54e8d60088d24"
SLICERS = [LINK_SCOPE_SLICER, STATUS_SLICER, CRITICALITY_SLICER, DRIVING_SLICER]

# KPI banner (y = 148, h = 70)
KPIS = [
    "cwbs17kpi1lnk0000017",
    "cwbs18kpi2drv0000018",
    "cwbs19kpi3crt0000019",
    "cwbs20kpi4act0000020",
]

# Analytical visuals & matrix legend
SUMMARY_TABLE = "c055a0c255a725e96736"
WBS_MATRIX = "673df8690a32f9fdfeff"
MATRIX_LEGEND = "cwbs25matxleg0000025"
INTERFACES_BAR = "7ad5b8e76591c9b749e7"
LINK_INSPECTOR = "47ceb5d7d41a2b89bf05"
DATA_VISUALS = [SUMMARY_TABLE, WBS_MATRIX, INTERFACES_BAR, LINK_INSPECTOR]

RETIRED_VISUALS = (
    "c25ab916ac9a587450df",
    "c5b3da7b948b79624521",
    "564019b5e64b29ba8e29",
    "bc3556dbcc6daf4a1bd6",
    "2bb8296a8a98ae9e2685",
    "77a062a0a61423c22251",
)

EXPECTED_VISUALS = set(UNTOUCHED_CHROME) | {MENU_BG, UPDATE_SLICER} | set(SLICERS) | set(KPIS) | set(DATA_VISUALS) | {MATRIX_LEGEND}

DESKTOP_MANAGED_KEYS = {"$schema", "z", "tabOrder", "active", "stateManagement", "developer"}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def desktop_neutral(value):
    if isinstance(value, dict):
        result = {k: desktop_neutral(v) for k, v in value.items() if k not in DESKTOP_MANAGED_KEYS}
        if "filterConfig" in result and isinstance(result["filterConfig"], dict):
            active_filters = [
                f for f in result["filterConfig"].get("filters", [])
                if isinstance(f, dict) and "filter" in f
            ]
            if active_filters:
                result["filterConfig"] = {**result["filterConfig"], "filters": active_filters}
            else:
                result.pop("filterConfig", None)
        return result
    if isinstance(value, list):
        return [desktop_neutral(item) for item in value]
    return value


def hex_colour(value: str) -> dict:
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{value}'"}}}}}


def measure_colour(entity: str, prop: str) -> dict:
    return {"solid": {"color": {"expr": {"Measure": field(entity, prop, "Measure")["Measure"]}}}}


def wbs_measure(name: str, label: str, fmt: str | None = None) -> dict:
    proj = {
        "field": field(WBS_MEASURES, name, "Measure"),
        "queryRef": f"{WBS_MEASURES}.{name}",
        "nativeQueryRef": label,
        "active": True,
        "displayName": label,
    }
    if fmt:
        proj["format"] = fmt
    return proj


def col_proj(table: str, name: str, label: str | None = None) -> dict:
    proj = {
        "field": field(table, name),
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": label or name,
        "active": True,
    }
    if label:
        proj["displayName"] = label
    return proj


def container(name: str, visual_type: str, x: float, y: float, width: float, height: float, order: int) -> dict:
    return {
        "$schema": SCHEMA + "visualContainer/2.14.0/schema.json",
        "name": name,
        "position": {
            "x": x,
            "y": y,
            "z": order * 1000,
            "height": height,
            "width": width,
            "tabOrder": order * 1000,
        },
        "visual": {
            "visualType": visual_type,
            "objects": {},
            "visualContainerObjects": {},
            "drillFilterOtherVisuals": True,
        },
    }


def card_frame(item: dict, title_measure: str, alt_text: str, *, style_preset: str | None = "BoldHeader") -> None:
    vco = item["visual"]["visualContainerObjects"]
    if style_preset is not None:
        vco["stylePreset"] = props(name=string(style_preset))
    vco["background"] = props(show=expr("true"), color=hex_colour("#FFFFFF"), transparency=expr("0D"))
    vco["title"] = props(
        show=expr("true"),
        text={"expr": {"Measure": field(WBS_MEASURES, title_measure, "Measure")["Measure"]}},
        fontSize=expr("13D"),
        fontColor=colour(1),
        bold=expr("true"),
        titleWrap=expr("true"),
    )
    vco["subTitle"] = props(
        show=expr("true"),
        text={"expr": {"Measure": field(WBS_MEASURES, "CWBS Scope Prompt", "Measure")["Measure"]}},
        fontSize=expr("9D"),
        fontColor=colour(1, 0.4),
        titleWrap=expr("true"),
    )
    vco["general"] = props(altText=string(alt_text))
    vco["border"] = props(show=expr("true"), color=colour(1, 0.6), radius=expr("4D"))
    vco["padding"] = props(top=expr("6D"), bottom=expr("6D"), left=expr("8D"), right=expr("8D"))


def column_ref(source: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": source}}, "Property": name}}


def not_null_visual_filter(filter_name: str, table: str, column: str, alias: str = "s") -> dict:
    return {
        "name": filter_name,
        "field": field(table, column),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Not": {
                            "Expression": {
                                "In": {
                                    "Expressions": [column_ref(alias, column)],
                                    "Values": [[{"Literal": {"Value": "null"}}]],
                                }
                            }
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
        "objects": {
            "general": [
                {
                    "properties": {
                        "isInvertedSelectionMode": expr("true"),
                    }
                }
            ]
        },
    }


def tile_slicer(
    name: str,
    table: str,
    column: str,
    caption: str,
    x: float,
    y: float,
    width: float,
    height: float,
    cols: int,
    order: int,
    *,
    defaults: list[str] | None = None,
    sort_dir: str | None = None,
    filter_name: str,
) -> dict:
    item = container(name, "advancedSlicerVisual", x, y, width, height, order)
    vis = item["visual"]
    vis["query"] = {"queryState": {"Values": {"projections": [col_proj(table, column)]}}}
    if sort_dir:
        vis["query"]["sortDefinition"] = {"sort": [{"field": field(table, column), "direction": sort_dir}]}

    general_props: dict = {}
    if defaults:
        general_props["filter"] = {
            "filter": {
                "Version": 2,
                "From": [{"Name": "s", "Entity": table, "Type": 0}],
                "Where": [
                    {
                        "Condition": {
                            "In": {
                                "Expressions": [column_ref("s", column)],
                                "Values": [[{"Literal": {"Value": f"'{val}'"}}] for val in defaults],
                            }
                        }
                    }
                ],
            }
        }

    vis["objects"] = {
        "general": [{"properties": general_props}],
        "label": [{"properties": {"show": expr("false"), "labelSource": string("auto")}, "selector": {"id": "default"}}],
        "layout": props(rowCount=expr("1L"), columnCount=expr(f"{cols}L"), cellPadding=expr("4L")),
        "value": [
            {"properties": {"show": expr("true")}},
            {
                "properties": {
                    "horizontalAlignment": string("center"),
                    "fontSize": expr("11D"),
                    "fontColor": colour(1),
                    "fontFamily": string("'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"),
                },
                "selector": {"id": "default"},
            },
            {
                "properties": {
                    "horizontalAlignment": string("center"),
                    "fontColor": hex_colour("#d50000"),
                },
                "selector": {"id": "interaction:press"},
            },
        ],
        "outline": [
            {"properties": {"lineColor": colour(9)}, "selector": {"id": "default"}},
            {"properties": {"lineColor": colour(1)}, "selector": {"id": "selection:selected"}},
            {"properties": {"lineColor": colour(9)}, "selector": {"id": "interaction:press"}},
        ],
        "fillCustom": [
            {"properties": {"fillColor": colour(9)}, "selector": {"id": "selection:selected"}},
        ],
        "padding": [
            {
                "properties": {
                    "paddingSelection": string("Custom"),
                    "leftMargin": expr("0L"),
                    "rightMargin": expr("0L"),
                },
                "selector": {"id": "default"},
            }
        ],
    }
    vis["visualContainerObjects"] = {
        "title": props(
            show=expr("true"),
            text=string(caption),
            fontSize=expr("10D"),
            fontColor=colour(1),
            bold=expr("true"),
            titleWrap=expr("true"),
        ),
        "background": props(show=expr("false")),
        "padding": props(top=expr("1D"), bottom=expr("1D"), left=expr("1D"), right=expr("1D")),
        "general": props(altText=string(caption + " slicer")),
    }
    item["filterConfig"] = {"filters": [not_null_visual_filter(filter_name, table, column)]}
    return item


def kpi_cards(template: dict) -> dict[str, dict]:
    specs = [
        (
            KPIS[0],
            12,
            [
                ("CWBS KPI Handoff Links", "Handoff Links", True),
                ("CWBS KPI Active Interfaces", "WBS Interfaces", True),
            ],
            "Scoped handoff links and active WBS interfaces",
        ),
        (
            KPIS[1],
            456,
            [
                ("CWBS KPI Driving Links", "Driving Links", True),
                ("CWBS KPI Driving Share", "Driving Share", False),
            ],
            "Driving relationships and driving share",
        ),
        (
            KPIS[2],
            900,
            [
                ("CWBS KPI Critical Handoffs", "Into Critical (TF ≤ 0)", True),
                ("CWBS KPI Zero Free Float Links", "Zero Free Float (FF ≤ 0d)", True),
            ],
            "Critical handoffs and zero free float links",
        ),
        (
            KPIS[3],
            1344,
            [
                ("CWBS KPI Distinct Predecessors", "Unique Predecessors", True),
                ("CWBS KPI Distinct Successors", "Unique Successors", True),
            ],
            "Unique predecessor and successor boundary activities",
        ),
    ]
    cards: dict[str, dict] = {}
    for order, (name, x, metrics, alt_text) in enumerate(specs, start=9):
        item = copy.deepcopy(template)
        item.pop("isHidden", None)
        item["name"] = name
        item["position"] = {"x": x, "y": 148, "z": order * 1000, "height": 70, "width": 432, "tabOrder": order * 1000}
        item["visual"]["query"]["queryState"]["Data"]["projections"] = [
            wbs_measure(m, label) for m, label, _ in metrics
        ]
        item["visual"]["query"]["sortDefinition"]["sort"][0]["field"] = field(WBS_MEASURES, metrics[0][0], "Measure")
        # Keep whole-number cards unscaled (1D); percentages keep their 0.0% measure format.
        item["visual"]["objects"]["value"] = [item["visual"]["objects"]["value"][0]] + [
            {"properties": {"labelDisplayUnits": expr("1D")}, "selector": {"metadata": f"{WBS_MEASURES}.{m}"}}
            for m, _, whole in metrics
            if whole
        ]
        vco = item["visual"]["visualContainerObjects"]
        vco["general"] = props(altText=string(alt_text))
        vco["title"][0]["properties"]["text"] = string(alt_text)
        cards[name] = item
    return cards


def build_summary_table() -> dict:
    item = container(SUMMARY_TABLE, "tableEx", 12, 226, 688, 370, 13)
    vis = item["visual"]
    cols = [
        (col_proj(PRED, "Predecessor_Level_2", "From WBS"), 150, "Left", False),
        (col_proj(PRED, "Successor_Level_2", "To WBS"), 150, "Left", False),
        (wbs_measure("CWBS Interface Links", "Links", "#,0"), 60, "Center", True),
        (wbs_measure("CWBS Interface Driving Links", "Driving", "#,0"), 66, "Center", True),
        (wbs_measure("CWBS Interface Driving Share", "Driving %", "0.0%"), 74, "Center", True),
        (wbs_measure("CWBS Interface Critical Links", "Critical (TF≤0)", "#,0"), 84, "Center", True),
        (wbs_measure("CWBS Interface Min Free Float", "Min FF (d)", "#,0.0"), 68, "Center", True),
    ]
    vis["query"] = {
        "queryState": {"Values": {"projections": [p for p, _, _, _ in cols]}},
        "sortDefinition": {
            "sort": [{"field": field(WBS_MEASURES, "CWBS Interface Links", "Measure"), "direction": "Descending"}]
        },
    }
    vis["objects"] = {
        "columnWidth": [
            {"properties": {"value": expr(f"{w}D")}, "selector": {"metadata": p["queryRef"]}}
            for p, w, _, _ in cols
        ],
        "values": props(fontSize=expr("10D")),
        "columnHeaders": props(
            fontSize=expr("10D"),
            autoSizeColumnWidth=expr("true"),
            alignment=string("Center"),
        ),
        "total": props(totals=expr("true"), italic=expr("false")),
        "columnFormatting": [
            {
                "properties": {
                    "alignment": string(align),
                    **({"styleTotal": expr("true")} if style_tot else {}),
                },
                "selector": {"metadata": p["queryRef"]},
            }
            for p, _, align, style_tot in cols
            if align != "Left" or style_tot
        ],
    }
    card_frame(item, "CWBS Interface Summary Title", "WBS Interface Summary table")
    return item


def build_wbs_matrix() -> dict:
    item = container(WBS_MATRIX, "pivotTable", 712, 226, 1064, 322, 14)
    vis = item["visual"]
    val_proj = wbs_measure("CWBS Matrix Link Count", "Links")
    vis["query"] = {
        "queryState": {
            "Rows": {"projections": [col_proj(PRED, "Predecessor_Level_2", "Predecessor WBS")]},
            "Columns": {"projections": [col_proj(PRED, "Successor_Level_2", "Successor WBS")]},
            "Values": {"projections": [val_proj]},
        },
        "sortDefinition": {
            "sort": [
                {"field": field(PRED, "Predecessor_Level_2"), "direction": "Ascending"},
                {"field": field(PRED, "Successor_Level_2"), "direction": "Ascending"},
            ]
        },
    }
    vis["objects"] = {
        "subTotals": props(columnSubtotals=expr("true"), rowSubtotals=expr("true")),
        "columnWidth": [
            {"properties": {"value": expr("185D")}, "selector": {"metadata": f"{PRED}.Predecessor_Level_2"}},
        ],
        "columnHeaders": props(
            bold=expr("true"),
            fontColor=colour(0),
            backColor=colour(1),
            fontSize=expr("10D"),
            autoSizeColumnWidth=expr("true"),
            alignment=string("Center"),
        ),
        "rowHeaders": props(
            bold=expr("true"),
            fontColor=colour(0),
            backColor=colour(1),
            fontSize=expr("10D"),
        ),
        "values": [
            {
                "properties": {
                    "valuesOnRow": expr("false"),
                    "fontSize": expr("11D"),
                    "bandedRowHeaders": expr("false"),
                }
            },
            {
                "properties": {
                    "backColor": measure_colour(WBS_MEASURES, "CWBS Matrix Cell Colour"),
                    "fontColor": measure_colour(WBS_MEASURES, "CWBS Matrix Font Colour"),
                },
                "selector": {
                    "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                    "metadata": val_proj["queryRef"],
                },
            },
        ],
        "columnFormatting": [
            {
                "properties": {"alignment": string("Center"), "labelDisplayUnits": expr("1D")},
                "selector": {"metadata": val_proj["queryRef"]},
            }
        ],
        "grid": props(gridHorizontal=expr("true"), gridVertical=expr("true")),
    }
    card_frame(item, "CWBS Matrix Title", "WBS-to-WBS Interface Matrix", style_preset="None")
    return item


def build_matrix_legend() -> dict:
    item = container(MATRIX_LEGEND, "textbox", 712, 554, 1064, 42, 15)
    runs = [
        {"value": "Cell colour:  ", "textStyle": {"fontWeight": "bold", "fontFamily": "Segoe UI", "fontSize": "10pt", "color": "#252525"}},
        {"value": "■", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt", "color": "#FFC7CE"}},
        {"value": " Critical driving (TF ≤ 0)   ", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10pt", "color": "#252525"}},
        {"value": "■", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt", "color": "#FFEB9C"}},
        {"value": " Driving / near-critical (TF ≤ 10)   ", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10pt", "color": "#252525"}},
        {"value": "■", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt", "color": "#DDEBF7"}},
        {"value": " Buffered cross-WBS   ", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10pt", "color": "#252525"}},
        {"value": "■", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt", "color": "#E7E6E6"}},
        {"value": " Internal (same WBS; '—' when Cross-WBS only)", "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10pt", "color": "#252525"}},
    ]
    item["visual"]["objects"] = {"general": props(paragraphs=[{"textRuns": runs}])}
    item["visual"]["visualContainerObjects"] = {
        "background": props(show=expr("true"), color=hex_colour("#FFFFFF"), transparency=expr("0D")),
        "general": props(altText=string("Links Between WBS Chapters cell colour legend")),
        "visualHeader": props(show=expr("false")),
        "border": props(show=expr("true"), color=colour(1, 0.6), radius=expr("4D")),
    }
    return item


def top_interfaces_filter(filter_name: str) -> dict:
    """Top 15 WBS_Link_Direction pairs ordered by 'WBS Measures'[Count of Links]."""
    return {
        "name": filter_name,
        "field": field(PRED, "WBS_Link_Direction"),
        "type": "TopN",
        "filter": {
            "Version": 2,
            "From": [
                {
                    "Name": "subquery",
                    "Expression": {
                        "Subquery": {
                            "Query": {
                                "Version": 2,
                                "From": [
                                    {"Name": "p", "Entity": PRED, "Type": 0},
                                    {"Name": "w", "Entity": WBS_MEASURES, "Type": 0},
                                ],
                                "Select": [{**column_ref("p", "WBS_Link_Direction"), "Name": "field"}],
                                "OrderBy": [
                                    {
                                        "Direction": 2,
                                        "Expression": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Source": "w"}},
                                                "Property": "Count of Links",
                                            }
                                        },
                                    }
                                ],
                                "Top": 15,
                            }
                        }
                    },
                    "Type": 2,
                },
                {"Name": "p", "Entity": PRED, "Type": 0},
            ],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [column_ref("p", "WBS_Link_Direction")],
                            "Table": {"SourceRef": {"Source": "subquery"}},
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
    }


def build_interfaces_bar() -> dict:
    item = container(INTERFACES_BAR, "barChart", 12, 608, 580, 460, 16)
    vis = item["visual"]
    stack = [
        ("CWBS Interface Driving Links", "Driving links", "#C00000"),
        ("CWBS Interface Non-Driving Links", "Non-driving links", "#BFBFBF"),
    ]
    vis["query"] = {
        "queryState": {
            "Category": {"projections": [col_proj(PRED, "WBS_Link_Direction", "WBS Interface")]},
            "Y": {"projections": [wbs_measure(m, label) for m, label, _ in stack]},
            "Tooltips": {
                "projections": [
                    wbs_measure("CWBS Interface Links", "Total links"),
                    wbs_measure("CWBS Interface Driving Share", "Driving share"),
                    wbs_measure("CWBS Interface Critical Links", "Into Critical (TF ≤ 0)"),
                    wbs_measure("CWBS Interface Min Free Float", "Min Free Float (days)"),
                ]
            },
        },
        "sortDefinition": {
            "sort": [{"field": field(WBS_MEASURES, "CWBS Interface Links", "Measure"), "direction": "Descending"}]
        },
    }
    vis["objects"] = {
        "dataPoint": [
            {"properties": {"fill": hex_colour(hex_val)}, "selector": {"metadata": f"{WBS_MEASURES}.{m}"}}
            for m, _, hex_val in stack
        ],
        "legend": props(show=expr("true"), position=string("Top")),
        "totals": props(show=expr("true")),
        "valueAxis": props(showAxisTitle=expr("true"), titleText=string("Scoped logic links")),
        "categoryAxis": props(showAxisTitle=expr("false"), maxMarginFactor=expr("45L")),
    }
    card_frame(item, "CWBS Top Interfaces Title", "Top 15 WBS Handoff Interfaces stacked bar chart", style_preset=None)
    item["filterConfig"] = {
        "filters": [
            top_interfaces_filter("cwbs7atopn0000000001"),
            not_null_visual_filter("cwbs7anonnull0000002", PRED, "WBS_Link_Direction", alias="p"),
        ]
    }
    return item


def build_link_inspector() -> dict:
    item = container(LINK_INSPECTOR, "tableEx", 604, 608, 1172, 460, 17)
    vis = item["visual"]
    cols = [
        (col_proj(PRED, "predecessor_task_code", "Pred. ID"), 85, "Left"),
        (wbs_measure("CWBS Link Predecessor Name", "Predecessor Name"), 165, "Left"),
        (wbs_measure("CWBS Link Predecessor WBS", "From WBS"), 115, "Left"),
        (col_proj(PRED, "task_code", "Succ. ID"), 85, "Left"),
        (wbs_measure("CWBS Link Successor Name", "Successor Name"), 165, "Left"),
        (wbs_measure("CWBS Link Successor WBS", "To WBS"), 115, "Left"),
        (col_proj(PRED, "pred_type", "Rel."), 50, "Center"),
        (wbs_measure("CWBS Link Lag Days", "Lag (d)", "#,0.0"), 56, "Center"),
        (wbs_measure("CWBS Link Predecessor Finish", "Pred. Finish", "dd-MMM-yy"), 78, "Center"),
        (wbs_measure("CWBS Link Successor Start", "Succ. Start", "dd-MMM-yy"), 78, "Center"),
        (wbs_measure("CWBS Link Free Float Days", "Free Float (d)", "#,0.0"), 68, "Center"),
        (wbs_measure("CWBS Link Successor Total Float", "Succ. TF (d)", "#,0.0"), 68, "Center"),
        (wbs_measure("CWBS Link Driving Status", "Driving"), 68, "Center"),
    ]
    tf_ref = f"{WBS_MEASURES}.CWBS Link Successor Total Float"
    vis["query"] = {
        "queryState": {"Values": {"projections": [p for p, _, _ in cols]}},
        "sortDefinition": {
            "sort": [
                {"field": field(WBS_MEASURES, "CWBS Link Free Float Days", "Measure"), "direction": "Ascending"},
                {"field": field(WBS_MEASURES, "CWBS Link Successor Total Float", "Measure"), "direction": "Ascending"},
            ]
        },
    }
    vis["objects"] = {
        "columnWidth": [
            {"properties": {"value": expr(f"{w}D")}, "selector": {"metadata": p["queryRef"]}}
            for p, w, _ in cols
        ],
        "values": [
            {"properties": {"fontSize": expr("10D")}},
            {
                "properties": {
                    "backColor": measure_colour(WBS_MEASURES, "CWBS Link Total Float Colour"),
                    "fontColor": measure_colour(WBS_MEASURES, "CWBS Link Total Float Font Colour"),
                },
                "selector": {
                    "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                    "metadata": tf_ref,
                },
            },
        ],
        "columnHeaders": props(
            fontSize=expr("10D"),
            autoSizeColumnWidth=expr("true"),
            alignment=string("Center"),
        ),
        "total": props(totals=expr("false")),
        "columnFormatting": [
            {"properties": {"alignment": string(align)}, "selector": {"metadata": p["queryRef"]}}
            for p, _, align in cols
            if align != "Left"
        ],
    }
    card_frame(item, "CWBS Link Inspector Title", "Unified Handoff Link Inspector table")
    return item


def build_interactions() -> list[dict]:
    interactions: list[dict] = [
        {"source": PROJECT_SLICER, "target": STATE_SLICER, "type": "NoFilter"},
    ]
    # Filter-bar slicers never empty the UpdateDate dropdown
    for slc in SLICERS:
        interactions.append({"source": slc, "target": UPDATE_SLICER, "type": "NoFilter"})

    # Analytical visuals never alter slicers or overwrite KPI banner cards
    protected_targets = [UPDATE_SLICER] + SLICERS + KPIS
    for src in DATA_VISUALS:
        for dst in protected_targets:
            interactions.append({"source": src, "target": dst, "type": "NoFilter"})

    # Mutual cross-filtering among overview visuals (Summary Table, Matrix, Top 15 Bar Chart) and down into Link Inspector
    overview = [SUMMARY_TABLE, WBS_MATRIX, INTERFACES_BAR]
    for src in overview:
        for dst in overview:
            if src != dst:
                interactions.append({"source": src, "target": dst, "type": "DataFilter"})
        interactions.append({"source": src, "target": LINK_INSPECTOR, "type": "DataFilter"})

    # Clicking a row in Link Inspector keeps the overview visuals intact
    for dst in overview:
        interactions.append({"source": LINK_INSPECTOR, "target": dst, "type": "NoFilter"})

    return interactions


def build_menu_bookmark(bookmark_id: str, display_name: str, *, hide: bool) -> dict:
    containers = {}
    for vid, vtype in [
        (MENU_BG, "shape"),
        (STATE_SLICER, "advancedSlicerVisual"),
        (PROJECT_SLICER, "advancedSlicerVisual"),
        (CLOSE_MENU_BTN, "actionButton"),
    ]:
        entry: dict = {"visualType": vtype, "objects": {}}
        if hide:
            entry["display"] = {"mode": "hidden"}
        containers[vid] = {"singleVisual": entry}

    return {
        "$schema": SCHEMA + "bookmark/2.1.0/schema.json",
        "displayName": display_name,
        "name": bookmark_id,
        "options": {
            "targetVisualNames": list(MENU_VISUALS),
            "applyOnlyToTargetVisuals": True,
            "suppressData": True,
            "suppressActiveSection": True,
        },
        "explorationState": {
            "version": "1.0",
            "activeSection": PAGE,
            "sections": {PAGE: {"visualContainers": containers}},
        },
    }


def build() -> dict[Path, dict | None]:
    page_dir = Path("pages") / PAGE
    page = read(DEFINITION / page_dir / "page.json")
    page["displayName"] = PAGE_NAME
    page["visualInteractions"] = build_interactions()

    # Clean accidental 'unique successors' text from the hidden Project Menu backdrop shape
    menu_bg = read(DEFINITION / page_dir / "visuals" / MENU_BG / "visual.json")
    menu_bg["visual"]["objects"]["text"] = [{"properties": {"show": expr("false")}}]
    menu_bg["isHidden"] = True

    # Align header UpdateDate dropdown while preserving its syncGroup and 'Update Has Visible Tasks' = 1L RLS filter
    update_slc = read(DEFINITION / page_dir / "visuals" / UPDATE_SLICER / "visual.json")
    update_slc["position"] = {"x": 874.3, "y": 41.4, "z": 1000, "height": 42.9, "width": 170.0, "tabOrder": 1000}

    kpi_template = read(DEFINITION / "pages" / CALENDAR_PAGE / "visuals" / "ca17kpi1cal000000017" / "visual.json")

    files: dict[Path, dict | None] = {
        page_dir / "page.json": page,
        page_dir / "visuals" / MENU_BG / "visual.json": menu_bg,
        page_dir / "visuals" / UPDATE_SLICER / "visual.json": update_slc,
        page_dir / "visuals" / LINK_SCOPE_SLICER / "visual.json": tile_slicer(
            LINK_SCOPE_SLICER,
            PRED,
            "Link_Type",
            "Link Scope",
            12,
            86,
            396,
            54,
            2,
            5,
            defaults=["Cross-WBS Link"],
            sort_dir="Ascending",
            filter_name="cwbs77flt00000000001",
        ),
        page_dir / "visuals" / STATUS_SLICER / "visual.json": tile_slicer(
            STATUS_SLICER,
            STATUS_FILTER_TABLE,
            "status_code",
            "Successor Status",
            420,
            86,
            468,
            54,
            3,
            6,
            defaults=["Not Started", "In Progress"],
            sort_dir="Descending",
            filter_name="cwbs14flt00000000001",
        ),
        page_dir / "visuals" / CRITICALITY_SLICER / "visual.json": tile_slicer(
            CRITICALITY_SLICER,
            CRIT_FILTER_TABLE,
            "CriticalStatus",
            "Successor Criticality",
            900,
            86,
            480,
            54,
            3,
            7,
            defaults=None,
            sort_dir="Ascending",
            filter_name="cwbs15flt00000000001",
        ),
        page_dir / "visuals" / DRIVING_SLICER / "visual.json": tile_slicer(
            DRIVING_SLICER,
            PRED,
            "Is Driving Predecessor",
            "Driving Relationship",
            1392,
            86,
            384,
            54,
            2,
            8,
            defaults=None,
            sort_dir="Ascending",
            filter_name="cwbsc4flt00000000001",
        ),
        page_dir / "visuals" / SUMMARY_TABLE / "visual.json": build_summary_table(),
        page_dir / "visuals" / WBS_MATRIX / "visual.json": build_wbs_matrix(),
        page_dir / "visuals" / MATRIX_LEGEND / "visual.json": build_matrix_legend(),
        page_dir / "visuals" / INTERFACES_BAR / "visual.json": build_interfaces_bar(),
        page_dir / "visuals" / LINK_INSPECTOR / "visual.json": build_link_inspector(),
        Path("bookmarks") / f"{MENU_BOOKMARKS[0]}.bookmark.json": build_menu_bookmark(
            MENU_BOOKMARKS[0], "Open Project Menu - Cross-WBS Analysis", hide=False
        ),
        Path("bookmarks") / f"{MENU_BOOKMARKS[1]}.bookmark.json": build_menu_bookmark(
            MENU_BOOKMARKS[1], "Close Project Menu - Cross-WBS Analysis", hide=True
        ),
    }
    for vid, card_item in kpi_cards(kpi_template).items():
        files[page_dir / "visuals" / vid / "visual.json"] = card_item

    for retired in RETIRED_VISUALS:
        files[page_dir / "visuals" / retired] = None

    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Exit 1 if the report differs from the generated definition")
    mode.add_argument("--output-dir", type=Path, help="Write review copy to an external directory")
    mode.add_argument("--apply", action="store_true", help="Write generated files into the PBIR report definition")
    args = parser.parse_args()

    files = build()
    if args.check:
        diffs: list[str] = []
        for rel, content in files.items():
            target = DEFINITION / rel
            if content is None:
                if target.exists():
                    diffs.append(f"retired path still exists: {rel.as_posix()}")
            elif not target.exists():
                diffs.append(f"missing file: {rel.as_posix()}")
            elif desktop_neutral(read(target)) != desktop_neutral(content):
                diffs.append(f"content differs: {rel.as_posix()}")
        if diffs:
            for d in diffs:
                print(d, file=sys.stderr)
            sys.exit(1)
        print(json.dumps({"status": "PASS", "page": PAGE, "visuals": len(EXPECTED_VISUALS)}, indent=2))
        return

    if args.output_dir is not None:
        out_root = args.output_dir.resolve()
        prod_report = DEFINITION.parent.resolve()
        if out_root == prod_report or prod_report in out_root.parents:
            raise RuntimeError("--output-dir must be outside the production report directory.")
        # Copy untouched chrome visuals so the review directory is a complete standalone page snapshot
        for vid in UNTOUCHED_CHROME:
            rel_vis = Path("pages") / PAGE / "visuals" / vid / "visual.json"
            dst = out_root / rel_vis
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(DEFINITION / rel_vis, dst)
        for rel, content in files.items():
            if content is not None:
                dst = out_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(rendered(content), encoding="utf-8")
        print(json.dumps({"written_to": str(out_root), "files": sum(1 for v in files.values() if v is not None)}, indent=2))
        return

    # --apply
    for rel, content in files.items():
        target = DEFINITION / rel
        if content is None:
            if target.exists():
                if target.is_dir():
                    try:
                        shutil.rmtree(target)
                    except PermissionError:
                        esc = str(target).replace("'", "''")
                        subprocess.run(
                            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", f"Remove-Item -LiteralPath '{esc}' -Recurse -Force"],
                            check=True,
                        )
                else:
                    target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered(content), encoding="utf-8")
    print(json.dumps({"applied": True, "page": PAGE, "visuals": len(EXPECTED_VISUALS)}, indent=2))


if __name__ == "__main__":
    main()

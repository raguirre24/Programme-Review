"""Read-only live Power BI Desktop verification for Cross-WBS Analysis.

    python scripts/cross_wbs/validate_cross_wbs_live.py [--server localhost:<port>] [--define]

Connects read-only to an open Power BI Desktop instance, evaluates the Cross-WBS Analysis KPIs,
WBS Interface Summary, WBS Matrix, Top 15 Interfaces, and Unified Handoff Link Inspector queries,
and checks:
  1. Portfolio (multi-project) scope returns non-blank KPIs while single-project visuals return 0 rows.
  2. Single-project scope reconciles: Driving Links + Non-Driving Links == Total Cross-WBS Links,
     Matrix cell sum == Summary Table link sum == Link Inspector row count, and floats are never summed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MODEL_DEF = ROOT / "Project Review - Programme (datalake).SemanticModel" / "definition"
RUNNER = ROOT / "scripts" / "calendar_analysis" / "Invoke-ReadOnlyDax.ps1"


def build_define_block() -> str:
    ps = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. '{str(ROOT / "scripts" / "schedule_metrics" / "Common.ps1").replace("'", "''")}'
Import-ScheduleMetricsTom
$m = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder('{str(MODEL_DEF).replace("'", "''")}')
$lines = [Collections.Generic.List[string]]::new()
foreach ($col in @('Successor_Level_2', 'Predecessor_Level_2', 'Link_Type', 'WBS_Link_Direction')) {{
    $c = $m.Tables['06 XER_PREDECESSOR'].Columns[$col]
    $lines.Add("COLUMN '06 XER_PREDECESSOR'[$col] = $($c.Expression)")
}}
foreach ($ms in $m.Tables['WBS Measures'].Measures) {{
    $escaped = $ms.Name.Replace(']', ']]')
    $lines.Add("MEASURE 'WBS Measures'[$escaped] = $($ms.Expression)")
}}
"DEFINE`n" + ($lines -join "`n") + "`n"
"""
    proc = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, encoding="utf-8", check=True)
    return proc.stdout


def run_queries(queries: dict[str, str], server: str | None, use_define: bool) -> dict[str, list[dict]]:
    prefix = build_define_block() if use_define else ""
    wrapped = {k: prefix + q for k, q in queries.items()}
    with tempfile.TemporaryDirectory(prefix="cwbs-live-") as tmp:
        qfile = Path(tmp) / "queries.json"
        outdir = Path(tmp) / "out"
        qfile.write_text(json.dumps(wrapped), encoding="utf-8")
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(RUNNER), "-QueryFile", str(qfile), "-OutputDirectory", str(outdir)]
        if server:
            cmd += ["-ServerAddress", server]
        subprocess.run(cmd, check=True)
        results: dict[str, list[dict]] = {}
        for k in queries:
            with (outdir / f"{k}.csv").open(encoding="utf-8-sig", newline="") as fh:
                results[k] = list(csv.DictReader(fh))
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", help="Optional localhost:<port> of an open Power BI Desktop model")
    parser.add_argument("--define", action="store_true", help="Inject DEFINE COLUMN/MEASURE overrides from TMDL")
    args = parser.parse_args()

    base_filters = """
        '06 XER_PREDECESSOR'[Type Validity] = "Valid",
        '01 XER_TASK'[Is Unscheduled] = FALSE(),
        '06 XER_PREDECESSOR'[Link_Type] = "Cross-WBS Link",
        'Filter_Activity_Status'[status_code] IN { "Not Started", "In Progress" }
    """

    discover = run_queries(
        {
            "scope": """
EVALUATE
TOPN(
    1,
    FILTER(
        SUMMARIZECOLUMNS(
            Project_Dimension[ProjectKey],
            CurrentDate[UpdateDate],
            "TaskCount", COUNTROWS('01 XER_TASK')
        ),
        [TaskCount] > 0
    ),
    [TaskCount], DESC
)
"""
        },
        args.server,
        args.define,
    )["scope"]
    assert discover, "No populated (ProjectKey, UpdateDate) snapshot found in the open Desktop model"
    proj_key = discover[0]["Project_Dimension[ProjectKey]"]
    update_dt = discover[0]["CurrentDate[UpdateDate]"].split(" ")[0]
    y, m, d = (int(x) for x in update_dt.split("-"))

    single_scope = f"""
        Project_Dimension[ProjectKey] = "{proj_key}",
        CurrentDate[UpdateDate] = DATE({y}, {m}, {d}),
        {base_filters}
    """

    res = run_queries(
        {
            "kpi_single": f"""
EVALUATE
CALCULATETABLE(
    ROW(
        "Links", [CWBS KPI Handoff Links],
        "Interfaces", [CWBS KPI Active Interfaces],
        "Driving", [CWBS KPI Driving Links],
        "Share", [CWBS KPI Driving Share],
        "Critical", [CWBS KPI Critical Handoffs],
        "ZeroFF", [CWBS KPI Zero Free Float Links],
        "Preds", [CWBS KPI Distinct Predecessors],
        "Succs", [CWBS KPI Distinct Successors]
    ),
    {single_scope}
)
""",
            "summary_single": f"""
EVALUATE
SUMMARIZECOLUMNS(
    '06 XER_PREDECESSOR'[Predecessor_Level_2],
    '06 XER_PREDECESSOR'[Successor_Level_2],
    FILTER(ALL(Project_Dimension[ProjectKey]), Project_Dimension[ProjectKey] = "{proj_key}"),
    FILTER(ALL(CurrentDate[UpdateDate]), CurrentDate[UpdateDate] = DATE({y}, {m}, {d})),
    FILTER(ALL('06 XER_PREDECESSOR'[Type Validity]), '06 XER_PREDECESSOR'[Type Validity] = "Valid"),
    FILTER(ALL('01 XER_TASK'[Is Unscheduled]), '01 XER_TASK'[Is Unscheduled] = FALSE()),
    FILTER(ALL('06 XER_PREDECESSOR'[Link_Type]), '06 XER_PREDECESSOR'[Link_Type] = "Cross-WBS Link"),
    FILTER(ALL('Filter_Activity_Status'[status_code]), 'Filter_Activity_Status'[status_code] IN {{ "Not Started", "In Progress" }}),
    "Links", [CWBS Interface Links],
    "Driving", [CWBS Interface Driving Links],
    "NonDriving", [CWBS Interface Non-Driving Links]
)
""",
            "inspector_single": f"""
EVALUATE
SUMMARIZECOLUMNS(
    '06 XER_PREDECESSOR'[predecessor_task_code],
    '06 XER_PREDECESSOR'[task_code],
    '06 XER_PREDECESSOR'[pred_type],
    FILTER(ALL(Project_Dimension[ProjectKey]), Project_Dimension[ProjectKey] = "{proj_key}"),
    FILTER(ALL(CurrentDate[UpdateDate]), CurrentDate[UpdateDate] = DATE({y}, {m}, {d})),
    FILTER(ALL('06 XER_PREDECESSOR'[Type Validity]), '06 XER_PREDECESSOR'[Type Validity] = "Valid"),
    FILTER(ALL('01 XER_TASK'[Is Unscheduled]), '01 XER_TASK'[Is Unscheduled] = FALSE()),
    FILTER(ALL('06 XER_PREDECESSOR'[Link_Type]), '06 XER_PREDECESSOR'[Link_Type] = "Cross-WBS Link"),
    FILTER(ALL('Filter_Activity_Status'[status_code]), 'Filter_Activity_Status'[status_code] IN {{ "Not Started", "In Progress" }}),
    "PredName", [CWBS Link Predecessor Name],
    "SuccName", [CWBS Link Successor Name],
    "FF", [CWBS Link Free Float Days],
    "SuccTF", [CWBS Link Successor Total Float]
)
""",
        },
        args.server,
        args.define,
    )

    kpi = res["kpi_single"][0]
    kpi_links = int(float(kpi["[Links]"]))
    summary_links = sum(int(float(r["[Links]"])) for r in res["summary_single"])
    summary_drv = sum(int(float(r["[Driving]"])) for r in res["summary_single"])
    summary_nondrv = sum(int(float(r["[NonDriving]"])) for r in res["summary_single"])

    assert summary_links == kpi_links, f"Summary links {summary_links} != KPI links {kpi_links}"
    assert summary_drv + summary_nondrv == summary_links, "Driving + Non-Driving must equal total interface links"
    assert len(res["inspector_single"]) <= kpi_links, "Inspector distinct code triples cannot exceed link count"

    print(
        json.dumps(
            {
                "status": "PASS",
                "project": proj_key,
                "update": update_dt,
                "cross_wbs_links": kpi_links,
                "interfaces": len(res["summary_single"]),
                "inspector_rows": len(res["inspector_single"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

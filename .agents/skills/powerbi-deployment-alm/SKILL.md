---
name: powerbi-deployment-alm
description: Manage Power BI application lifecycle — PBIP projects, TMDL, git version control, deployment pipelines, XMLA endpoint, Tabular Editor, workspace strategy, and documentation. Use this skill whenever the user mentions version control for Power BI, PBIP/PBIX files, TMDL, deploying between dev/test/prod, deployment pipeline rules, Tabular Editor, XMLA, code review of models, CI/CD, or asks how a team should collaborate on reports. Use it also when generating or editing model definitions as code.
---

# Power BI Deployment & ALM

Treat semantic models and reports as code. The enabling technology is the **PBIP** project format with **TMDL** model definitions — plain-text, diffable, git-friendly. Everything else (pipelines, review, automation) builds on that.

## PBIP + TMDL

- Save as `.pbip` (Desktop: enable *Power BI Project save option* and *TMDL format* preview features if not default). Output structure:

```
MyReport.pbip
MyReport.SemanticModel/
  definition/
    model.tmdl
    tables/*.tmdl        # one file per table: columns, partitions (M), measures
    relationships.tmdl
    expressions.tmdl     # shared parameters/expressions
MyReport.Report/
  definition/            # PBIR: pages/visuals as individual JSON files
```

- TMDL is human-writable. Agents can safely edit measures, add columns, and adjust partitions directly in `tables/*.tmdl` — preserve indentation (tab-based hierarchy matters) and property casing.
- **PBIR** (report definition, JSON-per-visual) makes report diffs reviewable too; enable it. Without PBIR, report layout is a single opaque file.
- `.gitignore`: exclude `*.pbix`, cache folders (`.pbi/localSettings.json`, `cache.abf`). Commit the PBIP tree only — no data lives in it, which is exactly the point.

## Git workflow

- One PBIP per repo folder; branch per change; PR review reads TMDL diffs (measure changes, relationship changes are line-diffs).
- Merge conflicts in TMDL are resolvable by hand precisely because it's one-file-per-table — smaller blast radius than a monolithic model.bim, though model.bim (TMSL/JSON) remains valid for tooling that needs it.
- Fabric **git integration** can sync a workspace directly to Azure DevOps/GitHub branches: dev workspace ↔ dev branch. Combine with deployment pipelines: git feeds Dev, pipeline promotes Dev→Test→Prod. Don't let people edit Prod in the browser — promotion is the only path.

## Deployment pipelines

- Stages: Dev → Test → Prod. Promotion copies items and preserves stage-specific settings.
- **Deployment rules** rewrite data source values and **parameter values** per stage — this is why every connection component must be a parameter (see powerbi-data-connections). Rule pattern: `pEnvironment = "prod"`, `pS3Staging = s3://prod-athena-results/`, `pSiteUrl = …/sites/ProjectX`.
- First deployment to a stage creates items; rules must then be set before first refresh. Automate promotion via the pipelines REST API in CI when maturity warrants.
- Thin reports: keep the semantic model and reports as separate items; reports rebind to the promoted model per stage automatically within the pipeline.

## XMLA endpoint & external tools

- The XMLA read/write endpoint (Premium/Fabric capacities) lets external tools operate on published models: **Tabular Editor** (bulk measure edits, best-practice analyser, C# scripting), **DAX Studio** (profiling), **ALM Toolkit** (schema diff/deploy without touching data — deploy metadata while keeping partitions' data).
- Tabular Editor's **Best Practice Analyzer** with the standard rules set is an automatable code review: run it in CI against the model definition; fail the build on violations you care about (missing format strings, bidirectional relationships, unhidden key columns...).
- Changes deployed via XMLA mean the PBIX can no longer be downloaded — acceptable because the PBIP in git is the source of truth. Establish that rule before first XMLA write, not after.

## Workspace & content strategy

- Separate workspaces per stage; app audiences for consumption (users read the App, never the workspace).
- One **shared, endorsed semantic model** per subject area; many thin reports connect live to it. Copies of models per report is the primary cause of "numbers differ between reports".
- Naming: `[Project] [Area] [Stage]` consistently; contact set on every item; sensitivity labels where mandated.
- Service principals for automation (refresh triggering, pipeline promotion, scanner API) — not personal accounts.

## Automation surface (for CI/CD scripts and agents)

| Task | Mechanism |
|---|---|
| Trigger/monitor refresh | Power BI REST API (`datasets/{id}/refreshes`), or enhanced refresh API for per-table/partition control |
| Promote stages | Deployment pipelines REST API |
| Schema deploy | ALM Toolkit / Tabular Editor CLI over XMLA |
| Rule checks | Tabular Editor CLI + Best Practice Analyzer rules JSON |
| Inventory/lineage | Scanner (admin) APIs |
| Fabric items | Fabric REST APIs / fabric-cicd tooling |

## Documentation as a by-product

- Populate `description` on every table, column, measure in TMDL — it's diffable, reviewable, and surfaces in the Service and to Copilot/agents.
- Generate a data dictionary from the model programmatically (DAX Studio `INFO.` DMV queries, e.g. `EVALUATE INFO.MEASURES()`), or from the TMDL files directly, into markdown committed alongside the model. Regenerate in CI so docs never drift.

## Release checklist

1. BPA clean (or violations consciously waived in the rules file).
2. Refresh succeeds in Test with Test rules — including from-scratch (full) refresh, not just incremental.
3. RLS tested per role with "View as" and a real low-privilege account.
4. Deployment rules verified in each stage (open dataset settings, confirm parameter values).
5. Tag/release in git matching what was promoted to Prod.

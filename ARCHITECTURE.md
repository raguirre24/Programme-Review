# Workspace Architecture & AI Agent Developer Guide

This document describes the architectural layout, component interactions, data pipeline flow, and operational protocols for the **Programme Review (Datalake)** Power BI repository. 

> [!IMPORTANT]
> **AI AGENT MANDATORY UPDATE PROTOCOL**
> Any time an AI agent adds, modifies, refactors, or deletes any table, column, measure, report page, visual, script, or theme asset within this repository, **the AI agent MUST update this `ARCHITECTURE.md` file** so it remains 100% accurate and up to date.

---

## 1. High-Level Architecture Overview

This repository hosts a developer-mode Power BI Project (**PBIP**) that delivers Primavera P6 schedule and programme analytics built over an AWS Athena Data Lake backend.

```mermaid
flowchart TD
    subgraph Data Source Layer
        Athena[Amazon Athena Data Lake\n`primary_p6_bi_reporting`]
        P6[Primavera P6 XER Exports\n`prod_projectcontrols_p6`]
        SharePoint[SharePoint Online\nProgramme Review XER CSV bundles]
    end

    subgraph Semantic Model Layer TMDL
        MExpr[M Query Expressions\nAthena routing + validated CSV loader]
        Params[Eight required parameters\nportable source + project scope settings]
        Tables[Star Schema Tables & Dimensions\n`01 XER_TASK`, `03 XER_PROJWBS`, etc.]
        Measures[DAX Measure Tables\n`XER Measures`, `XER Counts`, `XER Metrics`]
        RLS[Role-Based Security\n`Project Access` RLS]
    end

    subgraph Report Layer PBIR
        ReportRoot[`Project Review - Programme (datalake).Report`]
        Pages[16 PBIR Report Pages]
        Bookmarks[Bookmarks JSON]
        Themes[JSON Theme Schemas\n`Contract_Theme.json`, `Target_Theme.json`]
        Backgrounds[Background Canvas Images\n`Contract.png`, `Target.png`]
    end

    subgraph Automation Scripts
        ThemeScript[`scripts/switch_theme.js`]
    end

    P6 --> Athena
    Athena -->|Native Query| MExpr
    Params --> MExpr
    SharePoint --> Tables
    MExpr --> Tables
    Tables --> Measures
    Tables --> RLS
    Measures --> Pages
    Themes --> ReportRoot
    Backgrounds --> ThemeScript
    ThemeScript -->|Inject Canvas BG| Pages
```

---

## 2. How This Works

### A. Data Source & Ingestion Layer
- **AWS Athena & Power Query M Integration**: Raw Primavera P6 schedule data (`.xer` file parses) resides in AWS Athena under database `primary_p6_bi_reporting` and schema `prod_projectcontrols_p6`.
- **Query Expressions (`expressions.tmdl`)**:
  - `AthenaDB`: Establishes native Amazon Athena database connection.
  - `AthenaScopeSql`: Constructs SQL queries dynamically, extracting baseline numbers (`BL[0-9]+`), revision tags, filtering files based on parameters, and excluding both C/J aliases of projects explicitly routed to CSV.
  - `fnAthenaSource`: Parameterised M function executing SQL against kept filenames in Athena.
  - `XerCsvTableContracts`: Version `2.0` ordered columns, logical types, nullability and key rules for the ten fallback tables.
  - `XerCsvSelectedBundles`: Navigates SharePoint with `SharePoint.Contents` through `Active/<PROJECT_CODE>/<bundle_id>`, validates each completed bundle against its parent project folder, ignores staging folders without a manifest, and selects the newest completed bundle for each routed project/programme pair.
  - `fnXerCsvReadBundle`, `fnXerCsvReadBundleTable`, and `XerCsvValidatedData`: Validate manifests, CSV syntax, types, source ownership, row counts, namespaced keys and referential integrity before any fallback rows are combined with Athena.
  - `XerCsvGovernanceValidation`: Requires every routed C/J-equivalent project to exist in both `dbo_project` and project-specific `dbo_userpermission` data. Manifest content never grants RLS access.
  - **Parameters**:
    - `AthenaDsn`: Amazon Athena connection DSN; default `primary_p6_bi_reporting`.
    - `SharePointSite`: Required SharePoint site-root URL used by both external assets and CSV loading.
    - `SelectedProjects`: Comma-separated list of project codes (e.g. `"C5064, C5001, C4007, C4017"`) or `"ALL"`.
    - `SelectedProgrammeType`: Programme type code (`"C"` for Contract, `"T"` for Target, or `"ALL"`).
    - `XerCsvEnabled`: Logical opt-in; current default `true`.
    - `XerCsvProjectCodes`: Comma-separated routed project codes; current default `C6036`. Do not enter both C and J aliases for the same project.
    - `XerCsvLibrary`: Document library name; default `Documents`. Set it to the exact name exposed by `SharePoint.Contents` for `SharePointSite`.
    - `XerCsvRootFolder`: Path below the library; default `P6/XER CSV/Active`.

#### SharePoint XER CSV fallback

- **Ownership rule**: CSV routing is project-level. When active, Athena excludes both C/J aliases of each routed project inside the native SQL scope; all ten imported XER tables then append the selected CSV bundle data. A project cannot be owned by both sources. Tables `04 XER_BASELINE` and `06a XER_SUCCESSOR` remain calculated model tables.
- **Inactive rule**: If `XerCsvEnabled = false` or `XerCsvProjectCodes` is blank, the loader returns typed empty tables and does not evaluate `SharePoint.Contents`. Stale CSV settings cannot block Athena-only refresh.
- **Folder contract**: `<XerCsvLibrary>/P6/XER CSV/Active/<PROJECT_CODE>/<PROJECT>_<C|T>_<yyyyMMddTHHmmssZ>_<hash8>/`. `SharePointSite` uses `Documents`, which is therefore the default `XerCsvLibrary`; if the selected site exposes a different connector name, set the library parameter to that exact name. Each project has its own exact uppercase parent folder, whose name must match `XerCsvProjectCodes` and manifest `project_code`; bundle CSVs must never be placed loose in that parent. Superseded bundles belong under `Archive/<PROJECT_CODE>/`. If `SelectedProgrammeType = ALL`, every routed project requires separate active C and T bundles beneath the same project folder. Every manifest-bearing child in `Active` is validated before newest-bundle selection, so malformed completed bundles must be removed or archived; manifest-free staging folders are ignored.
- **Required files**: `01_XER_TASK.csv`, `02_XER_PROJECT.csv`, `03_XER_PROJWBS.csv`, `06_XER_PREDECESSOR.csv`, `07_XER_ACTVTYPE.csv`, `08_XER_ACTVCODE.csv`, `09_XER_TASKACTV.csv`, `10_XER_CALENDAR.csv`, `12_XER_RSRC.csv`, `15_XER_RESOURCE_DISTRIBUTION.csv`, and `XER_CSV_MANIFEST.csv`. A completed bundle may contain no other files or child folders.
- **CSV format**: UTF-8, comma-delimited, RFC-style CSV quoting, one exact ordered header row, ISO `yyyy-MM-dd` dates, invariant numbers, and lowercase `true`/`false`. Header-only optional tables are valid. Conversion occurs only after raw-token validation.
- **Manifest contract**: Schema version `2.0`; one row for every canonical source XER × ten table names. Per-source metadata must be identical across its ten rows. The bundle contains exactly one baseline (`BLnn` with optional `-A` revision), unique snapshot tags, and updates tagged `YYMM`. Canonical names are `<PROJECT>-<C|T>-<TAG>_<YYYYMMDD>.xer`, with the suffix date equal to manifest `data_date`. The baseline effective `update_date` must match Athena exactly: start at the end of its `monthupdate`, then move backwards by month-end only while the candidate collides with a retained update, bounded to 240 shifts.
- **Key contract**: Every relationship key is `CSV::<bundle_id>::<canonical_xer_filename>::<native_id>`. The `::` separator is safe for DAX `PATH`; vertical pipe is reserved by `PATH` and is forbidden in generated keys. Keys on one row must share the same canonical source. Cross-snapshot historical matching remains project + `task_code`; never use `task_id` across snapshots.
- **Fail-loud checks**: Unsupported schema, incomplete files, invalid metadata, malformed tokens, duplicate dimension/relationship keys, row-count mismatch per source, wrong project ownership, mixed snapshot prefixes, missing governed projects/permissions, and broken project/WBS/task/code/calendar/resource references stop refresh.
- **Hash boundary**: The manifest must contain consistent 64-character SHA-256 values. The parser/publication workflow is responsible for computing and verifying the exact file hashes; standard Power Query M in this PBIP does not expose a supported general-purpose SHA-256 primitive, so refresh validates hash syntax/consistency but does not recompute file bytes.
- **Evaluation boundary**: Loading `01 XER_TASK` forces the full ten-table referential-integrity pass once; the other nine partitions read and validate only their own files. Power Query can still re-evaluate shared query dependencies, so validate SharePoint request volume with Query Diagnostics and Power BI Service refresh history before broad rollout.

#### Activation and refresh procedure

1. Generate and locally validate a complete version `2.0` bundle. Under `Active`, create the matching `<PROJECT_CODE>` parent and exact parser-generated `<bundle_id>` child. Upload the ten table CSVs first and `XER_CSV_MANIFEST.csv` last; folders without a manifest are ignored. Archive every version `1.0` manifest-bearing bundle before refresh because the version `2.0` loader validates all completed folders beneath `Active`.
2. Confirm the routed project (or its C/J alias) exists in `dbo_project` and has a project-specific entry in `dbo_userpermission`.
3. Confirm `AthenaDsn`, the single required `SharePointSite`, `XerCsvLibrary` and `XerCsvRootFolder`; then set `XerCsvProjectCodes` and enable `XerCsvEnabled`. Configure Athena and SharePoint Online credentials with `Organizational` privacy. A durable organisational/service account remains preferable for shared production refresh.
4. Reopen Power BI Desktop and run a full refresh. Verify Athena-only, CSV-only and mixed ownership, baseline/previous-period logic, network links, codes, calendars, resources and RLS **View as**.
5. Publish to a test workspace and verify scheduled refresh and a real low-privilege RLS account. SharePoint Online normally needs no on-premises gateway; retain the established Athena connection/gateway path.
6. To replace a bundle, upload a newer completed bundle beneath the same project folder, validate refresh, then move the older folder to `Archive/<PROJECT_CODE>`. To roll back, move the newest bundle to Archive, restore the required preceding completed bundle from `Archive/<PROJECT_CODE>` to `Active/<PROJECT_CODE>`, and refresh. See the [SharePoint CSV setup guide](SHAREPOINT_CSV_SETUP.md) for the full operating procedure.

### B. Semantic Model Layer (TMDL Format)
- Location: `Project Review - Programme (datalake).SemanticModel/definition/`
- **Format**: **TMDL** (Tabular Model Definition Language) - plain-text, source-controlled definitions.
- **Core Entity Tables**:
  - `01 XER_TASK`: Task activities, dates (`act_end_date`, `early_end_date`, `late_end_date`, `Finish`), duration, critical status, constraint types, variance categories.
  - `02 XER_PROJECT`: Project-level metadata and settings.
  - `03 XER_PROJWBS`: Work Breakdown Structure hierarchy.
  - `04 XER_BASELINE`: Baseline schedule snapshots for variance comparison.
  - `06 XER_PREDECESSOR` & `06a XER_SUCCESSOR`: Network logic links and dependencies.
  - `07 XER_ACTVTYPE`, `08 XER_ACTVCODE`, `09 XER_TASKACTV`: Activity code definitions and assignments.
  - `10 XER_CALENDARS`, `12_XER_RSRC`, `15_XER_RESOURCE_DISTRIBUTION`: Calendars, resource master, and resource distribution data.
  - `00 CALENDAR`, `00 PLANNED DATE TABLE (PV)`, `CurrentDate`, `Project_Dimension`: Dimension date tables and project lookup tables.
- **Measure Tables**:
  - `XER Measures`: Core DAX measures for task calculations.
  - `XER  Counts`: Task, milestone, constraint, and logic count metrics.
  - `XER Metrics`: Schedule health indicator metrics.
  - `XER S-Curve`: Cumulative baseline vs actual vs forecast curves.
  - `Dynamic Titles & Formatting`: Dynamic visual title strings and conditional formatting flags.
  - `WBS Measures` & `Activity Completion`: Dedicated WBS rollup and progress completion DAX.
- **Row-Level Security (RLS)**:
  - Role defined in `roles/Project Access.tmdl`. Filters `Project_Dimension` by evaluating UPN / email against `dbo_userpermission` for explicit project, state, or global permissions.

### C. Report Layer (PBIR Format)
- Location: `Project Review - Programme (datalake).Report/definition/`
- **Format**: **PBIR** (Power BI Report definition) - modern JSON-structured folder layout.
- **Page Management**:
  - `pages/pages.json` lists 16 report pages and sets active/landing page (`2cc544dc10a1e237ae90` - Home).
  - Each page folder contains `page.json` (page settings and canvas layout) and a `visuals/` subdirectory containing individual visual JSON definitions.
- **Bookmarks**:
  - `bookmarks/*.bookmark.json` defines interactive state bookmarks (navigational toggles, visual state snapshots).

### D. Visual Theme & Canvas Background Subsystem
- **Themes (`Themes/`)**: Contains custom theme JSON definitions (`Contract_Theme.json` and `Target_Theme.json`).
- **Backgrounds (`Backgrounds/`)**: Canvas background graphics (`Contract.png`, `Target.png`).
- **Theme Switcher Script (`scripts/switch_theme.js`)**:
  - Node.js script that parses all `page.json` files and injects the corresponding canvas background image (`Contract.png` or `Target.png`) with 0% transparency and `'Fill'` scaling.
  - Usage: `node scripts/switch_theme.js contract` or `node scripts/switch_theme.js target`.

### E. Direct PBIP Publication

- `Project Review - Programme (datalake).pbip` is the single working project for editing, refreshing and publishing. No deployment copy or preparation script is required.
- The root project has been cleared of prior `.pbi/localSettings.json` Service bindings. Its first publication is therefore workspace-independent: a destination without matching items creates new items, while a destination with exactly one matching report and semantic model can offer an explicit **Replace** operation.
- After a successful publication, Desktop may recreate ignored `localSettings.json` files in the same root project. This is expected and lets subsequent publications from that PBIP update the same target directly. These machine-local bindings are never committed.
- Continue only when Desktop explicitly offers **Replace** for the expected same-name pair. Never delete, recreate or manually rename the existing Service items during replacement.
- Record and then verify the report/model IDs, links, direct and Build access, RLS membership, app inclusion, audiences, refresh settings, gateway mapping, endorsement and labels.
- A PBIX saved from the root PBIP is an optional fallback. PBIX files, caches, credentials and local Service bindings are never committed.

---

## 3. Directory Map

```
Programme-Review/
├── AGENTS.md                                           # Repository-specific rules for AI agents
├── ARCHITECTURE.md                                     # System architecture & AI maintenance guide (this file)
├── SHAREPOINT_CSV_SETUP.md                             # SharePoint folders, credentials, refresh and rollback guide
├── Backgrounds/                                        # Canvas background images (Contract.png, Target.png)
├── Themes/                                             # JSON theme definitions (Contract_Theme.json, Target_Theme.json)
├── scripts/                                            # Automation scripts
│   └── switch_theme.js                                 # Script to switch page canvas background images
├── Project Review - Programme (datalake).pbip          # Root Power BI Project declaration file
├── Project Review - Programme (datalake).SemanticModel/# TMDL Semantic Model root
│   ├── definition.pbism                                # Semantic Model metadata
│   ├── diagramLayout.json                              # Model diagram visual layout configuration
│   └── definition/                                     # TMDL model definition folder
│       ├── model.tmdl                                  # Model declaration & table/role references
│       ├── database.tmdl                               # Database declaration
│       ├── expressions.tmdl                            # Power Query M parameters & queries (Athena)
│       ├── relationships.tmdl                          # Model table relationships
│       ├── cultures/                                   # Locale definition (en-NZ)
│       ├── roles/                                      # Row-Level Security definitions (Project Access.tmdl)
│       └── tables/                                     # TMDL table & measure files (41 TMDL files)
└── Project Review - Programme (datalake).Report/       # PBIR Report root
    ├── definition.pbir                                 # Report metadata pointing to SemanticModel
    ├── CustomVisuals/                                  # Custom visual packages
    ├── StaticResources/                                # Embedded image resources
    └── definition/                                     # PBIR report definition folder
        ├── report.json                                 # Global report settings & theme bindings
        ├── version.json                                # PBIR format version
        ├── bookmarks/                                  # Report bookmark JSON files
        └── pages/                                      # 16 Report pages (page.json & visual folders)
```

---

## 4. AI Coding Agent Rules & Maintenance Protocol

When modifying this repository, any AI coding agent **MUST** adhere to the following rules:

### 1. Always Keep `ARCHITECTURE.md` Updated
- **Requirement**: If you add, remove, rename, or re-architect any dataset, table, measure, column, query parameter, report page, script, or theme asset, you **must update this document (`ARCHITECTURE.md`)** in the same task before declaring completion.

### 2. Git Status Discipline
- Run `git status --short` **before** making changes to inspect dirty states.
- Run `git status --short` **after** making changes to confirm exact modified/untracked files.

### 3. Safety for PBIP, TMDL, and PBIR Files
- Treat `.pbip`, `.SemanticModel`, `.Report`, TMDL, and PBIR files as source-controlled code files.
- **Do not edit or commit** `.pbi/cache.abf`, `.pbi/localSettings.json`, `.pbi/unappliedChanges.json`, or `.pbix` binaries. Desktop may recreate local Service bindings after publication; keep them ignored and use the normal root PBIP for subsequent updates to that target.
- Preserve table/column lineage tags, relationship IDs, page GUIDs, visual names, and TMDL structure.
- Perform impact checks (check DAX measures, relationships, and PBIR report visuals) before deleting or renaming any column or measure.

### 4. Language & Prose Standard
- Use **New Zealand English** (`en-NZ`) for user-facing text, documentation, and comments (e.g. *programme*, *organisation*, *colour*).

### 5. Post-Edit User Notification
- Whenever TMDL semantic model or PBIR report files are modified, inform the user to **reopen or restart Power BI Desktop** to reload updated files.

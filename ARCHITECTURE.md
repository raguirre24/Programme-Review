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
  - `XerCsvTableContracts`: Ordered columns, types, nullability and key rules for the ten fallback tables. New bundles use schema `3.0`; the loader remains compatible with schemas `1.0` and `2.0` during migration or rollback.
  - `XerCsvSelectedBundles`: Navigates SharePoint with `SharePoint.Contents` through `Active/<PROJECT_CODE>/<bundle_id>`, ignores manifest-free staging folders, validates the bundle-name timestamp before reading any manifest, and selects the newest project/programme folder.
  - `fnXerCsvReadBundle` and `XerCsvSelectedManifest`: Read and validate only the selected small manifest. The result is loaded once into the hidden `XER CSV Manifest` audit table.
  - `fnXerCsvReadBundleTable`: Streams one corresponding CSV per imported XER table and converts schema `1.0`/`2.0` keys to the compact schema `3.0` model grammar during the same row conversion. Large CSV binaries and tables are not buffered.
  - `XER CSV Refresh Audit`: Hidden calculated table that fails refresh through `ERROR()` for manifest/model row-count mismatch, Athena/CSV ownership overlap, or a routed project missing from `dbo_project` or `dbo_userpermission`. Manifest content never grants RLS access.
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

- **Ownership rule**: CSV routing is project-level. When active, Athena excludes both C/J aliases of each routed project inside the native SQL scope; all ten imported XER tables then append the selected CSV bundle data. A project cannot be owned by both sources. When a finite `SelectedProjects` list is entirely CSV-owned, all ten XER Athena branches return typed empty tables without opening `AthenaDB`; governed RLS tables remain Athena-authoritative. Tables `04 XER_BASELINE` and `06a XER_SUCCESSOR` remain calculated model tables.
- **Inactive rule**: If `XerCsvEnabled = false` or `XerCsvProjectCodes` is blank, the loader returns typed empty tables and does not evaluate `SharePoint.Contents`. Stale CSV settings cannot block Athena-only refresh.
- **Folder contract**: `<XerCsvLibrary>/P6/XER CSV/Active/<PROJECT_CODE>/<PROJECT>_<C|T>_<yyyyMMddTHHmmssZ>_<hash8>/`. `SharePointSite` uses `Documents`, which is therefore the default `XerCsvLibrary`; if the selected site exposes a different connector name, set the library parameter to that exact name. Each project has its own exact uppercase parent folder, whose name must match `XerCsvProjectCodes` and manifest `project_code`; bundle CSVs must never be placed loose in that parent. Superseded bundles belong under `Archive/<PROJECT_CODE>/`. If `SelectedProgrammeType = ALL`, every routed project requires separate active C and T bundles beneath the same project folder. Manifest-free staging folders are ignored. The contract-valid `bundle_id` timestamp selects the newest folder first, and only that folder's manifest is opened and validated.
- **Required files**: `01_XER_TASK.csv`, `02_XER_PROJECT.csv`, `03_XER_PROJWBS.csv`, `06_XER_PREDECESSOR.csv`, `07_XER_ACTVTYPE.csv`, `08_XER_ACTVCODE.csv`, `09_XER_TASKACTV.csv`, `10_XER_CALENDAR.csv`, `12_XER_RSRC.csv`, `15_XER_RESOURCE_DISTRIBUTION.csv`, and `XER_CSV_MANIFEST.csv`. A completed bundle may contain no other files or child folders.
- **CSV format**: UTF-8, comma-delimited, RFC-style CSV quoting, one exact ordered header row, ISO `yyyy-MM-dd` dates, invariant numbers, and lowercase `true`/`false`. Header-only optional tables are valid. Each data file uses one streaming conversion that validates its raw tokens while assigning model types.
- **Manifest contract**: New publication uses schema `3.0`; schemas `1.0`, `2.0` and `3.0` are load-compatible, with v1/v2 retained only for migration and rollback. The manifest has one row for every canonical source XER × ten table names. Per-source metadata must be identical across its ten rows. The bundle contains exactly one baseline (`BLnn` with optional `-A` revision), unique snapshot tags, and updates tagged `YYMM`. Canonical names are `<PROJECT>-<C|T>-<TAG>_<YYYYMMDD>.xer`, with the suffix date equal to manifest `data_date`. Selected rows are imported into hidden `XER CSV Manifest` and reconciled after import.
- **Compact key contract**: Schema `3.0` relationship keys use `CSV::<project_code>::<programme_type>::<snapshot_tag>::<native_id>`. During its single row conversion, the loader converts schema `1.0` keys (`CSV|<bundle_id>|<canonical_xer_filename>.<native_id>`) and schema `2.0` keys (`CSV::<bundle_id>::<canonical_xer_filename>::<native_id>`) to that same compact model grammar. The `::` delimiter is intentional: DAX `PATH` reserves vertical pipe and fails when an identifier contains `|`. Snapshot tags must be unique within a project/programme history. Cross-snapshot historical matching remains project + `task_code`; never use `task_id` across snapshots.
- **Source marker**: Each of the ten imported XER tables has a hidden Boolean `IsCsvSource`; it is `true` for SharePoint rows and `false` for Athena rows. It supports refresh auditing and diagnostics and does not replace governed RLS.
- **Validation boundary**: The parser is authoritative for SHA-256 computation, duplicate-key detection and complete project/WBS/task/code/calendar/resource referential integrity before it writes `bundle_status=complete`. Power Query independently validates the selected folder/manifest identity, supported schema, exact files and headers, required values, strict tokens, types, project ownership and compact key syntax. `XER CSV Refresh Audit` reconciles model row counts, ownership and governance. Power BI no longer rereads all ten CSVs through `01 XER_TASK` to repeat parser validation.
- **Evaluation boundary**: Every imported table streams only its corresponding CSV. Do not add `Table.Buffer` or large-table `Binary.Buffer`; buffers cannot share a cache between loaded Power BI queries and increase concurrent memory. `Binary.Buffer` is retained only for the selected small manifest.
- **Model-memory changes**: `Resource Calendar` derives its bounds from scalar minima/maxima instead of materialising a union of all resource rows. `06a XER_SUCCESSOR[Free Float]` is projected directly from `06 XER_PREDECESSOR`, and the near-unique `task_pred_id_key` is omitted from both stored model tables while remaining in the CSV file contract for parser validation.
- **Conditional future work**: Separate physical Athena/CSV partitions, aggregation or upstream `monthly_hours` changes for `15_XER_RESOURCE_DISTRIBUTION`, and upstream predecessor enrichment are not implemented. They require live VertiPaq/processing evidence, Desktop reopen/save proof and a matched Service result before adoption. The broader unused-column candidates remain stored until external thin-report/lineage dependencies are confirmed; only the specifically refactored `task_pred_id_key` has been removed and its local linguistic metadata cleaned.

#### Activation and refresh procedure

1. Generate and locally validate a complete schema `3.0` bundle. Under `Active`, create the matching `<PROJECT_CODE>` parent and exact parser-generated `<bundle_id>` child. Upload the ten table CSVs first and `XER_CSV_MANIFEST.csv` last; folders without a manifest are ignored. Schemas `1.0` and `2.0` remain usable for migration or rollback, but do not create new v1/v2 bundles.
2. Confirm the routed project (or its C/J alias) exists in `dbo_project` and has a project-specific entry in `dbo_userpermission`.
3. Confirm `AthenaDsn`, the single required `SharePointSite`, `XerCsvLibrary` and `XerCsvRootFolder`; then set `XerCsvProjectCodes` and enable `XerCsvEnabled`. Configure Athena and SharePoint Online credentials with `Organizational` privacy. A durable organisational/service account remains preferable for shared production refresh.
4. Reopen Power BI Desktop and run a full refresh. Verify `IsCsvSource`, compact keys, hidden manifest/audit reconciliation, Athena-only, CSV-only and mixed ownership, baseline/previous-period logic, network links, codes, calendars, resources and RLS **View as**.
5. Publish to a test workspace, verify scheduled refresh and a real low-privilege RLS account, then run the matched performance experiment below. SharePoint Online normally needs no on-premises gateway; retain the established Athena connection/gateway path.
6. To replace a bundle, upload a newer completed v3 bundle beneath the same project folder, validate refresh, then move the older folder to `Archive/<PROJECT_CODE>`. To roll back, move the newest bundle to Archive, restore the required preceding completed v1, v2 or v3 bundle from `Archive/<PROJECT_CODE>` to `Active/<PROJECT_CODE>`, and refresh. See the [SharePoint CSV setup guide](SHAREPOINT_CSV_SETUP.md) for the full operating procedure.

#### Refresh-performance acceptance

- Use the same Service capacity, parameters, bundles, credentials and comparable time window for every control. Use the median of two completed runs for CSV disabled, the active legacy v1/v2 compatibility path, and schema v3 loading.
- Where enhanced refresh is available, test transactional refresh with `maxParallelism` 6, 3 and 2. Capture wall duration, cumulative external-query time, total and M-engine CPU, total and M-engine peak memory, effective parallelism, VertiPaq rows, capacity throttling, data-source connection throttling and Athena query history. External-query time is cumulative across concurrent requests and can exceed wall time.
- Functional acceptance requires identical business row counts and values, no increase in VertiPaq rows, no audit error, one table-data read per CSV table/bundle, one selected-manifest validation and zero heavy XER Athena queries when every selected project is CSV-owned.
- Performance minimum: median wall duration no more than **40 minutes**. Target: **25 minutes or less**. M-engine peak no more than **0.938 GiB**. Total peak no more than **7.5 GiB**, with at least **20%** capacity headroom.
- Use `maxParallelism = 3` when it lowers peak memory by at least 15% with no more than a 10% wall-time penalty; otherwise retain the fastest setting that satisfies the memory and duration limits.

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
│       └── tables/                                     # TMDL table & measure files (43 TMDL files)
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

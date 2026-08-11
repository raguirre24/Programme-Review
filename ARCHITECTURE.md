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
        SharePoint[SharePoint Folder]
    end

    subgraph Semantic Model Layer TMDL
        MExpr[M Query Expressions\n`AthenaScopeSql` / `fnAthenaSource`]
        Params[Parameters\n`SelectedProjects`, `SelectedProgrammeType`]
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
  - `AthenaScopeSql`: Constructs SQL queries dynamically, extracting baseline numbers (`BL[0-9]+`), revision tags, and filtering files based on parameters.
  - `fnAthenaSource`: Parameterised M function executing SQL against kept filenames in Athena.
  - **Parameters**:
    - `SelectedProjects`: Comma-separated list of project codes (e.g. `"C5064, C5001, C4007, C4017"`) or `"ALL"`.
    - `SelectedProgrammeType`: Programme type code (`"C"` for Contract, `"T"` for Target, or `"ALL"`).
    - `SharePointSite`: Base SharePoint tenant URL for external asset references.

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

---

## 3. Directory Map

```
Programme-Review/
├── AGENTS.md                                           # Repository-specific rules for AI agents
├── ARCHITECTURE.md                                     # System architecture & AI maintenance guide (this file)
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
- **Do not edit** `.pbi/cache.abf`, `.pbi/localSettings.json`, `.pbi/unappliedChanges.json`, or `.pbix` binaries.
- Preserve table/column lineage tags, relationship IDs, page GUIDs, visual names, and TMDL structure.
- Perform impact checks (check DAX measures, relationships, and PBIR report visuals) before deleting or renaming any column or measure.

### 4. Language & Prose Standard
- Use **New Zealand English** (`en-NZ`) for user-facing text, documentation, and comments (e.g. *programme*, *organisation*, *colour*).

### 5. Post-Edit User Notification
- Whenever TMDL semantic model or PBIR report files are modified, inform the user to **reopen or restart Power BI Desktop** to reload updated files.

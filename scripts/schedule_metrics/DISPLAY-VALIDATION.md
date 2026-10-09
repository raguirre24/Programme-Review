# Schedule Metrics display validation — 9 October 2026

This note covers the existing **Sched. Metrics** page (`327b48a7fbd37ce0a51c`). It supplements [VALIDATION.md](VALIDATION.md); it does not replace its fixture, source-data or implementation evidence.

## Evidence boundaries

- **Saved report:** PBIR bindings, formats, bounds, filters, interactions and themes were inspected read-only. This establishes the saved configuration, not native rendering.
- **Loaded engine:** direct queries execute the model currently open in Desktop, without `DEFINE` overrides. Loaded/source expression and format parity is checked separately from numeric results.
- **Native Desktop:** the observations below were reported by the agent operating the user's open report. They cover the specific selections listed, not every possible report state or Power BI Service.

## Saved visual contracts

Core gauges use the listed base measure; their trends use the corresponding `(History)` measure. Gauge ranges are 0–1, colours come from the matching `SM … Colour` measure, and scope/coverage tooltips use the base or history context as appropriate.

| Metric | Gauge/card ID | Trend ID | Threshold |
| --- | --- | --- | --- |
| Checks passed (`Score`) | `81ad6771956ff5d1741f` | `c7f71fd2e347b3f85c92` | 100% of assessed checks |
| High float (`HighFloat%`) | `b472a4a2b0c50d6843ad` | `5a2ca16ab3096b524ccb` | ≤5% |
| Remaining duration (`HighDur%`, custom) | `29dd3e330552106c9b85` | `1cf588a229dd59ca0e55` | ≤5% |
| Leads (`<0Lead%`) | `64e14883854f7dfd70e3` | `79bb4d5993a6dc7f341d` | 0% |
| Positive lags (`Lags%`) | `66513b4afb7936ff6cfa` | `065aedc35dcac483ea63` | ≤5% |
| Missing logic (`SM Missing Logic %`) | `fc91b5bc44861bc3d9f6` | `befe996cf56ab1546db0` | ≤5% |
| FS relationships (`SM FS %`) | `272d935767d0a0cc930b` | `6ec723c640b6070ba15c` | ≥90% |
| Negative float (`<0Float%`) | `f87943c254f5cb251cb1` | `919fb0fbb7f910fb47b9` | 0% |
| Restrictive primary constraints (`Constraint%`) | `7430c5bc4cbe2ea53c87` | `b07222b4891891cf9403` | ≤5% |
| Date integrity (`SM Invalid Dates %`, custom) | `5d4f7a931da26bc6e9cd` | `75e5b6a1363cfb051068` | 0% |
| Selected detail (`SM Detail Value` / `SM Detail History`) | `61d63f208032a370fe3e` | `1347775f9312f8fbf095` | Dynamic; below |

The visible score coverage card `70df662118bf4276a18e` binds `SM Score Status`. The detail selector `b619bdaf7bac4917bfef` binds `Schedule Metric Detail[Metric]`, sorted by `[Metric ID]`, and filters only the detail gauge and trend. Its saved default is **Missed dates (matched)**; no conflicting Metric ID filter exists.

| Detail selection | ID | Dynamic format | Gauge target | Gauge maximum |
| --- | ---: | --- | ---: | --- |
| Missed dates (matched) | 1 | `0.0%` | 5% | 1 |
| Execution index (matched) | 2 | `0.00` | 0.95 | `MAX(1, value)` |
| Baseline coverage | 3 | `0.0%` | 100% | 1 |
| Longest-path share | 4 | `0.0%` | None | 1 |

All 11 trends have automatic Y-axis bounds, categorical `UpdateHistory[UpdateDate]` axes, ascending order and `showAll=true`. Core labels use one decimal; detail labels inherit the dynamic format. Neither the saved visual nor its theme imposes a percentage format or a fixed upper bound on the execution-index trend. Categorical dates have equal update spacing, rather than elapsed-day spacing.

Each core trend filters `SM History In Scope=1`; the detail trend filters `SM Detail History In Scope=1`. These retain existing project/programme snapshots up to the selected cutoff independently of missing metric inputs. They do not filter on the displayed metric being nonblank.

The date slicer filters all 24 metric/card/table visuals. The table cannot filter the other 23 metric visuals. All 674 explicit interaction pairs are unique and reference existing visuals. The two project-menu bookmarks suppress data and do not alter the detail selector or charts.

The counts table `58fbc09d197fe53515d8` uses `01 XER_TASK[UpdateDate]` and base measures, preserving drill-through field identities. Native inspection showed historical rows for all available updates, not only the selected update. It uses the corrected restrictive-primary and positive-lag counts and includes logic, FS, date-integrity and whole-project baseline-coverage columns. Its only visual filter is nonblank `Task_Count`. Horizontal scrolling was checked in both projects; the visible snapshot rows agreed with the corresponding gauges and rounded trend labels, including populated Malabar FS values in April–July.

Page filters remain incomplete statuses and Activity/Milestone classification. Report filters remain `Is Unscheduled=false` and `IsExcludedFromDataLake=false`; the metric measures rebuild their documented populations while retaining the governance exclusion. Detail measures use whole-project scope. These are different from the preserved drill-through target behaviour described in [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Direct loaded-engine evidence

The initial direct-loaded core suite, before the cutoff helper was added, passed with no `DEFINE` overrides: all **70 loaded measures** matched disk expressions, formats and lineage; **16 snapshots**, **224 base/history comparisons**, **eight earlier cutoffs**, **160 colour checks**, **112 tooltip ratios**, **16 score labels** and **64 history scope/tooltip checks** passed. Missing snapshots returned BLANK. The latest scores were **J5064 33.33% (3/9)** and **J4007 66.67% (6/9)**. Partial months returned the expected amber colours and coverage labels.

Expected core engine values are percentages, rounded here to two decimals. The initial suite used task project/programme filters and available cutoffs. The separate `Project_Dimension`/unavailable-cutoff defect was subsequently reproduced, corrected and validated as described below; the initial suite alone did not cover that case.

| Metric | J5064 Sep 2026 | J5064 Mar 2026 | J4007 Aug 2026 |
| --- | ---: | ---: | ---: |
| High float | 48.91 | 61.69 | 61.94 |
| Remaining duration | 3.67 | 3.09 | 3.34 |
| Leads | 0.06 | 0.07 | 0.00 |
| Positive lags | 7.03 | 7.37 | 5.73 |
| Missing logic | 0.57 | 0.15 | 0.00 |
| FS relationships | 83.02 | 81.16 | 81.99 |
| Restrictive primary constraints | 0.00 | 0.01 | 0.00 |
| Negative float | 24.03 | 8.05 | 0.00 |
| Date integrity | 0.02 | 0.46 | 0.00 |
| Checks passed | 33.33 | 33.33 | 66.67 |
| Partial check count | 0 | 3 | 0 |

Score status is respectively **3/9 passed**, **3/9 passed | partial inputs**, and **6/9 passed**. At their latest cutoffs all nine core metrics and Score have 11/11 numeric J5064 points and 5/5 J4007 points; the March cutoff retains five J5064 points.

Direct loaded-engine execution-index queries using the exact selector label **Execution index (matched)** returned all 11 J5064 monthly values, each with history scope 1. Displayed to two decimals, November 2025–September 2026 is:

`1.00, 0.54, 0.38, 0.44, 0.78, 0.72, 0.90, 0.86, 0.85, 0.80, 0.80`.

All 42 loaded detail expressions and static/dynamic formats matched disk at that check. These results establish that the engine supplied the missing execution-index points; they do not establish that the visual had re-rendered them.

The complete direct detail runner passed **1,431 assertions**: all **64 gauge selections** agreed under label-only, ID-only and combined selector filters, and **324 history cells across every cutoff** matched their corresponding gauges. Each of the four selectors returned all **11 Malabar / J5064** and **five Alkimos / J4007** points. No calculation, selector or scope mismatch was found.

Expected detail values from the saved direct-loaded outputs:

| Detail metric | J5064 Sep 2026 | J5064 Mar 2026 | J4007 Aug 2026 |
| --- | ---: | ---: | ---: |
| Missed dates | 71.2% | 76.5% | 39.4% |
| Execution index | 0.80 | 0.78 | 0.81 |
| Baseline coverage | 81.6% | 93.2% | 82.2% |
| Longest-path share | 3.0% | 1.9% | 2.9% |
| Points through cutoff, each selector | 11 | 5 | 5 |

September J5064 missed dates and execution index returned red (`#6f0516`) in the captured engine result. The native observations below independently establish the colours for all tested detail selections, including the partial-input amber execution index in March.

## Native observations

All observations below were made in the user's open Desktop report. Each detail row covers all four dropdown choices in order: missed dates, execution index, baseline coverage and longest-path share.

| Scenario | Native result |
| --- | --- |
| Malabar / J5064, September 2026, core page | All nine core gauges and Score agreed with the engine values. Every core trend showed all **11** November–September points after visual refresh. |
| Malabar, September, all detail choices | **71.2% red**, **0.80 red**, **81.6% amber**, **3.0% blue**; each trend had **11** points. |
| Execution-index cached display | Initially BLANK with only four history points. **Optimize > Refresh visuals** restored **0.80** and all **11** points. |
| Malabar, March 2026, core page | All nine core gauges and Score agreed with the engine values. Trends stopped at March with **five** points. High float, negative float and remaining duration were amber; Score showed **3/9 passed \| partial inputs**. |
| Malabar, March, all detail choices | **76.5% red**, **0.78 amber**, **93.2% amber**, **1.9% blue**; each trend had **five** November–March points. |
| Return from March to September | September baseline coverage returned to **81.6%** and all **11** core history points returned without another visual refresh. |
| Alkimos / J4007, August 2026, core page | All nine core gauges and Score agreed with the engine values. Every core trend showed the **five** actual update months: February, May, June, July and August. |
| Alkimos, August, all detail choices | **39.4% red**, **0.81 red**, **82.2% amber**, **2.9% blue**; each trend had **five** points. |
| Alkimos while September remains selected, after cutoff fix | All **10 core/score trends** retained the five actual past updates. Current September gauges remained **BLANK/grey**, correctly reflecting the absent snapshot. The detail execution trend also retained its five past points. |
| Final return to Malabar, September | Execution index returned to **0.80** with all **11** history points. |
| Counts table | Horizontal scrolling in both projects confirmed populated FS, logic, date-integrity and baseline-coverage columns. Corresponding monthly values agreed with gauges/trend labels; Malabar April–July FS rows had no holes. |
| High-float history tooltip | With September selected, hovering March showed **4,137 / 6,706 = 61.69%** and **10 excluded float records** and **10 excluded duration records**. |
| Execution-index history tooltip | Hovering March showed **312 / 402 = 0.78**, **20 excluded of 6,602 matched activities**, **three excluded of 405 due activities**, and a partial-input warning. The tooltip correctly showed data date **25 March** and update date **31 March**. |

## Two distinct display issues and their resolution

**Cached visual results.** The correct model and updated report were loaded, and direct engine queries already returned the complete series, while the current visual or a previously selected detail option still showed older results. **Optimize > Refresh visuals** restored those displays. This was a visual-query refresh, not a source-data refresh, and that issue required no model/source changes.

**Unavailable-cutoff calculation defect.** Switching from Malabar to Alkimos while keeping September selected exposed a separate reproducible DAX bug. Alkimos has no September snapshot. Its project filter propagated through the bidirectional task relationship, making `MAX(CurrentDate[UpdateDate])` BLANK; every core history and its scope helper then became BLANK. Refresh visuals did not correct this case. Detail history already preserved the explicit cutoff and remained visible.

The fix adds hidden **`SM Selected History Cutoff`**, which reads the maximum explicitly selected date from `FILTERS(CurrentDate[UpdateDate])` when that column is directly filtered, retaining the previous `MAX` fallback otherwise. Sixteen existing history/tooltip/scope expressions now use it. Current-snapshot gauge definitions were unchanged, so an absent September snapshot still produces unavailable gauges while the available earlier history remains visible.

The initial 70-measure suite must be distinguished from this final evidence:

- All **71 current source/live core measures** passed parity checks for expressions, formats, lineage, descriptions, display folders and visibility.
- The post-application [Test-History-Cutoff.ps1](Test-History-Cutoff.ps1) run with **`-UseLoadedModel`**, and no `DEFINE` overrides, passed **862 assertions**, **630 history cells** and **eight cases** using the actual `Project_Dimension` filters. It covered all 16 snapshots, all 14 rate histories, tooltip/scope helpers, unavailable September, earlier and multiple selected cutoffs, and the no-explicit-cutoff fallback. Gauges were unchanged.
- The earlier **160 colour checks**, **112 tooltip-ratio checks** and **16 score-label checks** remain evidence for unchanged base expressions; they are not presented as a rerun of the full initial suite after adding the helper.
- Native Desktop then confirmed the repaired Alkimos/September case and the return to Malabar/September, as recorded above.

The cutoff fix was applied narrowly to the loaded model through TOM: **16 existing expressions plus one new helper**, with exact preimage checks and a backup. This was an explicit live-model write during validation. No source refresh, Desktop save, report-definition edit, publication or unrelated/global model change was performed for that correction.

## Validation limits

This validation is complete for the selections and observations listed above. Drill-through was **not newly exercised in native Desktop** during this pass; its saved bindings, retained scope and earlier static evidence remain documented in [IMPLEMENTATION.md](IMPLEMENTATION.md) and [VALIDATION.md](VALIDATION.md). Power BI Service, RLS impersonation, export, reopening/persistence and exhaustive report states were outside this display-validation scope.

Reusable direct-load checks are [Validate-Live.ps1](Validate-Live.ps1) (`-UseLoadedModel`), [Validate-Detail-Loaded.ps1](Validate-Detail-Loaded.ps1), and [Test-History-Cutoff.ps1](Test-History-Cutoff.ps1) (`-UseLoadedModel`).

## In-report metric guide acceptance — 9 October 2026

Added a **Metric guide** button to the existing Schedule Metrics page. It opens
a native, scrollable reference table on the same page: 19 rows covering the nine
scored checks, overall score, four detail options and five supporting counts.
Each row states its meaning/calculation, target/score treatment and scope/limits.
The guide also explains colours, partial inputs, tooltips and trend cutoffs.

The guide adds one disconnected constant table, seven visuals and two
display-only bookmarks. The existing 49 visual files/positions and both core
and detail measure files were unchanged by this guide addition, verified against
the pre-guide source backup. Both existing project-menu bookmarks now explicitly
control all 56 page visuals, independently of the guide, with data capture
suppressed. A previously unsaved date-slicer-to-summary-table `NoFilter`
interaction was recovered and preserved.

Validation performed:

- Full TMDL deserialisation succeeded. Direct queries against the loaded main
  report confirmed all 19 guide rows, source/content parity and no relationships
  to the guide table. `Validate-Guide.ps1` passed again after final reload.
- Static page checks passed for 56 visuals, all 11 history/base pairs and all
  11 gap-safe trends. The existing WBS field-reference warning remains unrelated.
- All four affected bookmarks have matching, unique targets/states for all
  56 visuals, `applyOnlyToTargetVisuals = true`, and `suppressData = true`.
  Repeating the builder changed zero bytes across 518 inspected files.
- Native Desktop confirmed the visible red opener, white guide panel, wrapped
  four-column table, scrolling through every row, pinned heading/footer and
  working Close guide button. No new page or chart rearrangement was required.
- Opening and closing the guide retained Malabar / September 2026 and the
  selected execution index of **0.80**, with all **11** trend points. The project
  menu was tested before and after the guide; the final full-state project
  bookmarks were reloaded and their open/close actions verified again.
- The final report was left on Schedule Metrics, Malabar / September 2026,
  Missed dates **71.2%**, with the guide closed and its button visible.

Native tests used Desktop edit mode (Ctrl+Enter on the selected action button;
Ctrl+click is the usual mouse equivalent). Service reading mode, screen-reader
navigation, exports and direct transitions from the Bookmarks pane were not
newly tested. The latter transition is covered by explicit static visibility
state checks, not claimed as native evidence. `git diff --check` passed.

Before reload, the open report was saved as a recovery project at
`../.sg-9f22/R.pbip`, and its original on-disk definitions were archived at
`../.sg-9f22/source-before-guide.zip`. The recovery window remains available.
Source refresh and publication were not performed. Automatic approval review
blocked cleanup of the separate failed long-path recovery folder, which was
left untouched.

### Guide wording revision

The guide now leads with each metric's meaning, practical rationale, calculation
and interpretation. Repeated DCMA classifications and compliance comparisons
were removed from reader-facing text. All 19 rows include a concise
**Why it matters** explanation; numerical thresholds, scoring and metric
calculations remain unchanged.

Before reloading, the open report was preserved at `../.sgw-a23c/R.pbip`.
Comparison found no non-guide model changes or report binding/interaction
changes. The three native guide column-sizing settings were preserved.
Only the guide table content, introduction text and those sizing settings
changed in the model/report definitions during this revision.

Full TMDL deserialisation, scoped static validation, `git diff --check` and
`Validate-Guide.ps1` passed. Direct queries confirmed 19 loaded rows, all with
rationales and none with DCMA references. Native Desktop confirmed the revised
introduction and wrapped table fit the existing page. The revised guide was
left open for review, with Malabar / September 2026 retained.

## Drill-through repair and acceptance — 9 October 2026

[DRILLTHROUGH-VALIDATION.md](DRILLTHROUGH-VALIDATION.md) records the subsequent
repair and acceptance of all three metric-detail routes. It supersedes this
document's earlier global `Is Unscheduled=false` description and statement
that native drill-through was not newly exercised: the exclusion now resides
on the 12 normal pages, with Schedule Metrics and its three targets exempt.

The final full loaded-model run passed **118,899 assertions**, including all
**48 route comparisons across 16 snapshots**, WBS reconciliation, unscheduled
and blank-classification fixtures, and the 11 display helpers. Native Desktop
verified the three Malabar August routes while September remained selected,
the Alkimos zero-result route, Back navigation and the four Summary buttons.
The post-reload focused loaded-helper pass added **617 passing assertions**;
the loaded guide again passed content parity for all **19 rows**. The linked
record separates these results from synthetic fixtures and records the final
native observations and evidence limits.

Final native inspection confirmed all three guide-introduction paragraphs fit
without a scrollbar. Closing the guide retained Malabar / September 2026,
all WBS and baseline coverage **81.6%**. The linked record distinguishes the
earlier native zero-result test from the final supplementary context-label
binding, whose repeat native check was interrupted, and does not claim a
subsequent Desktop save of that closing UI selection.

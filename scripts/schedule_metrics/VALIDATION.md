# Validation evidence — 9 October 2026

Validated proposed definitions against the already loaded Programme Review
Desktop cache. No model writes, source refreshes, publishing or Desktop saves
were performed. Temporary numeric results were moved out of the repository;
the reusable tests contain synthetic fixtures, not business-data snapshots.

## Approved available-record policy

Following the user's clarification, `PR_FS1` is treated as an FS alias, and
affected core ratios use known/valid input records as their denominators.
Other eligible rows remain visible in excluded-record coverage counts. The
score now divides passed checks by assessed checks; an entirely unavailable
check is omitted, and partial or omitted evidence is disclosed with amber and
coverage labels. This replaces the initial all-or-nothing missing-input policy.

The revised definitions were reevaluated on all 16 loaded snapshots: all 128
available-record denominator checks and 16 score/coverage reconciliations
passed. FS, high float, negative float, remaining duration and Score now each
return all 11 J5064 monthly points and all five J4007 points. All six J5064
March–August snapshots have nine assessed checks and three partial checks;
their score is 33.33%. No missing values were replaced with zero, and imported
relationship rows were not deduplicated when recognising the FS alias.

## Desktop load failure and metadata correction

The first Desktop reopen failed because `SM Detail Value`, `SM Detail Target`,
`SM Detail Maximum` and `SM Detail History` each specified both a static
`formatString` and a dynamic `formatStringDefinition`. The earlier TOM
deserialisation and query-scoped expression tests passed but did not validate
Desktop's requirement that these measure properties be mutually exclusive.
The earlier selector-format assertions checked format expressions, not whether
Desktop could load the complete measure metadata.

The correction removes the static format from these four measures and retains
their dynamic format definitions. The static validator now checks every TMDL
file for this conflict. All 65 files pass, and three offline regression tests
pass, including proof that the pre-fix measure metadata raises a validation
failure and the corrected metadata passes. No live queries were required for
that metadata-only correction. Subsequent loaded-model inspection and the user's
screenshot confirmed that the corrected format version loaded in Desktop. The
available-record changes were subsequently verified in the loaded model and
native visuals. The latest completed checks and cutoff correction are recorded
in [DISPLAY-VALIDATION.md](DISPLAY-VALIDATION.md).

## Automated evidence

Completed checks:

- Full TMDL folder deserialises with Microsoft TOM: 59 tables, 70 core Schedule
  Metrics measures and 42 detail measures.
- Core expressions evaluated over all 16 loaded project/snapshot combinations.
- 224 base/history comparisons matched, with eight earlier-cutoff checks.
- All core rates and Score returned BLANK for an unavailable snapshot.
- 29 score/ratio fixtures passed: exact boundaries, individual failures, all
  failures, available-record denominators, partial coverage labels and colours,
  all-missing checks, assessed-only score denominators, genuine non-applicability,
  zero and BLANK populations.
- 30 aggregate/rate assertions passed against query-local task and relationship
  fixtures using the actual proposed expressions, including `PR_FS1`, a truly
  unknown type, and available-record denominators.
- 22 date-rule cases / 44 assertions passed, including completed, unscheduled,
  status, milestone, missing-date and date-order cases.
- Two multi-scope cases / 20 assertions passed: mixed projects and mixed
  snapshots return unavailable core metrics rather than aggregated percentages.
- The history-axis scope helper passed 29 assertions over both projects and
  latest/earlier cutoffs. It retains existing snapshot dates independently of
  activity-key validity, allowing unassessed metric periods to remain gaps.
- The revised detail runner passed all 16 snapshots, 64 gauge/history selector
  endpoints and 280 assertions. A separate 64 consolidated/canonical comparison
  run passed 80 assertions, and the fixture-only run passed 72 assertions for
  metric-specific cohorts, unrelated source warnings, partial exclusions, scope,
  cutoff, provenance, identity, no-due-work, formatting and indices above 1.
- Static page checks passed: original page identity, 49 visuals, 45 core metric
  references, 11 history/base pairs and valid bounds.
- `git diff --check` passed. Git reports normal LF/CRLF conversion notices.
- All 33 original core measures and their lineage tags were preserved. The
  original source partition was unchanged.

The static reference audit reports one pre-existing missing column reference in
the unchanged WBS slicer: `03 XER_PROJWBS[Has_Unscheduled_Task_In_Path]`.
The Microsoft report authoring validator reports no diagnostics on the modified
or new report files; existing diagnostics elsewhere in the report were retained.

Both matched-baseline detail metrics now return values for all 16 snapshots
(11 J5064 and five J4007). At the latest J5064 snapshot, missed dates are
1,497 / 2,103 = 71.1840%, and execution index is 1,684 / 2,103 = 0.8007608.
Neither metric has an excluded record in that snapshot. Two unrelated source
warnings are disclosed without making those complete-input metrics amber.

Current isolated detail query timings, including value/target/maximum/title/
colour/tooltip, were 0.90 seconds for missed dates and 1.09 seconds for execution
index. Their 11-point J5064 histories, including tooltip and scope, took 1.64
and 1.97 seconds respectively. These are read-only local DAX query timings, not
native Desktop rendering, whole-page or Service performance measurements.

## Earlier performance investigation

The timings in this section were recorded for the earlier strict missing-input
implementation. They have not been remeasured for the current core policy and
must not be presented as current-version or native page-load timings.

An initial overly broad validation query exceeded its 30-second bound. The
reusable runner now evaluates bounded snapshot statements and history batches.
Representative isolated Score DAX queries exposed avoidable repeated evaluation;
the implementation was simplified and rechecked. For the same loaded project
and snapshot, Score fell from approximately 6.0–6.2 seconds to 1.18 seconds; its
history query fell from 16.59 seconds to 5.15 seconds. These are local DAX wall
times, not Desktop rendering or Service performance claims. The actual
tooltip-inclusive trend bindings were also timed without concurrent validation
queries. Removing redundant score-status evaluation from the shared coverage
tooltip reduced the high-float trend from 14.50 to 3.22 seconds and the Score
trend from 19.25 to 7.55 seconds. The numeric results were unchanged. These
figures must not be presented as native page-load measurements.

The earlier detail gauge query, including value, target, maximum, title, colour
and tooltip, took 1.04 seconds after consolidation (initially 9.27 seconds).
The detail history with tooltips took 1.78 seconds across all 11 available
periods (initially 21.82 seconds while displaying only four assessed periods).
The additional periods carry unavailable-state explanations; numeric outputs
matched the canonical measures in all 64 selector/snapshot comparisons.

## Presentation scope

All 11 line charts use categorical axes, category `showAll` and a separate
snapshot-scope filter. This retains known but unassessed periods as gaps while
excluding future dates and absent project snapshots. Native rendering of those
gaps remains a Desktop acceptance check.

See [IMPLEMENTATION.md](IMPLEMENTATION.md) for metric definitions, data gaps,
baseline scope and the future unscheduled-row drill-through limitation. Native
Desktop rendering, interactions and dynamic formatting were subsequently checked
for the scenarios in [DISPLAY-VALIDATION.md](DISPLAY-VALIDATION.md). Service and
source refresh remain separate from these loaded-data checks.

## Native Desktop visual refresh verified

A subsequent check of the user's open report found that the correct PBIP and
updated measures were already loaded, but the page still displayed cached
visual results. Direct queries of that loaded model, without query-scoped
measure overrides, returned all 11 J5064 monthly points. Running **Optimize >
Refresh visuals** in Desktop restored the visible FS, high-float, negative-float,
remaining-duration and score trends. The matched missed-date gauge changed
from BLANK to 71.2%, and its trend also populated. The existing layout was
preserved. This was a visual-query refresh, with no source-data refresh,
publication, model write or Desktop save.

This verifies the previously reported gaps on the displayed Malabar page.
The later full page validation also found and corrected a project/date cutoff
bug, documented below. Drill-through and Service checks remain separate.

## Full page validation — 9 October 2026

All nine core gauges, Score and all four detail selections were checked in the
open Desktop report for Malabar September/March and Alkimos August. Values,
monthly point counts, formats, threshold markers, partial colours, table values
and hovered-month coverage tooltips agreed with direct loaded-model queries.
Malabar's execution-index selector initially retained cached results; Refresh
visuals restored 0.80 and all 11 monthly points.

Switching to Alkimos while September remained selected revealed a second cause:
the selected history cutoff became BLANK when that project had no September
snapshot. One hidden cutoff helper and 16 dependent expressions were updated on
disk and narrowly applied to the open model after exact preimage and metadata
checks, with a before-image backup. All 71 core measures then matched the saved
model; 862 direct-loaded cutoff assertions passed across eight cases and 630
history cells. Native Desktop confirmed Alkimos retained all five earlier points
while unavailable September gauges stayed BLANK. No source refresh, publication,
global external-change application or Desktop save was performed.

The detailed matrix and 1,431 direct-loaded detail assertions are documented in
[DISPLAY-VALIDATION.md](DISPLAY-VALIDATION.md). Execution indices above 1 are
covered by fixtures and saved visual bounds, not a native data example. Counts
table drill-through, exhaustive WBS combinations, exports, reopening, Service,
RLS and source refresh were not newly exercised during this display validation.

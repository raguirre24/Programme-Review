# Validation boundaries

`validation-runtime.ps1` is an **offline** validator despite its filename. It never connects to Analysis Services, refreshes data or executes DAX. It deserialises TMDL with Microsoft TOM, checks scenario field references and variable names, detects measure dependency cycles, parses M with Microsoft's parser and compares report-authoring diagnostics to an optional baseline.

## Open-horizon revision

The fixed twelve-month end has been removed. Today remains the earliest start and the full existing Scenario Date maximum is the finite end. Date-axis filtering must not change that bound. No calendar expansion, new relationships or input domains are introduced. The new revision's evidence is recorded separately under `resource_playground_review/open_horizon_20260911`; the one-year tests below remain historical evidence for their earlier contract.

The new marked source-free fixture passed **42 of 42 cases and 39,356 assertions**. All 48 measures executed and all 62 expressions matched source (61 scenario expressions plus CurrentDate). Cases include starts/targets beyond a year, a 1,000-day forecast, inverse rates, invalid dates, unresolved calendars, sparse buckets and the unchanged coverage maximum under Date/Week/Month filters. Ten native-shaped chart/daily queries passed under 1 GB. The complete 3,765-row daily result from 11-09-2026 through 31-12-2036 completed in 2.20 seconds; the shared date axis remained at 4,383 rows. These are local synthetic-engine timings, not Service performance guarantees.

Static source/draft parity passed 48 measures, 61 scenario expressions and 25 column mappings. Integration checked 513 qualified references, 782 variable declarations and 35 visuals. All 60 M syntax checks passed. A complete baseline comparison, including unchanged report-root metadata and registered resources, retained 32 existing errors and 92 warnings with no added or removed diagnostics.

After Desktop Apply, read-only production checks passed all 61 source-expression comparisons and found all 101 playground objects Ready. Counts remained 18,346 sparse table-11 rows, 72 calendar identities and 4,383 rows in each shared axis/start/target table. The marked synthetic fixture was removed with protected production metadata unchanged.

Separate native acceptance verified typed start 13-09-2028 and target 31-12-2030, with finish 01-02-2029, 100 working dates and 142 elapsed dates. Week and Month charts rendered correctly. **Optimize → Refresh visuals** cleared cached one-year labels after Apply; no source-data refresh was performed. The latest user inputs, including both cleared date controls, were restored and saved at 21:35. The original finish 02-02-2027, default target 11-10-2026 and quantities 1,050 / 3,950 returned. See [INPUT_CONTROL_EVIDENCE.md](INPUT_CONTROL_EVIDENCE.md) and the separate open-horizon `NATIVE_ACCEPTANCE.md` for native details.

Post-Save integration and generator parity passed. All fifteen saved controls exactly match the latest native snapshot. Preservation checked 555 files: 542 remained byte-identical, with thirteen authorised changes and no unrelated or new definition files. All 451 other report definitions are unchanged. The only native culture change is one generated suggested Month term from the Week/Month interaction; every culture byte outside that entry is unchanged. `git diff --check` passed.

## Earlier shared-context and rolling-window refinement

The current feature contains 48 measures, 13 calculated partitions, 57 total model tables and 38 relationships. The 61 scenario expressions and 25 generated-column mappings match their generator draft. Static integration checks cover 486 qualified references, 782 variable declarations, 35 visuals, the three existing context sync groups and the two one-way selector relationships. Offline TOM and all 60 M syntax checks pass. These are distinct from processing and running the expressions.

This revision uses a separate marked 20-table, source-free fixture. It includes the production calculated CurrentDate expression and the existing Project/WBS/Task/update relationship topology. Its cases cover exact DD-MM-YYYY selection, query-time window bounds, invalid explicit inputs, project/update calendar-name isolation, restricted-role denial, sparse exceptions, Week/Month reconciliation and full-window daily output. The historical 101-case suite below describes the preceding repair and is not reused as this revision's acceptance count.

The new fixture caught a reserved `Key` variable in the compact source mapping; it is renamed `TaskKey` and included in the evidence-based static regression guard. It also caught two inverse scalar queries where the otherwise unbound `Scenario Period Quantity` helper exceeded 1 GB. That helper now uses the same fused allocation template as the chart, without the chart-only Period selection requirement. An early guard makes the unsupported hourly inverse/cap combination return blank without the engine's dense-spool error. Native chart and daily measure expressions are unaffected by that narrow fix and passed their additional unsupported-mode tests.

Final processed-fixture acceptance passed **114 of 114 logical cases and 5,324 assertions**, plus **22 of 22 focused raw-allocation checks**. All 48 measures executed. Source parity passed 62 comparisons: the 61 scenario expressions and the production calculated CurrentDate expression. All 44 chart/daily queries passed under 1 GB, with maximum recorded duration 1.17 seconds. The original failing runs remain as diagnostic evidence; the accepted result consolidates final reruns for changed measures with verified results for unchanged expressions.

Native Desktop checks confirm simple calendar names, a changed calendar list when switching June/August, Week/Month rendering, DD-MM-YYYY entry, invalid-date suppression and Reset preserving shared context. At the test clock, the permitted interval is 11-09-2026 to 11-09-2027 inclusive. Full-window daily fixture queries return 366 dates; synthetic leap-window arithmetic checks are separate from an end-to-end run under a future clock.

Final Desktop Apply and Save at 21:01 restored the user's 5,000-unit / rate 50 / cap 100 scenario, 4d Tunnel, Alkimos/August, target 31-10-2026 and Month. Native outputs remained finish 02-02-2027, 100 working dates, 145 elapsed dates, target quantity 1,800 and remaining 3,200. The separate final read-only production check passed 61 expression comparisons and found all 101 scenario objects Ready, with 18,346 table-11 rows and 72 calendar identities unchanged. This verifies the existing Desktop process; full restart, production View as and Service acceptance remain separate.

Post-Save source/generator parity and preservation pass. Of 538 pre-refinement files, 502 remain byte-identical and 36 contain authorised changes; three context visuals were added. Report filters and all 37 existing relationships are unchanged. Native Save adjusted only two Playground linguistic entries: the Month suggested term and the new Planning window entity; all 464 other entities and remaining linguistic metadata are byte-identical. The recorded checkpoint comparison reported 34 to 32 errors and 92 unchanged warnings, with zero new diagnostics. Subsequent inspection identified the two baseline-only errors as missing report-root `definition.pbir` and `.platform` files in that validation artifact, not repaired report errors. The newer open-horizon comparison supplies both unchanged files. `git diff --check` passes.

Evidence for this revision is kept under the separate `resource_playground_review/refinement_20260911` review directory. See its `ACCEPTANCE.md`, `NATIVE_ACCEPTANCE.md`, `offline_validation.json`, `production_after.json` and `window_revision` results. No source refresh or publication is part of these checks.

## Earlier repair and validation tooling

Run from the repository root using PowerShell 7/.NET 8 and Node.js:

```powershell
& ./scripts/resource_playground/validation-runtime.ps1 -OutputPath ./playground-validation.json
```

To check that report diagnostics have not increased, supply `-BaselineReportRoot` pointing to an untouched export of the `.Report` folder. The implementation baseline came from `git archive HEAD` before the new page was committed. Without that argument the script reports the current diagnostics; it cannot demonstrate preservation of an earlier result.

The script discovers installed dependency caches. On another machine, supply:

- `-TomDirectory`: the `lib/net8.0` folder of `Microsoft.AnalysisServices` (tested 19.114.8).
- `-PowerQueryParserDirectory`: the installed `@microsoft/powerquery-parser` package directory (tested 2.0.0).
- `-ReportAuthoringCli`: the `dist/cli.js` file of `@microsoft/powerbi-report-authoring-cli` (tested 0.1.4).

The companion `validation-runtime-m.cjs` runs the M syntax parser. No packages are installed automatically. Output paths are optional and should point to a review-artifact location rather than a model cache.

The repair check contains 57 tables, 14 playground tables, 47 scenario measures and 37 relationships. TOM extracts all 13 calculated partitions and 47 measures: 60 DAX expressions, including Desktop's ordinary and fenced expression forms. Deserialisation and round-trip checks, 433 qualified references, 700 variable-name checks, the dependency graph and all 60 M expressions pass. The report retains its baseline 32 errors and 92 warnings with no new diagnostics. Three remote JSON schemas were unavailable in both snapshots, so full remote-schema coverage is not claimed.

Integration checks also require the six expected daily fields to be active, both visuals to bind bounded display measures, daily totals to be disabled, and their old visual-level row-measure filters to be absent. The filters produced native queries that consumed Desktop's 1,024 MB per-query memory allowance even though simpler hand-written queries completed. Removing the chart filter alone fixed forward scenarios but exposed repeated target-rate dependency expansion in inverse scenarios. A shared display template now resolves the selected calendar and rate once per bucket and reuses its weekday capacities and exception corrections for the necessary endpoints.

Captured native-query regression tests retain the original failures and run the replacement queries with `DbpropMsmdRequestMemoryLimit=1048576` KB. Final display tests execute the synchronised fixture model, use the full date axis and reconcile each returned bucket; they do not narrow dates artificially to make a query pass. Five daily display measures remain independent of the chart period selector and suppress inactive rows without a visual filter. Unknown rows remain numerically blank and are omitted; `Scenario Status` identifies unknown coverage.

The final 11 September 2026 acceptance run passed **101 of 101 logical cases and 2,512 assertions**, covering all 47 measures. All 60 processed-fixture expressions matched final source: 13 calculated tables and 47 measures. Final grouped chart queries completed in approximately 0.31–0.41 seconds; native-shaped six-field daily forward/inverse queries completed in approximately 1.9–2.2 seconds, and the 365-row detail case in 1.61 seconds, under the recorded 1 GB limit. These are local fixture query timings, not a Service performance guarantee. Cleared, multiple and unmatched chart Period selections did not change daily detail. Earlier diagnostic failures remain preserved; the accepted summary uses final runs for changed display expressions and earlier verified results for unchanged core branches.

`verify_rule_calculations.py` is separate algorithm evidence: an exact-rational weekday/exception implementation is compared with an independent daily oracle over 3,000 random scenarios, 10 deterministic scenarios and 3 invalid calendars. `verify_integration.py` checks registrations, relationship boundaries, references and geometry; optional `--baseline` verifies untouched source-file hashes from the implementation backup. Neither runs generated DAX.

The initial implementation's static checks did not establish DAX execution. The 11 September live repair review subsequently reproduced the reserved-variable compilation failures, fixed the calculated-table output mapping and verified all 14 playground partitions Ready in Desktop. Additional actual-DAX tests caught fixed-decimal inverse-rate rounding: 1,050 units over 18 working dates previously left 0.0006 units unfinished. Arithmetic operands are now explicitly converted to double after exact input selection.

Actual calculation tests are separate from the offline validator:

```powershell
python scripts/resource_playground/test_build_fixture.py
python scripts/resource_playground/test_fixture_cases.py
# Open the generated source-free fixture PBIP in Desktop and identify its port.
pwsh -NoProfile -File scripts/resource_playground/test_execute_fixture.ps1 -Port <fixture-port>
```

The fixture copies production scenario expressions, supplies synthetic table-11 rules and sparse exceptions, and has a dedicated project-scope test role. The query harness requires the fixture annotation, marker table, expected table count and Ready partitions. It refuses an unmarked production model. Its expected results come from an independent exact-rational daily oracle. It does not refresh or mutate models. Local authentication may require running the shell at the same Windows integrity level as Desktop.

Use the processed fixture for dependency-chain acceptance. A query-local `DEFINE MEASURE` replacement can affect a directly projected value while existing compiled dependent measures still use their original binding. The repair reproduced this with an applied rate of 888 while the dependent capacity retained the original rate of 50. Query-only experiments must redefine the complete dependency graph and verify propagation; final acceptance checks the synchronised model and source-expression equivalence.

The temporary marked fixture database was removed after acceptance. Its cleanup evidence confirms unchanged protected-production metadata. After Desktop applied the final source changes, a separate read-only production check found 47 measures, 60 matching expressions and 99 Ready playground objects without errors. Counts remained 18,346 table-11 rows, 72 calendar identities and 4,383 axis/start/target dates each. This check read metadata and ran one row-count query; it did not refresh source data.

Separate native Desktop inspection verified forward and inverse chart/daily-table rendering, Day/Week/Month switching and Focus Mode. A typed hourly rate of `12.3` produced `98.4` daily capacity on an eight-hour date; unsupported `12.35` produced the explicit input-validation message. Hourly inverse calculation with a daily cap was explicitly unavailable, as designed.

Native Reset also passed from a selected calendar, Day view and rate 1,050: calendar/date selections cleared, Month/rate 120/quantity 1,050/cap 100 were restored, and the status requested one authorised calendar with blank results. Both original global filters remained False and `report.json` stayed byte-identical after saving. The bookmark now sets `options.applyOnlyToTargetVisuals=true` as well as its 12 target names; target names alone did not restrict native replay. The calendar retains single selection while permitting an empty state.

Saved-source reload through **Apply external changes** passed after restoring the original 12 inputs. Returning to Resource Playground retained the selected August calendar, Day view, quantity 1,050, rate 1,050 and cap 100. The chart and six daily columns rendered correctly, with finish 25 September 2026, 11 working days, 15 civil days and final allocation 50. The report was saved again. This verifies the existing Desktop process; a full process restart was not tested. Keyboard/accessibility, other display scales, export, production **View as** and real-user Service acceptance remain separate checks. No report was published. Follow [RESOURCE_PLAYGROUND.md](../../RESOURCE_PLAYGROUND.md); do not describe metadata deserialisation or a Python oracle as DAX or native-host proof.

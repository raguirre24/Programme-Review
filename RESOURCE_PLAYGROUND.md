# Resource Playground

The new **Resource Playground** page follows **Resources**. It distributes a hypothetical quantity using the selected version of `11 XER_CALENDAR_DETAILED`. The existing Resources calculations are unchanged. This is a planning estimate, not a P6 scheduling or resource-levelling calculation.

## Using the page

1. Select the **Project** and **Monthly update**. These controls share the same context as the other report pages. Choose a calendar from that project and update; only its name is displayed.
2. Enter a quantity, quantity multiplier, unit and start date. Dates use exact **DD-MM-YYYY** text. Start today or later; there is no fixed twelve-month cap. The page displays the full available date range, currently through **31-12-2036**.
3. In **Find finish date**, enter production per working day or working hour and optionally enable a daily quantity limit.
4. In **Meet target date**, enter the inclusive target date. The page calculates the required daily rate, or the required hourly rate with no daily cap. Hourly target solving with a daily cap is explicitly unavailable in this version.
5. Compare period quantities and cumulative quantity by **Week** or **Month**. Month is the default. The separate daily audit shows calendar hours, available capacity, allocated quantity and quantity remaining.

The finish card reports a day, not a time within a shift. A partial final day receives only the remaining quantity. **Per working day** assigns the same quantity to every positive-hour working date; use **Per working hour** when shorter shifts must reduce production. Units are labels; no implicit labour-hour, currency or material conversion is performed.

If the daily cap makes a target infeasible, the page shows the required rate and the attainable forecast under the cap. Known allocation is retained when later calendar data becomes unresolved. Remaining quantity at the last known date can therefore refer to a date earlier than the planning horizon. An explicitly invalid start or target blocks the scenario and displays a validation message.

## Inputs and bounds

Native Power BI Input slicers filter disconnected numeric columns. They do not supply unrestricted scalar values or write back to a model. Values are exact within these explicit domains; unmatched or ambiguous entries produce a validation message rather than a rounded selection.

| Input | Supported values |
|---|---|
| Quantity entry | Whole numbers from 0 to 100,000 |
| Quantity multiplier | 0.01, 0.1, 1, 1,000 or 1,000,000 |
| Rate | 0 to 10,000 in increments of 0.1 |
| Daily quantity limit | 0 to 10,000 in increments of 0.1 |
| Start and target | Today through the last date in the shared Scenario Date axis, inclusive; exact DD-MM-YYYY entry |
| Chart | Week or Month; Month by default |
| Daily audit | Known dates in the permitted window, ending at completion or unresolved availability |

For example, quantity `1050` with multiplier `1` means 1,050 units; `12345` with multiplier `0.01` means 123.45 units. The supported domains do not represent every possible decimal at every magnitude. The evaluated quantity and assumptions appear on the page.

**Reset scenario** restores the sample: quantity 1,050, rate 120 per working day, daily limit 100, unit m³, monthly chart; the calendar and dates clear. Completely cleared inputs use quantity 1,000, multiplier 1, rate 100, no limit, per working day, items, start today and target start plus 30 days, capped at the window end. A filtered input with no match never receives a default. Reset affects only the twelve scenario inputs; it preserves Project, State, Monthly update and report filters.

## Calendar calculation and storage

Table 11 is consumed in its existing grain: seven undated `Standard` weekday rules and sparse dated exceptions. A dated exception replaces that date's ordinary weekday hours. The model does not store or calculate a calendar-by-date cross join.

For an inclusive interval from start to endpoint, a weekday's occurrence count is its complete-week count plus its occurrence in the final partial week. Interval capacity is:

```text
sum over 7 weekdays (occurrences × daily capacity from standard hours)
+ sum over dated exceptions (replacement daily capacity − ordinary daily capacity)
```

Daily capacity is rate for a positive-hour working day, or rate × hours for hourly production. The optional cap applies to each daily capacity before summation. Allocation through an endpoint is the lesser of quantity and known capacity. A period uses two allocation endpoints. Non-contiguous visible periods are summed without filling their gaps; explicitly sparse date selections are evaluated only for those selected dates.

The finish solver checks month boundaries, including the final partial month of known coverage, then checks at most 31 dates in the first qualifying month. It is not called for every chart point or daily row. The completion comparison allows only `max(1e-8, quantity × 1e-14)` floating-point tolerance; raw daily capacities are not rounded.

Exact numeric input selection uses fixed-decimal columns. Quantity and production arithmetic then explicitly use double precision so calculated target rates are not truncated to four decimal places. Two chart display measures and five daily-detail display measures share a generator template that calculates the selected rate, seven weekday capacities and sparse exception corrections once per bucket, reusing them for its required endpoints. This avoids repeatedly expanding the target-rate calculation through nested measures or visual filters. They preserve the underlying allocation and cumulative measures used by totals and target comparisons. Choose one display period; an empty or ambiguous period selection shows a prompt and does not run the chart calculation. The daily table remains independent of that period selection.

The daily table shows known dates through completion within the available date range, including its final date. No fixed one-year or 365-row restriction is used. Unknown dates have blank numeric results and are omitted; the scenario status identifies the first unknown date. No unknown hours or capacity are changed to zero.

Storage added by the playground is independent of project or update counts except for the calendar selector:

- One shared date axis, plus two disconnected date-input projections: roughly 4,383 dates each.
- Three bounded numeric-input tables: 300,003 rows in total across the whole model, independent of calendars.
- A calendar selector with one row per `ProjectKey`, scoped calendar key and source tuple.
- Small option tables, one native axis field parameter, and a measure table.

The selector has direct, one-way relationships from `Project_Dimension` and `CurrentDate`. It inherits the existing Project Access role through the project relationship. Its hidden Report Update Date is resolved from the existing Task source-to-UpdateDate mapping, not from the calendar's source date or a guessed month end. A compact grouping is built before source-key parsing, and calendars unused by tasks remain available when their source snapshot is mapped. Missing or conflicting mappings remain unresolved. Measures apply the selected project/key/source tuple to table 11 with `KEEPFILTERS` and `TREATAS`.

Calendar names may repeat across projects and updates; the shared context resolves those versions. If multiple calendar identities still share a name inside one selected project/update, calculation is blocked instead of choosing an arbitrary calendar. RLS must still be checked with **View as** and a restricted Service account before release.

The physical shared date tables run from the beginning of the previous year through the end of the refresh year plus ten. Measures calculate `TODAY()` at query time and use the full, unfiltered shared date-axis maximum for the upper bound. A Week, Month or sparse-date selection cannot shorten that bound. Longer scenarios add query work without multiplying calendar rows by projects or updates. A scenario that cannot finish within the available range reports the unallocated quantity; it never invents a finish beyond that range.

Invalid or duplicate weekday rules, unresolved undated markers and ambiguous calendar identities block calculation. The first invalid or duplicated dated exception limits verified coverage. Dates after a proven completion retain the completed quantity even when later availability is unknown. Future holidays are only those contained in the selected source calendar; none are inferred.

## Files and regeneration

The 13 `Scenario ...` tables and `Resource Scenario Measures` are registered in the semantic model. Report page ID is `4c53a34bba9dcc7f3e8c`; reset bookmark ID is `e899bf3a9c2d243f33bf`. Existing Resources visuals are unchanged.

The source generators under `scripts/resource_playground/` are:

- `generate_scaffold.py`: disconnected input tables, calendar selector, field parameter, table registration and selector relationship.
- `generate_measures.py`: scenario measures, with shared generation of the weekday/exception interval kernels.
- `generate_page.py`: the native page and its reset bookmark.

Keep generators and deployed files together when changing this feature. Once production files exist, generators require an explicit `--output-dir` for review drafts and refuse to overwrite the deployed feature. Compare the draft expressions using TOM, then apply targeted changes that preserve Desktop's metadata, lineage tags and visual IDs. Native input capability and serialisation evidence is in [INPUT_CONTROL_EVIDENCE.md](scripts/resource_playground/INPUT_CONTROL_EVIDENCE.md).

## Open-horizon validation — 11 September 2026

The open horizon passed 42 executed DAX cases and 39,356 assertions, covering all 48 measures. Multi-year starts, targets and forecasts, sparse weekly/monthly totals and the final available date were checked independently. All ten chart/daily query shapes passed under 1 GB, including the complete 3,765-date available interval. The shared date axis and sparse table-11 rows were not expanded. See [VALIDATION.md](scripts/resource_playground/VALIDATION.md) for detailed evidence and native acceptance.

Native Desktop accepted start 13-09-2028 and target 31-12-2030, with the forecast finishing 01-02-2029 in both Week and Month views. The page displays date coverage through 31-12-2036. The user's latest inputs were restored, including cleared Start and Target controls and Month view, then saved at 21:35. The original 5,000 m³ scenario still finishes 02-02-2027. All 61 applied scenario expressions match source, with 101 playground objects Ready and unchanged calendar/date row counts.

## Earlier twelve-month refinement validation — 11 September 2026

This section records the preceding version, before the user removed the twelve-month cap. Its one-year boundary assertions remain historical evidence. Current open-horizon checks are recorded separately in [VALIDATION.md](scripts/resource_playground/VALIDATION.md).

The revised project/update, date-entry and rolling-window contract passed 114 executed DAX cases and 5,324 assertions, plus 22 focused raw-allocation regressions. All 48 measures were executed in a marked, source-free fixture. Its final expressions matched all 61 scenario expressions and the unchanged calculated CurrentDate expression. The 44 chart/daily queries passed under a 1 GB limit, including the complete 366-date current window, invalid-input suppression, inverse modes and unsupported-mode rejection. Fixture timing is not a Service performance guarantee.

Native Desktop checks verified the calendar list changing with June/August context, names without source suffixes, Week/Month rendering, exact DD-MM-YYYY entry and explicit rejection outside the window. Reset preserved the selected Project and Monthly update. After final Apply and Save, the preserved 5,000 m³ / rate 50 / cap 100 example still finished on 02-02-2027, with 100 working dates and 145 elapsed dates. It retained August, 4d Tunnel, target 31-10-2026 and the requested Month view. Validation details and the distinction between static, engine and native evidence are in [VALIDATION.md](scripts/resource_playground/VALIDATION.md).

## Earlier repair evidence

The following evidence records the completed repair before the project/update, DD-MM-YYYY and rolling-window refinement. Its historical Day-view and 365-date tests are not claims about the revised feature.

Automated evidence collected during implementation:

- Exact-rational calendar arithmetic versus an independent daily oracle: 3,000 random scenarios, 10 deterministic scenarios and 3 invalid-calendar checks passed. This validates the algorithm, not execution of the generated DAX.
- Full-model TMDL deserialization with Microsoft TOM and Power Query parsing passed.
- Microsoft report-authoring validation added **zero diagnostics** relative to the existing report baseline. Its 32 existing errors and 92 existing warnings remain outside this change.
- Static integration checks passed for table registrations, measure references and dependency cycles, variable/table-name collisions, the single governed selector relationship, page bounds and unique visual IDs.
- The existing table-11 source, CSV loader, refresh audit and SharePoint setup file remained byte-identical to the implementation backup. `git diff --check` passed.

The initial implementation had only static and independent arithmetic evidence. Live review on 11 September exposed DAX compilation errors in `Scenario Calendar`, `Scenario Date` and `Scenario Bucket Quantity`, plus an implicit calendar output-column mapping. The repair replaces reserved variable names and explicitly projects all six calendar-selector columns. The reopened Desktop model has all 14 playground partitions Ready, with 72 calendar identities and 4,383 shared dates for the current data.

Native page inspection also found five inactive daily-table measures, an overlapping theme title and a chart query that exhausted Desktop's 1 GB query-memory limit. The table bindings and heading were repaired. The captured chart query is used for performance regression testing under the same memory limit; simple hand-written query success is insufficient evidence for this visual.

Actual calculation regression tests use a separately marked, source-free model containing the production scenario DAX and synthetic table-11 rules and exceptions. Expected values come from an independent exact-rational daily oracle. The completed repair run passed **101 of 101 logical cases and 2,512 assertions**, covering all 47 measures. All 60 final DAX expressions matched the source: 13 calculated tables and 47 measures. Native-shaped chart and six-field daily queries passed under a 1 GB per-query memory limit, including forward and inverse scenarios and the 365-day detail bound. The temporary fixture database was then removed; protected production metadata remained unchanged during its cleanup.

After Desktop applied the final model changes, read-only production verification found all 47 measures present, all 60 expressions equal to source and all 99 playground partitions, columns and measures Ready without errors. Table counts remained 18,346 sparse table-11 rows, 72 calendar selectors and 4,383 shared dates.

Native Desktop inspection confirmed chart and daily-table rendering in forward and inverse modes, Day/Week/Month switching and Focus Mode. Typing hourly production `12.3` produced `98.4` capacity on an eight-hour working date. Typing unsupported `12.35` produced an explicit invalid-input message instead of rounding. Hourly inverse calculation with a daily cap remains explicitly unsupported.

Native Reset was verified from a selected calendar, Day view and rate 1,050. It cleared calendar/date selections, restored Month, rate 120, quantity 1,050 and cap 100, and correctly left results blank with the instruction to select one authorised calendar. Both original global filters remained False, and `report.json` remained byte-identical after saving. The repair explicitly scopes the bookmark to its 12 target inputs and permits an empty calendar selection.

Saved-source reload through Desktop's **Apply external changes** also passed. After restoring the original 12 inputs and returning to Resource Playground, the selected August calendar, Day view, quantity 1,050, rate 1,050 and cap 100 were retained. The chart and all six daily columns rendered; finish was 25 September 2026, with 11 working days, 15 civil days and a final allocation of 50. The report was saved again. This verifies reload within the existing Desktop process; a full process restart was not tested.

Remaining acceptance includes keyboard navigation, accessible labels, wrapping at other display scales, export, production **View as** and real-user Service checks. See [VALIDATION.md](scripts/resource_playground/VALIDATION.md) and [INPUT_CONTROL_EVIDENCE.md](scripts/resource_playground/INPUT_CONTROL_EVIDENCE.md) for the evidence boundaries. No report was published, and neither static deserialisation nor the independent Python oracle is presented as native-host proof.

Repeat the independent checks from the repository root:

```powershell
python scripts/resource_playground/verify_rule_calculations.py
python scripts/resource_playground/verify_integration.py
git diff --check
```

Runtime validation commands and requirements are documented alongside the runtime scripts in the same folder. The arithmetic and integration scripts use the Python standard library and do not contact any data source.

---
name: dax-development
description: Write correct and fast DAX — measures, calculated columns, filter context, CALCULATE, time intelligence, variables, calculation groups, and performance patterns. Use this skill whenever the user asks for any DAX code, mentions measures, KPIs, totals behaving strangely, year-to-date / period comparisons, "filter context", slow visuals, or asks why a number is wrong in Power BI. Use it even for one-line measures — most DAX bugs are context bugs that look fine at first glance.
---

# DAX Development

DAX correctness is about **evaluation context**. Almost every "wrong number" is a context problem, and almost every slow measure is an iterator or materialisation problem. Reason about context first, syntax second.

## Core mental model

- **Filter context** comes from visuals, slicers, and CALCULATE. **Row context** comes from calculated columns and iterators (SUMX, FILTER, ...).
- `CALCULATE` does exactly two things: transforms row context into filter context (context transition), then applies its filter arguments. Every mysterious result traces back to one of these.
- Filter arguments in CALCULATE **replace** existing filters on the same column(s) by default. Use `KEEPFILTERS` to intersect instead:

```dax
Sales High Value = CALCULATE([Sales], KEEPFILTERS(Product[Class] = "High"))
```

- Measures always run in filter context; referencing a measure inside an iterator triggers context transition per row. This is powerful and expensive — know when you're doing it.

## Non-negotiable habits

1. **Variables for everything referenced twice**, and for readability:

```dax
Margin % =
VAR Sales = [Total Sales]
VAR Cost  = [Total Cost]
RETURN DIVIDE(Sales - Cost, Sales)
```

Variables are evaluated once, in the context where defined — they also protect against later context changes, which is sometimes exactly what you want (snapshot a value before applying more filters).

2. **DIVIDE, not `/`** — handles divide-by-zero without IF gymnastics.
3. **Measures over calculated columns** whenever the logic is an aggregation. Calculated columns consume model memory, are computed at refresh in row context, and don't respond to slicers. Legitimate calculated column uses: grouping/bucketing keys, values needed on slicers, relationship keys. If it can be pushed to Power Query or the source, push it further upstream still.
4. **Format strings on every measure**; name measures the way they'll read on a visual.
5. **Never filter a whole table when you mean a column.** `FILTER(Sales, ...)` as a CALCULATE argument materialises and iterates the table; `Sales[Region] = "North"` (column predicate) stays in the storage engine. Table filters also carry all other columns' context with them, causing subtle correctness bugs.

## Time intelligence

- Requires a proper **date table**: contiguous dates, marked as date table, related to fact tables. Without it, TOTALYTD/SAMEPERIODLASTYEAR silently misbehave.
- For non-standard calendars (4-4-5, project period calendars, or reporting-period logic like data-date-driven scheduling periods), built-in time intelligence does not apply. Build period logic from columns on the date/period dimension:

```dax
Cumulative To Data Date =
VAR MaxPeriod = MAX('Period'[PeriodEnd])
RETURN CALCULATE([Planned Value],
    'Date'[Date] <= MaxPeriod,
    ALL('Date'))
```

- Prior-period comparison template (works with custom period tables): compute the prior period key in a variable, then `CALCULATE(measure, REMOVEFILTERS('Period'), 'Period'[PeriodKey] = priorKey)`.

## Common patterns

```dax
-- % of total within visual, robust to slicers
Pct of Total = DIVIDE([Sales], CALCULATE([Sales], ALLSELECTED(Product)))

-- Cumulative (running) total
Cumulative = 
VAR d = MAX('Date'[Date])
RETURN CALCULATE([Sales], 'Date'[Date] <= d, ALL('Date'))

-- Top N with ties handled by RANKX
Rank = RANKX(ALLSELECTED(Product[Name]), [Sales], , DESC, Dense)

-- Semi-additive (balance at last date with data)
Closing = CALCULATE([Balance], LASTNONBLANK('Date'[Date], [Balance]))
```

- `ALLSELECTED` answers "of what's on the report", `ALL` answers "of everything". Choose deliberately; ALLSELECTED inside iterators has notoriously subtle semantics — avoid nesting it.
- Totals rows: totals are not the sum of visible rows, they're the measure evaluated in the total's context. If a total looks wrong, the measure is context-dependent — decide whether you need `SUMX(VALUES(dim[col]), [Measure])` to force per-row evaluation.

## Performance

- The storage engine (fast, compressed, parallel) handles simple aggregations and column predicates. The formula engine (slow, single-threaded) handles everything else. Goal: keep work in the storage engine.
- Red flags: iterators over large tables with measure references inside; `FILTER` over fact tables; `SUMMARIZE` with added columns (use `SUMMARIZECOLUMNS` or ADDCOLUMNS+SUMMARIZE); repeated identical sub-expressions (hoist to variables); bi-directional relationships forcing expensive expansion.
- Distinct counts are the most expensive common aggregation — pre-aggregate or model around them where possible.
- Diagnose with Performance Analyzer (copy the visual's DAX query) → DAX Studio (server timings, storage vs formula engine split). If SE queries number in the hundreds for one visual, a callback or context-transition-per-row pattern is the culprit.

## Calculation groups

Use for families of variations (YTD/PY/Δ across many base measures) instead of measure explosion. Cautions: they change measure semantics globally (format strings, ordering), interact with other calc groups by precedence, and confuse report builders if over-used. Keep one clear purpose per group.

## Debugging workflow

1. Reproduce the wrong number in a table visual with the relevant dimensions.
2. Decompose: create temp measures for each VAR / sub-expression and put them side by side.
3. Question the context: what filters does this cell actually have? (Tooltip a `CONCATENATEX(FILTERS(...))` helper or use DAX Studio's query view.)
4. Only then touch the formula. Most fixes are adding/removing a `KEEPFILTERS`, `ALL`, or fixing an unintended context transition.


## This workspace: DAX Guardrails & Patterns

1. **Engine-Rejected DAX Variable Names**:
   - The Analysis Services / Power BI Desktop engine rejects certain identifier names inside `VAR` declarations. Never name a DAX variable `firstdate`, `lastdate`, `updates`, `key`, or `ordinal` ( regardless of casing; enforced by `scripts/resource_playground/verify_integration.py`).
2. **TMDL Measure Formatting & `ERROR()` Rules**:
   - Never specify both `formatString` and `formatStringDefinition` on the same measure in TMDL — Power BI Desktop refuses to load the model if both are present.
   - When calling `ERROR("...")` in calculated tables or measures (such as `XER CSV Refresh Audit`), always pass a **literal string constant**, never a dynamic concatenated expression, because Power BI Service rejects dynamic `ERROR()` arguments during cloud refresh.
3. **Table & Column Naming Gotchas**:
   - `'XER  Counts'` has **two spaces** between `XER` and `Counts`.
   - `'01 XER_TASK'[status_code]` uses `"Not Started"`, `"In Progress"`, `"Complete"`, whereas `'06 XER_PREDECESSOR'[status_code]` and `[predecessor_status_code]` use `"TK_NotStart"`, `"TK_Active"`, `"TK_Complete"`.
   - In `06 XER_PREDECESSOR[pred_type]`, always include `"PR_FS1"` alongside `"PR_FS"` when filtering Finish-to-Start links.
   - Durations, floats, and lags in `01 XER_TASK` and `06 XER_PREDECESSOR` are **already in working days** — never divide them by 8.
4. **Display Wrapper Measures Instead of Visual-Level Measure Filters**:
   - On high-grain axes such as `Scenario Date` (on the `Resources` page, Simulator view), visual-level row measure filters (`Scenario Show Daily Row` / `Scenario Show Period Row`) exceed the native query memory budget. Always bind visuals to bounded display wrapper measures (`Scenario Daily Display *`, `Scenario Chart Quantity`, `Scenario Chart Cumulative Quantity`, `Comparison Chart Quantity`) that return `BLANK()` outside the active planning window.
5. **Detail Scope Toggle (`Schedule Metric Detail`)**:
   - Measures in `Schedule Metric Detail` (`SM Detail *`) check `ISFILTERED('Schedule Metric Detail'[DetailScope])`: when unfiltered on the main counts table, they return the activity's own metric; when filtered to `"Baseline coverage"` in the detail panel, they evaluate the baseline comparison across the whole project/programme.
6. **`LOOKUPVALUE` in Calculated Columns Follows the Row's Relationships**:
   - Inside a calculated column, `LOOKUPVALUE` into a table reachable from the current row through many-to-one relationships is restricted to the related row. On `06 XER_PREDECESSOR`, `LOOKUPVALUE('03 XER_PROJWBS'[Level_2], '03 XER_PROJWBS'[wbs_id_key], x)` returned blank for every link whose predecessor sat in a different WBS than its successor (153,613 of 249,291 rows in October 2026). Use `RELATED` along the active chain, or `CALCULATE(..., REMOVEFILTERS(), TREATAS({x}, ...))`, and compare every rewrite against the stored column with a query-scoped `DEFINE COLUMN` (mismatch count 0) before replacing it.
7. **No `CALCULATE` in Calculated Tables Related to Their Source**:
   - A calculated table that is related to the table it reads (`04 XER_BASELINE` ↔ `01 XER_TASK`, one-to-one on `task_id_key`) must not use `CALCULATE`, `CALCULATETABLE`, `TREATAS` filters or `ADDCOLUMNS` with context transition over that source: filter propagation depends on the source's relationships, including the link back to the calculated table, and Desktop fails to open the project with "A circular dependency was detected" (October 2026). Use `SUMMARIZE`/`GROUPBY`, `FILTER` and `IN` instead. Evaluating the expression as a DAX query does not reveal the cycle; only loading the model does.
8. **Calendar Stretch (`CS *`) Patterns**:
   - Workweeks come only from `'10 XER_CALENDARS'[Workweek Mask]`, never from calendar names. The O(1) finish without exceptions is `Eff + QUOTIENT(N - 1, w) * 7 + FIND("X", SUBSTITUTE(MID(Mask & Mask, WEEKDAY(Eff, 2), 7), "1", "X", r)) - 1` with `w` working days per week, `r = N - QUOTIENT(N - 1, w) * w` and `N = INT(CEILING(ROUND(remaining_duration, 4), 1))`.
   - Per-date calendar searches (`CS Cliff Finish Date`) use closed-form weekday counts plus sparse exception deltas and an unrolled bisection rendered by `scripts/calendar_analysis/stretch_dax.py`; never `GENERATESERIES`/`CALENDAR` per activity. Change the levels in that script, paste the re-rendered block, and re-run `validate_calendar_stretch.py`. Bound the search exactly (cap at the scheduled finish + 400 days only when the latest candidate start still completes by then), and evaluate many candidate dates in one pass over `'Scenario Date'` (ADDCOLUMNS over VALUES) rather than separate `CALCULATE([measure], TREATAS(...))` probes: each probe repeats the measure's date-independent work (0.3 s each), while one pass shares it (callout 8 s to 0.8 s).
   - Deneb receives dates as ISO text (`FORMAT(d, "yyyy-MM-dd")`) and parses them with `utcParse` on a UTC scale, so time zones never shift a bar by a day.

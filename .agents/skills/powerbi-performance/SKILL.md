---
name: powerbi-performance
description: Diagnose and fix slow Power BI reports, slow refreshes, and oversized models using Performance Analyzer, DAX Studio, VertiPaq Analyzer, and Query Diagnostics. Use this skill whenever the user says a report, visual, refresh, or model is slow, too big, timing out, or hitting capacity/memory limits — or asks how to profile anything in Power BI. Use it before proposing fixes — measure first, then optimise the actual bottleneck.
---

# Power BI Performance & Troubleshooting

Never optimise blind. Every performance problem lives in exactly one of four layers — identify the layer first, then apply that layer's fixes.

## Step 0: Which layer?

| Symptom | Layer | Tool |
|---|---|---|
| Report slow to interact, visuals spin | Query/DAX or visuals | Performance Analyzer → DAX Studio |
| Refresh slow or failing | Power Query / source | Query Diagnostics, gateway logs, source profiling |
| Model too big / memory errors | Storage | VertiPaq Analyzer (DAX Studio → Advanced → View Metrics) |
| Slow only in Service, fine in Desktop | Capacity/gateway/network | Capacity metrics app, gateway performance logs |

## Report/visual layer

- Performance Analyzer splits each visual into **DAX query / visual display / other**. "Other" dominating usually means too many visuals queuing — each visual is ≥1 query, and pages with 30+ visuals are slow regardless of DAX quality.
- Fixes at this layer: fewer visuals per page (consolidate cards into multi-row cards/tables), avoid top-N via visual-level filters on huge dimensions, reduce slicers (each slicer queries), turn off unnecessary interactions between visuals, and prefer buttons/bookmarks over always-rendered hidden visuals.
- Copy the slowest visual's query from Performance Analyzer → run in DAX Studio with **Server Timings** on.

## DAX layer (in DAX Studio)

Read server timings:
- **SE (storage engine) % high, few queries, fast**: healthy.
- **FE (formula engine) % high**: expression too complex for SE — look for iterators with measure references, ALLSELECTED nests, SWITCH over many measures inside iterators.
- **Many SE queries (hundreds) or CallbackDataID present**: per-row context transition or IF/error-handling inside an iterator pushing callbacks into SE scans. Hoist logic out of the iterator, replace `IF` inside SUMX with filtered CALCULATEs, pre-compute flags as columns.
- **Large materialisation (rows spooled ≫ rows returned)**: a table filter or crossjoin materialising the fact — replace `FILTER(Fact,...)` with column predicates; check bi-directional relationships expanding the query.
- Re-test after each single change; keep a benchmark query set.

## Model/storage layer

VertiPaq Analyzer, read in this order: total size → largest tables → largest columns → cardinality. Actions, highest yield first:
1. Drop or narrow the top offending columns (usually high-cardinality text/datetime on facts).
2. Split datetimes; strip time where unused.
3. Check dictionary vs data size — huge dictionaries mean high-cardinality strings; recode to integers upstream.
4. Verify Auto date/time is off (hidden LocalDateTables in the metrics = it's on).
5. Relationship columns: integers, matching types both sides.
6. Partitioning: incremental refresh partitions refresh less data and parallelise.

## Power Query / refresh layer

- Query Diagnostics shows where time goes per step; the "Data Source Query" events reveal actual native queries — confirm folding happened where expected.
- Common refresh killers: broken folding on large sources (full download), referenced base queries evaluating multiple times, correlated per-row source calls, combine-files over thousands of files, privacy-level partitioning splitting otherwise-foldable work.
- Refresh in the Service is more memory-constrained than Desktop: a refresh that fits locally can exceed capacity limits (whole model + new data during refresh). Incremental refresh reduces peak memory.
- Gateway: check spooling to disk, CPU during refresh windows, and stagger scheduled refreshes; gateway performance logging can be enabled for per-query timing.
- Sources billed per scan (Athena): performance work is also cost work — partition pruning and Parquet reduce both.

## Service/capacity layer

- Fabric/Premium capacity metrics app: identify interactive vs background operation load, throttling events, and which items consume Capacity Units.
- Symptoms of throttling: reports fast at 7am, slow at 10am; intermittent visual errors. Fix load (above layers) before buying capacity.
- Large semantic model storage format: enable for models >1GB needs; be aware of the download-PBIX restriction.

## Systematic method

1. Reproduce with a specific, named scenario ("Page 3, Period slicer = latest, 8s").
2. Identify the layer (table above). Capture baseline numbers.
3. Apply **one** change. Re-measure. Keep a log — performance work without a log becomes folklore.
4. Stop when the target is met; further optimisation trades maintainability for nothing.

## Quick wins checklist (safe to apply almost always)

- Auto date/time off; unused columns removed; datetimes split.
- Top N visuals limited; page visual count < ~15.
- Slicers converted to filter pane where interactivity isn't needed.
- All fact filters in CALCULATE are column predicates, not table filters.
- Incremental refresh on any fact > a few million rows with a reliable date column.
- Measure sub-expressions hoisted into variables.

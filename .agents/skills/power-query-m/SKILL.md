---
name: power-query-m
description: Write correct, performant Power Query (M language) code — query folding, custom functions, error handling, schema-drift defence, buffering, and the formula firewall. Use this skill whenever the user asks for any Power Query / M code, mentions the Advanced Editor, transformations, combining files, slow refresh, "query folding", or asks to clean/reshape data before it lands in a Power BI model. Use it even for small snippets — M has sharp edges that make small snippets wrong.
---

# Power Query M Development

M is a lazy, functional language. Most real-world M bugs come from three sources: broken query folding, silent schema drift, and misunderstanding evaluation order. Write M with those three in mind.

## Query folding — the first-order concern

Folding means the source (SQL, Athena, etc.) does the work instead of the mashup engine. A folded query over 50M rows is fine; an unfolded one downloads 50M rows to transform locally.

Rules of thumb:
- Keep foldable steps **first**: filter rows, select columns, simple renames, joins between tables of the same source.
- Steps that commonly **break** folding: `Table.Buffer`, index columns, most `Table.TransformColumns` with custom functions, changing types to types the driver can't map, merging across different sources, any step after native SQL (`Value.NativeQuery` / `Odbc.Query`) unless `EnableFolding=true` is supported.
- Verify: right-click a step → **View Native Query**. Greyed out = folding stopped at or before that step. Also use Query Diagnostics for stubborn cases.
- Once folding is broken, it never resumes. Order steps: fold everything possible, then do local-only work.
- `Value.NativeQuery(source, sql, null, [EnableFolding = true])` lets subsequent simple steps fold on top of hand-written SQL for sources that support it (SQL Server yes; ODBC sources usually no — test).

## Structure and style

- Name steps meaningfully (`FilteredToCurrentPeriod`, not `Filtered Rows1`). Steps are documentation.
- One logical concern per query. Stage shared logic in a disabled-load base query, reference it from others — but be aware referenced queries **re-evaluate per reference** (no shared cache across queries during refresh, except within some dataflow scenarios). If a base query is expensive and referenced 3 times, it may run 3 times: consider a dataflow or materialise upstream.
- Disable load on staging queries (right-click → uncheck Enable Load) or they bloat the model.

## Schema-drift defence

File-based and SharePoint sources drift. Defend explicitly:

```powerquery
// Select by name, tolerate missing, and type-check loudly
Selected = Table.SelectColumns(Source,
    {"task_id", "task_code", "task_name", "early_start_date"},
    MissingField.UseNull),
Typed = Table.TransformColumnTypes(Selected, {
    {"task_id", Int64.Type},
    {"early_start_date", type datetime}
})
```

- Never rely on column position. Never use `Table.PromoteHeaders` on data whose first row isn't guaranteed to be headers.
- For CSV: pin `Columns=` and `Encoding=` in `Csv.Document` explicitly. Auto-detected delimiters and encodings change between refreshes. Watch for embedded newlines in quoted fields — use `QuoteStyle.Csv`.
- Where correctness matters, add a validation query that counts nulls in key columns or checks row counts, and surface it on a hidden QA page or fail the refresh deliberately with `error`.

## Error handling

- `try ... otherwise` is a scalpel, not a blanket. Wrapping whole tables in `try` hides real failures. Handle the *specific* fallible expression:

```powerquery
SafeDate = Table.TransformColumns(Prev,
    {{"finish_date", each try Date.From(_) otherwise null, type nullable date}})
```

- Raise intentional errors with context: `error Error.Record("SchemaDrift", "Expected column missing", [Column="task_code"])`.
- Cell-level errors survive into the model as blank + refresh warnings; step-level errors fail refresh. Decide which behaviour you want per case.

## Performance

- `Table.Buffer` pins a table in memory for the current evaluation — use it when a table is scanned repeatedly *within one query* (e.g. the right side of a `List.Generate` or repeated `Table.SelectRows` lookups). It breaks folding and consumes RAM: never buffer a source you could have folded.
- Merges: fold them (same source) or ensure the smaller table is bufferable. For lookup-style merges on large local data, `Table.Join` with `JoinAlgorithm.SortMerge` on pre-sorted keys can massively outperform default nested-loop behaviour — but only when both sides are genuinely sorted.
- Avoid row-by-row `Table.AddColumn` calling a function that itself queries a source (correlated subquery pattern) — this is the classic 10-minute→10-hour refresh. Restructure as a merge.
- Group/aggregate as early as possible; carry the narrowest table forward.

## Custom functions

```powerquery
// fnGetLatestFile: returns newest file content matching a pattern from a folder table
(folderTable as table, pattern as text) as binary =>
let
    Filtered = Table.SelectRows(folderTable, each Text.Contains([Name], pattern)),
    Sorted = Table.Sort(Filtered, {{"Date modified", Order.Descending}})
in
    Sorted{0}[Content]
```

- Type annotations (`as table`, `as text`) catch mistakes early and document intent.
- Keep functions pure where possible; a function that hits a data source creates firewall partitions (see below).
- Parameterise; don't hard-code environment values inside functions.

## Formula firewall / privacy levels

The firewall prevents data from one source being sent to another without matching privacy levels. Symptoms: "Query references other queries or steps, so it may not directly access a data source" — often Service-only.

Fixes, in order of preference:
1. Restructure so each query touches **one** source; combine in a downstream query.
2. Set privacy levels consistently (both Organizational, typically).
3. Only for personal/dev use: ignore privacy levels. Never ship that setting.

## Evaluation model gotchas

- M is lazy: a step defined but never referenced never runs. Diagnostic steps must be referenced to execute.
- `let` bindings are not sequential statements; they're expressions evaluated on demand. Order in the editor is convention, not execution order.
- Each query evaluation may hit the source **multiple times** (schema check + data). Sources with side effects or per-query costs (Athena!) feel this — one more reason to keep Athena logic in views and keep M thin.

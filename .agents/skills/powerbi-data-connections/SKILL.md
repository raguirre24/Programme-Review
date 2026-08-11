---
name: powerbi-data-connections
description: Connect Power BI to data sources reliably — SharePoint (files, folders, lists), Amazon Athena (ODBC/Simba), SQL databases, dataflows — and configure gateways, authentication, and environment parameterisation. Use this skill whenever the user mentions connecting Power BI to any data source, refresh failures tied to credentials or gateways, SharePoint file paths, Athena/S3 data, ODBC drivers, or moving a report between dev/test/prod environments. Use it even if the user only says "my refresh is failing" or "the connection broke".
---

# Power BI Data Connections

Reliable connectivity is mostly about three things: choosing the right connector for the job, keeping the connection foldable and gateway-compatible, and parameterising everything that differs between environments. Get these right up front — retrofitting them after a report is published is painful.

## Universal rules (apply to every source)

1. **Parameterise every connection string component.** Server, database, site URL, S3 staging directory, workgroup, environment name — all should be Power Query parameters, never hard-coded. This enables deployment pipelines rules and painless dev/test/prod switching.
2. **Never mix credential scopes.** One data source = one credential entry in the Service. If two queries hit the same source with different privacy levels or auth types, refresh breaks in non-obvious ways (formula firewall errors that only appear in the Service, not Desktop).
3. **Test refresh in the Service early**, not just Desktop. Desktop uses your user context; the Service uses stored credentials plus (possibly) a gateway. Many connections work in Desktop and fail on first scheduled refresh.
4. **Prefer sources the gateway doesn't need.** SharePoint Online and Athena (via a VNet or cloud connection where available) can refresh without an on-premises gateway. Only route through a gateway what genuinely requires it.

## SharePoint

### Files: choose the right connector

| Scenario | Connector | Notes |
|---|---|---|
| One stable file | `SharePoint.Files` or `Web.Contents` with the direct URL | `Web.Contents` is faster but the URL must be the *download* path, and it is less discoverable |
| Many files in a folder (combine pattern) | `SharePoint.Files` filtered by `Folder Path` | Filter **before** invoking the combine function; otherwise it enumerates the whole site |
| Very large sites (thousands of files) | `SharePoint.Contents` | Navigates folder-by-folder instead of listing every file on the site — dramatically faster |
| SharePoint list data | `SharePoint.Tables` with `Implementation="2.0"` | v2 is faster and returns friendlier column names |

Key facts:
- The connector URL is the **site** URL (`https://tenant.sharepoint.com/sites/ProjectX`), never a folder or file path. Filter to folders/files in M afterwards.
- `SharePoint.Files` on a big site is the number-one cause of slow refreshes. Switch to `SharePoint.Contents` and drill: `Source{[Name="Shared Documents"]}[Content]{[Name="Reports"]}[Content]`.
- Excel files stored in SharePoint frequently change schema (users add columns). Read defensively: select needed columns by name with `MissingField.UseNull`, and promote headers explicitly rather than by position.
- Authentication is Organizational account (OAuth). Service refresh needs a credential owner whose account keeps access — prefer a service account, not a person who might leave the project.

### Combine-files pattern, done safely

The auto-generated "Combine Files" helper queries are fragile. Prefer a hand-written pattern:

```powerquery
let
    Source = SharePoint.Contents("https://tenant.sharepoint.com/sites/W2TH", [ApiVersion = 15]),
    Folder = Source{[Name="Shared Documents"]}[Content]{[Name="MonthlyExports"]}[Content],
    Filtered = Table.SelectRows(Folder, each Text.EndsWith([Name], ".xlsx") and not Text.StartsWith([Name], "~")),
    Latest = Table.FirstN(Table.Sort(Filtered, {{"Date modified", Order.Descending}}), 1),
    Workbook = Excel.Workbook(Latest{0}[Content], null, true)
in
    Workbook
```

Always exclude `~$` lock files and consider taking only the latest file when exports accumulate.

## Amazon Athena

Athena connects via ODBC (Simba/Amazon Athena ODBC driver) or the native Athena connector (newer Desktop versions). Rules that matter:

- **Driver parity**: the exact same driver version must exist on every gateway machine in the cluster and ideally on developer desktops. Version drift causes "worked yesterday" refresh failures.
- **DSN-less connection strings** beat machine DSNs. A DSN configured on your laptop does not exist on the gateway. Use a connection string in `Odbc.DataSource` so the definition travels with the PBIX:

```powerquery
Odbc.DataSource(
    "Driver=Simba Athena ODBC Driver;AwsRegion=" & pRegion &
    ";S3OutputLocation=" & pS3Staging &
    ";Workgroup=" & pWorkgroup &
    ";AuthenticationType=IAM Credentials;",
    [HierarchicalNavigation = true]
)
```

- **Query folding**: Athena via ODBC folds basic filters/projections but not everything. Verify folding with "View Native Query". For heavy transformations, push logic into an Athena **view** or CTAS table instead of M — Athena scans cost money per TB and Power Query rarely writes efficient SQL.
- **Partitions are your friend**: if the underlying S3 data is partitioned (e.g. by `data_date` or project), ensure filters hit the partition column *with a foldable step* early in the query, or write native SQL with the partition predicate.
- **Native SQL**: `Odbc.Query` with hand-written SQL is legitimate and often the right call for Athena — it guarantees the scan is what you intend. Trade-off: it disables further folding, so do all filtering in the SQL.
- **Timeouts**: Athena queries queue. Set gateway timeout settings generously and prefer smaller, partition-pruned queries over one giant scan.
- Costs and speed both improve when source data is **Parquet** rather than CSV/JSON. If you control the pipeline, land Parquet with sensible partitioning.

## Gateways

- Gateway cluster > single gateway. Two members minimum for anything business-critical.
- The gateway impersonates nothing for cloud sources — check whether the source actually needs the gateway at all. A gateway in the path that isn't needed is a refresh failure waiting to happen.
- ODBC on a gateway: install the 64-bit driver, matching version, and restart the gateway service after install.
- "Mashup" errors in the Service that don't reproduce in Desktop are usually privacy levels / formula firewall. Fix by isolating sources into separate queries and setting privacy levels consistently, not by turning privacy checks off in production.

## Environment parameterisation pattern

Create these parameters in every model: `pEnvironment`, plus one per connection component. Then use deployment pipeline rules (or manual parameter edits in Service settings) to swap values per stage. Never create separate "dev" and "prod" copies of queries.

## Diagnosing refresh failures — checklist

1. Does it fail in Desktop too? If yes, it's the query/source. If Service-only: credentials, gateway, privacy levels, or timeouts.
2. Read the exact error class: `DataSource.Error` (source/driver), `Expression.Error` (M logic, often schema drift), `Formula.Firewall` (privacy levels / query interdependence), timeout (gateway or source performance).
3. Schema drift is the most common silent killer with file sources — a renamed column upstream. Defend with explicit column selection and `MissingField.UseNull`, and fail loudly with a validation query where correctness matters.

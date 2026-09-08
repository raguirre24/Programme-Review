# Export profiles and fixed contracts

Corrected implementation snapshot: 2026-09-07. Read actual headers rather than inferring profile from a table number or assuming an older build has these fixes. Field names/case below are intentional.

## Profile identity

| Property | Standard / legacy Enhanced | Programme Review | Tender Review |
| --- | --- | --- | --- |
| Versioned report contract | None | 4.0 | 2.0 |
| Numbered tables | 01,02,03,04,06,07,08,09,10,11,12,13,14,15 when generated/selected | 01,02,03,06,07,08,09,10,12,15 | Same ten as Programme |
| 05 | Not defined | Not defined | Not defined |
| Manifest | None | XER_CSV_MANIFEST.csv | XER_CSV_MANIFEST.csv |
| Public key | `<public-source-namespace>.<native-id>`; ordinary unique filenames retain legacy keys | `CSV::<PROJECT>::<C-or-T>::<snapshot-tag>::<native-id>` | `CSV::<PROJECT>::TENDER::<yyyyMMdd-status-date>::<native-id>` |
| Original filename uniqueness | Repeated filenames/paths/hashes are valid in one ordered batch | Duplicate input filenames rejected | Repeated filenames, paths, hashes and native IDs across stages are valid |
| Source occurrence identity | Immutable per-occurrence token, separate from public namespace and original filename | Shared parser occurrence tokens; governed snapshot filenames remain distinct | Stable ordered internal source token; never key input collections by filename/path/hash |
| Boolean output | Usually 0/1 fields; raw XER flags also exist | Contract booleans `true` / `false` | Contract booleans `true` / `false` |
| Date output | Raw source dates and derived formats coexist | Fixed date fields `yyyy-MM-dd` | Fixed date fields `yyyy-MM-dd` |
| Table 10 | Raw CALENDAR plus keys/metadata | Key and name only | Key and name only |
| Table 15 grain | Assignment x actual/remaining x month | Assignment x actual/remaining x month | Task x resource x actual/remaining x month within stage/project |

Both review profiles emit all ten fixed numbered tables, the supplemental `XER_DATA_QUALITY.csv`, and a manifest: twelve files. Their numbered schemas are Programme 4.0 / Tender 2.0 following the three new table 06 relationship-metadata columns; the companion is independently versioned `diagnostic_schema_version=1.2`. Standard emits the companion whenever any Enhanced numbered table is selected, alongside every selected numbered output, and leaves raw-only exports unchanged. Header-only output replaces stale data when no exportable rows exist; inspect warnings to distinguish unavailable input/calculations from genuinely empty source tables. Windows and Web make Enhanced tables available from their primary source alone: missing lookup tables do not hide available activity, relationship or assignment evidence.

Loaders locked to Programme 3.0/Tender 1.0 or the old exact table 06 header must explicitly accept the new versions and `free_float_status`, `free_float_basis`, `free_float_reason` before refreshing a new bundle. Update field typing/projection without coalescing blank float to zero. No external report, SharePoint loader or LongestPathVisual migration is performed by this exporter change. The optional relationship audit is separately versioned 1.1 with 46 columns.

Source-data problems are isolated to the affected rows, fields, calendar definitions or allocation portions across all Enhanced numbered tables. Available imported values and unaffected calculations remain exported; unresolved derived values stay blank with diagnostic evidence, not fabricated zeroes, calendars, dates or quantities. Malformed calendars and WBS identities must not suppress other valid rows or tables. Missing TASK/PROJWBS/CALENDAR sources produce their fixed header-only tables and warnings. Duplicate dimension keys and orphan references are preserved with warnings and may require source correction before a report can assert uniqueness. Programme leaves ambiguous task history blank; Tender retains individual contributions when an aggregate overflows or grouped labels conflict. Governed review PROJECT/request identity, snapshot/status metadata and safe publication remain separate: the exporter cannot guess these choices or claim success after unreadable input, cancellation or failed file writes. See the table dictionary for companion evidence and calculation rules for allocation reconciliation. A successful export with warnings is not a data-quality certification.

Programme project codes accept uppercase ASCII letters, digits and underscores; programme type is C or T. Programme also rejects duplicate source content. Tender codes accept uppercase ASCII letters and digits only and permits repeated content across distinct stages. Do not infer cross-profile identity by stripping punctuation.

### Internal identity versus report keys

The shared ordered parser assigns `SourceToken = <batch-GUID>:source-<six-digit-input-ordinal>`. This token remains unchanged for the parsed occurrence and is independent of filename, path and content hash. Its GUID is fresh per batch: it is not a persistent cross-run reporting key. Low-level parser calls also mint a fresh per-invocation token; they cannot silently share identity just because their filenames match. Tender binds parsed rows to its explicitly ordered governed stage tokens before calculations, including parsed-data entry points, without changing caller-owned rows. Shared calendar, task, relationship and resource lookups use the bound token; row copies retain it.

For Standard, `SourceFilename` is the public key namespace. A unique input keeps its trimmed original filename. Every colliding name receives a deterministic `#source-000001`-style suffix based on input order; an extra numeric suffix avoids collision with an unusual real filename already using that spelling. Matching/reservations are case-insensitive and whitespace-normalized. `OriginalSourceFilename` remains the supplied provenance for CSV `FileName` and filename-derived `MonthUpdate`. Consume the exported keys rather than recreating these namespaces in a report.

Inputs must remain an ordered sequence, including repeated occurrences. Independently parsed batches have distinct internal tokens, but merging batches with the same public namespace is rejected at Standard export: reparse those sources together so public keys can be allocated consistently. Do not fix that rejection by dropping repeated files. Tender's governed source-token/stage path remains independent of this Standard naming rule. Programme filters its resolved retained snapshots before calendar/resource calculations, including for parsed-data entry points; discarded snapshots do not participate in those calculations.

## Date and history meaning

Programme snapshots are Baseline (`BLnn`, optionally a suffix such as `BL01-A`) or Update (`YYMM`). The service resolves the retained baseline anchor and applicable updates before export; not every supplied file necessarily survives. Canonical filenames are `<PROJECT>-<C/T>-<TAG>_<yyyyMMdd-data-date>.xer`. `UpdateDate` is the effective report update date (update month-end for monthly updates); `data_date` comes from snapshot metadata and is validated against the project's P6 Data Date. Do not substitute one date for the other.

Programme history is matched across snapshots by project/activity business identity, not by the snapshot-qualified `task_id_key`. Previous activity values can refer to the previous observed snapshot containing that activity; `PreviousDataDate` follows project date history. Missing activity snapshots matter. History variances use the profile's weekday business rule, not task calendars; see calculation rules.

Tender canonical filenames are `<PROJECT>-TENDER-<yyyyMMdd-status-date>.xer`. `status_date` and `UpdateDate` are the selected stage status date. `data_date` and `monthupdate` are the independently read P6 `PROJECT.last_recalc_date`. `udf_datalake_status_date` reflects the selected status date; `add_date` is independent source project metadata. A status date must be unique per project within a bundle. Never collapse two stages because their hashes match. The source token protects parsing identity; the public namespace identifies the stage in reports.

Numbered review-table dates are date-only. They cannot reconstruct intraday relationship calculations or shifts; the parser uses timestamps before serialization. The diagnostic companion instead preserves source date strings, including timestamps and malformed values; import those diagnostic fields as text.

## Exact Programme Review headers

01_XER_TASK (47):

```text
status_code,task_code,total_float,task_type,id_name,early_start_date,calendar_id_key,task_id_key,driving_path_flag,remaining_duration,early_end_date,monthupdate,task_name,data_date,act_end_date,Finish,proj_id_key,wbs_id_key,free_float,cstr_type,Start,filename,late_end_date,ProjectCode,UpdateDate,ProjectName,Finish_Variance_Previous_Month,Driven_DataDate,Variance_Finish_BL,Variance_Finish_Adjusted_BL,Baseline Finish,Baseline Start,Previous Month Start,Previous Month Finish,Planned Not Completed Last Period,Start_Variance_Previous_Month,PreviousDataDate,Previous Remaining Working Days,Planned Last Period,Completed Last Period,Completed of Planned Last Period,Baseline Effective_Early_End,Baseline Effective_Late_End,Adjusted Baseline Finish,Adjusted Baseline Start,Adjusted Baseline Source Month,Adjusted Baseline Source
```

02_XER_PROJECT:

```text
last_recalc_date,proj_id_key,monthupdate,ProjectCode
```

## Exact Tender Review headers

01_XER_TASK (27):

```text
status_code,task_code,total_float,task_type,id_name,early_start_date,calendar_id_key,task_id_key,driving_path_flag,remaining_duration,early_end_date,monthupdate,status_date,task_name,data_date,act_end_date,Finish,proj_id_key,wbs_id_key,free_float,cstr_type,Start,filename,late_end_date,ProjectCode,UpdateDate,ProjectName
```

02_XER_PROJECT:

```text
last_recalc_date,proj_id_key,monthupdate,ProjectCode,add_date,state,region,tender_status,udf_datalake_status_date
```

## Eight shared review table headers

```text
03_XER_PROJWBS:
wbs_name,wbs_id_key,parent_wbs_id_key,ProjectCode

06_XER_PREDECESSOR:
task_id_key,pred_type,predecessor_status_code,task_type,predecessor_task_type,lag,start,finish,predecessor_start,predecessor_finish,free_float,free_float_status,free_float_basis,free_float_reason,pred_task_id_key,status_code,total_float,task_pred_id_key,ProjectCode

07_XER_ACTVTYPE:
actv_code_type_id_key,actv_code_type

08_XER_ACTVCODE:
actv_code_id_key,actv_code_name,actv_code_type_id_key

09_XER_TASKACTV:
task_id_key,actv_code_id_key

10_XER_CALENDAR:
clndr_id_key,clndr_name

12_XER_RSRC:
rsrc_id_key,def_qty_per_hr

15_XER_RESOURCE_DISTRIBUTION:
task_id_key,rsrc_id_key,is_actual,distribution_month,monthly_quantity,rsrc_name,rsrc_type,unit,ProjectCode
```

`12.def_qty_per_hr` is text in the contract and represents a source default units/time rate, not earned units. Table 01 status labels are `Not Started`, `In Progress`, `Complete`; relationship status fields in 06 retain raw `TK_*` codes. `pred_type` preserves the relationship type. Do not use one status-label filter on both tables.

## Manifests

Programme headers:

```text
schema_version,bundle_id,bundle_status,parser_version,project_code,project_name,programme_type,original_xer_filename,canonical_xer_filename,snapshot_kind,snapshot_tag,monthupdate,update_date,data_date,source_sha256,table_name,row_count,csv_sha256,exported_at_utc
```

Tender headers:

```text
schema_version,bundle_profile,bundle_id,bundle_status,parser_version,project_code,project_name,original_xer_filename,canonical_xer_filename,status_date,update_date,data_date,source_sha256,table_name,row_count,csv_sha256,exported_at_utc
```

Programme completion literal remains `complete`; Tender uses `COMPLETE` and `bundle_profile=tender_review`. These indicate completed publication, not absence of warnings. Manifest rows describe each retained snapshot/stage and each exported table, including `table_name=XER_DATA_QUALITY`: eleven manifest rows per retained source. The companion's per-source row count is its warning count; its hash is validated like numbered CSVs. Validate the declared version/profile, source-stage coverage, row counts at the declared source/table grain, and CSV hashes against actual files. Consumers hard-coded to eleven bundle files or ten manifest rows per source must accept the approved supplemental artifact; Programme 4.0/Tender 2.0 also require the expanded table 06 headers shown above. A CSV hash can repeat for the same combined table across manifest source rows; it does not make those source rows duplicates. Do not assemble one export from files belonging to different bundles or attach old files to a new manifest. Independently validated bundles can coexist in a comparison model when profile/bundle/scenario provenance remains explicit; public keys can recur across successive bundles, so do not accidentally join or sum duplicate snapshots across them.

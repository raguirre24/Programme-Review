[CmdletBinding()]
param(
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [string]$OutputDirectory,
    [int]$Top = 40,
    [double]$MaxModelMB = 0,
    [switch]$SkipProjects
)
# Read-only VertiPaq memory and column-usage audit for the open Programme Review model.
# Reads storage DMVs, the engine's calculation dependencies and the PBIR report JSON; never refreshes,
# runs TMSL or saves. Usage status: REPORT (bound in a visual, filter or bookmark), VIA:<object> (needed by
# a used measure or calculated column), RELATIONSHIP, RLS, SORTBY:<column>, CALCTABLE:<table> or UNUSED.
# Run it with the Service parameters (SelectedProjects = ALL) loaded to judge the 1 GB Pro limit.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot '../schedule_metrics/Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory

function Get-Member($node, [string]$name) {
    if ($node -isnot [pscustomobject]) { return $null }
    $property = $node.PSObject.Properties[$name]
    if ($property) { $property.Value } else { $null }
}

# Report references: every Column/Measure/Aggregation/HierarchyLevel node, resolving filter "From" aliases.
$reportRefs = [Collections.Generic.HashSet[string]]::new()
function Add-ReportRefs($node, [hashtable]$aliases) {
    if ($null -eq $node) { return }
    if ($node -is [System.Collections.IList]) { foreach ($item in $node) { Add-ReportRefs $item $aliases }; return }
    if ($node -isnot [pscustomobject]) { return }
    $scope = $aliases
    $from = Get-Member $node 'From'
    if ($from -is [System.Collections.IList]) {
        $scope = @{} + $aliases
        foreach ($source in $from) {
            $name = Get-Member $source 'Name'; $entity = Get-Member $source 'Entity'
            if ($name -and $entity) { $scope[$name] = $entity }
        }
    }
    foreach ($kind in 'Column', 'Measure', 'Aggregation', 'HierarchyLevel') {
        $field = Get-Member $node $kind
        $property = Get-Member $field 'Property'
        $sourceRef = Get-Member (Get-Member $field 'Expression') 'SourceRef'
        if (-not $property -or -not $sourceRef) { continue }
        $entity = Get-Member $sourceRef 'Entity'
        if (-not $entity) { $alias = Get-Member $sourceRef 'Source'; if ($alias) { $entity = $scope[$alias] } }
        if ($entity) { [void]$reportRefs.Add("$entity|$property") }
    }
    foreach ($property in $node.PSObject.Properties) {
        if ($property.Value -is [pscustomobject] -or $property.Value -is [System.Collections.IList]) { Add-ReportRefs $property.Value $scope }
    }
}
$reportRoot = Join-Path $PSScriptRoot '../../Project Review - Programme (datalake).Report/definition'
foreach ($file in Get-ChildItem -LiteralPath $reportRoot -Recurse -Filter *.json) {
    Add-ReportRefs (Get-Content -Raw -LiteralPath $file.FullName | ConvertFrom-Json -Depth 200) @{}
}

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
try {
    $model = $target.Database.Model
    $dictionary = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query (
        "SELECT DIMENSION_NAME, ATTRIBUTE_NAME, COLUMN_ID, DICTIONARY_SIZE FROM `$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS WHERE COLUMN_TYPE = 'BASIC_DATA'")
    $segments = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query (
        "SELECT DIMENSION_NAME, TABLE_ID, COLUMN_ID, RECORDS_COUNT, USED_SIZE FROM `$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS")
    $storages = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query (
        "SELECT [Name], [Statistics_DistinctStates] FROM `$SYSTEM.TMSCHEMA_COLUMN_STORAGES")
    $dependencies = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query (
        "SELECT [OBJECT_TYPE], [TABLE], [OBJECT], [REFERENCED_OBJECT_TYPE], [REFERENCED_TABLE], [REFERENCED_OBJECT] FROM `$SYSTEM.DISCOVER_CALC_DEPENDENCY")
    $projectRows = @()
    if (-not $SkipProjects) {
        $projectRows = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query @"
EVALUATE
SUMMARIZECOLUMNS(
    '01 XER_TASK'[ProjectCode],
    "Updates", DISTINCTCOUNT('01 XER_TASK'[UpdateDate]),
    "Tasks", COUNTROWS('01 XER_TASK'),
    "Links", COUNTROWS('06 XER_PREDECESSOR'),
    "CodeAssignments", COUNTROWS('09 XER_TASKACTV'),
    "ResourceRows", COUNTROWS('15_XER_RESOURCE_DISTRIBUTION')
)
ORDER BY [Tasks] DESC
"@
    }
} finally { $target.Connection.Disconnect() }

# Sizes per column: dictionary + data segments + attribute hierarchy (H$); relationships (R$) per table.
$cardinality = @{}; foreach ($row in $storages) { $cardinality[$row.Name] = $row.Statistics_DistinctStates }
$columnName = @{}; $sizes = @{}
foreach ($row in $dictionary) {
    $columnName["$($row.DIMENSION_NAME)|$($row.COLUMN_ID)"] = $row.ATTRIBUTE_NAME
    $sizes["$($row.DIMENSION_NAME)|$($row.ATTRIBUTE_NAME)"] = [ordered]@{
        Dictionary = [int64]$row.DICTIONARY_SIZE; Data = 0L; Hierarchy = 0L; Cardinality = $cardinality[$row.COLUMN_ID] }
}
$tableRows = @{}; $relationshipBytes = @{}; $userHierarchyBytes = 0L
foreach ($row in $segments) {
    $segmentTable = [string]$row.TABLE_ID
    if ($segmentTable.StartsWith('R$')) { $relationshipBytes[$row.DIMENSION_NAME] += [int64]$row.USED_SIZE; continue }
    if ($segmentTable.StartsWith('U$')) { $userHierarchyBytes += [int64]$row.USED_SIZE; continue }
    $isHierarchy = $segmentTable.StartsWith('H$')
    $columnId = if ($isHierarchy) { $segmentTable.Substring(2).Split('$')[-1] } else { [string]$row.COLUMN_ID }
    if (-not $isHierarchy -and $columnId -like 'RowNumber*') { $tableRows[$row.DIMENSION_NAME] += [int64]$row.RECORDS_COUNT }
    $name = $columnName["$($row.DIMENSION_NAME)|$columnId"]
    if (-not $name) { continue }
    if ($isHierarchy) { $sizes["$($row.DIMENSION_NAME)|$name"].Hierarchy += [int64]$row.USED_SIZE }
    else { $sizes["$($row.DIMENSION_NAME)|$name"].Data += [int64]$row.USED_SIZE }
}

# Usage closure from the report, relationships, RLS and calculated tables through measures and calculated columns.
$referencesOf = @{}
foreach ($row in $dependencies) {
    $key = "$($row.TABLE)|$($row.OBJECT)"
    if (-not $referencesOf.ContainsKey($key)) { $referencesOf[$key] = [Collections.Generic.List[object]]::new() }
    $referencesOf[$key].Add($row)
}
$usage = @{}
$queue = [Collections.Generic.Queue[string]]::new()
function Add-Usage([string]$key, [string]$reason) {
    if (-not $usage.ContainsKey($key)) { $usage[$key] = $reason; $queue.Enqueue($key) }
}
foreach ($reference in $reportRefs) { Add-Usage $reference 'REPORT' }
foreach ($relationship in $model.Relationships) {
    Add-Usage "$($relationship.FromTable.Name)|$($relationship.FromColumn.Name)" 'RELATIONSHIP'
    Add-Usage "$($relationship.ToTable.Name)|$($relationship.ToColumn.Name)" 'RELATIONSHIP'
}
foreach ($row in $dependencies) {
    if (-not $row.REFERENCED_OBJECT -or $row.REFERENCED_OBJECT_TYPE -eq 'TABLE') { continue }
    if ($row.OBJECT_TYPE -eq 'ROWS_ALLOWED') { Add-Usage "$($row.REFERENCED_TABLE)|$($row.REFERENCED_OBJECT)" 'RLS' }
    elseif ($row.OBJECT_TYPE -eq 'CALC_TABLE') { Add-Usage "$($row.REFERENCED_TABLE)|$($row.REFERENCED_OBJECT)" "CALCTABLE:$($row.TABLE)" }
}
while ($queue.Count) {
    $key = $queue.Dequeue()
    $tableName, $objectName = $key.Split('|', 2)
    $table = $model.Tables.Find($tableName)
    $column = if ($table) { $table.Columns.Find($objectName) } else { $null }
    if ($column -and $column.SortByColumn) { Add-Usage "$tableName|$($column.SortByColumn.Name)" "SORTBY:$objectName" }
    if (-not $referencesOf.ContainsKey($key)) { continue }
    foreach ($row in $referencesOf[$key]) {
        if ($row.REFERENCED_OBJECT -and $row.REFERENCED_OBJECT_TYPE -in 'COLUMN', 'CALC_COLUMN', 'MEASURE') {
            Add-Usage "$($row.REFERENCED_TABLE)|$($row.REFERENCED_OBJECT)" "VIA:$objectName"
        }
    }
}

$columns = foreach ($table in $model.Tables) {
    $calculatedTable = $table.Partitions.Count -and $table.Partitions[0].SourceType -eq 'Calculated'
    foreach ($column in $table.Columns) {
        if ($column.Type -eq 'RowNumber') { continue }
        $key = "$($table.Name)|$($column.Name)"
        $size = $sizes[$key]
        $kind = switch ($column.Type) { 'Calculated' { 'Calculated column' } 'CalculatedTableColumn' { 'Calculated table' } default { 'Imported' } }
        [pscustomobject]@{
            Table = $table.Name; Column = $column.Name; Kind = $(if ($calculatedTable -and $kind -eq 'Imported') { 'Calculated table' } else { $kind })
            DataType = [string]$column.DataType; Hidden = $column.IsHidden; MdxHierarchy = $column.IsAvailableInMDX
            Cardinality = $(if ($size) { $size.Cardinality } else { $null })
            TotalMB = $(if ($size) { [math]::Round(($size.Dictionary + $size.Data + $size.Hierarchy) / 1MB, 3) } else { 0 })
            DictionaryMB = $(if ($size) { [math]::Round($size.Dictionary / 1MB, 3) } else { 0 })
            DataMB = $(if ($size) { [math]::Round($size.Data / 1MB, 3) } else { 0 })
            HierarchyMB = $(if ($size) { [math]::Round($size.Hierarchy / 1MB, 3) } else { 0 })
            Usage = $(if ($usage.ContainsKey($key)) { $usage[$key] } else { 'UNUSED' })
        }
    }
}
$tables = $columns | Group-Object Table | ForEach-Object {
    $columnMB = ($_.Group | Measure-Object TotalMB -Sum).Sum
    [pscustomobject]@{
        Table = $_.Name; Rows = [int64]$tableRows[$_.Name]; Columns = $_.Count
        ColumnsMB = [math]::Round($columnMB, 2); RelationshipsMB = [math]::Round($relationshipBytes[$_.Name] / 1MB, 2)
        TotalMB = [math]::Round($columnMB + $relationshipBytes[$_.Name] / 1MB, 2)
    }
} | Sort-Object TotalMB -Descending
$totalMB = [math]::Round(($tables | Measure-Object TotalMB -Sum).Sum + $userHierarchyBytes / 1MB, 1)
$unused = @($columns | Where-Object Usage -eq 'UNUSED' | Sort-Object TotalMB -Descending)

"Model: $totalMB MB (columns and relationships; hierarchies $([math]::Round(($columns | Measure-Object HierarchyMB -Sum).Sum, 1)) MB of it)"
# Straight after a refresh each string dictionary holds a working allocation of about 1 MB however few values it
# has; it is compacted when the model is saved and reopened. Sizes measured in that state are not comparable.
$inflated = @($columns | Where-Object { $_.DataType -eq 'String' -and $null -ne $_.Cardinality -and [int64]$_.Cardinality -lt 1000 -and $_.DictionaryMB -ge 0.9 })
if ($inflated.Count -ge 5) {
    Write-Warning "$($inflated.Count) low-cardinality text columns report about 1 MB dictionaries: the model was measured straight after a refresh. Save, close and reopen Power BI Desktop, then measure again."
}
"`n=== Tables ==="
$tables | Format-Table -AutoSize | Out-String -Width 200
"=== Top $Top columns ==="
$columns | Sort-Object TotalMB -Descending | Select-Object -First $Top Table, Column, Kind, Cardinality, TotalMB, DictionaryMB, DataMB, HierarchyMB, Usage |
    Format-Table -AutoSize | Out-String -Width 220
"=== Unused columns: $($unused.Count), $([math]::Round(($unused | Measure-Object TotalMB -Sum).Sum, 2)) MB ==="
$unused | Select-Object Table, Column, Kind, TotalMB | Format-Table -AutoSize | Out-String -Width 200
if ($projectRows.Count) {
    "=== Rows per project ==="
    $projectRows | Format-Table -AutoSize | Out-String -Width 200
}
if ($OutputDirectory) {
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    $columns | Export-Csv -NoTypeInformation -Encoding utf8 (Join-Path $OutputDirectory 'columns.csv')
    $tables | Export-Csv -NoTypeInformation -Encoding utf8 (Join-Path $OutputDirectory 'tables.csv')
    if ($projectRows.Count) { $projectRows | Export-Csv -NoTypeInformation -Encoding utf8 (Join-Path $OutputDirectory 'projects.csv') }
    "Wrote columns.csv, tables.csv$(if ($projectRows.Count) { ', projects.csv' }) to $OutputDirectory"
}
if ($MaxModelMB -gt 0 -and $totalMB -gt $MaxModelMB) { throw "Model is $totalMB MB, above the $MaxModelMB MB limit." }

[CmdletBinding()]
param(
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [switch]$FailOnUnused
)
# Read-only: lists tables, relationships, measures, columns, RLS permissions and M expressions the report
# does not use, from the open Desktop model (inventory and the engine's DISCOVER_CALC_DEPENDENCY) and the
# PBIR report JSON. The rules are in find_unused_objects.py. Never refreshes, runs TMSL or saves.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot '../schedule_metrics/Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
try {
    $model = $target.Database.Model
    $dependencies = Invoke-ScheduleMetricsDax -Target $target -TimeoutSeconds 600 -Query (
        "SELECT [OBJECT_TYPE], [TABLE], [OBJECT], [REFERENCED_OBJECT_TYPE], [REFERENCED_TABLE], [REFERENCED_OBJECT] FROM `$SYSTEM.DISCOVER_CALC_DEPENDENCY")
    $expressions = [Collections.Generic.List[object]]::new()
    $tables = foreach ($table in $model.Tables) {
        $source = $table.Partitions[0].Source
        $isCalculated = $source -is [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]
        if ($isCalculated) { $expressions.Add([ordered]@{ kind = 'T'; table = $table.Name; name = $null; expression = $source.Expression }) }
        foreach ($measure in $table.Measures) { $expressions.Add([ordered]@{ kind = 'M'; table = $table.Name; name = $measure.Name; expression = $measure.Expression }) }
        foreach ($column in $table.Columns) {
            if ($column.Type -eq 'Calculated') { $expressions.Add([ordered]@{ kind = 'C'; table = $table.Name; name = $column.Name; expression = $column.Expression }) }
        }
        [ordered]@{
            name = $table.Name; kind = $(if ($isCalculated) { 'calc' } else { 'M' })
            measures = @($table.Measures | ForEach-Object Name)
            columns = @($table.Columns | Where-Object Type -ne 'RowNumber' | ForEach-Object {
                [ordered]@{ name = $_.Name; type = [string]$_.Type; sortBy = $(if ($_.SortByColumn) { $_.SortByColumn.Name } else { $null }) } })
        }
    }
    $document = [ordered]@{
        tables = @($tables)
        expressions = $expressions
        relationships = @($model.Relationships | ForEach-Object {
            [ordered]@{ name = $_.Name; from = $_.FromTable.Name; fromCol = $_.FromColumn.Name; to = $_.ToTable.Name; toCol = $_.ToColumn.Name } })
        mExpressions = @($model.Expressions | ForEach-Object Name)
        dependencies = @($dependencies | ForEach-Object {
            [ordered]@{ ot = $_.OBJECT_TYPE; t = $_.TABLE; o = $_.OBJECT; rt = $_.REFERENCED_OBJECT_TYPE; rtab = $_.REFERENCED_TABLE; ro = $_.REFERENCED_OBJECT } })
    }
} finally { $target.Connection.Disconnect() }

$arguments = @((Join-Path $PSScriptRoot 'find_unused_objects.py'))
if ($FailOnUnused) { $arguments += '--fail-on-unused' }
$document | ConvertTo-Json -Depth 8 -Compress | python @arguments
exit $LASTEXITCODE

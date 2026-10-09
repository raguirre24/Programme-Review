param(
    [string]$ModelRoot,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory
)

# Validate what Desktop currently executes. Intentionally do not use query-scoped
# definitions: proposed-expression tests cannot establish loaded report behaviour.
. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
if (-not $ModelRoot) {
    $ModelRoot = Join-Path $PSScriptRoot '../../Project Review - Programme (datalake).SemanticModel/definition'
}
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $ModelRoot).Path)
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$assertions = 0
$gauges = @{}
$series = [Collections.Generic.List[object]]::new()

function Invoke-LoadedDetailQuery {
    param([string]$Query)
    if ($Query -match '(?im)^\s*DEFINE\b') { throw 'Loaded validation must not override the live model.' }
    return ,(Invoke-ScheduleMetricsDax $target $Query -TimeoutSeconds 30)
}

function Get-LoadedDetailFilter {
    param($Snapshot)
    $project = $Snapshot.'01 XER_TASK[ProjectCode]'.Replace('"', '""')
    $programme = $Snapshot.'01 XER_TASK[ProgrammeType]'.Replace('"', '""')
    $date = [datetime]$Snapshot.'01 XER_TASK[UpdateDate]'
    # Include the actual Schedule Metrics page filters and report governance.
    return @"
TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),
TREATAS({"$programme"},'01 XER_TASK'[ProgrammeType]),
TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},CurrentDate[UpdateDate]),
TREATAS({"In Progress","Not Started"},'01 XER_TASK'[status_code]),
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),
TREATAS({FALSE()},'01 XER_TASK'[Is Unscheduled]),
TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake])
"@
}

function Get-LoadedDetailKey {
    param([string]$Project, [string]$Programme, [datetime]$Date, [int]$ID)
    return '{0}|{1}|{2:yyyy-MM-dd}|{3}' -f $Project,$Programme,$Date,$ID
}

try {
    $disk = $model.Tables.Find('Schedule Metric Detail')
    $live = $target.Database.Model.Tables.Find('Schedule Metric Detail')
    Assert-ScheduleMetric ($null -ne $live) 'Detail table must be loaded in Desktop.'
    Assert-ScheduleMetric ($disk.Measures.Count -eq $live.Measures.Count) 'Live/disk detail measure counts differ.'
    $assertions += 2
    foreach ($measure in $disk.Measures) {
        $loaded = $live.Measures.Find($measure.Name)
        Assert-ScheduleMetric ($null -ne $loaded) "Missing loaded measure: $($measure.Name)"
        Assert-ScheduleMetric ($measure.Expression.Trim() -eq $loaded.Expression.Trim()) "Loaded expression differs: $($measure.Name)"
        Assert-ScheduleMetric ($measure.FormatString -eq $loaded.FormatString) "Loaded static format differs: $($measure.Name)"
        $diskFormat = if ($measure.FormatStringDefinition) { $measure.FormatStringDefinition.Expression } else { '' }
        $liveFormat = if ($loaded.FormatStringDefinition) { $loaded.FormatStringDefinition.Expression } else { '' }
        Assert-ScheduleMetric ($diskFormat -eq $liveFormat) "Loaded dynamic format differs: $($measure.Name)"
        $assertions += 4
    }
    Assert-ScheduleMetric ($live.Columns.Find('Metric').SortByColumn.Name -eq 'Metric ID') 'Selector sort-by contract changed.'
    $assertions++
    $snapshots = Invoke-LoadedDetailQuery @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate]
'@

    foreach ($snapshot in $snapshots) {
        $filter = Get-LoadedDetailFilter $snapshot
        # Grouping by label+ID reproduces the native selector sort-by context;
        # the other two columns independently remove it and apply label-only/ID-only.
        $rows = Invoke-LoadedDetailQuery @"
EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('Schedule Metric Detail'[Metric],'Schedule Metric Detail'[Metric ID],
"Gauge",[SM Detail Value],
"LabelGauge",VAR Label=SELECTEDVALUE('Schedule Metric Detail'[Metric]) RETURN CALCULATE([SM Detail Value],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({Label},'Schedule Metric Detail'[Metric])),
"IDGauge",VAR SelectedMetricID=SELECTEDVALUE('Schedule Metric Detail'[Metric ID]) RETURN CALCULATE([SM Detail Value],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({SelectedMetricID},'Schedule Metric Detail'[Metric ID])),
"Maximum",[SM Detail Maximum],"Format",[SM Detail Format],"Status",[SM Detail Status],"Colour",[SM Detail Colour]),$filter)
"@
        Assert-ScheduleMetric ($rows.Count -eq 4) 'Every live snapshot must expose all four selector choices.'
        $assertions++
        foreach ($row in $rows) {
            $id = [int]$row.'Schedule Metric Detail[Metric ID]'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Gauge]' $row.'[LabelGauge]') 'Label-only gauge differs from label+sort-ID context.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Gauge]' $row.'[IDGauge]') 'ID-only gauge differs from label+sort-ID context.'
            Assert-ScheduleMetric ($row.'[Format]' -eq $(if ($id -eq 2) { '0.00' } else { '0.0%' })) 'Loaded selector numeric format is wrong.'
            if ($null -ne $row.'[Gauge]') {
                Assert-ScheduleMetric ([double]$row.'[Gauge]' -ge 0 -and [double]$row.'[Gauge]' -le [double]$row.'[Maximum]') 'Loaded gauge maximum clips its numeric value.'
                $assertions++
            }
            $assertions += 3
            $key = Get-LoadedDetailKey $snapshot.'01 XER_TASK[ProjectCode]' $snapshot.'01 XER_TASK[ProgrammeType]' $snapshot.'01 XER_TASK[UpdateDate]' $id
            $gauges[$key] = $row.'[Gauge]'
        }
        Write-Output ('PASS loaded gauges {0} {1:yyyy-MM-dd}: four metrics, label/ID/both filters' -f $snapshot.'01 XER_TASK[ProjectCode]',[datetime]$snapshot.'01 XER_TASK[UpdateDate]')
    }

    foreach ($snapshot in $snapshots) {
        $filter = Get-LoadedDetailFilter $snapshot
        $rows = Invoke-LoadedDetailQuery @"
EVALUATE FILTER(CALCULATETABLE(SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],'Schedule Metric Detail'[Metric],'Schedule Metric Detail'[Metric ID],
"History",[SM Detail History],"InScope",[SM Detail History In Scope],
"LabelHistory",VAR Label=SELECTEDVALUE('Schedule Metric Detail'[Metric]) RETURN CALCULATE([SM Detail History],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({Label},'Schedule Metric Detail'[Metric])),
"IDHistory",VAR SelectedMetricID=SELECTEDVALUE('Schedule Metric Detail'[Metric ID]) RETURN CALCULATE([SM Detail History],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({SelectedMetricID},'Schedule Metric Detail'[Metric ID]))),$filter),[InScope]=1)
ORDER BY 'Schedule Metric Detail'[Metric ID],UpdateHistory[UpdateDate]
"@
        $expected = @($snapshots | Where-Object {
            $_.'01 XER_TASK[ProjectCode]' -eq $snapshot.'01 XER_TASK[ProjectCode]' -and
            $_.'01 XER_TASK[ProgrammeType]' -eq $snapshot.'01 XER_TASK[ProgrammeType]' -and
            [datetime]$_.'01 XER_TASK[UpdateDate]' -le [datetime]$snapshot.'01 XER_TASK[UpdateDate]'
        }).Count * 4
        Assert-ScheduleMetric ($rows.Count -eq $expected) 'Loaded history omits an existing snapshot or shows a point beyond the selected cutoff.'
        $assertions++
        foreach ($row in $rows) {
            $id = [int]$row.'Schedule Metric Detail[Metric ID]'
            $axis = [datetime]$row.'UpdateHistory[UpdateDate]'
            $key = Get-LoadedDetailKey $snapshot.'01 XER_TASK[ProjectCode]' $snapshot.'01 XER_TASK[ProgrammeType]' $axis $id
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[History]' $row.'[LabelHistory]') 'Loaded history differs under label-only selector filtering.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[History]' $row.'[IDHistory]') 'Loaded history differs under ID-only selector filtering.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[History]' $gauges[$key]) 'Loaded history point differs from the gauge at that snapshot.'
            $assertions += 3
            $series.Add([pscustomobject]@{Project=$snapshot.'01 XER_TASK[ProjectCode]'; Programme=$snapshot.'01 XER_TASK[ProgrammeType]'; Cutoff=$snapshot.'01 XER_TASK[UpdateDate]'; Axis=$axis; ID=$id; Value=$row.'[History]'})
        }
        Write-Output ('PASS loaded histories {0} cutoff {1:yyyy-MM-dd}: {2} points, label/ID/both filters' -f $snapshot.'01 XER_TASK[ProjectCode]',[datetime]$snapshot.'01 XER_TASK[UpdateDate]',$rows.Count)
    }

    $latestSeries = @($series | Group-Object Project,Programme | ForEach-Object {
        $latest = ($_.Group | Sort-Object Cutoff | Select-Object -Last 1).Cutoff
        $_.Group | Where-Object { $_.Cutoff -eq $latest }
    })
    [pscustomobject]@{
        Status='PASS'; Scope='Actual loaded Desktop expressions and data, no query overrides or model writes; native rendering remains separate.'
        Server=$target.Address; Catalog=$target.Database.ID; MeasuresCompared=$disk.Measures.Count
        Snapshots=$snapshots.Count; GaugeCells=$gauges.Count; HistoryCellsAcrossAllCutoffs=$series.Count
        SelectorFilterModes=3; Assertions=$assertions; LatestSeries=$latestSeries
    } | ConvertTo-Json -Depth 5
} finally { $target.Connection.Disconnect() }

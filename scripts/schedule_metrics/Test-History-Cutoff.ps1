[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [switch]$UseLoadedModel
)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder(
    (Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'))
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$rates = @('MissingPredecessor%', 'MissingSuccessor%', 'HighFloat%', 'HighDur%',
    'Lags%', '<0Lead%', '<0Float%', '0Float%', 'Constraint%', 'Score',
    'SM Missing Logic %', 'SM FS %', 'SM Invalid Dates %')
$pageFilters = @'
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),
TREATAS({"Not Started","In Progress"},'01 XER_TASK'[status_code]),
TREATAS({FALSE()},'01 XER_TASK'[Is Unscheduled]),
TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake])
'@
$cases = @(
    @{ Project='J4007'; Dates=@('2026-09-30'); Name='absent September cutoff preserves five past snapshots' },
    @{ Project='J4007'; Dates=@('2026-08-31'); Name='available latest cutoff' },
    @{ Project='J4007'; Dates=@('2026-06-30'); Name='earlier cutoff excludes later snapshots' },
    @{ Project='J4007'; Dates=@('2026-03-31','2026-06-30'); Name='multiple earlier dates use maximum explicit cutoff' },
    @{ Project='J4007'; Dates=@('2026-08-31','2026-09-30'); Name='multiple dates retain absent maximum cutoff' },
    @{ Project='J4007'; Dates=@(); Name='no explicit date preserves existing maximum fallback' },
    @{ Project='J5064'; Dates=@('2026-09-30'); Name='other project latest cutoff unchanged' },
    @{ Project='J5064'; Dates=@('2026-03-31','2026-06-30'); Name='other project multiple earlier dates' }
)
function Dax-Date([datetime]$Value) { return "DATE($($Value.Year),$($Value.Month),$($Value.Day))" }
function Metric-Projection([string]$Suffix='') {
    return (($rates | ForEach-Object { '"' + $_ + '",[' + $_ + $Suffix + ']' }) -join ',')
}
function Context-Filters([string]$ProjectName, [string[]]$Dates) {
    $projectFilter = 'TREATAS({"' + $ProjectName.Replace('"','""') + '"},Project_Dimension[Project])'
    $parts = @($projectFilter, $pageFilters)
    if ($Dates.Count) { $parts += 'TREATAS({' + (($Dates | ForEach-Object { Dax-Date ([datetime]$_) }) -join ',') + '},CurrentDate[UpdateDate])' }
    return $parts -join ','
}

try {
    $definitions = if ($UseLoadedModel) { '' } else {
        Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model
    }
    if ($UseLoadedModel) {
        Assert-ScheduleMetric ($target.Database.Model.Tables['XER Metrics'].Measures.Contains('SM Selected History Cutoff')) 'The cutoff fix is not loaded.'
    }
    $projects = Invoke-ScheduleMetricsDax -Target $target -Query @'
EVALUATE SELECTCOLUMNS(FILTER(Project_Dimension,Project_Dimension[ProjectCode] IN {"J4007","J5064"}),
"Code",Project_Dimension[ProjectCode],"Project",Project_Dimension[Project])
'@
    $inventory = Invoke-ScheduleMetricsDax -Target $target -Query @'
EVALUATE SUMMARIZE('01 XER_TASK','01 XER_TASK'[ProjectCode],'01 XER_TASK'[UpdateDate])
'@
    $baselineCache = @{}
    $assertions = 0
    $historyCells = 0
    foreach ($case in $cases) {
        $projectName = @($projects | Where-Object { $_.'[Code]' -eq $case.Project })[0].'[Project]'
        $dates = @($inventory | Where-Object { $_.'01 XER_TASK[ProjectCode]' -eq $case.Project } |
            ForEach-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' } | Sort-Object -Unique)
        $cutoff = if ($case.Dates.Count) { [datetime]($case.Dates | Sort-Object | Select-Object -Last 1) } else { $dates[-1] }
        $filters = Context-Filters $projectName $case.Dates
        $projection = Metric-Projection
        # Reference gauges execute the currently loaded, unmodified expressions.
        $gaugeQuery = "EVALUATE CALCULATETABLE(ROW($projection),$filters)"
        $originalGauge = (Invoke-ScheduleMetricsDax -Target $target -Query $gaugeQuery)[0]
        $candidateGauge = (Invoke-ScheduleMetricsDax -Target $target -Query "$definitions`n$gaugeQuery")[0]
        foreach ($name in $rates) {
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $candidateGauge.PSObject.Properties["[$name]"].Value $originalGauge.PSObject.Properties["[$name]"].Value) "$($case.Name): gauge changed for $name."
            $assertions++
        }
        if ($case.Project -eq 'J4007' -and $case.Dates.Count -eq 1 -and $case.Dates[0] -eq '2026-09-30') {
            foreach ($name in $rates) {
                Assert-ScheduleMetric ($null -eq $candidateGauge.PSObject.Properties["[$name]"].Value) 'Unavailable September must not acquire a gauge value.'
                $assertions++
            }
        }
        $actualCutoff = (Invoke-ScheduleMetricsDax -Target $target -Query "$definitions`nEVALUATE CALCULATETABLE(ROW(`"Cutoff`",[SM Selected History Cutoff]),$filters)")[0].'[Cutoff]'
        Assert-ScheduleMetric ($null -ne $actualCutoff -and [datetime]$actualCutoff -eq $cutoff) "$($case.Name): explicit cutoff was lost."
        $assertions++
        $historyProjection = Metric-Projection ' (History)'
        $history = Invoke-ScheduleMetricsDax -Target $target -Query @"
$definitions
EVALUATE FILTER(SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],$filters,
"Scope",[SM History In Scope],"Tooltip",[SM Coverage Tooltip (History)],$historyProjection),[Scope]=1)
ORDER BY UpdateHistory[UpdateDate]
"@
        $expectedDates = @($dates | Where-Object { $_ -le $cutoff })
        Assert-ScheduleMetric ($history.Count -eq $expectedDates.Count) "$($case.Name): history count $($history.Count), expected $($expectedDates.Count)."
        $assertions++
        foreach ($row in $history) {
            $date = [datetime]$row.'UpdateHistory[UpdateDate]'
            Assert-ScheduleMetric ($date -in $expectedDates) "$($case.Name): unexpected history date $date."
            $assertions++
            $key = "$($case.Project)|$($date.ToString('yyyy-MM-dd'))"
            if (-not $baselineCache.ContainsKey($key)) {
                $pointFilters = Context-Filters $projectName @($date.ToString('yyyy-MM-dd'))
                $baselineCache[$key] = (Invoke-ScheduleMetricsDax -Target $target -Query "EVALUATE CALCULATETABLE(ROW($projection,`"Tooltip`",[SM Coverage Tooltip]),$pointFilters)")[0]
            }
            $expected = $baselineCache[$key]
            foreach ($name in $rates) {
                Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.PSObject.Properties["[$name]"].Value $expected.PSObject.Properties["[$name]"].Value) "$($case.Name): $date $name differs from its loaded snapshot gauge."
                $assertions++
                $historyCells++
            }
            Assert-ScheduleMetric ($row.'[Tooltip]' -ceq $expected.'[Tooltip]') "$($case.Name): history tooltip changed at $date."
            $assertions++
        }
    }
    [pscustomobject]@{Status='passed'; Mode=if($UseLoadedModel){'loaded, no DEFINE'}else{'query-scoped proposed fix'};
        Cases=$cases.Count; Assertions=$assertions; HistoryCells=$historyCells; GaugeExpressionsUnchanged=$true; ModelWrites=$false} | ConvertTo-Json
} finally { $target.Connection.Disconnect() }

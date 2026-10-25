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
    'SM Missing Logic %', 'SM FS %', 'SM Invalid Dates %', 'SM Out Of Sequence %')
$pageFilters = @'
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),
TREATAS({"Not Started","In Progress"},'01 XER_TASK'[status_code]),
TREATAS({FALSE()},'01 XER_TASK'[Is Unscheduled]),
TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake])
'@
function Dax-Date([datetime]$Value) { return "DATE($($Value.Year),$($Value.Month),$($Value.Day))" }
function New-CutoffCase($Project, [datetime[]]$Dates, [string]$Name, [switch]$Unavailable) {
    return @{ Project=$Project.Code; ProjectName=$Project.Name; ProjectDates=$Project.Dates
        Dates=@($Dates | ForEach-Object { $_.ToString('yyyy-MM-dd') }); Name="$($Project.Code) $Name"; Unavailable=[bool]$Unavailable }
}
# The Desktop development subset changes, so cases come from the loaded
# projects and updates. CurrentDate holds every loaded update, so a date that
# another project has but this one lacks is a selectable unavailable update.
function Get-CutoffPlan($Projects, $Inventory) {
    $allDates = @($Inventory | ForEach-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' } | Sort-Object -Unique)
    $candidates = @(foreach ($group in @($Inventory | Group-Object { $_.'01 XER_TASK[ProjectCode]' })) {
        $names = @($Projects | Where-Object { $_.'[Code]' -eq $group.Name } | ForEach-Object { $_.'[Project]' } | Sort-Object -Unique)
        if ($names.Count -ne 1) { continue }
        $dates = @($group.Group | ForEach-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' } | Sort-Object -Unique)
        $absent = @($allDates | Where-Object { $_ -notin $dates })
        [pscustomobject]@{ Code=$group.Name; Name=$names[0]; Dates=$dates; Absent=$absent
            Later=@($absent | Where-Object { $_ -gt $dates[-1] }) }
    })
    $plan = @{ Cases=[Collections.Generic.List[object]]::new(); Skipped=[Collections.Generic.List[string]]::new(); Projects=@() }
    if (-not $candidates.Count) { return $plan }
    # Primary: the project that exercises the most scenarios (an unavailable
    # later update enables two), then the most updates, then project code.
    $primary = @($candidates | Sort-Object @{ e={ [Math]::Min($_.Dates.Count, 3) + [int]($_.Later.Count -gt 0) + [int]($_.Absent.Count -gt 0) }; Descending=$true },
        @{ e={ $_.Dates.Count }; Descending=$true }, Code)[0]
    $dates = $primary.Dates
    if ($primary.Later.Count) {
        $plan.Cases.Add((New-CutoffCase $primary @($primary.Later[0]) 'unavailable later cutoff keeps every earlier snapshot' -Unavailable))
    } elseif ($primary.Absent.Count) {
        $plan.Cases.Add((New-CutoffCase $primary @($primary.Absent[-1]) 'unavailable gap cutoff keeps only earlier snapshots' -Unavailable))
    } else { $plan.Skipped.Add('unavailable cutoff: every loaded update exists for every loaded project') }
    $plan.Cases.Add((New-CutoffCase $primary @($dates[-1]) 'available latest cutoff'))
    if ($dates.Count -ge 2) {
        $plan.Cases.Add((New-CutoffCase $primary @($dates[[Math]::Floor(($dates.Count - 1) / 2)]) 'earlier cutoff excludes later snapshots'))
    } else { $plan.Skipped.Add("earlier cutoff: $($primary.Code) has one loaded update") }
    if ($dates.Count -ge 3) {
        $plan.Cases.Add((New-CutoffCase $primary @($dates[0], $dates[-2]) 'multiple earlier dates use maximum explicit cutoff'))
    } else { $plan.Skipped.Add("multiple earlier dates: $($primary.Code) has fewer than three loaded updates") }
    if ($primary.Later.Count) {
        $plan.Cases.Add((New-CutoffCase $primary @($dates[-1], $primary.Later[0]) 'multiple dates retain unavailable maximum cutoff'))
    } else { $plan.Skipped.Add("unavailable maximum cutoff: no loaded update is later than $($primary.Code)'s latest") }
    $plan.Cases.Add((New-CutoffCase $primary @() 'no explicit date preserves existing maximum fallback'))
    $others = @($candidates | Where-Object { $_.Code -ne $primary.Code } |
        Sort-Object @{ e={ $_.Dates.Count }; Descending=$true }, Code)
    $plan.Projects = @($primary.Code)
    if ($others.Count) {
        $other = $others[0]
        $plan.Projects += $other.Code
        $plan.Cases.Add((New-CutoffCase $other @($other.Dates[-1]) 'other project latest cutoff unchanged'))
        if ($other.Dates.Count -ge 3) {
            $plan.Cases.Add((New-CutoffCase $other @($other.Dates[0], $other.Dates[-2]) 'other project multiple earlier dates'))
        } else { $plan.Skipped.Add("other project multiple earlier dates: $($other.Code) has fewer than three loaded updates") }
    } else { $plan.Skipped.Add('other project cases: only one project is loaded') }
    return $plan
}
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
EVALUATE SELECTCOLUMNS(Project_Dimension,"Code",Project_Dimension[ProjectCode],"Project",Project_Dimension[Project])
'@
    $inventory = Invoke-ScheduleMetricsDax -Target $target -Query @'
EVALUATE SUMMARIZE('01 XER_TASK','01 XER_TASK'[ProjectCode],'01 XER_TASK'[UpdateDate])
'@
    $plan = Get-CutoffPlan $projects $inventory
    $cases = $plan.Cases.ToArray()
    if (-not $cases.Count) {
        Write-Warning 'Skipped: no loaded project has updates and a single Project_Dimension name.'
        [pscustomobject]@{Status='skipped'; Reason='No loaded project with updates and a single Project_Dimension name'; ModelWrites=$false} | ConvertTo-Json
        return
    }
    foreach ($reason in $plan.Skipped) { Write-Warning "Scenario skipped: $reason." }
    $baselineCache = @{}
    $assertions = 0
    $historyCells = 0
    foreach ($case in $cases) {
        $projectName = $case.ProjectName
        $dates = $case.ProjectDates
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
        if ($case.Unavailable) {
            foreach ($name in $rates) {
                Assert-ScheduleMetric ($null -eq $candidateGauge.PSObject.Properties["[$name]"].Value) "$($case.Name): unavailable update must not acquire a gauge value for $name."
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
        Projects=$plan.Projects; Cases=@($cases | ForEach-Object { "$($_.Name) [$($_.Dates -join ', ')]" }); SkippedScenarios=$plan.Skipped.ToArray()
        Assertions=$assertions; HistoryCells=$historyCells; GaugeExpressionsUnchanged=$true; ModelWrites=$false} | ConvertTo-Json
} finally { $target.Connection.Disconnect() }

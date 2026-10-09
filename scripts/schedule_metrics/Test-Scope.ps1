[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory
)
. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder(
    (Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'))
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
try {
    $definitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model
    $inventory = Invoke-ScheduleMetricsDax -Target $target -Query @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[UpdateDate],"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[UpdateDate]
'@
    $rates = @('HighFloat%', 'HighDur%', 'Lags%', '<0Lead%', '<0Float%', 'Constraint%',
        'SM Missing Logic %', 'SM FS %', 'SM Invalid Dates %', 'Score')
    $projection = ($rates | ForEach-Object { '"' + $_ + '",[' + $_ + ']' }) -join ','
    $cases = [Collections.Generic.List[object]]::new()
    $projectGroup = @($inventory | Group-Object { $_.'01 XER_TASK[ProjectCode]' } | Where-Object Count -gt 1)[0]
    $project = $projectGroup.Name.Replace('"', '""')
    $dates = @($projectGroup.Group | Select-Object -First 2 | ForEach-Object {
        $d = [datetime]$_.'01 XER_TASK[UpdateDate]'; "DATE($($d.Year),$($d.Month),$($d.Day))"
    }) -join ','
    $cases.Add([pscustomobject]@{ Name = 'multiple snapshots'; Filters = "TREATAS({""$project""},'01 XER_TASK'[ProjectCode]),TREATAS({$dates},CurrentDate[UpdateDate])" })
    $dateGroup = @($inventory | Group-Object { $_.'01 XER_TASK[UpdateDate]' } | Where-Object Count -gt 1)[0]
    $date = [datetime]$dateGroup.Group[0].'01 XER_TASK[UpdateDate]'
    $projects = ($dateGroup.Group | ForEach-Object { '"' + $_.'01 XER_TASK[ProjectCode]'.Replace('"', '""') + '"' }) -join ','
    $cases.Add([pscustomobject]@{ Name = 'multiple projects'; Filters = "TREATAS({$projects},'01 XER_TASK'[ProjectCode]),TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},CurrentDate[UpdateDate])" })
    foreach ($case in $cases) {
        $query = "$definitions`nEVALUATE CALCULATETABLE(ROW($projection),$($case.Filters))"
        $rows = Invoke-ScheduleMetricsDax -Target $target -Query $query
        foreach ($name in $rates) {
            Assert-ScheduleMetric ($null -eq $rows[0].PSObject.Properties["[$name]"].Value) "$name should be unavailable for $($case.Name)."
        }
    }
    [pscustomobject]@{ Status = 'passed'; ScopeCases = $cases.Count; Assertions = $cases.Count * $rates.Count; ModelWrites = $false } |
        ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }

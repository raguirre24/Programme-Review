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
    $inventory = Invoke-ScheduleMetricsDax $target @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate]
'@
    $groups = $inventory | Group-Object { "$($_.'01 XER_TASK[ProjectCode]')|$($_.'01 XER_TASK[ProgrammeType]')" }
    $assertions = 0
    foreach ($group in $groups) {
        $ordered = @($group.Group | Sort-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' })
        $project = $ordered[0].'01 XER_TASK[ProjectCode]'.Replace('"', '""')
        $programme = $ordered[0].'01 XER_TASK[ProgrammeType]'.Replace('"', '""')
        foreach ($cutoff in @([datetime]$ordered[-1].'01 XER_TASK[UpdateDate]', [datetime]$ordered[[Math]::Floor(($ordered.Count - 1) / 2)].'01 XER_TASK[UpdateDate]')) {
            $query = @"
$definitions
EVALUATE SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],
TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),TREATAS({"$programme"},'01 XER_TASK'[ProgrammeType]),
TREATAS({DATE($($cutoff.Year),$($cutoff.Month),$($cutoff.Day))},CurrentDate[UpdateDate]),
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),
TREATAS({"Not Started","In Progress"},'01 XER_TASK'[status_code]),
TREATAS({FALSE},'01 XER_TASK'[Is Unscheduled]),TREATAS({FALSE},'01 XER_TASK'[IsExcludedFromDataLake]),
"Scope",[SM History In Scope])
"@
            $rows = Invoke-ScheduleMetricsDax $target $query
            $expected = @($ordered | Where-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' -le $cutoff })
            $inScope = @($rows | Where-Object { $_.'[Scope]' -eq 1 })
            Assert-ScheduleMetric ($inScope.Count -eq $expected.Count) "History scope count differs for $($group.Name) at $cutoff."
            foreach ($row in $inScope) {
                $pointDate = [datetime]$row.'UpdateHistory[UpdateDate]'
                Assert-ScheduleMetric (@($expected | Where-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' -eq $pointDate }).Count -eq 1) "Future or absent project snapshot retained at $pointDate."
                $assertions++
            }
            $assertions++
        }
    }
    [pscustomobject]@{ Status = 'passed'; Assertions = $assertions; ModelWrites = $false;
        Scope = 'All available snapshot axis rows remain in scope, including unknown metric periods; future and absent project snapshots do not.' } |
        ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }

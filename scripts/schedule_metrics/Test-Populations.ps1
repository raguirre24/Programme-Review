[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory
)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$proposed = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder(
    (Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'))
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog

# Query-local tables cannot replace an existing model table by name. The exact
# proposed aggregate expressions below are therefore redirected to two isolated
# fixture tables; no predicate, threshold or filter modifier is rewritten.
# Snapshot identity is supplied as valid, since this fixture tests populations.
$fixtureTables = @'
TABLE '__SM Tasks' = DATATABLE(
    "task_id_key",STRING,"status_code",STRING,"StatusCategory",STRING,
    "task_type",STRING,"TaskType_Classified",STRING,"Is Unscheduled",BOOLEAN,
    "total_float",DOUBLE,"remaining_duration",DOUBLE,"cstr_type",STRING,
    "No Predecessor",INTEGER,"No Successor",INTEGER,"Driven_DataDate",STRING,
    {
        {"A","Not Started","Not Complete","TT_Task","Activity",FALSE,44,44,BLANK(),1,1,"Not Driven"},
        {"B","In Progress","Not Complete","TT_Rsrc","Activity",FALSE,44.01,44.01,"CS_MSO",0,0,"Not Driven"},
        {"C","Not Started","Not Complete","TT_Task","Activity",TRUE,BLANK(),BLANK(),"UNKNOWN",0,0,BLANK()},
        {"D","Not Started","Not Complete","TT_Task","Activity",FALSE,-1,-1,BLANK(),0,0,"Not Driven"},
        {"I","Not Started","Not Complete","TT_Task","Activity",FALSE,0,0,"CS_MSOA",0,0,"Not Driven"},
        {"E","Not Started","Not Complete","TT_Mile","Milestone",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"F","Complete","Complete","TT_Task","Activity",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"G","Not Started","Not Complete","TT_LOE","Level Of Effort",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"H","Not Started","Not Complete","TT_WBS","WBS Summary",FALSE,99,99,"CS_MSO",1,1,"Not Driven"}
    })
TABLE '__SM Links' = DATATABLE("task_id_key",STRING,"lag",DOUBLE,"pred_type",STRING,
    {
        {"B",0,"PR_FS"},{"B",0.1,"PR_SS"},{"D",5,"PR_FS"},
        {"I",5.1,"PR_FS"},{"A",-0.1,"PR_SF"},{"C",BLANK(),"PR_FS1"},
        {"C",BLANK(),"PR_FS"},
        {"C",0,"PR_UNKNOWN"},
        {"E",100,"PR_FS"},{"F",100,"PR_FS"},{"G",100,"PR_FS"},{"H",100,"PR_FS"}
    })
'@
$expected = [ordered]@{
    'Task_Count' = 5
    'Missing Predecessor' = 1
    'Missing Successor' = 1
    'SM Missing Logic Count' = 1
    'Float >44' = 1
    'Dur >44' = 1
    'Task_Count_Negative_Float' = 1
    'Task_Count_Float_0' = 1
    'Primary Constraints' = 3
    'SM Restrictive Primary Count' = 1
    'SM Unknown Constraint Count' = 1
    'SM Missing Float Count' = 1
    'SM Missing Duration Count' = 2
    'SM Eligible Relationship Count' = 8
    'SM Positive Lag Count' = 3
    'Lags>5d' = 1
    'Leads<0d' = 1
    'SM FS Count' = 5
    'SM Missing Lag Count' = 2
    'SM Unknown Relationship Type Count' = 1
    'HighFloat%' = 0.25
    '<0Float%' = 0.25
    '0Float%' = 0.25
    'HighDur%' = (1.0 / 3.0)
    'Constraint%' = 0.25
    'Lags%' = 0.5
    '<0Lead%' = (1.0 / 6.0)
    'SM FS %' = (5.0 / 7.0)
    'SM Partial Checks' = 6
}
try {
    $overrides = @{ 'XER Metrics[SM Snapshot Valid]' = 'TRUE()' }
    foreach ($name in $expected.Keys) {
        $expression = $proposed.Tables['XER Metrics'].Measures[$name].Expression
        $overrides["XER Metrics[$name]"] = $expression.Replace("'01 XER_TASK'", "'__SM Tasks'").Replace("'06 XER_PREDECESSOR'", "'__SM Links'")
    }
    $definitions = Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model -Overrides $overrides
    $definitions = "DEFINE`n$fixtureTables`n" + $definitions.Substring('DEFINE'.Length)
    $projection = ($expected.Keys | ForEach-Object { '"' + $_ + '",[' + $_ + ']' }) -join ','
    # Deliberately impose the old page's filters. Aggregates must apply their
    # defined populations and recover the unscheduled work row C.
    $query = @"
$definitions
EVALUATE CALCULATETABLE(ROW($projection),
TREATAS({"Activity","Milestone"},'__SM Tasks'[TaskType_Classified]),
TREATAS({"Not Started","In Progress"},'__SM Tasks'[status_code]),
TREATAS({FALSE},'__SM Tasks'[Is Unscheduled]))
"@
    $rows = Invoke-ScheduleMetricsDax -Target $target -Query $query
    foreach ($name in $expected.Keys) {
        $actual = $rows[0].PSObject.Properties["[$name]"].Value
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $actual $expected[$name]) "$name expected $($expected[$name]), got $actual."
    }
    [pscustomobject]@{ Status = 'passed'; AggregateAssertions = $expected.Count; ModelWrites = $false;
        Scope = 'Actual aggregate expressions redirected to isolated query-local tasks and links' } |
        ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }

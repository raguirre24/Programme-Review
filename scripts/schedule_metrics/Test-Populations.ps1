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
        {"D","Not Started","Not Complete","TT_Task","Activity",FALSE,-5,-1,BLANK(),0,0,"Not Driven"},
        {"I","Not Started","Not Complete","TT_Task","Activity",FALSE,0,0,"CS_MSOA",0,0,"Not Driven"},
        {"J","Not Started","Not Complete","TT_Task","Activity",FALSE,-5.01,1,BLANK(),0,0,"Not Driven"},
        {"K","In Progress","Not Complete","TT_Task","Activity",FALSE,10,10,BLANK(),0,0,"Not Driven"},
        {"E","Not Started","Not Complete","TT_Mile","Milestone",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"F","Complete","Complete","TT_Task","Activity",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"G","Not Started","Not Complete","TT_LOE","Level Of Effort",FALSE,99,99,"CS_MSO",1,1,"Not Driven"},
        {"H","Not Started","Not Complete","TT_WBS","WBS Summary",FALSE,99,99,"CS_MSO",1,1,"Not Driven"}
    })
TABLE '__SM Links' = DATATABLE("task_id_key",STRING,"lag",DOUBLE,"pred_type",STRING,
    "status_code",STRING,"predecessor_status_code",STRING,"predecessor_task_type",STRING,
    {
        {"B",0,"PR_FS","TK_Active","TK_Active","TT_LOE"},{"B",0.1,"PR_SS","TK_Active","TK_Active","TT_Task"},
        {"D",5,"PR_FS","TK_NotStart","TK_Complete","TT_Task"},
        {"I",5.1,"PR_FS","TK_NotStart","TK_Complete","TT_Task"},{"A",-0.1,"PR_SF","TK_NotStart","TK_Complete","TT_Task"},
        {"C",BLANK(),"PR_FS1","TK_NotStart","TK_Complete","TT_Task"},
        {"C",BLANK(),"PR_FS","TK_NotStart","TK_Complete","TT_Task"},
        {"C",0,"PR_UNKNOWN","TK_NotStart","TK_Complete","TT_Task"},
        {"K",0,"PR_FS","TK_Active","TK_Active","TT_Task"},
        {"E",100,"PR_FS","TK_NotStart","TK_Complete","TT_Task"},{"F",100,"PR_FS","TK_Complete","TK_Complete","TT_Task"},
        {"G",100,"PR_FS","TK_NotStart","TK_Complete","TT_Task"},{"H",100,"PR_FS","TK_NotStart","TK_Complete","TT_Task"}
    })
'@
$expected = [ordered]@{
    'Task_Count' = 8
    'Missing Predecessor' = 2
    'Missing Successor' = 2
    'SM Missing Logic Count' = 2
    'Float >44' = 2
    'Dur >44' = 2
    'Task_Count_Negative_Float' = 2
    'Task_Count_Float_0' = 1
    'Primary Constraints' = 4
    'SM Restrictive Primary Count' = 2
    'SM Unknown Constraint Count' = 1
    'SM Missing Float Count' = 1
    'SM Missing Duration Count' = 2
    'SM Eligible Relationship Count' = 10
    'SM Positive Lag Count' = 4
    'Lags>5d' = 2
    'Leads<0d' = 1
    'SM FS Count' = 7
    'SM Missing Lag Count' = 2
    'SM Unknown Relationship Type Count' = 1
    'SM In Progress Count' = 2
    'Out Of Sequence Count' = 1
    'HighFloat%' = (2.0 / 7.0)
    '<0Float%' = (2.0 / 7.0)
    '0Float%' = (1.0 / 7.0)
    'HighDur%' = (2.0 / 6.0)
    'Constraint%' = (2.0 / 7.0)
    'Lags%' = (2.0 / 8.0)
    '<0Lead%' = (1.0 / 8.0)
    'SM FS %' = (7.0 / 9.0)
    'SM Out Of Sequence %' = 0.5
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

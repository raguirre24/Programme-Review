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
$fixture = @'
TABLE '__SM Dates' = DATATABLE(
"Case",STRING,"task_type",STRING,"status_code",STRING,"StatusCategory",STRING,
"TaskType_Classified",STRING,"Is Unscheduled",BOOLEAN,
"data_date",DATETIME,"Start",DATETIME,"Finish",DATETIME,"act_end_date",DATETIME,
"Expected Bad",INTEGER,"Expected Eligible",INTEGER,
{
{"future plan","TT_Task","Not Started","Not Complete","Activity",FALSE,"2026-01-10","2026-01-11","2026-01-12",BLANK(),0,1},
{"overdue start","TT_Task","Not Started","Not Complete","Activity",FALSE,"2026-01-10","2026-01-09","2026-01-12",BLANK(),1,1},
{"valid active","TT_Task","In Progress","Not Complete","Activity",FALSE,"2026-01-10","2026-01-05","2026-01-12",BLANK(),0,1},
{"future actual start","TT_Task","In Progress","Not Complete","Activity",FALSE,"2026-01-10","2026-01-11","2026-01-12",BLANK(),1,1},
{"valid complete","TT_Task","Complete","Complete","Activity",FALSE,"2026-01-10","2026-01-05","2026-01-09","2026-01-09",0,1},
{"complete missing actual finish","TT_Task","Complete","Complete","Activity",FALSE,"2026-01-10","2026-01-05","2026-01-09",BLANK(),1,1},
{"future actual finish","TT_Task","Complete","Complete","Activity",FALSE,"2026-01-10","2026-01-05","2026-01-11","2026-01-11",1,1},
{"missing start","TT_Task","Not Started","Not Complete","Activity",TRUE,"2026-01-10",BLANK(),"2026-01-12",BLANK(),1,1},
{"missing finish","TT_Task","Not Started","Not Complete","Activity",TRUE,"2026-01-10","2026-01-11",BLANK(),BLANK(),1,1},
{"valid start milestone","TT_Mile","Not Started","Not Complete","Milestone",FALSE,"2026-01-10","2026-01-11",BLANK(),BLANK(),0,1},
{"valid finish milestone","TT_FinMile","Not Started","Not Complete","Milestone",FALSE,"2026-01-10",BLANK(),"2026-01-11",BLANK(),0,1},
{"complete start milestone","TT_Mile","Complete","Complete","Milestone",FALSE,"2026-01-10","2026-01-05",BLANK(),BLANK(),0,1},
{"complete finish milestone","TT_FinMile","Complete","Complete","Milestone",FALSE,"2026-01-10",BLANK(),"2026-01-09","2026-01-09",0,1},
{"reversed interval","TT_Task","Not Started","Not Complete","Activity",FALSE,"2026-01-10","2026-01-13","2026-01-12",BLANK(),1,1},
{"overdue active finish","TT_Task","In Progress","Not Complete","Activity",FALSE,"2026-01-10","2026-01-05","2026-01-09",BLANK(),1,1},
{"open with actual finish","TT_Task","Not Started","Not Complete","Activity",FALSE,"2026-01-10","2026-01-11","2026-01-12","2026-01-09",1,1},
{"unknown status","TT_Task","UNKNOWN","Not Complete","Activity",FALSE,"2026-01-10","2026-01-11","2026-01-12",BLANK(),1,1},
{"missing data date","TT_Task","Not Started","Not Complete","Activity",FALSE,BLANK(),"2026-01-11","2026-01-12",BLANK(),1,1},
{"LOE excluded","TT_LOE","Not Started","Not Complete","Level Of Effort",TRUE,BLANK(),BLANK(),BLANK(),BLANK(),BLANK(),BLANK()},
{"WBS excluded","TT_WBS","Not Started","Not Complete","WBS Summary",TRUE,BLANK(),BLANK(),BLANK(),BLANK(),BLANK(),BLANK()},
{"start milestone missing endpoint","TT_Mile","Not Started","Not Complete","Milestone",TRUE,"2026-01-10",BLANK(),BLANK(),BLANK(),1,1},
{"finish milestone missing endpoint","TT_FinMile","Not Started","Not Complete","Milestone",TRUE,"2026-01-10",BLANK(),BLANK(),BLANK(),1,1}
})
'@
try {
    $overrides = @{ 'XER Metrics[SM Snapshot Valid]' = 'TRUE()' }
    foreach ($name in @('SM Date Eligible Count', 'SM Invalid Dates Count')) {
        $overrides["XER Metrics[$name]"] = $proposed.Tables['XER Metrics'].Measures[$name].Expression.Replace("'01 XER_TASK'", "'__SM Dates'")
    }
    $definitions = Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model -Overrides $overrides
    $definitions = "DEFINE`n$fixture`n" + $definitions.Substring('DEFINE'.Length)
    $query = @"
$definitions
EVALUATE ADDCOLUMNS(VALUES('__SM Dates'[Case]),
"Expected Bad",CALCULATE(MAX('__SM Dates'[Expected Bad])),
"Expected Eligible",CALCULATE(MAX('__SM Dates'[Expected Eligible])),
"Bad",CALCULATE([SM Invalid Dates Count],TREATAS({"Not Started","In Progress"},'__SM Dates'[status_code]),TREATAS({FALSE},'__SM Dates'[Is Unscheduled])),
"Eligible",CALCULATE([SM Date Eligible Count],TREATAS({"Not Started","In Progress"},'__SM Dates'[status_code]),TREATAS({FALSE},'__SM Dates'[Is Unscheduled])))
"@
    $rows = Invoke-ScheduleMetricsDax -Target $target -Query $query
    Assert-ScheduleMetric ($rows.Count -eq 22) 'Date fixture did not return all cases.'
    foreach ($row in $rows) {
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Bad]' $row.'[Expected Bad]') "Invalid-date predicate failed for $($row.'__SM Dates[Case]')."
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Eligible]' $row.'[Expected Eligible]') "Date population failed for $($row.'__SM Dates[Case]')."
    }
    [pscustomobject]@{ Status = 'passed'; DateCases = $rows.Count; Assertions = 2 * $rows.Count; ModelWrites = $false } |
        ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }

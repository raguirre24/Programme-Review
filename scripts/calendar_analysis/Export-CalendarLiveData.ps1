[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$ServerAddress,
    [string]$AssemblyDirectory
)
# Read-only export for validate_calendar_live.py: runs DAX statements against the open Power BI Desktop model.
# No refresh, TMSL, SaveChanges or other model mutation is used.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot '../schedule_metrics/Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory

if (-not $ServerAddress) {
    # Pick the open model that already carries the table-11 alignment column (refreshed with this fix).
    $processIds = @(Get-Process -Name msmdsrv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -in $processIds } | Select-Object -ExpandProperty LocalPort -Unique)
    $candidates = @()
    foreach ($port in $ports) {
        $server = New-Object Microsoft.AnalysisServices.Tabular.Server
        try {
            $server.Connect("Data Source=localhost:$port")
            foreach ($database in $server.Databases) {
                $table = $database.Model.Tables.Find('11 XER_CALENDAR_DETAILED')
                if ($table -and $table.Columns.Contains('ExceptionDateShiftDays')) { $candidates += "localhost:$port" }
            }
        } catch { } finally { $server.Disconnect() }
    }
    if ($candidates.Count -ne 1) {
        throw "Expected one open model with '11 XER_CALENDAR_DETAILED'[ExceptionDateShiftDays], found $($candidates.Count). Refresh the report in Power BI Desktop or pass -ServerAddress."
    }
    $ServerAddress = $candidates[0]
}

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress
try {
    $queries = [ordered]@{
        calendar = @'
EVALUATE
SELECTCOLUMNS(
    FILTER('11 XER_CALENDAR_DETAILED', NOT ISBLANK('11 XER_CALENDAR_DETAILED'[clndr_id_key])),
    "key", '11 XER_CALENDAR_DETAILED'[clndr_id_key],
    "date", IF(ISBLANK('11 XER_CALENDAR_DETAILED'[date]), BLANK(), FORMAT('11 XER_CALENDAR_DETAILED'[date], "yyyy-MM-dd")),
    "weekday", '11 XER_CALENDAR_DETAILED'[day_of_week_num],
    "weekday_name", '11 XER_CALENDAR_DETAILED'[day_of_week],
    "hours", '11 XER_CALENDAR_DETAILED'[work_hours],
    "type", '11 XER_CALENDAR_DETAILED'[exception_type],
    "shift", '11 XER_CALENDAR_DETAILED'[ExceptionDateShiftDays]
)
'@
        activities = @'
EVALUATE
SELECTCOLUMNS(
    FILTER(
        '01 XER_TASK',
        '01 XER_TASK'[status_code] = "Not Started"
            && '01 XER_TASK'[TaskType_Classified] = "Activity"
            && NOT ISBLANK('01 XER_TASK'[Start]) && NOT ISBLANK('01 XER_TASK'[Finish])
            && NOT ISBLANK('01 XER_TASK'[calendar_id_key])
    ),
    "task_code", '01 XER_TASK'[task_code],
    "project", '01 XER_TASK'[ProjectCode],
    "update", FORMAT('01 XER_TASK'[UpdateDate], "yyyy-MM-dd"),
    "key", '01 XER_TASK'[calendar_id_key],
    "start", FORMAT('01 XER_TASK'[Start], "yyyy-MM-dd"),
    "finish", FORMAT('01 XER_TASK'[Finish], "yyyy-MM-dd"),
    "remaining", '01 XER_TASK'[remaining_duration]
)
'@
    }
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    foreach ($name in $queries.Keys) {
        $rows = Invoke-ScheduleMetricsDax -Target $target -Query $queries[$name] -TimeoutSeconds 300
        $rows | ConvertTo-Csv -NoTypeInformation | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "$name.csv")
    }
    @{ server = $ServerAddress; catalog = $target.Database.Name } | ConvertTo-Json -Compress
} finally { $target.Connection.Disconnect() }

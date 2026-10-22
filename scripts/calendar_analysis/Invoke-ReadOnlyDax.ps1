[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$QueryFile,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$ServerAddress,
    [string]$AssemblyDirectory,
    [switch]$DefineFromTmdl
)
# Read-only DAX runner for the Calendar Stretch live checks. $QueryFile is JSON {"name": "EVALUATE ...", ...}.
# Writes <name>.csv per query plus timings.json, and prints {server, catalog}. No refresh, TMSL or SaveChanges.
# -DefineFromTmdl prefixes each query with DEFINE COLUMN/MEASURE text from the TMDL files, so changes can be
# checked against a model opened before them (only for objects the loaded model lacks or that differ).
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot '../schedule_metrics/Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory

if (-not $ServerAddress) {
    # Pick the one open model that has the Calendar Analysis measures.
    $processIds = @(Get-Process -Name msmdsrv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -in $processIds } | Select-Object -ExpandProperty LocalPort -Unique)
    $candidates = @()
    foreach ($port in $ports) {
        $server = New-Object Microsoft.AnalysisServices.Tabular.Server
        try {
            $server.Connect("Data Source=localhost:$port")
            foreach ($database in $server.Databases) {
                $measures = $database.Model.Tables.Find('XER Measures')
                if ($measures -and $measures.Measures.Contains('CA Inspector Scope Ready')) { $candidates += "localhost:$port" }
            }
        } catch { } finally { $server.Disconnect() }
    }
    if ($candidates.Count -ne 1) { throw "Expected one open Programme Review model with Calendar Analysis measures, found $($candidates.Count). Pass -ServerAddress." }
    $ServerAddress = $candidates[0]
}

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress
try {
    $define = ''
    if ($DefineFromTmdl) {
        $definition = Resolve-Path (Join-Path $PSScriptRoot '../../Project Review - Programme (datalake).SemanticModel/definition')
        $source = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($definition)
        $live = $target.Database.Model
        $lines = [Collections.Generic.List[string]]::new()
        foreach ($pair in @(@('10 XER_CALENDARS', 'Workweek Mask'), @('01 XER_TASK', 'Finish Without Exceptions'), @('01 XER_TASK', 'Calendar Delay Days'))) {
            $column = $source.Tables[$pair[0]].Columns[$pair[1]]
            $loaded = $live.Tables[$pair[0]].Columns.Find($pair[1])
            if (-not $loaded) { $lines.Add("COLUMN '$($pair[0])'[$($pair[1])] = $($column.Expression)") }
        }
        foreach ($measure in $source.Tables['XER Measures'].Measures) {
            if ($measure.Name -notlike 'CS *' -and $measure.Name -notlike 'CA *') { continue }
            $loaded = $live.Tables['XER Measures'].Measures.Find($measure.Name)
            if ($loaded -and ([string]$loaded.Expression).Replace("`r`n", "`n").Trim() -ceq ([string]$measure.Expression).Replace("`r`n", "`n").Trim()) { continue }
            $lines.Add("MEASURE 'XER Measures'[$($measure.Name.Replace(']', ']]'))] = $($measure.Expression)")
        }
        if ($lines.Count) { $define = "DEFINE`n" + ($lines -join "`n") + "`n" }
    }
    $queries = Get-Content -Raw -LiteralPath $QueryFile | ConvertFrom-Json
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    $timings = [ordered]@{}
    foreach ($property in $queries.PSObject.Properties) {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $rows = Invoke-ScheduleMetricsDax -Target $target -Query ($define + $property.Value) -TimeoutSeconds 600
        $timings[$property.Name] = [math]::Round($watch.Elapsed.TotalSeconds, 3)
        $rows | ConvertTo-Csv -NoTypeInformation | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "$($property.Name).csv")
    }
    $timings | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutputDirectory 'timings.json')
    @{ server = $ServerAddress; catalog = $target.Database.Name; defined = ($define -ne '') } | ConvertTo-Json -Compress
} finally { $target.Connection.Disconnect() }

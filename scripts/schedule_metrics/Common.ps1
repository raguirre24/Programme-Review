Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Import-ScheduleMetricsTom {
    param([string]$AssemblyDirectory)
    if (-not $AssemblyDirectory) {
        $packageRoot = Join-Path $env:USERPROFILE '.nuget/packages/microsoft.analysisservices'
        $candidates = @(Get-ChildItem -LiteralPath $packageRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object { [version]$_.Name } -Descending |
            ForEach-Object { Join-Path $_.FullName 'lib/net8.0' } |
            Where-Object { Test-Path -LiteralPath (Join-Path $_ 'Microsoft.AnalysisServices.Tabular.dll') })
        if (-not $candidates.Count) { throw 'TOM was not found. Supply -AssemblyDirectory; this validator does not install dependencies.' }
        $AssemblyDirectory = $candidates[0]
    }
    foreach ($name in @('Microsoft.AnalysisServices.Core.dll', 'Microsoft.AnalysisServices.Tabular.dll')) {
        [Reflection.Assembly]::LoadFrom((Join-Path $AssemblyDirectory $name)) | Out-Null
    }
}

function Connect-ScheduleMetricsModel {
    param([string]$ServerAddress, [string]$Catalog)
    if (-not $ServerAddress) {
        $processIds = @(Get-Process -Name msmdsrv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
        $addresses = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -in $processIds } |
            Select-Object -ExpandProperty LocalPort -Unique |
            ForEach-Object { "localhost:$_" })
    } else { $addresses = @($ServerAddress) }
    $matches = @()
    foreach ($address in $addresses) {
        $connection = New-Object Microsoft.AnalysisServices.Tabular.Server
        try {
            $connection.Connect("Data Source=$address")
            foreach ($database in $connection.Databases) {
                if ($Catalog -and $database.ID -ne $Catalog -and $database.Name -ne $Catalog) { continue }
                if ($database.Model.Tables.Contains('01 XER_TASK') -and $database.Model.Tables.Contains('XER Metrics')) {
                    $matches += [pscustomobject]@{ Connection = $connection; Database = $database; Address = $address }
                }
            }
            if (-not @($matches | Where-Object { $_.Connection -eq $connection }).Count) { $connection.Disconnect() }
        } catch { $connection.Disconnect() }
    }
    if ($matches.Count -ne 1) {
        foreach ($match in $matches) { $match.Connection.Disconnect() }
        throw "Expected one Programme Review model, found $($matches.Count). Specify -ServerAddress and optionally -Catalog."
    }
    return $matches[0]
}

function Invoke-ScheduleMetricsDax {
    param($Target, [string]$Query, [int]$TimeoutSeconds = 30)
    # ExecuteReader submits only a DAX Statement. No TMSL, refresh, deployment,
    # SaveChanges, Process or other model mutation is used by this validator.
    $response = $null
    $statement = '<Statement xmlns="urn:schemas-microsoft-com:xml-analysis">' +
        [Security.SecurityElement]::Escape($Query) + '</Statement>'
    $reader = $Target.Connection.ExecuteReader($statement, [ref]$response,
        @{ Catalog = $Target.Database.ID; Format = 'Tabular'; Timeout = "$TimeoutSeconds" }, $true)
    if (-not $reader) {
        $errors = @($response.Messages | ForEach-Object {
            $description = $_.Description
            $queryEcho = $description.IndexOf('(DEFINE', [StringComparison]::OrdinalIgnoreCase)
            if ($queryEcho -ge 0) { $description.Substring(0, $queryEcho).Trim() } else { $description }
        })
        throw ($errors -join [Environment]::NewLine)
    }
    $rows = [Collections.Generic.List[object]]::new()
    try {
        while ($reader.Read()) {
            $row = [ordered]@{}
            for ($index = 0; $index -lt $reader.FieldCount; $index++) {
                $value = $reader.GetValue($index)
                $row[$reader.GetName($index)] = if ($value -is [DBNull]) { $null } else { $value }
            }
            $rows.Add([pscustomobject]$row)
        }
    } finally { $reader.Close() }
    return ,$rows.ToArray()
}

function Get-ScheduleMetricsDefinitions {
    param($Model, $LiveModel, [hashtable]$Overrides = @{})
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add('DEFINE')
    foreach ($table in $Model.Tables) {
        if ($LiveModel.Tables.Contains($table.Name)) { continue }
        if (@($Model.Relationships | Where-Object { $_.FromTable.Name -eq $table.Name -or $_.ToTable.Name -eq $table.Name }).Count) {
            throw "New table '$($table.Name)' has relationships; a query-scoped table cannot reproduce those."
        }
        if ($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]) {
            throw "New table '$($table.Name)' must be a disconnected calculated table to validate without loading it."
        }
        $escapedTable = $table.Name.Replace("'", "''")
        $lines.Add("TABLE '$escapedTable' = $($table.Partitions[0].Source.Expression)")
    }
    foreach ($table in $Model.Tables) {
        if ($table.Name -ne 'XER Metrics' -and $table.Name -notlike 'Schedule Metric*') { continue }
        $escapedTable = $table.Name.Replace("'", "''")
        foreach ($measure in $table.Measures) {
            $key = "$($table.Name)[$($measure.Name)]"
            $expression = if ($Overrides.ContainsKey($key)) { $Overrides[$key] } else { $measure.Expression }
            $escapedMeasure = $measure.Name.Replace(']', ']]')
            $lines.Add("MEASURE '$escapedTable'[$escapedMeasure] =`n$expression")
        }
    }
    return ($lines -join "`n")
}

function Assert-ScheduleMetric {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Validation failed: $Message" }
}

function Test-ScheduleMetricNumber {
    param($Actual, $Expected, [double]$Tolerance = 0.0000000001)
    if ($null -eq $Expected) { return $null -eq $Actual }
    if ($null -eq $Actual) { return $false }
    return [double]::IsFinite([double]$Actual) -and [Math]::Abs([double]$Actual - [double]$Expected) -le $Tolerance
}

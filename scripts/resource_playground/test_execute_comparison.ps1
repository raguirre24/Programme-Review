param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Database,
    [Parameter(Mandatory=$true)][string]$CasesPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$FixtureMarker,
    [string]$NamePattern = '*',
    [int]$TimeoutSeconds = 30,
    [int]$MemoryLimitKB = 1048576
)

# Query-only runner. Explicit localhost/catalog; no refresh, save or model writes.
# Grouped alternatives are compared by calendar/period keys, never added together.
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'An explicit localhost port is required.' }
$suite = Get-Content -LiteralPath $CasesPath -Raw | ConvertFrom-Json
if ($FixtureMarker -and $suite.marker -ne $FixtureMarker) { throw 'Suite marker mismatch.' }
$package = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE '.nuget/packages/microsoft.analysisservices') -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'lib/net8.0/Microsoft.AnalysisServices.Tabular.dll') } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if (-not $package) { throw 'Microsoft TOM net8.0 assemblies are required.' }
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $package.FullName ('lib/net8.0/' + $dll))) | Out-Null
}
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
$roles = @{}
$results = [Collections.Generic.List[object]]::new()

function Invoke-Query($Connection, [string]$Dax) {
    if ($Dax -notmatch '^\s*(EVALUATE|DEFINE)\b') { throw 'Only DAX queries are allowed.' }
    $messages = $null; $reader = $null
    $rows = [Collections.Generic.List[object]]::new()
    try {
        $reader = $Connection.ExecuteReader('<Statement>' + [Security.SecurityElement]::Escape($Dax) + '</Statement>', [ref]$messages,
            @{Catalog=$Database;Format='Tabular';Timeout=[string]$TimeoutSeconds;DbpropMsmdRequestMemoryLimit=[string]$MemoryLimitKB}, $true)
        if ($null -eq $reader) {
            throw ('No rowset: ' + (($messages | ForEach-Object { $_.Messages } | ForEach-Object Description) -join '; '))
        }
        while ($reader.Read()) {
            if ($rows.Count -ge 100000) { throw 'Query exceeded the audit row limit.' }
            $row = [ordered]@{}
            for ($i=0; $i -lt $reader.FieldCount; $i++) {
                $name = $reader.GetName($i) -replace '^.*\[([^\]]+)\]$', '$1'
                if ($row.Contains($name)) { throw ('Ambiguous returned column: ' + $name) }
                $value = $reader.GetValue($i)
                $row[$name] = if ($value -is [DBNull]) { $null } elseif ($value -is [DateTime]) { $value.ToString('yyyy-MM-dd') } else { $value }
            }
            $rows.Add($row)
        }
    } finally { if ($reader) { $reader.Close() } }
    return ,$rows.ToArray()
}
function Test-Value($Expected, $Actual) {
    if ($null -eq $Expected) { return $null -eq $Actual }
    if ($null -eq $Actual) { return $false }
    if ($Expected -is [string]) { return $Expected -ceq [string]$Actual }
    if ($Expected -is [bool]) { return $Expected -eq [bool]$Actual }
    if ($Expected -is [ValueType]) {
        return [Math]::Abs([double]$Expected - [double]$Actual) -le [Math]::Max(0.000001, [Math]::Abs([double]$Expected) * 0.000000001)
    }
    return $Expected -eq $Actual
}
function Get-RowKey($Row, $Columns) {
    foreach ($column in $Columns) { if (-not $Row.Contains($column)) { throw ('Missing row key column: ' + $column) } }
    return ConvertTo-Json -InputObject @($Columns | ForEach-Object { $Row[$_] }) -Compress
}
try {
    $server.Connect("localhost:$Port")
    $model = $server.Databases.Find($Database)
    if ($null -eq $model) { throw 'Explicit catalog was not found.' }
    if ($FixtureMarker) {
        if ($model.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $FixtureMarker -or $model.Model.DataSources.Count -ne 0) { throw 'Source-free fixture guard failed.' }
        $clock = Invoke-Query $server 'EVALUATE ROW("Matches",MAX(''Fixture Identity''[AnchorDate])=TODAY())'
        if ($clock.Count -ne 1 -or -not $clock[0]['Matches']) { throw 'Rebuild the fixture for the current engine date.' }
    }
    foreach ($test in $suite.tests) {
        if ($test.name -notlike $NamePattern) { continue }
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $assertions = [Collections.Generic.List[object]]::new()
        $rows = @(); $failure = $null; $timings = [Collections.Generic.List[object]]::new()
        try {
            $connection = $server
            if ($test.role) {
                if (-not $FixtureMarker -or $test.role -ne 'Fixture Project P1') { throw 'Only the explicit fixture role is supported.' }
                if (-not $roles.ContainsKey($test.role)) {
                    $roleConnection = [Microsoft.AnalysisServices.Tabular.Server]::new()
                    $roleConnection.Connect("Data Source=localhost:$Port;Initial Catalog=$Database;Roles=$($test.role)")
                    $roles[$test.role] = $roleConnection
                }
                $connection = $roles[$test.role]
            }
            if ($test.fragments) {
                $merged = [ordered]@{}
                foreach ($fragment in $test.fragments) {
                    $fragmentWatch = [Diagnostics.Stopwatch]::StartNew()
                    $part = Invoke-Query $connection $fragment.dax
                    $timings.Add([pscustomobject]@{name=$fragment.name;ms=$fragmentWatch.Elapsed.TotalMilliseconds})
                    if ($part.Count -ne 1) { throw 'Scalar fragment must return exactly one row.' }
                    foreach ($key in $part[0].Keys) {
                        if ($merged.Contains($key)) { throw ('Duplicate scalar alias: ' + $key) }
                        $merged[$key] = $part[0][$key]
                    }
                }
                $rows = @($merged)
            } else { $rows = Invoke-Query $connection $test.dax }
            if ($test.PSObject.Properties.Name -contains 'expectedRows') {
                if (-not $test.keyColumns) { throw 'Grouped comparison needs explicit keyColumns.' }
                $actualByKey = @{}
                foreach ($row in $rows) {
                    $key = Get-RowKey $row $test.keyColumns
                    if ($actualByKey.ContainsKey($key)) { throw ('Duplicate actual row key: ' + $key) }
                    $actualByKey[$key] = $row
                }
                $assertions.Add([pscustomobject]@{field='Row count';expected=$test.expectedRows.Count;actual=$rows.Count;pass=($test.expectedRows.Count -eq $rows.Count)})
                foreach ($expectedRow in $test.expectedRows) {
                    $expectedMap = @{}; foreach ($property in $expectedRow.PSObject.Properties) { $expectedMap[$property.Name] = $property.Value }
                    $key = Get-RowKey $expectedMap $test.keyColumns
                    $assertions.Add([pscustomobject]@{field='Row exists';key=$key;pass=$actualByKey.ContainsKey($key)})
                    if (-not $actualByKey.ContainsKey($key)) { continue }
                    foreach ($property in $expectedRow.PSObject.Properties) {
                        $present = $actualByKey[$key].Contains($property.Name)
                        $assertions.Add([pscustomobject]@{field='Column exists';column=$property.Name;key=$key;pass=$present})
                        if (-not $present) { continue }
                        $actual = $actualByKey[$key][$property.Name]
                        $assertions.Add([pscustomobject]@{field=$property.Name;key=$key;expected=$property.Value;actual=$actual;pass=(Test-Value $property.Value $actual)})
                    }
                }
            } else {
                if ($rows.Count -ne 1) { throw 'Scalar test must return exactly one row.' }
                foreach ($property in $test.expect.PSObject.Properties) {
                    $present = $rows[0].Contains($property.Name)
                    $assertions.Add([pscustomobject]@{field='Column exists';column=$property.Name;pass=$present})
                    if (-not $present) { continue }
                    $actual = $rows[0][$property.Name]
                    $assertions.Add([pscustomobject]@{field=$property.Name;expected=$property.Value;actual=$actual;pass=(Test-Value $property.Value $actual)})
                }
                foreach ($property in $test.contains.PSObject.Properties) {
                    $present = $rows[0].Contains($property.Name)
                    $assertions.Add([pscustomobject]@{field='Column exists';column=$property.Name;pass=$present})
                    if (-not $present) { continue }
                    $actual = [string]$rows[0][$property.Name]
                    $assertions.Add([pscustomobject]@{field=$property.Name;contains=$property.Value;actual=$actual;pass=$actual.Contains([string]$property.Value,[StringComparison]::OrdinalIgnoreCase)})
                }
            }
            if ($assertions.Count -eq 0) { throw 'A verification test must contain an assertion.' }
        } catch { $failure = $_.Exception.Message }
        $passed = -not $failure -and @($assertions | Where-Object { -not $_.pass }).Count -eq 0
        $results.Add([pscustomobject]@{name=$test.name;pass=$passed;ms=$watch.Elapsed.TotalMilliseconds;error=$failure;assertions=$assertions.ToArray();rows=$rows;fragments=$timings.ToArray()})
        Write-Output ("{0}: {1} ({2:N0} ms)" -f $(if($passed){'PASS'}else{'FAIL'}),$test.name,$watch.Elapsed.TotalMilliseconds)
    }
} finally {
    foreach ($roleConnection in $roles.Values) { $roleConnection.Disconnect() }
    $server.Disconnect()
}
$summary = [ordered]@{database=$Database;marker=$FixtureMarker;cases=$results.Count;passed=@($results | Where-Object pass).Count;failed=@($results | Where-Object { -not $_.pass }).Count;assertions=@($results | ForEach-Object assertions).Count;tests=$results.ToArray()}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
[pscustomobject]$summary | Select-Object cases,passed,failed,assertions | ConvertTo-Json -Compress
if ($summary.failed -or -not $summary.cases) { exit 1 }

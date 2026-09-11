param(
    [Parameter(Mandatory=$true)][int]$Port,
    [string]$CasesPath,
    [string]$OutputPath,
    [string]$TomDirectory,
    [string]$NamePattern = '*',
    [int]$TimeoutSeconds = 60,
    [int]$MemoryLimitKB = 0
)

# Queries only. Never refreshes, saves, replaces or deletes a model. Both the
# localhost endpoint and fixture annotation are checked before test execution.
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'An explicit local fixture port is required.' }
$fixtureMarker = 'resource-playground-repair-20260911'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifactRoot = Join-Path (Split-Path $repoRoot -Parent) 'resource_playground_review\repair_20260911'
if (-not $CasesPath) { $CasesPath = Join-Path $artifactRoot 'fixture_cases.json' }
if (-not $OutputPath) { $OutputPath = Join-Path $artifactRoot 'fixture_results.json' }
$suite = Get-Content -LiteralPath $CasesPath -Raw | ConvertFrom-Json
if ($suite.marker -ne $fixtureMarker) { throw 'Test manifest marker mismatch.' }
if (-not $TomDirectory) {
    $cache = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.nuget\packages\microsoft.analysisservices'
    $package = Get-ChildItem -LiteralPath $cache -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'lib\net8.0\Microsoft.AnalysisServices.Tabular.dll') } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $package) { throw 'Microsoft TOM net8.0 assemblies are required.' }
    $TomDirectory = Join-Path $package.FullName 'lib\net8.0'
}
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $TomDirectory $dll)) | Out-Null
}
$server = New-Object Microsoft.AnalysisServices.Tabular.Server
$roleServer = $null
$results = [Collections.Generic.List[object]]::new()
$catalog = $null

function Assert-Fixture($Connection) {
    $matches = @($Connection.Databases | Where-Object { $_.Model.Annotations.Find('ResourcePlaygroundFixture').Value -eq $fixtureMarker })
    if ($matches.Count -ne 1) { throw 'Refusing queries: the endpoint does not contain exactly one marked fixture model.' }
    $database = $matches[0]
    if ($null -eq $database.Model.Tables.Find('Fixture Identity')) { throw 'Fixture marker table is missing.' }
    if ($database.Model.Tables.Count -ne 17) { throw 'Unexpected fixture table count.' }
    if ($database.Model.Tables.Find('01 XER_TASK')) { throw 'Production table detected; refusing fixture tests.' }
    return $database
}

function Test-Expected($Expected, $Actual) {
    if ($null -eq $Expected) { return ($null -eq $Actual -or $Actual -is [DBNull]) }
    if ($null -eq $Actual -or $Actual -is [DBNull]) { return $false }
    if ($Expected -is [string]) {
        if ($Actual -is [DateTime]) { return $Expected -eq $Actual.ToString('yyyy-MM-dd') }
        if ($Expected -match '^\d{4}-\d{2}-\d{2}$' -and $Actual -is [ValueType]) {
            return $Expected -eq [DateTime]::FromOADate([double]$Actual).ToString('yyyy-MM-dd')
        }
        return $Expected -ceq [string]$Actual
    }
    if ($Expected -is [bool]) { return $Expected -eq [bool]$Actual }
    if ($Expected -is [ValueType]) {
        $tolerance = [Math]::Max(0.000001, [Math]::Abs([double]$Expected) * 0.000000001)
        return [Math]::Abs([double]$Actual - [double]$Expected) -le $tolerance
    }
    return $Expected -eq $Actual
}

try {
    $server.Connect("localhost:$Port")
    $database = Assert-Fixture $server
    $catalog = $database.ID
    $partitionStates = @($database.Model.Tables | ForEach-Object { $table = $_; $_.Partitions | ForEach-Object { [PSCustomObject]@{table=$table.Name;partition=$_.Name;state=$_.State.ToString();error=$_.ErrorMessage} } })
    $notReady = @($partitionStates | Where-Object state -ne 'Ready')
    if ($notReady.Count) { throw ('Fixture partitions are not processed: ' + (($notReady | ForEach-Object { $_.table + ': ' + $_.state + ' ' + $_.error }) -join '; ')) }
    foreach ($test in $suite.tests) {
        if ($test.name -notlike $NamePattern) { continue }
        if ($test.dax -notmatch '^\s*(EVALUATE|DEFINE)\b') { throw 'Only DAX query statements are allowed.' }
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $reader = $null
        $activeFragment = 'connection/role'
        $fragmentTimings = [Collections.Generic.List[object]]::new()
        $assertions = [Collections.Generic.List[object]]::new()
        try {
            $connection = $server
            if ($test.role) {
                if ($test.role -ne 'Fixture Project P1') { throw 'Only the fixture role may be tested.' }
                if ($null -eq $roleServer) {
                    $roleServer = New-Object Microsoft.AnalysisServices.Tabular.Server
                    try {
                        $roleServer.Connect("Data Source=localhost:$Port;Initial Catalog=$catalog;Roles=Fixture Project P1")
                        # Read-role metadata does not expose model annotations. The
                        # admin connection already verified this exact catalog;
                        # additionally require its immutable data marker here.
                        $markerMessages = $null
                        $markerStatement = "<Statement>EVALUATE VALUES('Fixture Identity'[Marker])</Statement>"
                        $markerReader = $roleServer.ExecuteReader($markerStatement,[ref]$markerMessages,@{Catalog=$catalog;Format='Tabular';Timeout='10'},$true)
                        try {
                            if ($null -eq $markerReader -or -not $markerReader.Read() -or $markerReader.GetValue(0) -ne $fixtureMarker -or $markerReader.Read()) { throw 'Role connection fixture marker mismatch.' }
                        } finally { if ($null -ne $markerReader) { $markerReader.Close() } }
                    } catch {
                        $roleServer.Disconnect()
                        $roleServer = $null
                        throw
                    }
                }
                $connection = $roleServer
            }
            $fragments = if ($test.fragments) { @($test.fragments) } else { @([PSCustomObject]@{name='bundle';dax=$test.dax}) }
            $merged = [ordered]@{}
            foreach ($fragment in $fragments) {
                $activeFragment = $fragment.name
                if ($fragment.dax -notmatch '^\s*(EVALUATE|DEFINE)\b') { throw 'Only DAX query fragments are allowed.' }
                $fragmentWatch = [Diagnostics.Stopwatch]::StartNew()
                $messages = $null
                $statement = '<Statement>' + [Security.SecurityElement]::Escape($fragment.dax) + '</Statement>'
                $queryProperties = @{Catalog=$catalog;Format='Tabular';Timeout=[string]$TimeoutSeconds}
                if($MemoryLimitKB -gt 0){$queryProperties['DbpropMsmdRequestMemoryLimit']=[string]$MemoryLimitKB}
                $reader = $connection.ExecuteReader($statement,[ref]$messages,$queryProperties,$true)
                if ($null -eq $reader) { throw ((@($messages | ForEach-Object { $_.Messages } | ForEach-Object Description)) -join [Environment]::NewLine) }
                try {
                    if ($test.aggregateRows) {
                        $nativeRows = [Collections.Generic.List[object]]::new()
                        while ($reader.Read()) {
                            if ($nativeRows.Count -ge $test.maxRows) { throw 'Native query exceeded its bounded row limit.' }
                            $nativeRow = [ordered]@{}
                            for ($i=0; $i -lt $reader.FieldCount; $i++) {
                                $name = $reader.GetName($i)
                                if ($name.StartsWith('[') -and $name.EndsWith(']')) { $name = $name.Substring(1,$name.Length-2) }
                                $value = $reader.GetValue($i)
                                $nativeRow[$name] = if ($value -is [DBNull]) { $null } else { $value }
                            }
                            $nativeRows.Add($nativeRow)
                        }
                        $merged['Buckets'] = $nativeRows.Count
                        $merged['Quantity'] = ($nativeRows | ForEach-Object { $_['Allocated'] } | Measure-Object -Sum).Sum
                        $merged['FinalCumulative'] = ($nativeRows | ForEach-Object { $_['Cumulative'] } | Measure-Object -Maximum).Maximum
                    } else {
                        if (-not $reader.Read()) { throw 'Scalar fixture assertion returned no row.' }
                        for ($i=0; $i -lt $reader.FieldCount; $i++) {
                            $name = $reader.GetName($i)
                            if ($name.StartsWith('[') -and $name.EndsWith(']')) { $name = $name.Substring(1,$name.Length-2) }
                            $value = $reader.GetValue($i)
                            $merged[$name] = if ($value -is [DBNull]) { $null } else { $value }
                        }
                        if ($reader.Read()) { throw 'Scalar fixture assertion returned more than one row.' }
                    }
                } finally { $reader.Close(); $reader=$null }
                $fragmentTimings.Add([PSCustomObject]@{name=$fragment.name;milliseconds=$fragmentWatch.ElapsedMilliseconds})
            }
            $rows = @($merged)
            foreach ($property in $test.expect.PSObject.Properties) {
                $pass = Test-Expected $property.Value $rows[0][$property.Name]
                $assertions.Add([PSCustomObject]@{column=$property.Name;expected=$property.Value;actual=$rows[0][$property.Name];pass=$pass})
            }
            foreach ($property in $test.contains.PSObject.Properties) {
                $actual = [string]$rows[0][$property.Name]
                $assertions.Add([PSCustomObject]@{column=$property.Name;contains=$property.Value;actual=$actual;pass=$actual.Contains([string]$property.Value,[StringComparison]::OrdinalIgnoreCase)})
            }
            if ($test.aggregateRows -and $nativeRows.Count) {
                [string[]]$axisColumn = if ($test.axisColumn) { $test.axisColumn } else { $nativeRows[0].Keys | Where-Object { $_ -notin @('Allocated','Cumulative') } }
                if ($axisColumn.Count -ne 1) { throw 'Native query must return exactly one grouping column.' }
                $runningQuantity = 0.0
                foreach ($nativeRow in @($nativeRows | Sort-Object { $_[$axisColumn[0]] })) {
                    $allocated = $nativeRow['Allocated']
                    $cumulative = $nativeRow['Cumulative']
                    $runningQuantity += [double]$allocated
                    $assertions.Add([PSCustomObject]@{column='Bucket nonnegative';bucket=$nativeRow[$axisColumn[0]];actual=$allocated;pass=($null -ne $allocated -and [double]$allocated -ge -0.000001)})
                    $assertions.Add([PSCustomObject]@{column='Bucket cumulative reconciliation';bucket=$nativeRow[$axisColumn[0]];expected=$runningQuantity;actual=$cumulative;pass=(Test-Expected $runningQuantity $cumulative)})
                }
                if ($test.expectedNativeRows) {
                    $orderedRows = @($nativeRows | Sort-Object { $_[$axisColumn[0]] })
                    $assertions.Add([PSCustomObject]@{column='Native oracle row count';expected=$test.expectedNativeRows.Count;actual=$orderedRows.Count;pass=($test.expectedNativeRows.Count -eq $orderedRows.Count)})
                    for ($rowIndex=0; $rowIndex -lt [Math]::Min($orderedRows.Count,$test.expectedNativeRows.Count); $rowIndex++) {
                        foreach ($expectedColumn in $test.expectedNativeRows[$rowIndex].PSObject.Properties) {
                            $actualValue = $orderedRows[$rowIndex][$expectedColumn.Name]
                            $assertions.Add([PSCustomObject]@{column=$expectedColumn.Name;row=$rowIndex;expected=$expectedColumn.Value;actual=$actualValue;pass=(Test-Expected $expectedColumn.Value $actualValue)})
                        }
                    }
                }
            }
            $failures = @($assertions | Where-Object { -not $_.pass })
            $result = [ordered]@{name=$test.name;status=if($failures.Count){'FAIL'}else{'PASS'};milliseconds=$watch.ElapsedMilliseconds;fragments=@($fragmentTimings);assertions=@($assertions);rows=$rows;role=$test.role;dax=$test.dax}
            if ($test.aggregateRows) { $result['nativeRows'] = @($nativeRows) }
        } catch {
            $result = [ordered]@{name=$test.name;status='ERROR';milliseconds=$watch.ElapsedMilliseconds;fragment=$activeFragment;completedFragments=@($fragmentTimings);error=$_.Exception.Message;role=$test.role;dax=$test.dax}
        } finally { if ($null -ne $reader) { $reader.Close() } }
        $results.Add([PSCustomObject]$result)
        Write-Host ($test.name + ': ' + $result.status + ' (' + $result.milliseconds + ' ms)')
        [PSCustomObject]@{marker=$fixtureMarker;port=$Port;catalog=$catalog;timeoutSeconds=$TimeoutSeconds;memoryLimitKB=$MemoryLimitKB;partitionStates=$partitionStates;tests=@($results)} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    }
    $assertionCount = ($results | ForEach-Object { if ($_.assertions) { $_.assertions.Count } else { 0 } } | Measure-Object -Sum).Sum
    $summary = [PSCustomObject]@{marker=$fixtureMarker;port=$Port;catalog=$catalog;timeoutSeconds=$TimeoutSeconds;memoryLimitKB=$MemoryLimitKB;tests=$results.Count;passed=@($results | Where-Object status -eq 'PASS').Count;failed=@($results | Where-Object status -eq 'FAIL').Count;errors=@($results | Where-Object status -eq 'ERROR').Count;assertions=$assertionCount;output=$OutputPath}
    $summary | ConvertTo-Json -Depth 5
    if ($summary.failed -gt 0 -or $summary.errors -gt 0) { exit 1 }
} finally {
    if ($null -ne $roleServer) { $roleServer.Disconnect() }
    $server.Disconnect()
}

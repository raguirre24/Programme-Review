param([Parameter(Mandatory=$true)][int]$Port)

# Authorised after final acceptance: remove this exact temporary fixture only.
$ErrorActionPreference = 'Stop'
if ($Port -ne 65096) { throw 'Cleanup is pinned to the authorised local endpoint.' }
$fixtureId = 'ResourcePlaygroundFixture_20260911_d0377702f34d44de94dce6902844a08a'
$protectedId = '3848c689-7848-44b6-8dfe-8b8c1f7f8fa8'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts = Join-Path (Split-Path $repo -Parent) 'resource_playground_review\repair_20260911'
$acceptance = Get-Content -LiteralPath (Join-Path $artifacts 'fixture_acceptance_summary.json') -Raw | ConvertFrom-Json
$sourceHash = (Get-FileHash -LiteralPath (Join-Path $repo 'Project Review - Programme (datalake).SemanticModel\definition\tables\Resource Scenario Measures.tmdl') -Algorithm SHA256).Hash
if ($acceptance.result -ne 'PASS' -or $acceptance.fixtureDatabase -ne $fixtureId -or $acceptance.sourceMeasureSha256 -ne $sourceHash -or $acceptance.sourceExpressionChecks -ne 60) { throw 'Final source acceptance is required before fixture cleanup.' }
$tom = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')) { [Reflection.Assembly]::LoadFrom((Join-Path $tom $dll)) | Out-Null }
function Get-MetadataHash($Database) {
    $options = [Microsoft.AnalysisServices.Tabular.SerializeOptions]::new()
    $serialized = [Microsoft.AnalysisServices.Tabular.JsonSerializer]::SerializeDatabase($Database,$options)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($serialized)))
}
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
try {
    $server.Connect("localhost:$Port")
    $protected = $server.Databases.Find($protectedId)
    $fixture = $server.Databases.Find($fixtureId)
    if ($null -eq $protected -or $null -eq $fixture -or $fixture.Name -ne $fixtureId -or $fixture.ID -eq $protectedId -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne 'resource-playground-repair-20260911' -or $fixture.Model.Tables.Count -ne 17 -or $null -eq $fixture.Model.Tables.Find('Fixture Identity') -or $fixture.Model.Tables.Find('01 XER_TASK')) { throw 'Cleanup identity guards failed.' }
    $beforeIds = @($server.Databases | ForEach-Object ID | Sort-Object)
    $beforeHash = Get-MetadataHash $protected
    $beforeTables = $protected.Model.Tables.Count
    $fixture.Drop()
    $server.Disconnect()
    $server.Connect("localhost:$Port")
    $protectedAfter = $server.Databases.Find($protectedId)
    if ($null -eq $protectedAfter -or $server.Databases.Find($fixtureId)) { throw 'Post-cleanup database-preservation check failed.' }
    $afterHash = Get-MetadataHash $protectedAfter
    $afterIds = @($server.Databases | ForEach-Object ID | Sort-Object)
    $expectedIds = @($beforeIds | Where-Object { $_ -ne $fixtureId })
    if ($beforeHash -ne $afterHash -or @(Compare-Object $expectedIds $afterIds).Count) { throw 'Protected database metadata or unrelated database inventory changed during cleanup.' }
    $result = [PSCustomObject]@{result='PASS';port=$Port;removedFixture=$fixtureId;protectedDatabase=$protectedId;protectedTables=$beforeTables;protectedMetadataSha256Before=$beforeHash;protectedMetadataSha256After=$afterHash;remainingDatabaseIds=$afterIds;scope='Only the exact accepted synthetic fixture was dropped. Protected metadata and all other database IDs match.'}
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $artifacts 'fixture_cleanup.json') -Encoding utf8
    $result | ConvertTo-Json -Depth 6
} finally { $server.Disconnect() }

param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$FixtureDatabaseId
)

# Experimental expressions are applied only to the marked synthetic fixture.
$ErrorActionPreference = 'Stop'
if ($Port -ne 65096 -or $FixtureDatabaseId -notmatch '^ResourcePlaygroundFixture_20260911_[a-f0-9]{32}$') { throw 'Authorised fixture endpoint and ID are required.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts = Join-Path (Split-Path $repo -Parent) 'resource_playground_review\repair_20260911'
$tom = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')) { [Reflection.Assembly]::LoadFrom((Join-Path $tom $dll)) | Out-Null }
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
try {
    $server.Connect("localhost:$Port")
    $fixture = $server.Databases.Find($FixtureDatabaseId)
    if ($null -eq $fixture -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne 'resource-playground-repair-20260911' -or $fixture.Model.Tables.Count -ne 17 -or $fixture.Model.Tables.Find('01 XER_TASK')) { throw 'Fixture identity guard failed.' }
    $table = $fixture.Model.Tables.Find('Resource Scenario Measures')
    $map = @{'Scenario Chart Quantity'='chart_quantity_local_candidate.dax';'Scenario Chart Cumulative Quantity'='chart_cumulative_local_candidate.dax'}
    $evidence = @()
    foreach ($name in $map.Keys) {
        $path = Join-Path $artifacts $map[$name]
        $measure = $table.Measures.Find($name)
        if ($null -eq $measure) { throw "Missing existing fixture measure: $name" }
        $evidence += [PSCustomObject]@{measure=$name;candidate=$path;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash;previousExpression=$measure.Expression}
        $measure.Expression = Get-Content -LiteralPath $path -Raw
    }
    $fixture.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Calculate)
    $fixture.Model.SaveChanges() | Out-Null
    [PSCustomObject]@{result='PASS';fixtureDatabase=$FixtureDatabaseId;port=$Port;scope='Only two existing chart measures in the marked fixture';changes=$evidence} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $artifacts 'fixture_candidate_sync.json') -Encoding utf8
    Write-Host 'Two chart candidates applied only to the marked fixture.'
} finally { $server.Disconnect() }

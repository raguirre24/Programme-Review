[CmdletBinding()]
param([string]$ServerAddress, [string]$Catalog)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom
$guideSource = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder(
    (Join-Path $PSScriptRoot '../../Project Review - Programme (datalake).SemanticModel/definition'))
$guidePorts = if ($ServerAddress) { @($ServerAddress) } else {
    $guideProcesses = @(Get-Process msmdsrv | Select-Object -ExpandProperty Id)
    @(Get-NetTCPConnection -State Listen | Where-Object { $_.OwningProcess -in $guideProcesses } |
        Select-Object -ExpandProperty LocalPort -Unique | ForEach-Object { "localhost:$_" })
}
$guideMatches = @()
foreach ($guideAddress in $guidePorts) {
    $guideConnection = [Microsoft.AnalysisServices.Tabular.Server]::new()
    $guideConnection.Connect("Data Source=$guideAddress")
    foreach ($guideDatabase in $guideConnection.Databases) {
        if ($Catalog -and $guideDatabase.ID -ne $Catalog) { continue }
        if ($guideDatabase.Model.Tables.Contains('Schedule Metric Guide')) {
            $guideMatches += [pscustomobject]@{Connection=$guideConnection;Database=$guideDatabase;Address=$guideAddress}
        }
    }
    if (-not @($guideMatches | Where-Object Connection -eq $guideConnection).Count) { $guideConnection.Disconnect() }
}
try {
    Assert-ScheduleMetric ($guideMatches.Count -eq 1) 'Specify the main project connection; expected exactly one loaded guide.'
    $guideTarget = $guideMatches[0]
    $guideLive = $guideTarget.Database.Model.Tables['Schedule Metric Guide']
    $guideDisk = $guideSource.Tables['Schedule Metric Guide']
    Assert-ScheduleMetric ($guideLive.Partitions[0].Source.Expression.Trim() -eq $guideDisk.Partitions[0].Source.Expression.Trim()) 'Guide content is stale.'
    Assert-ScheduleMetric (@($guideTarget.Database.Model.Relationships | Where-Object {
        $_.FromTable.Name -eq 'Schedule Metric Guide' -or $_.ToTable.Name -eq 'Schedule Metric Guide'
    }).Count -eq 0) 'Guide must be disconnected.'
    $guideRows = Invoke-ScheduleMetricsDax -Target $guideTarget -Query @'
EVALUATE 'Schedule Metric Guide' ORDER BY 'Schedule Metric Guide'[Order]
'@
    Assert-ScheduleMetric ($guideRows.Count -eq 18) 'Guide must contain all 18 retained metric definitions.'
    $guideExpected = @(Get-Content (Join-Path $PSScriptRoot 'metric_guide.json') -Raw | ConvertFrom-Json | Select-Object -ExpandProperty rows | Sort-Object sort_order)
    for ($guideIndex=0; $guideIndex -lt $guideRows.Count; $guideIndex++) {
        Assert-ScheduleMetric ($guideRows[$guideIndex].'Schedule Metric Guide[Metric]' -eq $guideExpected[$guideIndex].metric) 'Guide metric order/content mismatch.'
        $expectedRow = $guideExpected[$guideIndex]
        $expectedCells = @{
            'Meaning and calculation' = $expectedRow.meaning + ' Why it matters: ' + $expectedRow.rationale + ' Calculation: ' + $expectedRow.calculation
            'Target / score' = $expectedRow.threshold + ' ' + $expectedRow.score_note
            'Scope and notes' = $expectedRow.population + ' ' + $expectedRow.limitations
        }
        foreach($guideColumn in @('Meaning and calculation','Target / score','Scope and notes')) {
            Assert-ScheduleMetric (-not [string]::IsNullOrWhiteSpace($guideRows[$guideIndex]."Schedule Metric Guide[$guideColumn]")) "Empty guide field: $guideColumn"
            $expectedCell = $expectedCells[$guideColumn].Replace("`n", ' ')
            Assert-ScheduleMetric ($guideRows[$guideIndex]."Schedule Metric Guide[$guideColumn]" -ceq $expectedCell) "Stale loaded guide cell: $($expectedRow.metric) / $guideColumn"
        }
    }
    [pscustomobject]@{Server=$guideTarget.Address;Catalog=$guideTarget.Database.ID;GuideRows=$guideRows.Count;Disconnected=$true;ContentParity=$true;Status='passed'} | ConvertTo-Json
} finally {
    foreach ($guideMatch in $guideMatches) { $guideMatch.Connection.Disconnect() }
}

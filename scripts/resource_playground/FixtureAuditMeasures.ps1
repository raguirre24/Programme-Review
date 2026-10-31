# Dot-source from the fixture create/sync scripts. The fixture suites read measures the report does not use
# (audit_measures.json, written by generate_measures.py --audit-json); the model trim of October 2026 removed
# them from the semantic model, so each marked fixture database receives them here instead.
function Set-FixtureAuditMeasures {
    param([Parameter(Mandatory = $true)]$Table, [string[]]$Only)
    $records = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'audit_measures.json') | ConvertFrom-Json
    $applied = 0
    foreach ($record in $records) {
        if ($Only -and $record.name -notin $Only) { continue }
        $measure = $Table.Measures.Find($record.name)
        if ($null -eq $measure) {
            $measure = [Microsoft.AnalysisServices.Tabular.Measure]::new()
            $measure.Name = $record.name
            $Table.Measures.Add($measure)
        }
        $measure.Expression = $record.expression
        $measure.FormatString = $record.formatString
        $measure.IsHidden = [bool]$record.isHidden
        $measure.DisplayFolder = $record.displayFolder
        $applied++
    }
    if ($Only -and $applied -ne @($Only).Count) { throw 'Requested fixture audit measure is not in audit_measures.json.' }
    return $applied
}

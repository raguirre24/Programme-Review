$rsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\12_XER_RSRC.csv'
$dist = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\15_XER_RESOURCE_DISTRIBUTION.csv'

$rsrcKeys = $rsrc | Group-Object rsrc_id_key
$dupes = $rsrcKeys | Where-Object { $_.Count -gt 1 }
Write-Output ("12_XER_RSRC: {0} total, {1} unique rsrc_id_key, {2} duplicates" -f $rsrc.Count, $rsrcKeys.Count, $dupes.Count)

$distUniqueKeys = ($dist | Select-Object -ExpandProperty rsrc_id_key -Unique)
$rsrcKeySet = @{}
foreach ($r in $rsrc) { $rsrcKeySet[$r.rsrc_id_key] = $true }
$missing = $distUniqueKeys | Where-Object { -not $rsrcKeySet.ContainsKey($_) }
Write-Output ("15_DIST: {0} unique rsrc_id_keys, {1} missing from 12_RSRC" -f $distUniqueKeys.Count, @($missing).Count)

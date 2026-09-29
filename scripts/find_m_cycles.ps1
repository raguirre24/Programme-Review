$ErrorActionPreference = "Stop"

$expressionsFile = "Project Review - Programme (datalake).SemanticModel/definition/expressions.tmdl"
$tablesDir = "Project Review - Programme (datalake).SemanticModel/definition/tables"

# Function to strip comments and string literals from M code
function Strip-MCommentsAndStrings($code) {
    # Replace block comments /* ... */
    $code = [regex]::Replace($code, '/\*.*?\*/', '', [System.Text.RegularExpressions.RegexOptions]::Singleline)
    # Replace line comments // ...
    $code = [regex]::Replace($code, '//.*$', '', [System.Text.RegularExpressions.RegexOptions]::Multiline)
    # Replace string literals "..." (handling escaped "")
    $code = [regex]::Replace($code, '"([^"]|"")*"', '""')
    return $code
}

# 1. Parse expressions.tmdl
$expLines = Get-Content -Path $expressionsFile

$definitions = @{} # Name -> Raw Code
$cleanDefinitions = @{} # Name -> Code stripped of strings/comments
$currentName = $null
$currentCode = New-Object System.Text.StringBuilder

foreach ($line in $expLines) {
    if ($line -match '^expression\s+([^\s=]+)') {
        if ($currentName) {
            $raw = $currentCode.ToString()
            $definitions[$currentName] = $raw
            $cleanDefinitions[$currentName] = Strip-MCommentsAndStrings $raw
        }
        $currentName = $matches[1].Trim("'")
        $currentCode = New-Object System.Text.StringBuilder
        [void]$currentCode.AppendLine($line)
    } elseif ($currentName) {
        [void]$currentCode.AppendLine($line)
    }
}
if ($currentName) {
    $raw = $currentCode.ToString()
    $definitions[$currentName] = $raw
    $cleanDefinitions[$currentName] = Strip-MCommentsAndStrings $raw
}

# 2. Parse table TMDLs that have m partitions
$tableFiles = Get-ChildItem -Path $tablesDir -Filter "*.tmdl"
foreach ($tf in $tableFiles) {
    $tLines = Get-Content -Path $tf.FullName
    $tableName = [System.IO.Path]::GetFileNameWithoutExtension($tf.Name)
    
    $inPartition = $false
    $isM = $false
    $partCode = New-Object System.Text.StringBuilder

    foreach ($line in $tLines) {
        if ($line -match '^\s*partition\s+.*=\s*(m|calculated)') {
            $inPartition = $true
            $isM = ($matches[1] -eq 'm')
        } elseif ($inPartition -and $line -match '^\s*annotation') {
            $inPartition = $false
        }
        if ($inPartition -and $isM) {
            [void]$partCode.AppendLine($line)
        }
    }
    if ($isM -and $partCode.Length -gt 0) {
        $raw = $partCode.ToString()
        $definitions[$tableName] = $raw
        $cleanDefinitions[$tableName] = Strip-MCommentsAndStrings $raw
    }
}

# 3. Build adjacency list based on clean code
$allKeys = $definitions.Keys | Sort-Object -Property Length -Descending

$graph = @{}
foreach ($node in $cleanDefinitions.Keys) {
    $graph[$node] = [System.Collections.Generic.HashSet[string]]::new()
    $code = $cleanDefinitions[$node]
    
    foreach ($candidate in $allKeys) {
        if ($candidate -eq $node) { continue }
        
        $pattern = "(?<![#""\w])" + [regex]::Escape($candidate) + "(?![#""\w])|#""" + [regex]::Escape($candidate) + """"
        if ($code -match $pattern) {
            $graph[$node].Add($candidate) | Out-Null
        }
    }
}

# 4. Detect cycles using DFS
$visited = @{}
$recStack = @{}
$cyclesFound = 0

function FindCycles($curr, $path) {
    $visited[$curr] = $true
    $recStack[$curr] = $true
    $newPath = $path + @($curr)

    foreach ($neighbor in $graph[$curr]) {
        if (-not $visited[$neighbor]) {
            FindCycles $neighbor $newPath
        } elseif ($recStack[$neighbor]) {
            $cycleStartIdx = [array]::IndexOf($newPath, $neighbor)
            $cyclePath = $newPath[$cycleStartIdx..($newPath.Length - 1)] + @($neighbor)
            Write-Host "CYCLE DETECTED: $($cyclePath -join ' -> ')" -ForegroundColor Red
            $script:cyclesFound++
        }
    }

    $recStack[$curr] = $false
}

foreach ($node in $graph.Keys) {
    $visited[$node] = $false
    $recStack[$node] = $false
}

foreach ($node in $graph.Keys) {
    if (-not $visited[$node]) {
        FindCycles $node @()
    }
}

if ($cyclesFound -eq 0) {
    Write-Host "No cycles found in global query dependency graph." -ForegroundColor Green
} else {
    Write-Host "`nTotal cycles found: $cyclesFound" -ForegroundColor Red
}

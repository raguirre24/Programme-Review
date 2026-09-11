param(
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [string]$TomDirectory,
    [switch]$CheckRoundTrip
)

# Read metadata through TOM so fenced, inline and Desktop-indented expressions
# receive identical coverage. This does not compile DAX or connect to an engine.
$ErrorActionPreference = 'Stop'
if (-not $TomDirectory) {
    $cache = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.nuget\packages\microsoft.analysisservices'
    $package = Get-ChildItem -LiteralPath $cache -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'lib\net8.0\Microsoft.AnalysisServices.Tabular.dll') } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $package) { throw 'Pass -TomDirectory pointing to Microsoft.AnalysisServices net8.0 assemblies.' }
    $TomDirectory = Join-Path $package.FullName 'lib\net8.0'
}
foreach ($name in @('Microsoft.AnalysisServices.Core.dll', 'Microsoft.AnalysisServices.Tabular.dll', 'Microsoft.AnalysisServices.Tabular.Json.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $TomDirectory $name)) | Out-Null
}

function Read-ModelMetadata($Model) {
    return [ordered]@{
        tables = @($Model.Tables | Sort-Object Name | ForEach-Object {
            $table = $_
            [ordered]@{
                name = $table.Name
                columns = @($table.Columns | Sort-Object Name | ForEach-Object {
                    [ordered]@{ name = $_.Name; type = $_.GetType().Name; dataType = $_.DataType.ToString(); sourceColumn = $_.SourceColumn }
                })
                measures = @($table.Measures | Sort-Object Name | ForEach-Object {
                    [ordered]@{ name = $_.Name; expression = $_.Expression.Trim().Replace("`r`n", "`n") }
                })
                calculatedPartitions = @($table.Partitions | Where-Object {
                    $_.Source -is [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]
                } | Sort-Object Name | ForEach-Object {
                    [ordered]@{ name = $_.Name; expression = $_.Source.Expression.Trim().Replace("`r`n", "`n") }
                })
            }
        })
    }
}

$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $ModelRoot).Path)
$metadata = Read-ModelMetadata $model
$roundTrip = @{ status = 'NOT_RUN'; scope = 'TOM serialisation only, not a Desktop or engine test.' }
if ($CheckRoundTrip) {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $tempName = 'resource-playground-tom-' + [Guid]::NewGuid().ToString('N')
    $tempFolder = [IO.Path]::GetFullPath((Join-Path $tempRoot $tempName))
    if ([IO.Path]::GetDirectoryName($tempFolder) -ne $tempRoot -or [IO.Path]::GetFileName($tempFolder) -ne $tempName) {
        throw 'The task-owned round-trip folder must be an immediate child of the temporary directory.'
    }
    try {
        [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::SerializeModelToFolder($model, $tempFolder)
        $roundTrippedModel = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($tempFolder)
        $roundTrippedMetadata = Read-ModelMetadata $roundTrippedModel
        if (($metadata | ConvertTo-Json -Depth 12 -Compress) -cne ($roundTrippedMetadata | ConvertTo-Json -Depth 12 -Compress)) {
            throw 'TOM round-trip changed the extracted table, field or expression metadata.'
        }
        $roundTrip = @{ status = 'PASS'; scope = 'TOM serialisation of the supplied definitions preserves all extracted expressions and fields; no Desktop or engine execution.' }
    }
    finally {
        if ((Test-Path -LiteralPath $tempFolder) -and
            [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($tempFolder)) -eq $tempRoot -and
            [IO.Path]::GetFileName($tempFolder) -eq $tempName) {
            Remove-Item -LiteralPath $tempFolder -Recurse -Force
        }
    }
}
$metadata.roundTrip = $roundTrip
$metadata | ConvertTo-Json -Depth 12 -Compress

[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory
)

# Compatibility entry point: the eight-check review policy supersedes the
# former nine-check binary score. The focused runner evaluates real candidate
# expressions with aggregate inputs, including missing/partial denominators.
& (Join-Path $PSScriptRoot 'Validate-ReviewBands.ps1') @PSBoundParameters -FixturesOnly

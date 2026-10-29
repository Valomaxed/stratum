param([int]$Port = 8766, [switch]$Train, [switch]$Study, [switch]$Robust)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$twinPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $twinPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
}
& $twinPython -c 'import numpy, scipy, sklearn'
if ($LASTEXITCODE -ne 0) {
    python -m pip --python .venv install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
if ($Train -or !(Test-Path -LiteralPath 'data\forest.joblib')) {
    & $twinPython -m twin train
    if ($LASTEXITCODE -ne 0) { throw 'Training failed' }
}
if ($Study -or !(Test-Path -LiteralPath 'data\load-study\multi.joblib') -or !(Test-Path -LiteralPath 'data\load-study\single.joblib')) {
    & $twinPython -m twin study
    if ($LASTEXITCODE -ne 0) { throw 'Paired excitation study failed' }
}
if ($Robust -or $Study -or !(Test-Path -LiteralPath 'data\robust-study\config.json') -or !(Test-Path -LiteralPath 'data\robust-study\report.json')) {
    & $twinPython -m twin robust-study
    if ($LASTEXITCODE -ne 0) { throw 'Noise-aware refinement validation failed' }
}
& $twinPython -m twin serve --port $Port

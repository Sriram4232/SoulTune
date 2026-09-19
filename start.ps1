param([switch]$Install)
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if ($Install -or !(Test-Path -LiteralPath $pythonExecutable)) {
    if (!(Test-Path -LiteralPath $pythonExecutable)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
    }
    & $pythonExecutable -m pip install -r Backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Push-Location -LiteralPath (Join-Path $projectDirectory 'Frontend')
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } finally { Pop-Location }
}
if (!(Test-Path -LiteralPath 'Frontend/node_modules')) {
    throw 'Dependencies are missing. Run .\start.ps1 -Install first.'
}
Push-Location -LiteralPath (Join-Path $projectDirectory 'Frontend')
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'VibeTune is starting at http://127.0.0.1:8000. Press Ctrl+C to stop.'
& $pythonExecutable -m uvicorn app.main:app --app-dir Backend --host 127.0.0.1 --port 8000

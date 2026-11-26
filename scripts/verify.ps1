$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Push-Location $RootDir

function Resolve-PythonInterpreter {
    $Candidates = @()
    if ($env:DATN2_PYTHON) { $Candidates += $env:DATN2_PYTHON }
    $Candidates += ".venv\Scripts\python.exe"
    $Candidates += "C:\Python314\python.exe"
    $Candidates += "C:\Program Files\Python311\python.exe"
    $PathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($PathPython) { $Candidates += $PathPython.Source }

    $Available = @()
    foreach ($Candidate in $Candidates) {
        if (-not $Candidate) { continue }
        if ((Test-Path $Candidate) -or (Get-Command $Candidate -ErrorAction SilentlyContinue)) {
            $Available += $Candidate
            $PrevPref = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                & $Candidate -m pytest --version *> $null
                if ($LASTEXITCODE -eq 0) {
                    return $Candidate
                }
            }
            finally {
                $ErrorActionPreference = $PrevPref
            }
        }
    }

    if (Test-Path "C:\Python314\python.exe") { return "C:\Python314\python.exe" }
    if ($Available.Count -gt 0) { return $Available[0] }
    return "python"
}

try {
    $Python = Resolve-PythonInterpreter
    Write-Host "Using Python: $Python" -ForegroundColor DarkGray

    Write-Host "=== [1/6] Python syntax check (compileall) ===" -ForegroundColor Cyan
    & $Python -m compileall -q src tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [2/6] Architecture & size guardrails ===" -ForegroundColor Cyan
    & $Python scripts/check_guardrails.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [3/6] Schema & MCP config validation ===" -ForegroundColor Cyan
    & $Python scripts/validate_schemas.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "=== [4/6] Python static lint (ruff) ===" -ForegroundColor Cyan
    $RuffCmd = Get-Command ruff -ErrorAction SilentlyContinue
    if ($RuffCmd) {
        & $RuffCmd.Source check src tests scripts
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        $HasPythonRuff = $false
        $PrevPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $Python -m ruff --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $HasPythonRuff = $true
            }
        }
        finally {
            $ErrorActionPreference = $PrevPref
        }
        if ($HasPythonRuff) {
            & $Python -m ruff check src tests scripts
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        } else {
            Write-Host "SKIP: ruff not installed (pip install ruff)" -ForegroundColor Yellow
        }
    }

    Write-Host "=== [5/6] Frontend JS syntax check ===" -ForegroundColor Cyan
    $JsFiles = Get-ChildItem -Path "src\frontend\js" -Filter "*.js" -Recurse -ErrorAction SilentlyContinue
    if ($JsFiles) {
        $NodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($NodeCmd) {
            foreach ($f in $JsFiles) {
                & node --check $f.FullName
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            }
            Write-Host "JS SYNTAX OK ($($JsFiles.Count) files)" -ForegroundColor Green
        } else {
            Write-Host "SKIP: node not found in PATH" -ForegroundColor Yellow
        }
    } else {
        Write-Host "SKIP: no JS files yet" -ForegroundColor DarkGray
    }

    Write-Host "=== [6/6] Automated tests (pytest) ===" -ForegroundColor Cyan
    $TestFiles = Get-ChildItem -Path "tests" -Filter "test_*.py" -Recurse -ErrorAction SilentlyContinue
    if ($TestFiles) {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        Write-Host "SKIP: no test_*.py files yet" -ForegroundColor DarkGray
    }

    Write-Host "`nVERIFY PASSED" -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}

# Optima AI Browser installer for Windows.
#   powershell -ExecutionPolicy Bypass -File install.ps1          first-run window
#   powershell -ExecutionPolicy Bypass -File install.ps1 --cli    first run in the terminal
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$OptimaHome = if ($env:OPTIMA_HOME) { $env:OPTIMA_HOME } else { Join-Path $HOME ".optima" }
New-Item -ItemType Directory -Force -Path $OptimaHome | Out-Null

# Copy the program into ~/.optima so it keeps working if this folder moves.
$App = Join-Path $OptimaHome "app"
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null
foreach ($d in @("src", "skill", "assets")) { Copy-Item -Recurse (Join-Path $Here $d) (Join-Path $App $d) }
$env:PYTHONPATH = Join-Path $App "src"

function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# Find Python 3.9+ (the py launcher first, then python).
$PyCmd = $null
foreach ($cand in @(@("py", "-3"), @("python"))) {
  if (Get-Command $cand[0] -ErrorAction SilentlyContinue) {
    $rest = @($cand | Select-Object -Skip 1)
    & $cand[0] @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $PyCmd = $cand; break }
  }
}
if (-not $PyCmd) {
  Write-Host "Python 3.9 or newer is required: https://www.python.org/downloads/windows/ (tick 'Add to PATH')"
  exit 1
}

$Venv = Join-Path $OptimaHome "venv"
Say "Preparing Python + Playwright in $Venv"
$rest = @($PyCmd | Select-Object -Skip 1)
& $PyCmd[0] @rest -m venv $Venv
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -r (Join-Path $Here "requirements.txt")

# Microsoft Edge ships with Windows, so usually nothing else is downloaded.
$Edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ }
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ }
if ($Edge -or $Chrome) {
  Say "Using the browser already on this PC (Edge or Chrome)"
} else {
  Say "Downloading Playwright's Chromium (one time)"
  & $Py -m playwright install chromium
}

Say "First run"
& $Py -m optima setup @args

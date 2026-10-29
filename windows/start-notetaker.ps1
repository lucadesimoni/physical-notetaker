# Start the Meeting Notetaker on Windows (test setup).
#
# Double-click start-notetaker.bat. The first start installs the Python
# packages (a few minutes); later starts take seconds. The web page opens
# in the browser; Enter in this window starts/stops a recording.

# "Continue": in Windows PowerShell 5.1, "Stop" turns any stderr output of a
# program (e.g. "Python 3.12 not found" while probing) into a fatal error.
# Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
# Python output with umlauts and symbols works in every console
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

function Find-Python {
    # PyAudio (microphone access) has ready-made packages for these versions;
    # 3.12 is the safest choice.
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($v in @("3.12", "3.11", "3.13", "3.10")) {
            & py "-$v" -c "import sys" 2>$null
            # The leading comma keeps the list a list when returned
            if ($LASTEXITCODE -eq 0) { return ,@("py", "-$v") }
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $ok = & python -c "import sys; print(int((3, 10) <= sys.version_info[:2] <= (3, 13)))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ok -eq "1") { return ,@("python") }
    }
    return $null
}

$Venv = Join-Path $Root "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $py = Find-Python
    if (-not $py) {
        Write-Host ""
        Write-Host "Python 3.10 - 3.13 not found." -ForegroundColor Red
        Write-Host "Install Python 3.12 from https://www.python.org/downloads/windows/"
        Write-Host "(tick 'Add python.exe to PATH'), then start again."
        exit 1
    }
    Write-Step "Creating the Python environment"
    $pyArgs = @($py | Select-Object -Skip 1)
    & $py[0] @pyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# Install or update the packages when the requirements changed
$Marker = Join-Path $Venv ".installed"
$Hash = (Get-FileHash (Join-Path $Root "requirements.txt")).Hash + (Get-FileHash (Join-Path $Root "setup.py")).Hash
if (-not (Test-Path $Marker) -or (Get-Content $Marker -Raw).Trim() -ne $Hash) {
    Write-Step "Installing packages (first start: a few minutes)"
    & $VenvPython -m pip install --quiet --upgrade pip
    # Editable install: 'git pull' updates the program without reinstalling
    & $VenvPython -m pip install --quiet -e $Root
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Installing failed. If the error mentions PyAudio, install Python 3.12" -ForegroundColor Red
        Write-Host "and delete the 'venv' folder, then start again."
        exit 1
    }
    Set-Content -Path $Marker -Value $Hash
}

$Config = Join-Path $Root "config.yaml"
if (-not (Test-Path $Config)) {
    Write-Step "Creating config.yaml"
    & $VenvPython -c @"
from voxtral_notetaker.config import NotetakerConfig
c = NotetakerConfig()
c.service.recordings_dir = 'recordings'
c.storage.local_path = 'recordings'
c.web.port = 8080
c.web.setup_hotspot = False   # Wi-Fi setup is for the Raspberry Pi
c.device.input_device = ''    # USB device buttons are Linux only
c.save('config.yaml')
"@
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Step "Starting (web page opens in the browser)"
Write-Host "    First time: choose a PIN and enter your Mistral API key in Einstellungen."
Write-Host "    If Windows asks about network access: allow it to use the page on your phone."
Write-Host ""
& $VenvPython -m voxtral_notetaker run --open --config $Config
exit $LASTEXITCODE

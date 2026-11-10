# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
# Start the Meeting Notetaker on Windows.
#
# Double-click start-notetaker.bat. Everything else is automatic:
#   - installs Python 3.12 if needed (winget, built into Windows 10/11)
#   - installs the packages (first start: a few minutes)
#   - creates a desktop shortcut "Notetaker"
#   - opens the web page: paste the Mistral API key once, done
# Enter in this window starts/stops a recording.

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
    foreach ($exe in @("python", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $ok = & $exe -c "import sys; print(int((3, 10) <= sys.version_info[:2] <= (3, 13)))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ok -eq "1") { return ,@($exe) }
    }
    return $null
}

function Install-Python {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }
    Write-Step "Installing Python 3.12 (one time, about a minute)"
    & winget install --id Python.Python.3.12 --exact --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    return ($LASTEXITCODE -eq 0)
}

$Venv = Join-Path $Root "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $py = Find-Python
    if (-not $py) {
        if (Install-Python) { $py = Find-Python }
    }
    if (-not $py) {
        Write-Host ""
        Write-Host "Python could not be installed automatically." -ForegroundColor Red
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
    Write-Step "Installing packages (first start: a few minutes, please wait)"
    # pip and its build tools print harmless warnings that look alarming:
    # keep their output in a log and show it only if installing fails
    $Log = Join-Path $Venv "install.log"
    & $VenvPython -m pip install --quiet --upgrade pip *> $Log
    # Editable install: 'git pull' updates the program without reinstalling
    & $VenvPython -m pip install --quiet -e $Root *>> $Log
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Get-Content $Log -Tail 30
        Write-Host ""
        Write-Host "Installing failed (full log: $Log)." -ForegroundColor Red
        Write-Host "If the error mentions PyAudio, install Python 3.12, delete the 'venv' folder"
        Write-Host "and start again."
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
c.web.host = '127.0.0.1'      # only this PC: no firewall question, no PIN needed
c.web.setup_hotspot = False   # Wi-Fi setup is for the Raspberry Pi
c.device.input_device = ''    # USB device buttons are Linux only
c.save('config.yaml')
"@
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# Desktop shortcut, so next time it is one double-click from the desktop
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = Join-Path $Desktop "Notetaker.lnk"
# Installed with Notetaker-Setup.exe: the installer manages the shortcuts
$Installed = Test-Path (Join-Path $Root "unins000.exe")
if ($Desktop -and -not $Installed -and -not (Test-Path $Shortcut)) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($Shortcut)
        $link.TargetPath = Join-Path $PSScriptRoot "start-notetaker.bat"
        $link.WorkingDirectory = $Root
        $link.Description = "Meeting Notetaker"
        $link.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,168"
        $link.Save()
        Write-Step "Desktop shortcut 'Notetaker' created"
    } catch {
        # Not important enough to stop for
    }
}

# Automated test (GitHub Actions on Windows): set up, but do not start
if ($env:NOTETAKER_SETUP_ONLY -eq "1") {
    Write-Step "Setup done"
    exit 0
}

Write-Step "Starting (the web page opens in the browser)"
Write-Host "    First time: paste your Mistral API key on the page. That's all."
Write-Host "    Keep this window open while you use the notetaker."
Write-Host ""
& $VenvPython -m voxtral_notetaker run --open --config $Config
exit $LASTEXITCODE

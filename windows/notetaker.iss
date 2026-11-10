; SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
; Copyright (c) 2026 Outthinkx by Luca De Simoni
;
; Windows installer (Inno Setup 6): Notetaker-Setup-<version>.exe
;
; Build:  iscc /DAppVersion=1.1.0 /DSourceRoot=<folder with the program files> windows\notetaker.iss
; Signed: add /DSign and /Ssigntool="..." (see .github/workflows/release.yml)
;
; Installs per user (no administrator rights, no UAC prompt) into
; %LOCALAPPDATA%\Programs\Notetaker, because the program keeps its Python
; environment, settings and recordings next to itself.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "Notetaker"
#define AppPublisher "Outthinkx by Luca De Simoni"
#define AppUrl "https://github.com/lucadesimoni/physical-notetaker"
#define PowerShell "{sys}\WindowsPowerShell\v1.0\powershell.exe"

[Setup]
AppId={{7E3C6E2A-5B7D-4C9E-9A63-0B1F2D8C4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppCopyright=Copyright (c) 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=Copyright (c) 2026 {#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#SourceRoot}\LICENSE
SetupIconFile={#SourceRoot}\windows\notetaker.ico
UninstallDisplayIcon={app}\windows\notetaker.ico
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename=Notetaker-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
#ifdef Sign
SignTool=signtool
SignedUninstaller=yes
#endif

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.LaunchNow=Notetaker jetzt starten
en.LaunchNow=Start Notetaker now

[Messages]
de.FinishedLabel=[name] ist installiert.%n%nBeim ersten Start werden Python und die benötigten Pakete eingerichtet (einige Minuten). Danach nur noch den Mistral-API-Schlüssel eintragen.
en.FinishedLabel=[name] is installed.%n%nThe first start sets up Python and the required packages (a few minutes). Then just enter your Mistral API key.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceRoot}\voxtral_notetaker\*"; DestDir: "{app}\voxtral_notetaker"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__,*.pyc"
Source: "{#SourceRoot}\windows\*"; DestDir: "{app}\windows"; Flags: recursesubdirs ignoreversion; Excludes: "*.iss"
Source: "{#SourceRoot}\examples\*"; DestDir: "{app}\examples"; Flags: recursesubdirs ignoreversion
Source: "{#SourceRoot}\setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{#PowerShell}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\start-notetaker.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\windows\notetaker.ico"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{#PowerShell}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\start-notetaker.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\windows\notetaker.ico"; Tasks: desktopicon

[Run]
Filename: "{#PowerShell}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\start-notetaker.ps1"""; WorkingDir: "{app}"; Description: "{cm:LaunchNow}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; The Python environment and caches are created by the first start.
; Settings (config.yaml) and recordings are kept: they are the user's data.
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\voxtral_notetaker\__pycache__"
Type: filesandordirs; Name: "{app}\*.egg-info"
Type: filesandordirs; Name: "{app}\build"
Type: files; Name: "{app}\smoke-service.log"
Type: filesandordirs; Name: "{app}\smoke-voice"

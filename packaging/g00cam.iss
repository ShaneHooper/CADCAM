; Inno Setup script for G00 CAM: one "G00-CAM-Setup.exe" instead of a zip.
;   iscc /DAppVersion=0.1.0 packaging\g00cam.iss      (after pyinstaller packaging/g00cam.spec)
; Installs per user (no admin rights needed on a work laptop) into
; %LOCALAPPDATA%\Programs\G00 CAM, with a Start menu entry and an optional desktop icon.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "G00 CAM"
#define AppExe "G00 CAM.exe"

[Setup]
; Keep AppId fixed: a new setup then upgrades the installed copy instead of adding a second one.
AppId={{5C0A7E61-2F9B-4F00-9C0D-6A3D5F1B2E47}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=G-SEND.IO
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=G00-CAM-Setup
SetupIconFile=..\gsend_cad\ui\assets\g00code_logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; An upgrade replaces the whole runtime so files dropped from a newer build don't linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\G00 CAM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "READ_ME_FIRST.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Read me first"; Filename: "{app}\READ_ME_FIRST.txt"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

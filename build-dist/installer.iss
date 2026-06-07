; Inno Setup script — Axon Voice installer
; Builds a single setup.exe that installs the one-folder PyInstaller build,
; creates Start Menu + (optional) desktop shortcuts, and registers an
; uninstaller. No admin rights needed (installs per-user to LocalAppData).
;
; Compile:  iscc build-dist\installer.iss
; (Install Inno Setup 6 first:  winget install JRSoftware.InnoSetup)

#define AppName "Axon Voice"
#define AppVersion "1.0.0"
#define AppPublisher "Theo Janeway"
#define AppURL "https://theojaneway.com"
#define AppExeName "AxonVoice.exe"

[Setup]
AppId={{8F3A1C7E-AX0N-4V01-CE00-THEOJANEWAY01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={localappdata}\Programs\AxonVoice
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=AxonVoice-Setup-{#AppVersion}
SetupIconFile=axon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire one-folder PyInstaller output.
Source: "..\dist\AxonVoice\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

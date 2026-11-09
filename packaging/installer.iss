#define AppName "PresenceGuard"
#define AppVersion "1.1.2"
#define AppExe "PresenceGuard.exe"

[Setup]
AppId={{B5809D54-6B85-4C12-B44D-C799FA2272C6}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\PresenceGuard
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=PresenceGuard-Setup-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=app.ico
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\PresenceGuard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{userstartup}\PresenceGuard v1.lnk"

[Icons]
Name: "{autoprograms}\PresenceGuard"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\PresenceGuard"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open PresenceGuard"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{userstartup}\PresenceGuard.lnk"
Type: files; Name: "{userstartup}\PresenceGuard v1.lnk"

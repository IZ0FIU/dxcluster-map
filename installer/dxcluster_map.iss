; Installer Windows per DX Cluster Map (Inno Setup 6).
; Compilato da GitHub Actions con: ISCC /DAppVersion=x.y.z installer\dxcluster_map.iss
; Installazione per utente (nessun permesso di amministratore necessario).

#define MyAppName "DX Cluster Map"
#define MyAppExeName "DXClusterMap.exe"

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7C1E5E10-8F2A-4C0F-9B37-6A6B9B2E1A01}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} v{#AppVersion}
WizardStyle=modern
DefaultDirName={localappdata}\Programs\DXClusterMap
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=DXClusterMap-v{#AppVersion}-windows-setup
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMADictionarySize=65536
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=no
DisableDirPage=no

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; \
    GroupDescription: "Collegamenti:"

[Files]
Source: "..\dist\DXClusterMap\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Avvia {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; nessun file extra: i dati utente restano in %LOCALAPPDATA%\DXClusterMap

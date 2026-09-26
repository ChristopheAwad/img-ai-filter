; Inno Setup script for the Image Filter Windows x86-64 test distribution.
; Build with: ISCC.exe /DAppVersion=<version> installer.iss

#ifndef AppVersion
  #error AppVersion must be defined with /DAppVersion=<version>
#endif

#define MyAppName "Image Filter"
#define MyAppExeName "image-filter.exe"

[Setup]
AppId={{14eb3522-cfa7-4e75-abe1-442384183cf4}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\Image Filter
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=ImageFilter.ico
OutputDir=..\..\packaging-build
OutputBaseFilename=ImageFilter-{#AppVersion}-windows-x86_64-setup
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\packaging-build\dist\image-filter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

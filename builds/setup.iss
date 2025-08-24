#define AppName        "DELTAHUB"
#define AppVersion     "2.0.0"
#define AppExeName     "DELTAHUB.exe"
#define AppIcon        "..\\src\\resources\\icons\\icon.ico"
#define AppSmallIcon   "..\\src\\resources\\icons\\icon_small.bmp"

[Setup]
AppId={{6A8E9F32-1B3A-4F2F-9C0A-6E28B9B8C5D1}}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
Compression=lzma
SolidCompression=yes
SetupIconFile={#AppIcon}
WizardStyle=modern
DisableDirPage=no
UsePreviousAppDir=no
WizardSmallImageFile={#AppSmallIcon}
OutputBaseFilename={#AppName}_setup_v{#AppVersion}
OutputDir=..\\Output
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=0,10.0.17763
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"

[Files]
Source: "..\\dist\\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppIcon}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; IconFilename: "{app}\\icon.ico"
Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; IconFilename: "{app}\\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent shellexec

[Code]
function InitializeSetup(): Boolean;
var
  Win: TWindowsVersion;
begin
  GetWindowsVersionEx(Win);

  if (Win.Major < 10) or ((Win.Major = 10) and (Win.Build < 17763)) then
  begin
    MsgBox('DELTAHUB поддерживает только Windows 10 1809 и выше.'#13#10 +
           'Установка будет прервана.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end
  else
    Result := True;
end;

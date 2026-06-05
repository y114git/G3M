#define AppName        "G3M"
#define AppVersion     "3.1.2"
#define AppExeName     "G3M.exe"
#define AppIcon        "assets\\icons\\icon.ico"
#define AppSmallIcon   "assets\\SmallIcon.bmp"
#define AppWizardImage "assets\\WizardImage.bmp"

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
WizardImageFile={#AppWizardImage}
OutputBaseFilename={#AppName}_setup_{#AppVersion}
OutputDir=..\\Output
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=0,10.0.17763
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\\Spanish.isl"
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
    MsgBox('G3M supports only Windows 10 1809 and higher.'#13#10 +
           'Installation will be cancelled.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end
  else
    Result := True;
end;


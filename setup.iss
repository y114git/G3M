#define AppName        "DELTAHUB"
#define AppVersion     "2.0.0"
#define AppExeName     "DELTAHUB.exe"
#define AppIcon        "assets\\icon.ico"

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
; Показ папки установки всегда и не использовать каталог прошлых версий
DisableDirPage=no
UsePreviousAppDir=no
; Картинка в правом верхнем углу мастера (BMP 55x55)
WizardSmallImageFile=assets\icon_small.bmp
OutputBaseFilename={#AppName}_setup_v{#AppVersion}
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; --- Требуем минимум Windows 10 1809 (build 17763) ---
MinVersion=0,10.0.17763
; Показывать выбор языка явно
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"

[Files]
Source: "dist\\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppIcon}"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; IconFilename: "{app}\\icon.ico"
Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; IconFilename: "{app}\\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
Win: TWindowsVersion;
begin
GetWindowsVersionEx(Win);
{ Major < 10 -> Windows 7/8/8.1 }
if Win.Major < 10 then
begin
MsgBox('DELTAHUB поддерживает только Windows 10 и выше.'#13#10 +
'Установка будет прервана.', mbCriticalError, MB_OK);
Result := False; { прерываем установку }
Exit;
end;
{ Windows 10, но сборка ниже 1809 }
if Win.Build < 17763 then
begin
MsgBox('У вас устаревшая сборка Windows 10 (' + IntToStr(Win.Build) + ').'#13#10 +
'Минимально поддерживается версия 1809 (17763).', mbCriticalError, MB_OK);
Result := False;
end
else
Result := True; { продолжаем }
end;
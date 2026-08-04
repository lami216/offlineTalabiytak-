#define AppVersion "0.1.0"
[Setup]
AppId={{6BEE24BD-0171-4A6F-9EA1-02D188E23F2B}
AppName=Talabiytak
AppVersion={#AppVersion}
AppPublisher=PLACEHOLDER_PUBLISHER
DefaultDirName={localappdata}\Programs\Talabiytak
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=Talabiytak-Setup
Compression=lzma2
SolidCompression=yes
#ifexist "..\assets\Talabiytak.ico"
SetupIconFile=..\assets\Talabiytak.ico
#endif
UninstallDisplayIcon={app}\Talabiytak.exe
[Files]
Source: "..\dist\Talabiytak\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"
[Icons]
Name: "{autoprograms}\Talabiytak"; Filename: "{app}\Talabiytak.exe"
Name: "{autodesktop}\Talabiytak"; Filename: "{app}\Talabiytak.exe"; Tasks: desktopicon
[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft WebView2..."; Flags: waituntilterminated
Filename: "{app}\Talabiytak.exe"; Description: "Launch Talabiytak"; Flags: nowait postinstall skipifsilent
[UninstallDelete]
; User data is deliberately not removed. Support can remove %LOCALAPPDATA%\Talabiytak manually after explicit consent.
[Code]
var DeleteData: TNewCheckBox;
procedure InitializeUninstallProgressForm;
begin
  DeleteData := TNewCheckBox.Create(UninstallProgressForm);
  DeleteData.Parent := UninstallProgressForm;
  DeleteData.Caption := 'حذف جميع بيانات Talabiytak المحلية';
  DeleteData.Checked := False;
  DeleteData.Left := UninstallProgressForm.StatusLabel.Left;
  DeleteData.Top := UninstallProgressForm.StatusLabel.Top + 45;
end;
procedure CurUninstallStepChanged(Step: TUninstallStep);
begin
  if (Step = usPostUninstall) and DeleteData.Checked then
    DelTree(ExpandConstant('{localappdata}\Talabiytak'), True, True, True);
end;

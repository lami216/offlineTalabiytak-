#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
#ifndef AppPublisher
#define AppPublisher "PLACEHOLDER_PUBLISHER"
#endif
#ifndef AppName
#define AppName "طلبياتك"
#endif
[Setup]
AppId={{6BEE24BD-0171-4A6F-9EA1-02D188E23F2B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Talabiytak
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=Talabiytak-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\build-assets\Talabiytak.ico
UninstallDisplayIcon={app}\Talabiytak.exe
[Files]
Source: "..\dist\Talabiytak\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Talabiytak.exe"; IconFilename: "{app}\Talabiytak.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Talabiytak.exe"; Tasks: desktopicon; IconFilename: "{app}\Talabiytak.exe"
[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft WebView2..."; Flags: waituntilterminated; Check: NeedsWebView2
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


function NeedsWebView2: Boolean;
var
  Version: String;
begin
  Result := not RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1D9A2A6-BC09-4E1B-B349-3C5C9CF9B0E1}', 'pv', Version);
  if Result then
    Result := not RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1D9A2A6-BC09-4E1B-B349-3C5C9CF9B0E1}', 'pv', Version);
end;

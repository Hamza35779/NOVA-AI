; ============================================================================
; NOVA AI — Windows Setup (Inno Setup 6)
; ============================================================================
; Packages the self-contained PyInstaller ONEDIR backend (dist\nova-ai-windows-x64\)
; into a per-user installer. The bundled backend embeds Python 3.13 and the
; web workstation UI — no uv, no git, no Python, no Ollama required to boot.
;
; Build:
;   1. pyinstaller --noconfirm --clean nova-ai-windows-x64.spec
;   2. ISCC deploy\windows\nova-ai-setup.iss
;
; Output: dist\NOVA-AI-Setup-<version>.exe
;
; NOTE: this replaces the dev-mode Tauri installer flow (which spawned
; `uv run nova serve` and required uv + git + a repo clone on first launch).
; ============================================================================

#define MyAppName "NOVA AI"
#define MyAppVersion "1.2.4"
#define MyAppExeName "nova-ai-windows-x64.exe"
#define MyAppId "{{7E6F8A2C-1D34-4E5A-9B8C-2F0D1A3B4C5D}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=NOVA AI Contributors
AppPublisherURL=https://github.com/Hamza35779/NOVA-AI
AppSupportURL=https://github.com/Hamza35779/NOVA-AI/issues
AppUpdatesURL=https://github.com/Hamza35779/NOVA-AI/releases
DefaultDirName={localappdata}\Programs\NOVA AI
DisableProgramGroupPage=yes
; Win10 1809+ (build 17763) — matches the requirement enforced by
; deploy\windows\install.ps1 (numpy/pyd wheels unavailable on older builds).
MinVersion=0,10.0
; Per-user install: no elevation, Start Menu/Desktop shortcuts land in the
; user's profile ({autopf*} constants resolve to user locations below).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\..\dist
OutputBaseFilename=NOVA-AI-Setup-{#MyAppVersion}
SetupIconFile=..\..\frontend\src-tauri\icons\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Ask to close a running NOVA AI server before installing over it.
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add NOVA AI to PATH (run 'nova-ai-windows-x64' from any terminal)"; GroupDescription: "Integration:"

[Files]
Source: "..\..\dist\nova-ai-windows-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "NOVA AI — modular AI assistant"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "NOVA AI — modular AI assistant"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Runtime scratch (chat history DB, logs live in %USERPROFILE%\.nova_ai —
; intentionally PRESERVED across uninstall; delete manually if desired).

[Code]
const
  WM_SETTINGCHANGE = $001A;

procedure BroadcastEnvironmentChange();
begin
  SendMessage(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 0);
end;

// Take the next ';'-separated token off S (in-place), like Split.
function NextToken(var S: String): String;
var
  P: Integer;
begin
  P := Pos(';', S);
  if P = 0 then
  begin
    Result := S;
    S := '';
  end
  else
  begin
    Result := Copy(S, 1, P - 1);
    S := Copy(S, P + 1, Length(S));
  end;
end;

// Append the install dir to the user PATH (idempotent). Runs on install
// when the "addtopath" task is selected; the counterpart cleanup runs on
// uninstall so PATH never keeps a dead entry.
procedure ModPathAdd();
var
  UserPath, AppDir: string;
begin
  AppDir := ExpandConstant('{app}');
  if RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', UserPath) then
  begin
    if Pos(';' + Uppercase(AppDir) + ';', ';' + Uppercase(UserPath) + ';') > 0 then
      Exit; // already present
    UserPath := UserPath + ';' + AppDir;
  end
  else
    UserPath := AppDir;
  RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', UserPath);
end;

procedure ModPathRemove();
var
  UserPath, AppDir, NewPath, Entry: string;
begin
  AppDir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', UserPath) then
    Exit;
  NewPath := '';
  while UserPath <> '' do
  begin
    Entry := Trim(NextToken(UserPath));
    if (Entry <> '') and (Uppercase(Entry) <> Uppercase(AppDir)) then
    begin
      if NewPath = '' then
        NewPath := Entry
      else
        NewPath := NewPath + ';' + Entry;
    end;
  end;
  RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', NewPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('addtopath') then
    begin
      ModPathAdd();
      BroadcastEnvironmentChange();
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    ModPathRemove();
    BroadcastEnvironmentChange();
  end;
end;

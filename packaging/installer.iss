; 第七史诗自动助手 —— Inno Setup 6 安装脚本
;
; ⚠️ **本脚本尚未在本机构建验证**：这台机器没有装 Inno Setup 6（ISCC.exe），
;    第一次真正编译时请当它可能有一两处需要修，不要默认它已经能用。
;
; 用法（版本号由打包脚本传进来，避免在两处各维护一份）：
;
;     & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
;         "/DMyAppVersion=0.1.0" packaging\installer.iss
;
; 前置：先跑 `python packaging/build.py`，它会在 packaging\dist\ 下产出目录版。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "第七史诗自动助手"
#define MyAppExeName "Epic7AutoAssistant.exe"
#define MyAppPublisher "Kangkangnice"

[Setup]
; AppId 一旦发布就不要再改：它决定「升级」还是「装出第二个」。
AppId={{8E4C1B2A-6F3D-4A7E-9C15-2D8B7F0A6E31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Epic7AutoAssistant
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 程序要往游戏窗口里发点击，运行时要管理员；安装到 Program Files 也需要提权。
PrivilegesRequired=admin
OutputDir=dist
OutputBaseFilename=第七史诗自动助手-安装版-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; 用户的日志与诊断在 %LOCALAPPDATA%\Epic7AutoAssistant，卸载时**不删**：
; 那是用户自己的运行记录，卸载不该顺手清掉。

[Languages]
; Inno 自带的语言列表里没有简体中文（需要额外的 ChineseSimplified.isl）。
; 首版先用英文安装界面，避免为了一个语言文件把编译搞挂。
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "dist\Epic7AutoAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

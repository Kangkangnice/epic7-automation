; 第七史诗自动助手 —— Inno Setup 6 安装脚本
;
; 用法（版本号由打包脚本传进来，避免在两处各维护一份）：
;
;     & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" `
;         "/DMyAppVersion=0.1.0" packaging\installer.iss
;
; 也可以直接 `python packaging/build.py`，它会自己找 ISCC 并把这个编出来。
;
; 前置：先跑 PyInstaller，本脚本要求 packaging\dist\Epic7AutoAssistant\ 已存在。
;
; 两个约定，改之前先看：
;
;  1. **按用户安装，不要提权**。PrivilegesRequired=lowest 时 {autopf} 自动展开成
;     {localappdata}\Programs，装完不需要管理员、不弹 UAC，非管理员账户也能装。
;     这个程序安装阶段本来就不需要管理员权限：它的日志、诊断、自检报告全都写在
;     %LOCALAPPDATA%\Epic7AutoAssistant（见 core/data_paths.py）。
;     运行阶段也**不是**必须提权 —— 只有模拟器本身以管理员身份启动时，往它窗口发
;     点击才会被 UIPI 拦掉，那种情况该由程序自己提示「以管理员身份重启」，而不是
;     让所有人一装上就顶着管理员令牌跑。
;
;  2. AppId 一旦发布就不要再改：它决定「升级」还是「装出第二个」。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "第七史诗自动助手"
#define MyAppExeName "Epic7AutoAssistant.exe"
#define MyAppPublisher "Kangkangnice"

[Setup]
AppId={{8E4C1B2A-6F3D-4A7E-9C15-2D8B7F0A6E31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Epic7AutoAssistant
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; 想装到 Program Files（所有用户可用）时可以加 /ALLUSERS 走提权路径：
;     setup.exe /ALLUSERS /SILENT
PrivilegesRequiredOverridesAllowed=commandline
; 打出来的 exe 是 64 位，32 位系统上装了也跑不起来，直接挡在安装前。
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=第七史诗自动助手-安装版-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; 用户的日志与诊断在 %LOCALAPPDATA%\Epic7AutoAssistant，卸载时**不删**：
; 那是用户自己的运行记录，卸载不该顺手清掉。

[Languages]
; Inno 官方发行版不带简体中文，这个文件来自 issrc 的 Unofficial 目录
; （维护者 Zhenghan Yang），随仓库一起分发，别删。
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
; 留一份英文兜底：语言包消息不全时安装界面不至于变成空白。
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 用内置消息而不是写死中文 —— 否则英文界面下会蹦出一行中文。
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "dist\Epic7AutoAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

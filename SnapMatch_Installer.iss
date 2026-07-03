#define MyAppName "SnapMatch"
#define MyAppVersion "1.0.4.0"
#define MyAppPublisher "WETQV"
#define MyAppExeName "SnapMatch.exe"

#ifexist "assets\ffmpeg\ffmpeg.exe"
#define FfmpegSource "assets\ffmpeg\ffmpeg.exe"
#endif
#ifndef FfmpegSource
#ifexist "..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\bin\ffmpeg.exe"
#define FfmpegSource "..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\bin\ffmpeg.exe"
#define FfmpegLicenseSource "..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\LICENSE"
#define FfmpegReadmeSource "..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\README.txt"
#endif
#endif

[Setup]
AppId={{A4B38A1D-7B43-4D7A-8F4B-7D33C2A83920}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
InfoBeforeFile=installer_info.txt
OutputDir=installer_output
OutputBaseFilename=SnapMatch_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon3.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=WizardImageFile.png
WizardSmallImageFile=WizardSmallImageFile.png
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer_info.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\icon3.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
#ifdef FfmpegSource
Source: "{#FfmpegSource}"; DestDir: "{app}\assets\ffmpeg"; DestName: "ffmpeg.exe"; Flags: ignoreversion
#endif
#ifdef FfmpegLicenseSource
Source: "{#FfmpegLicenseSource}"; DestDir: "{app}\third_party\ffmpeg"; DestName: "LICENSE"; Flags: ignoreversion
#endif
#ifdef FfmpegReadmeSource
Source: "{#FfmpegReadmeSource}"; DestDir: "{app}\third_party\ffmpeg"; DestName: "README.txt"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon3.ico"
Name: "{group}\{#MyAppName} - Документация"; Filename: "{app}\installer_info.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon3.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

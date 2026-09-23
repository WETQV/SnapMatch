; SnapMatch Installer Script
; Создан для WETQV Development
; Разработчик: WETQV (Индивидуальный разработчик)
; Использует Inno Setup Compiler

#define MyAppName "SnapMatch"
#define MyAppVersion "1.0.4.3"
#define MyAppPublisher "WETQV Development"
#define MyAppDeveloper "WETQV"
#define MyAppURL "https://github.com/WETQV/SnapMatch"
#define MyAppExeName "SnapMatch.exe"
#define MyAppSourceExe "SnapMatch_Vosk.exe"
#define MyAppAssocName "SnapMatch Config File"
#define MyAppAssocExt ".snapconfig"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; БАЗОВАЯ ИНФОРМАЦИЯ О ПРИЛОЖЕНИИ
AppId={{A4B38A1D-7B43-4D7A-8F4B-7D33C2A83920}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppContact=memasik554@gmail.com
AppComments=Разработано {#MyAppDeveloper} - Desktop AI Assistant с интеграцией Telegram бота
AppCopyright=© 2026 {#MyAppDeveloper}. Все права защищены.
DefaultDirName={autopf}\{#MyAppName}
ChangesAssociations=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=LICENSE
OutputDir=installer_output
OutputBaseFilename=SnapMatch_Setup_Vosk_v{#MyAppVersion}
; Используем альтернативную иконку
SetupIconFile=assets\icon3.ico
WizardImageFile=WizardImageFile.png
WizardSmallImageFile=WizardSmallImageFile.png
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductTextVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup with local Vosk STT
VersionInfoProductName={#MyAppName}
VersionInfoOriginalFileName=SnapMatch_Setup_Vosk_v{#MyAppVersion}.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; ПОДДЕРЖИВАЕМЫЕ СИСТЕМЫ
MinVersion=6.1sp1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ПРАВА ДОСТУПА
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ОСНОВНОЙ ИСПОЛНЯЕМЫЙ ФАЙЛ
Source: "dist\{#MyAppSourceExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion

; ДОКУМЕНТАЦИЯ И ЛИЦЕНЗИЯ
Source: "installer_info.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; ИКОНКИ И РЕСУРСЫ
Source: "assets\icon3.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
; ПРИМЕЧАНИЕ: Другие файлы при необходимости
; Source: "MyProg.chm"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; АССОЦИАЦИЯ ФАЙЛОВ
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".myp"; ValueData: ""

[Icons]
; ЯРЛЫКИ В МЕНЮ ПУСК
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon3.ico"; Comment: "Запустить SnapMatch (Разработчик: WETQV)"
Name: "{autoprograms}\{#MyAppName} - Документация"; Filename: "{app}\installer_info.txt"; Comment: "Открыть описание SnapMatch (Разработчик: WETQV)"

; ЯРЛЫК НА РАБОЧЕМ СТОЛЕ
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon3.ico"; Comment: "SnapMatch by WETQV"; Tasks: desktopicon

; ЯРЛЫК В БЫСТРОМ ЗАПУСКЕ

; ДЕИНСТАЛЛЯТОР
Name: "{autoprograms}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\assets\icon3.ico"; Comment: "Удалить SnapMatch (WETQV Development)"

[Run]
; ЗАПУСК ПОСЛЕ УСТАНОВКИ
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; ОТКРЫТИЕ ДОКУМЕНТАЦИИ
; Filename: "{app}\README.md"; Description: "Открыть документацию"; Flags: postinstall skipifsilent shellexec unchecked

[UninstallRun]
; ДЕЙСТВИЯ ПРИ УДАЛЕНИИ (если нужны)
; Filename: "{app}\cleanup.bat"; Flags: runhidden

[Messages]
russian.SelectLanguageTitle=Язык установки SnapMatch
russian.SelectLanguageLabel=Выберите язык интерфейса установщика.
russian.WelcomeLabel1=Добро пожаловать в установщик SnapMatch
russian.WelcomeLabel2=Сейчас мы установим [name/ver] на ваш компьютер.%n%nПеред продолжением лучше закрыть другие приложения, чтобы установка прошла без лишних вопросов.
russian.WizardInstalling=Установка SnapMatch
russian.InstallingLabel=Пожалуйста, подождите: SnapMatch копирует файлы и настраивает ярлыки.
russian.StatusCreateIcons=Создаем ярлыки SnapMatch...
russian.FinishedHeadingLabel=SnapMatch установлен
russian.FinishedLabelNoIcons=SnapMatch установлен и готов к запуску.
russian.FinishedLabel=SnapMatch установлен и готов к запуску. Ярлыки уже добавлены в меню «Пуск» и выбранные места.
russian.ClickFinish=Нажмите «Завершить», чтобы закрыть установщик.
russian.RunEntryExec=Запустить %1
english.SelectLanguageTitle=SnapMatch Setup Language
english.SelectLanguageLabel=Choose the language used by the installer.
english.WelcomeLabel1=Welcome to SnapMatch Setup
english.WelcomeLabel2=This will install [name/ver] on your computer.%n%nBefore continuing, close other applications to keep the installation smooth.
english.WizardInstalling=Installing SnapMatch
english.InstallingLabel=Please wait while SnapMatch copies files and prepares shortcuts.
english.StatusCreateIcons=Creating SnapMatch shortcuts...
english.FinishedHeadingLabel=SnapMatch is installed
english.FinishedLabelNoIcons=SnapMatch is installed and ready to run.
english.FinishedLabel=SnapMatch is installed and ready to run. Shortcuts have been added to the Start Menu and selected locations.
english.ClickFinish=Click Finish to close Setup.
english.RunEntryExec=Run %1

[CustomMessages]
russian.LaunchProgram=Запустить %1
russian.AssocFileExtension=&Ассоциировать %1 с расширением файла %2
russian.AssocingFileExtension=Ассоциация %1 с расширением файла %2...
russian.CreateDesktopIcon=Создать ярлык на &рабочем столе
russian.CreateQuickLaunchIcon=Создать ярлык на панели &быстрого запуска
russian.AdditionalIcons=Дополнительные значки:
russian.InfoPageTitle=SnapMatch готов к установке
russian.InfoPageDescription=Коротко о том, что будет установлено.
russian.InfoIntro=SnapMatch - desktop-помощник для управления AI-ботом в Telegram через удобный графический интерфейс.
russian.InfoFeaturesTitle=Что внутри
russian.InfoFeatures=Управление ботом через GUI%nПоддержка LM Studio, Ollama и других AI-моделей%nБалансировка нагрузки между моделями%nСтатистика, мониторинг, промпты и админ-панель
russian.InfoAudienceTitle=Для кого
russian.InfoAudience=Для пользователей, которые хотят запустить своего Telegram-бота и удобно работать с ИИ через Telegram.
russian.InfoFooter=Разработчик: WETQV. Версия: {#MyAppVersion}. Лицензия: GNU GPL v3.
english.InfoPageTitle=SnapMatch is ready to install
english.InfoPageDescription=A quick look at what will be installed.
english.InfoIntro=SnapMatch is a desktop assistant for managing an AI Telegram bot through a clean graphical interface.
english.InfoFeaturesTitle=What's included
english.InfoFeatures=Bot management through a GUI%nSupport for LM Studio, Ollama, and other AI models%nLoad balancing between models%nStats, monitoring, prompts, and an admin panel
english.InfoAudienceTitle=Who it's for
english.InfoAudience=For users who want to run their own Telegram bot and work with AI through Telegram comfortably.
english.InfoFooter=Developer: WETQV. Version: {#MyAppVersion}. License: GNU GPL v3.

[Code]
// ДОПОЛНИТЕЛЬНЫЙ КОД PASCAL (если нужен)
var
  InfoPage: TWizardPage;

procedure AddInfoText(Page: TWizardPage; var Y: Integer; const Text: String; const Bold: Boolean; const Size: Integer);
var
  LabelControl: TNewStaticText;
begin
  LabelControl := TNewStaticText.Create(Page);
  LabelControl.AutoSize := False;
  LabelControl.Left := 0;
  LabelControl.Top := Y;
  LabelControl.Width := Page.SurfaceWidth;
  LabelControl.WordWrap := True;
  LabelControl.Caption := Text;
  LabelControl.Parent := Page.Surface;
  LabelControl.Font.Size := Size;
  if Bold then
    LabelControl.Font.Style := [fsBold];
  LabelControl.AdjustHeight;
  Y := LabelControl.Top + LabelControl.Height + ScaleY(10);
end;

procedure AddInfoSection(Page: TWizardPage; var Y: Integer; const Title: String; const Body: String);
begin
  AddInfoText(Page, Y, Title, True, 9);
  AddInfoText(Page, Y, Body, False, 9);
  Y := Y + ScaleY(4);
end;

procedure InitializeWizard();
var
  Y: Integer;
begin
  InfoPage := CreateCustomPage(wpWelcome, ExpandConstant('{cm:InfoPageTitle}'), ExpandConstant('{cm:InfoPageDescription}'));
  Y := 0;

  AddInfoText(InfoPage, Y, ExpandConstant('{cm:InfoIntro}'), False, 9);
  Y := Y + ScaleY(2);
  AddInfoSection(InfoPage, Y, ExpandConstant('{cm:InfoFeaturesTitle}'), ExpandConstant('{cm:InfoFeatures}'));
  AddInfoSection(InfoPage, Y, ExpandConstant('{cm:InfoAudienceTitle}'), ExpandConstant('{cm:InfoAudience}'));
  AddInfoText(InfoPage, Y, ExpandConstant('{cm:InfoFooter}'), False, 8);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Действия после установки
  end;
end;

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  // Возвращает 1 если старая версия найдена и удалена успешно
  // иначе возвращает 0
  Result := 0;
  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := 1
    else
      Result := 2;
  end;
end;

; Programme d'installation de GrabDrop (Inno Setup 6). Compilé par build.ps1.
;
; - installe GrabDrop.exe dans Programmes (droits administrateur demandés une fois) ;
; - raccourcis menu Démarrer (et Bureau en option) ;
; - lancement à l'ouverture de session en option (même réglage que le menu de l'icône) ;
; - autorise GrabDrop dans le pare-feu Windows, réseaux privés seulement
;   (sinon, Windows le demanderait au premier lancement) ;
; - mise à jour : ne revient PAS sur les choix de l'utilisateur (démarrage automatique,
;   raccourci Bureau), arrête GrabDrop s'il tourne et le relance ensuite ;
; - la désinstallation retire tout cela, mais garde la configuration
;   (%APPDATA%\GrabDrop : appairage, journal) pour une réinstallation.
;
; Les définitions ci-dessous peuvent être remplacées à la compilation (ISCC /D...) :
; c'est ce que fait l'essai automatique pour obtenir un installateur isolé
; (autre identifiant, autre nom), sans risque pour la vraie installation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppGuid
  #define AppGuid "8C3F0E2A-6B1D-4E7A-9F5B-2D8C1A7E4B90"
#endif
#ifndef AppName
  #define AppName "GrabDrop"
#endif
; Nom de la valeur « Run » du registre, partagée avec le menu de l'icône (platform_win.py).
#ifndef RunValue
  #define RunValue "GrabDrop"
#endif

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=GrabDrop
AppPublisherURL=https://github.com/nouxel00/grabdrop_share
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; Par défaut pour tous les utilisateurs (administrateur, pare-feu configuré) ; l'utilisateur
; peut choisir « pour moi seulement » (sans administrateur : Windows demandera alors
; l'autorisation du pare-feu au premier lancement).
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=GrabDrop-Setup-{#AppVersion}
SetupIconFile=build\grabdrop.ico
UninstallDisplayIcon={app}\GrabDrop.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; GrabDrop n'a pas de fenêtre classique : le « Restart Manager » de Windows le ferme mal.
; Le code ci-dessous l'arrête lui-même (seulement la copie de cette installation) et le relance.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
; Proposées à la première installation seulement : une mise à jour garde les choix faits
; depuis (par exemple « Lancer au démarrage de Windows » décoché dans le menu de l'icône).
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; \
  Flags: unchecked; Check: not IsUpgrade
Name: "autostart"; Description: "Lancer GrabDrop à l'ouverture de session Windows"; GroupDescription: "Démarrage :"; \
  Check: not IsUpgrade

[Files]
Source: "dist\GrabDrop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\GrabDrop.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\GrabDrop.exe"; Tasks: desktopicon

[Registry]
; Même valeur que « Lancer au démarrage de Windows » dans le menu de l'icône. Retirée à la
; désinstallation par le code ci-dessous (seulement si elle désigne cette installation).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunValue}"; \
  ValueData: """{app}\GrabDrop.exe"""; Tasks: autostart

[Run]
; Pare-feu (installation pour tous les utilisateurs seulement) : supprimer une éventuelle
; règle d'une installation précédente, puis l'ajouter.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GrabDrop"""; \
  Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""GrabDrop"" dir=in action=allow program=""{app}\GrabDrop.exe"" enable=yes profile=private"; \
  StatusMsg: "Autorisation de GrabDrop dans le pare-feu (réseaux privés)…"; Flags: runhidden waituntilterminated; \
  Check: IsAdminInstallMode
; Lancé avec les droits de l'utilisateur, jamais en administrateur.
Filename: "{app}\GrabDrop.exe"; Description: "Lancer GrabDrop maintenant"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GrabDrop"""; \
  Flags: runhidden; RunOnceId: "RemoveFirewallRule"; Check: IsAdminInstallMode

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  WasRunning: Boolean;

{ Une version de GrabDrop est-elle déjà installée (pour tous les utilisateurs ou pour moi) ? }
function IsUpgrade: Boolean;
begin
  Result := RegKeyExists(HKLM64, UninstallKey) or RegKeyExists(HKLM32, UninstallKey)
    or RegKeyExists(HKCU, UninstallKey);
end;

{ Arrête GrabDrop.exe s'il tourne depuis CETTE installation (pas une autre copie, ni celle
  d'un autre dossier). Renvoie True si au moins une copie a été arrêtée. }
function StopGrabDrop(): Boolean;
var
  Locator, Service, Processes, Process: Variant;
  I: Integer;
  Target, Path: String;
begin
  Result := False;
  Target := Lowercase(ExpandConstant('{app}\GrabDrop.exe'));
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Processes := Service.ExecQuery('SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = ''GrabDrop.exe''');
    for I := 0 to Processes.Count - 1 do
    begin
      Process := Processes.ItemIndex(I);
      if VarIsNull(Process.ExecutablePath) then
        continue;  { processus d'un autre utilisateur : chemin illisible }
      Path := Process.ExecutablePath;
      if Lowercase(Path) = Target then
      begin
        Process.Terminate();
        Result := True;
      end;
    end;
  except
    Log('Impossible de vérifier si GrabDrop tourne : ' + GetExceptionMessage);
  end;
  if Result then
    Sleep(1000);  { laisser Windows libérer les fichiers }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  WasRunning := StopGrabDrop();
  if WasRunning then
    Log('GrabDrop tournait : arrêté pour la mise à jour, il sera relancé ensuite.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { Installation silencieuse : relancer GrabDrop s'il tournait avant (sans droits
    administrateur). En mode normal, la case « Lancer GrabDrop maintenant » s'en charge. }
  if (CurStep = ssPostInstall) and WasRunning and WizardSilent then
    ExecAsOriginalUser(ExpandConstant('{app}\GrabDrop.exe'), '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  if CurUninstallStep = usUninstall then
    StopGrabDrop();
  if CurUninstallStep = usPostUninstall then
  begin
    { Démarrage automatique : retiré s'il désigne cette installation, qu'il ait été activé
      par l'installateur ou par le menu de l'icône. }
    if RegQueryStringValue(HKCU, RunKey, '{#RunValue}', Command) and
       (Pos(Lowercase(ExpandConstant('{app}\GrabDrop.exe')), Lowercase(Command)) > 0) then
      RegDeleteValue(HKCU, RunKey, '{#RunValue}');
  end;
end;

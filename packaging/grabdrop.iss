; Programme d'installation de GrabDrop (Inno Setup 6). Compilé par build.ps1.
;
; - installe GrabDrop.exe dans Programmes (droits administrateur demandés une fois) ;
; - raccourcis menu Démarrer (et Bureau en option) ;
; - lancement à l'ouverture de session en option (même réglage que le menu de l'icône) ;
; - autorise GrabDrop dans le pare-feu Windows, réseaux privés seulement
;   (sinon, Windows le demanderait au premier lancement) ;
; - la désinstallation retire tout cela, mais garde la configuration
;   (%APPDATA%\GrabDrop : appairage, journal) pour une réinstallation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C3F0E2A-6B1D-4E7A-9F5B-2D8C1A7E4B90}
AppName=GrabDrop
AppVersion={#AppVersion}
AppVerName=GrabDrop {#AppVersion}
AppPublisher=GrabDrop
AppPublisherURL=https://github.com/nouxel00/grabdrop_share
DefaultDirName={autopf}\GrabDrop
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
UninstallDisplayName=GrabDrop
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Mise à jour : ferme GrabDrop s'il tourne, puis le relance.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "autostart"; Description: "Lancer GrabDrop à l'ouverture de session Windows"; GroupDescription: "Démarrage :"

[Files]
Source: "dist\GrabDrop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GrabDrop"; Filename: "{app}\GrabDrop.exe"
Name: "{autodesktop}\GrabDrop"; Filename: "{app}\GrabDrop.exe"; Tasks: desktopicon

[Registry]
; Même valeur que « Lancer au démarrage de Windows » dans le menu de l'icône.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GrabDrop"; \
  ValueData: """{app}\GrabDrop.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Pare-feu (installation pour tous les utilisateurs seulement) : supprimer une éventuelle
; règle d'une installation précédente, puis l'ajouter.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GrabDrop"""; \
  Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""GrabDrop"" dir=in action=allow program=""{app}\GrabDrop.exe"" enable=yes profile=private"; \
  StatusMsg: "Autorisation de GrabDrop dans le pare-feu (réseaux privés)…"; Flags: runhidden waituntilterminated; \
  Check: IsAdminInstallMode
Filename: "{app}\GrabDrop.exe"; Description: "Lancer GrabDrop maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM GrabDrop.exe /F"; Flags: runhidden; RunOnceId: "StopGrabDrop"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GrabDrop"""; \
  Flags: runhidden; RunOnceId: "RemoveFirewallRule"; Check: IsAdminInstallMode

; ===================================================================
; AkServer Installer Script - Corrected Version
; ===================================================================

[Setup]
AppName=AkServer
AppVersion=1.0
DefaultDirName={pf}\AkServer
DefaultGroupName=AkServer
UninstallDisplayIcon={app}\AkServerApp.exe
OutputDir=.
OutputBaseFilename=AkServer
Compression=lzma
SolidCompression=yes
DisableDirPage=no
SetupIconFile="static\akserver_icon.ico"
LicenseFile="licenses\EULA.txt"
WizardImageFile="static\akserver_logo.bmp"
WizardSmallImageFile="static\akserver_small_icon.bmp"
WizardImageStretch=no

[Files]
; GUI executable
Source: "dist\AkServerApp\AkServerApp.exe"; DestDir: "{app}"; Flags: ignoreversion

; Server executable
Source: "dist\AkServerApp\AkServer.exe"; DestDir: "{app}"; Flags: ignoreversion

; Internal folder (HTML, runtime, other files)
Source: "dist\AkServerApp\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Optional assets (icons, logos)
Source: "static\akserver_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "static\akserver_icon.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "static\akserver_logo.png"; DestDir: "{app}"; Flags: ignoreversion

; License and legal files 
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\AkServer"; Filename: "{app}\AkServerApp.exe"; WorkingDir: "{app}"; IconFilename: "{app}\akserver_icon.ico"

; Desktop shortcut (optional)
Name: "{commondesktop}\AkServer"; Filename: "{app}\AkServerApp.exe"; WorkingDir: "{app}"; Tasks: desktopicon

; Uninstall entry
Name: "{group}\Uninstall AkServer"; Filename: "{uninstallexe}"

; Shortcut to licenses folder
Name: "{group}\Licenses"; Filename: "{app}\licenses"

[Run]
Filename: "{app}\AkServerApp.exe"; Description: "Launch AkServer"; Flags: nowait postinstall skipifsilent
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""AkServer"" dir=in action=allow program=""{app}\AkServer.exe"" protocol=TCP localport=8443 enable=yes profile=any"; Flags: runhidden; StatusMsg: "Configuring firewall for AkServer..."

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""AkServer"""; Flags: runhidden

[Code]
function GetServerPort(Param: String): String;
begin
  Result := '8443'; // Hardcode since akserver_config.json confirms 8443
  Log('Using server port: ' + Result);
end;

[Tasks]
; Optional desktop icon prompt
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"

; Optional startup option
Name: "startup"; Description: "Start AkServer at startup"; GroupDescription: "Startup options:"

[Registry]
; If user selects the startup task, create Run key entry
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "AkServer"; ValueData: """{app}\AkServerApp.exe"""; Flags: uninsdeletevalue; Tasks: startup

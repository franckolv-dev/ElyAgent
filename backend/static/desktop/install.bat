@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title ELY Desktop — Installateur

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          ELY Desktop — Installateur / Lanceur               ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"
set "BINARY=%SCRIPT_DIR%ely-desktop-windows-amd64.exe"
set "CONFIG=%SCRIPT_DIR%ely-config.json"

:: ── 1. Vérifier le binaire ────────────────────────────────────────────────
if not exist "%BINARY%" (
    powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Impossible de trouver le fichier :\nely-desktop-windows-amd64.exe\n\nTelechargez-le depuis l interface ELY\n(Settings > ELY Desktop > Telecharger le daemon)', 'ELY Desktop — Fichier manquant', 'OK', 'Error')"
    exit /b 1
)
echo [OK] Binaire trouve : ely-desktop-windows-amd64.exe

:: ── 2. Premier lancement : créer la config ────────────────────────────────
if not exist "%CONFIG%" (
    echo.
    echo ==  Premier lancement — Configuration  ==
    echo.

    powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Bienvenue dans ELY Desktop !\n\nAucun fichier de configuration trouve.\n\nVous pouvez :\n 1. Telecharger ely-config.json depuis l interface ELY\n    (Settings > ELY Desktop > Telecharger la config)\n    et le placer dans ce dossier.\n\n 2. Entrer les informations manuellement\n    (les ecrans suivants vous guideront).', 'ELY Desktop — Configuration initiale', 'OK', 'Information')"

    :: Demander l'URL du serveur via PowerShell InputBox
    for /f "delims=" %%i in ('powershell -NoProfile -Command ^
        "$f=New-Object System.Windows.Forms.Form; $f.Text='ELY Desktop — Serveur'; $f.Size=New-Object Drawing.Size(440,160); $f.StartPosition='CenterScreen'; $f.TopMost=$true; $l=New-Object Windows.Forms.Label; $l.Text='URL du serveur ELY (ex : http://192.168.1.100:8000)'; $l.SetBounds(10,15,400,20); $t=New-Object Windows.Forms.TextBox; $t.SetBounds(10,40,400,20); $t.Text='http://'; $b=New-Object Windows.Forms.Button; $b.Text='OK'; $b.SetBounds(330,85,90,30); $b.DialogResult='OK'; $f.AcceptButton=$b; $f.Controls.AddRange(($l,$t,$b)); Add-Type -AssemblyName System.Windows.Forms; if($f.ShowDialog() -eq 'OK'){$t.Text} else{''}'^
    ') do set "VPS_URL=%%i"

    if "!VPS_URL!"=="" (
        powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('URL requise. Relancez l installateur.', 'ELY Desktop — Erreur', 'OK', 'Error')"
        exit /b 1
    )

    :: Demander le token
    for /f "delims=" %%i in ('powershell -NoProfile -Command ^
        "Add-Type -AssemblyName System.Windows.Forms; $f=New-Object Windows.Forms.Form; $f.Text='ELY Desktop — Token'; $f.Size=New-Object Drawing.Size(440,160); $f.StartPosition='CenterScreen'; $f.TopMost=$true; $l=New-Object Windows.Forms.Label; $l.Text='Token d authentification (Settings > ELY Desktop)'; $l.SetBounds(10,15,400,20); $t=New-Object Windows.Forms.TextBox; $t.SetBounds(10,40,400,20); $b=New-Object Windows.Forms.Button; $b.Text='OK'; $b.SetBounds(330,85,90,30); $b.DialogResult='OK'; $f.AcceptButton=$b; $f.Controls.AddRange(($l,$t,$b)); if($f.ShowDialog() -eq 'OK'){$t.Text} else{''}'^
    ') do set "TOKEN=%%i"

    if "!TOKEN!"=="" (
        powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Token requis. Relancez l installateur.', 'ELY Desktop — Erreur', 'OK', 'Error')"
        exit /b 1
    )

    :: Demander le répertoire autorisé
    for /f "delims=" %%i in ('powershell -NoProfile -Command ^
        "Add-Type -AssemblyName System.Windows.Forms; $f=New-Object Windows.Forms.Form; $f.Text='ELY Desktop — Repertoires'; $f.Size=New-Object Drawing.Size(440,160); $f.StartPosition='CenterScreen'; $f.TopMost=$true; $l=New-Object Windows.Forms.Label; $l.Text='Repertoire autorise (ex : C:\Users\Vous\Documents)'; $l.SetBounds(10,15,400,20); $t=New-Object Windows.Forms.TextBox; $t.SetBounds(10,40,400,20); $t.Text='C:\Users\%USERNAME%\Documents'; $b=New-Object Windows.Forms.Button; $b.Text='OK'; $b.SetBounds(330,85,90,30); $b.DialogResult='OK'; $f.AcceptButton=$b; $f.Controls.AddRange(($l,$t,$b)); if($f.ShowDialog() -eq 'OK'){$t.Text} else{'C:\Users\%USERNAME%\Documents'}'^
    ') do set "SANDBOX=%%i"

    :: Échapper les backslashes pour le JSON
    set "SANDBOX_JSON=!SANDBOX:\=\\!"

    :: Écrire le fichier JSON
    (
        echo {
        echo   "vps_url": "!VPS_URL!",
        echo   "token": "!TOKEN!",
        echo   "sandbox_dirs": ["!SANDBOX_JSON!"],
        echo   "version": "1"
        echo }
    ) > "%CONFIG%"

    echo [OK] Configuration creee : ely-config.json

    :: Proposer le démarrage automatique
    powershell -NoProfile -Command ^
        "Add-Type -AssemblyName PresentationFramework; $r=[System.Windows.MessageBox]::Show('Voulez-vous lancer ELY Desktop automatiquement au demarrage de Windows ?', 'ELY Desktop — Demarrage automatique', 'YesNo', 'Question'); if($r -eq 'Yes'){ $regPath='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'; Set-ItemProperty -Path $regPath -Name 'ELY Desktop' -Value '%BINARY%'; Write-Host 'Demarrage automatique active' }"

) else (
    echo [OK] Configuration trouvee : ely-config.json
)

:: ── 3. Lancer le daemon ──────────────────────────────────────────────────────
echo.
echo ==  Demarrage du daemon  ================================================
echo.
echo   Appuyez sur Ctrl+C pour arreter.
echo.

"%BINARY%"

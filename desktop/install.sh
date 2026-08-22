#!/usr/bin/env bash
# =============================================================================
# ELY Desktop — Installer & Launcher
# Compatible : Linux (apt/dnf/pacman) · macOS
#
# Usage :
#   chmod +x install.sh && ./install.sh
#   (ou double-clic si le gestionnaire de fichiers le supporte)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/ely-config.json"

# ── Détection OS / Arch ──────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)
    case "$ARCH" in
      x86_64)  BINARY="ely-desktop-linux-amd64" ;;
      aarch64) BINARY="ely-desktop-linux-arm64"  ;;
      *)       BINARY="ely-desktop-linux-amd64"  ;;
    esac
    ;;
  Darwin)
    case "$ARCH" in
      arm64)   BINARY="ely-desktop-macos-arm64"  ;;
      *)       BINARY="ely-desktop-macos-amd64"  ;;
    esac
    ;;
  *)
    echo "[ERROR] Système non supporté : $OS"
    echo "        Utilisez install.bat (Windows) ou contactez le support."
    exit 1
    ;;
esac

BINARY_PATH="$SCRIPT_DIR/$BINARY"

# ── Fonctions utilitaires ────────────────────────────────────────────────────
has_cmd() { command -v "$1" &>/dev/null; }

gui_available() {
  [[ "$OS" == "Linux" ]] && { has_cmd zenity || has_cmd kdialog; }
  [[ "$OS" == "Darwin" ]] && return 0
}

# Dialogue générique (GUI ou terminal)
gui_input() {
  local title="$1" prompt="$2" default="${3:-}"

  if [[ "$OS" == "Darwin" ]]; then
    osascript -e "text returned of (display dialog \"$prompt\" default answer \"$default\" with title \"$title\")" 2>/dev/null || echo "$default"
  elif has_cmd zenity; then
    zenity --entry --title="$title" --text="$prompt" --entry-text="$default" 2>/dev/null || echo "$default"
  elif has_cmd kdialog; then
    kdialog --title "$title" --inputbox "$prompt" "$default" 2>/dev/null || echo "$default"
  else
    echo -n "  $prompt [$default] : " >&2
    read -r _input
    echo "${_input:-$default}"
  fi
}

gui_info() {
  local title="$1" msg="$2"
  if [[ "$OS" == "Darwin" ]]; then
    osascript -e "display dialog \"$msg\" with title \"$title\" buttons {\"OK\"} default button 1" 2>/dev/null || true
  elif has_cmd zenity; then
    zenity --info --title="$title" --text="$msg" --width=420 2>/dev/null || true
  elif has_cmd kdialog; then
    kdialog --title "$title" --msgbox "$msg" 2>/dev/null || true
  else
    echo ""
    echo "  [$title] $msg"
    echo ""
  fi
}

gui_error() {
  local title="$1" msg="$2"
  if [[ "$OS" == "Darwin" ]]; then
    osascript -e "display dialog \"$msg\" with title \"$title\" buttons {\"Fermer\"} default button 1 with icon stop" 2>/dev/null || true
  elif has_cmd zenity; then
    zenity --error --title="$title" --text="$msg" --width=420 2>/dev/null || true
  elif has_cmd kdialog; then
    kdialog --title "$title" --error "$msg" 2>/dev/null || true
  else
    echo "[ERREUR] $msg" >&2
  fi
}

gui_yesno() {
  local title="$1" msg="$2"
  if [[ "$OS" == "Darwin" ]]; then
    local btn
    btn=$(osascript -e "button returned of (display dialog \"$msg\" with title \"$title\" buttons {\"Non\", \"Oui\"} default button 2)" 2>/dev/null) || return 1
    [[ "$btn" == "Oui" ]]
  elif has_cmd zenity; then
    zenity --question --title="$title" --text="$msg" --width=380 2>/dev/null
  elif has_cmd kdialog; then
    kdialog --title "$title" --yesno "$msg" 2>/dev/null
  else
    echo -n "  $msg [o/n] : " >&2
    read -r _yn
    [[ "${_yn,,}" == "o" || "${_yn,,}" == "oui" || "${_yn,,}" == "y" ]]
  fi
}

# ── Affichage terminal ───────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          ELY Desktop — Installateur / Lanceur               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Vérifier que le binaire existe ────────────────────────────────────────
if [[ ! -f "$BINARY_PATH" ]]; then
  gui_error "ELY Desktop — Fichier manquant" \
    "Impossible de trouver le binaire :\n$BINARY\n\nTéléchargez-le depuis l'interface ELY\n(Settings → ELY Desktop → Télécharger le daemon)"
  exit 1
fi

# ── 2. Rendre le binaire exécutable ──────────────────────────────────────────
chmod +x "$BINARY_PATH"
echo "✔  Binaire rendu exécutable : $BINARY"

# ── 3. Installer les dépendances (Linux uniquement) ──────────────────────────
if [[ "$OS" == "Linux" ]]; then
  MISSING_DEPS=()
  has_cmd scrot    || MISSING_DEPS+=("scrot")
  has_cmd xdotool  || MISSING_DEPS+=("xdotool")

  if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo ""
    echo "⚠  Dépendances manquantes : ${MISSING_DEPS[*]}"
    echo "   Installation en cours (sudo requis)..."

    if has_cmd apt-get; then
      sudo apt-get install -y "${MISSING_DEPS[@]}"
    elif has_cmd dnf; then
      sudo dnf install -y "${MISSING_DEPS[@]}"
    elif has_cmd pacman; then
      sudo pacman -S --noconfirm "${MISSING_DEPS[@]}"
    else
      gui_error "ELY Desktop — Dépendances manquantes" \
        "Installez manuellement : ${MISSING_DEPS[*]}\n\nExemple (Ubuntu/Debian) :\n  sudo apt install scrot xdotool"
      exit 1
    fi
    echo "✔  Dépendances installées"
  else
    echo "✔  Dépendances déjà présentes (scrot, xdotool)"
  fi
fi

# ── 4. Premier lancement : créer la config ───────────────────────────────────
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo ""
  echo "══  Premier lancement — Configuration  ══════════════════════════"
  echo ""

  gui_info "ELY Desktop — Configuration initiale" \
"Bienvenue dans ELY Desktop !

Aucun fichier de configuration trouvé.

Deux options :
 1. Téléchargez ely-config.json depuis l'interface ELY
    (Settings → ELY Desktop → Télécharger la config)
    puis placez-le dans ce dossier.

 2. Entrez manuellement l'URL du serveur et le token
    (les informations suivantes vous seront demandées)."

  # Demander l'URL du serveur
  VPS_URL=$(gui_input \
    "ELY Desktop — Serveur" \
    "URL du serveur ELY\n(ex : http://192.168.1.100:8000 ou https://mon-serveur.com)" \
    "http://")

  if [[ -z "$VPS_URL" || "$VPS_URL" == "http://" ]]; then
    gui_error "ELY Desktop — Erreur" "L'URL du serveur est requise.\nRelancez l'installateur."
    exit 1
  fi

  # Demander le token
  TOKEN=$(gui_input \
    "ELY Desktop — Token" \
    "Token d'authentification\n(disponible dans Settings → ELY Desktop)" \
    "")

  if [[ -z "$TOKEN" ]]; then
    gui_error "ELY Desktop — Erreur" "Le token est requis.\nRelancez l'installateur."
    exit 1
  fi

  # Demander les répertoires autorisés
  SANDBOX_DIR=$(gui_input \
    "ELY Desktop — Répertoires autorisés" \
    "Répertoire à autoriser (ex : /home/$USER/Documents)\nVous pourrez en ajouter d'autres depuis l'interface ELY." \
    "/home/$USER/Documents")

  # Construire le JSON
  cat > "$CONFIG_FILE" <<EOF
{
  "vps_url": "$VPS_URL",
  "token": "$TOKEN",
  "sandbox_dirs": ["$SANDBOX_DIR"],
  "version": "1"
}
EOF

  echo "✔  Configuration créée : $CONFIG_FILE"
  gui_info "ELY Desktop — Prêt !" \
    "Configuration sauvegardée.\n\nELY Desktop va maintenant démarrer."

else
  echo "✔  Configuration trouvée : $CONFIG_FILE"
fi

# ── 5. Démarrage automatique ─────────────────────────────────────────────────
#
# ⚠️ CE BLOC ÉTAIT « Linux uniquement », ET C'ÉTAIT LE DÉFAUT (21/08).
#
# Linux posait son entrée `~/.config/autostart`, Windows sa clé de registre
# `HKCU\...\Run` — macOS n'avait RIEN. Le script se terminait par un
# `exec "$BINARY_PATH"` au premier plan : on ferme le terminal, le démon meurt.
#
# Ce que ça a coûté : le dossier surveillé de Franck affichait « 0 fichier
# indexé » depuis des MOIS. Le démon avait tourné une fois, le jour de
# l'installation, puis plus jamais — et rien ne le disait (corrigé par #334,
# qui rend l'état visible ; ici on corrige la cause).
#
# macOS a droit au meilleur des trois mécanismes : `KeepAlive` relance le
# démon s'il plante, ce que ni l'autostart XDG ni la clé Run ne savent faire.
_autostart_installe=0

if [[ "$OS" == "Darwin" ]]; then
  PLIST_LABEL="fr.agent-ely.desktop"
  PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
  LOG_PATH="$HOME/Library/Logs/ely-desktop.log"

  if [[ ! -f "$PLIST_PATH" ]]; then
    if gui_yesno "ELY Desktop — Démarrage automatique" \
      "Voulez-vous lancer ELY Desktop automatiquement à l'ouverture de votre session ?\n\nIl se relancera aussi tout seul s'il s'arrête, et se reconnectera après chaque redémarrage d'ELY."; then

      mkdir -p "$HOME/Library/LaunchAgents" "$(dirname "$LOG_PATH")"
      # `os.Executable()` sert à trouver ely-config.json (cf. config.go), donc
      # aucun WorkingDirectory n'est nécessaire : le démon se repère seul.
      cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BINARY_PATH</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_PATH</string>
    <key>StandardErrorPath</key>
    <string>$LOG_PATH</string>
</dict>
</plist>
EOF
      # `unload` d'abord : rend l'opération rejouable sans erreur si un
      # agent du même label traînait déjà.
      launchctl unload "$PLIST_PATH" 2>/dev/null || true
      if launchctl load -w "$PLIST_PATH" 2>/dev/null; then
        _autostart_installe=1
        echo "✔  Démarrage automatique activé (LaunchAgent)"
        echo "   Journal : $LOG_PATH"
        echo "   Pour le retirer : launchctl unload -w '$PLIST_PATH' && rm '$PLIST_PATH'"
      else
        # On ne laisse pas un plist orphelin qui donnerait l'illusion que
        # l'automatisme est en place alors qu'il n'est pas chargé.
        rm -f "$PLIST_PATH"
        echo "⚠  Démarrage automatique impossible — le démon sera lancé au premier plan."
      fi
    fi
  else
    echo "✔  Démarrage automatique déjà configuré : $PLIST_PATH"
    _autostart_installe=1
  fi
fi

# ── 5b. Raccourci .desktop (Linux uniquement) ────────────────────────────────
if [[ "$OS" == "Linux" ]]; then
  DESKTOP_ENTRY="$HOME/.local/share/applications/ely-desktop.desktop"
  AUTOSTART_ENTRY="$HOME/.config/autostart/ely-desktop.desktop"

  if [[ ! -f "$DESKTOP_ENTRY" ]]; then
    mkdir -p "$HOME/.local/share/applications"
    cat > "$DESKTOP_ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=ELY Desktop
Comment=ELY Desktop Daemon
Exec=$BINARY_PATH
Icon=utilities-terminal
Terminal=true
Categories=Utility;
EOF
    echo "✔  Raccourci créé dans les applications"
  fi

  # Proposer le démarrage automatique
  if [[ ! -f "$AUTOSTART_ENTRY" ]]; then
    if gui_yesno "ELY Desktop — Démarrage automatique" \
      "Voulez-vous lancer ELY Desktop automatiquement\nat the session startup ?"; then
      mkdir -p "$HOME/.config/autostart"
      cp "$DESKTOP_ENTRY" "$AUTOSTART_ENTRY"
      # En mode autostart, pas de terminal visible
      sed -i 's/Terminal=true/Terminal=false/' "$AUTOSTART_ENTRY"
      echo "✔  Démarrage automatique activé"
    fi
  fi
fi

# ── 6. Lancer le daemon ───────────────────────────────────────────────────────
#
# ⚠️ Sauf si launchd vient de le faire. Sans ce garde-fou on lancerait une
# SECONDE instance, qui se battrait avec la première pour le même WebSocket —
# et l'utilisateur verrait des déconnexions inexplicables juste après avoir
# activé l'automatisme censé les supprimer.
if [[ "$_autostart_installe" == "1" ]]; then
  echo ""
  echo "══  ELY Desktop tourne en arrière-plan  ═════════════════════════"
  echo ""
  echo "  Lancé par launchd, il redémarrera à chaque ouverture de session."
  echo "  Rien à laisser ouvert : vous pouvez fermer ce terminal."
  echo ""
  echo "  Vérifier la connexion : Réglages → Intégrations → ELY Desktop"
  echo ""
  exit 0
fi

echo ""
echo "══  Démarrage du daemon  ════════════════════════════════════════"
echo ""
echo "  Serveur  : $(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d['vps_url'])" 2>/dev/null || grep vps_url "$CONFIG_FILE" | head -1)"
echo "  Config   : $CONFIG_FILE"
echo ""
echo "  Appuyez sur Ctrl+C pour arrêter."
echo ""

exec "$BINARY_PATH"

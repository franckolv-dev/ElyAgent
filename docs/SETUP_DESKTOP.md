# 🖥️ Installer ELY Desktop (le daemon local)

> **À quoi ça sert ?** ELY Desktop est un petit programme qui tourne sur ton Mac/PC/Linux et donne à ELY la capacité de **lire, écrire, déplacer des fichiers locaux** (sandboxés sur les dossiers que tu autorises). Sans lui, ELY ne peut pas voir ton `~/Documents/`.
>
> **Tu en as besoin si tu veux** : RAG sur des PDFs locaux, screenshot du bureau, lancer une app, automatiser ton bureau. Pour un usage chat + Gmail + Calendar, ce n'est PAS nécessaire.

---

## 🎯 Méthode A — Télécharger un binaire pré-buildé (le plus simple)

### Si tu utilises l'instance hostée par Franck (`agent-ely.fr`)

Va dans **Paramètres → Intégrations → ELY Desktop** et clique sur le bouton de téléchargement correspondant à ton OS.

Si tu vois un message *« Aucun binaire disponible »*, c'est que la personne qui héberge n'a pas encore buildé le daemon. Continue avec la **Méthode B** ou demande-lui de builder.

### Si tu auto-héberges ELY (clone repo)

Pour la version v1.1+, les binaires officiels seront attachés à chaque GitHub Release :

1. Va sur 👉 [github.com/franckolv-dev/PhysicalAgent/releases/latest](https://github.com/franckolv-dev/PhysicalAgent/releases/latest)
2. Télécharge le fichier qui correspond à ton OS :
   - `ely-desktop-macos-arm64` — Mac M1/M2/M3/M4
   - `ely-desktop-macos-amd64` — Mac Intel
   - `ely-desktop-linux-amd64` — Linux 64 bits
   - `ely-desktop-windows-amd64.exe` — Windows 10/11 64 bits
3. Place-les dans `desktop/dist/` à la racine de ton clone (le dossier existe déjà mais est vide).
4. Tu peux aussi récupérer les installers `install.sh` (Mac/Linux) et `install.bat` (Windows) qui automatisent le pas suivant.

---

## 🎯 Méthode B — Build toi-même depuis les sources

Si tu n'as pas accès aux binaires (release pas encore publiée, ou tu veux la version bleeding edge), tu les builds en 30 secondes.

### Prérequis : avoir Go installé

**Mac** : `brew install go`
**Linux** (Debian/Ubuntu) : `sudo apt install golang-go`
**Windows** : télécharge depuis [go.dev/dl](https://go.dev/dl/)

Vérifie avec `go version` (>= 1.21 requis).

### Build des 4 binaires en une commande

```bash
cd PhysicalAgent/desktop
bash build.sh
```

→ Les binaires apparaissent dans `desktop/dist/` (~5 MB chacun).

### Pas de Go installé ? Build via Docker

Si tu as déjà Docker (tu l'as forcément, ELY tourne dedans) :

```bash
cd PhysicalAgent/desktop
docker run --rm -v "$PWD":/src -w /src golang:1.23-alpine sh -c "
mkdir -p dist &&
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags='-s -w' -o dist/ely-desktop-linux-amd64 . &&
CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags='-s -w' -o dist/ely-desktop-macos-amd64 . &&
CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags='-s -w' -o dist/ely-desktop-macos-arm64 . &&
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags='-s -w' -o dist/ely-desktop-windows-amd64.exe . &&
cp install.sh install.bat dist/ && chmod +x dist/install.sh
"
```

---

## ⚙️ Installation (après avoir le binaire)

### 1. Télécharge ton fichier de configuration

Dans ELY → **Paramètres → Intégrations → ELY Desktop** → bouton **Télécharger ely-config.json**.

Ce fichier contient :
- L'URL WebSocket de ton instance ELY
- Un token JWT spécifique au daemon (valide 30 jours)
- Le user_id auquel le daemon est rattaché

**Place-le DANS LE MÊME DOSSIER que le binaire `ely-desktop-*`.**

### 2. Configure les dossiers autorisés

Toujours dans **Paramètres → Intégrations → ELY Desktop**, dans la section **Répertoires autorisés**, ajoute les chemins absolus que tu veux que ELY puisse explorer :

```
/Users/franck/Documents/dossier_recherche
/Users/franck/Desktop
```

⚠️ **Le daemon refusera tout accès en dehors de ces dossiers**, même si l'agent essaie. C'est volontaire (sandboxing). Tu peux ajouter/retirer à tout moment, le daemon se rafraîchit automatiquement.

### 3. Lance le daemon

**Mac / Linux** :
```bash
cd /chemin/vers/dossier-binaire
chmod +x ely-desktop-macos-arm64    # première fois seulement
./ely-desktop-macos-arm64
```

**Windows** :
Double-clique sur `ely-desktop-windows-amd64.exe`. Une fenêtre console s'ouvre. **Garde-la ouverte** tant que tu utilises ELY Desktop.

→ Tu dois voir :
```
[ELY Desktop] starting…
[ELY Desktop] connected to wss://ely.tondomaine.fr/ws/desktop
[ELY Desktop] sandbox: 2 directories allowed
[ELY Desktop] ready.
```

### 4. Vérifie dans ELY

Dans ELY → header en haut → l'icône ⚙️ Desktop doit afficher **● connecté** au lieu de ⚪ déconnecté.

Tu peux maintenant demander :
- *"Liste les fichiers PDF dans /Users/franck/Documents/dossier_recherche"*
- *"Lis le contenu de /Users/franck/Desktop/notes.txt"*
- *"Capture mon écran"*

---

## 🍎 Mac : « ELY Desktop ne peut pas être ouvert »

Mac bloque les binaires non-signés au premier lancement. Solution :

```bash
xattr -dr com.apple.quarantine ely-desktop-macos-arm64
```

Puis relance. **Une fois suffit**, Mac retiendra ton autorisation.

> 💡 Alternative : clique-droit → *Open* → *Open anyway*. Apple ouvre une exception une fois.

---

## 🚀 Lancer le daemon au démarrage

### Mac (LaunchAgent)

Crée `~/Library/LaunchAgents/fr.elyagent.desktop.plist` :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>fr.elyagent.desktop</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/TONUSER/ely-desktop/ely-desktop-macos-arm64</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/TONUSER/ely-desktop</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>
```

Puis :
```bash
launchctl load ~/Library/LaunchAgents/fr.elyagent.desktop.plist
```

### Linux (systemd user service)

Crée `~/.config/systemd/user/ely-desktop.service` :

```ini
[Unit]
Description=ELY Desktop daemon

[Service]
ExecStart=/home/TONUSER/ely-desktop/ely-desktop-linux-amd64
WorkingDirectory=/home/TONUSER/ely-desktop
Restart=always

[Install]
WantedBy=default.target
```

Puis :
```bash
systemctl --user daemon-reload
systemctl --user enable --now ely-desktop
```

### Windows (Task Scheduler)

Plus simple : place un raccourci de l'`.exe` dans le dossier `shell:startup` (Win+R → `shell:startup`).

---

## 🆘 Troubleshooting

### Le téléchargement me donne un fichier `.html`
Le serveur n'a pas le binaire. Soit la personne qui héberge n'a pas buildé (Méthode B), soit il y a un problème de routing nginx (depuis v1.1.x c'est corrigé). Re-update vers la dernière version d'ELY.

### Le daemon démarre mais ne se connecte pas
- Vérifie que `ely-config.json` est BIEN dans le même dossier que le binaire.
- Vérifie que l'URL WS dans le config est joignable depuis ton ordi (`wss://ely.tondomaine.fr/ws/desktop` ou similaire).
- Si tu utilises Tailscale, vérifie que tu es bien connecté au réseau Tail.

### « Connection refused »
Ton instance ELY n'est pas accessible. Vérifie qu'elle tourne (`make ps`) et que tu peux ouvrir l'UI dans ton navigateur.

### Le daemon se déconnecte aléatoirement
Normal si ton ordi se met en veille. Solutions :
- Laisse l'ordi éveillé pendant les sessions ELY Desktop
- Sur Mac : `caffeinate -i ./ely-desktop-macos-arm64` (le daemon empêche la veille tant qu'il tourne)

### « ELY Desktop ne peut pas être ouvert » (Mac)
Voir section **🍎 Mac** ci-dessus.

### Token expiré
Les tokens du daemon valident 30 jours. Re-télécharge `ely-config.json` depuis Settings et remplace l'ancien.

---

➡️ **Étape suivante** : retourne à [START_HERE.md](./START_HERE.md) pour explorer les autres canaux.

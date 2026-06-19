# 🐳 Installer Docker (pour les non-développeurs)

> **Tu n'as jamais utilisé Docker ?** Cette page est pour toi. Docker est ce qui permet à ELY de tourner sur ton ordinateur sans que tu aies à installer Python, Node.js, des bases de données, et 10 autres choses à la main.

⏱️ **Temps prévu** : 10-15 minutes (la plupart c'est l'attente du téléchargement).

---

## 🤔 C'est quoi Docker, en deux phrases ?

Docker, c'est comme une « boîte » qui contient une application **complète** avec tout ce dont elle a besoin pour fonctionner. Tu télécharges la boîte, tu la lances, ça marche. Pas besoin de bricoler des dépendances.

ELY est livrée comme **plusieurs boîtes Docker** : `frontend` (l'interface web), `backend` (le cerveau), `nginx` (le portier qui réunit tout sur un seul port), `qdrant` (la mémoire), plus un bac à sable Python isolé (`sandbox` + `egress-proxy`). Le LLM local (Ollama) tourne désormais directement sur ton Mac (pas dans Docker), pour profiter du GPU. Tu n'as rien à comprendre de leur intérieur — Docker s'en occupe.

---

## 💻 Installation par OS

### 🍎 Mac (Intel ou Apple Silicon)

1. Va sur 👉 [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Clique **Download for Mac** → choisis **Apple Silicon** (M1/M2/M3/M4) ou **Intel** selon ton Mac.
   *(Pas sûr ? Menu Apple en haut à gauche → À propos de ce Mac → si tu vois « M1/M2/M3/M4 », c'est Apple Silicon.)*
3. Ouvre le `.dmg` téléchargé → glisse Docker dans Applications.
4. Lance **Docker** depuis Launchpad → accepte les termes → tape ton mot de passe Mac quand demandé.
5. Attends que la baleine 🐳 dans la barre des menus arrête de bouger.

✅ **Vérification** : ouvre **Terminal** (Spotlight `⌘ + Espace` → tape "Terminal") et colle :
```bash
docker --version
docker compose version
```
Tu dois voir des numéros de version (ex. `Docker version 27.x.x`). Si oui, c'est gagné.

> 💡 **Conseil RAM** : *Docker Desktop → ⚙️ Settings → Resources → Memory* — mets au moins **16 GB**, idéalement **32 GB** si tu utilises Ollama/LM Studio en local. (Le conteneur `backend` est plafonné à 5 GB.)

---

### 🪟 Windows 10 / 11

1. Va sur 👉 [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) → **Download for Windows**.
2. Lance l'installeur `.exe`. Il va te dire qu'il faut **WSL 2** (Windows Subsystem for Linux). Accepte tout.
3. Si WSL 2 n'est pas activé, suis [ce guide officiel Microsoft](https://learn.microsoft.com/windows/wsl/install) — en résumé :
   ```powershell
   # Ouvre PowerShell EN ADMINISTRATEUR
   wsl --install
   # Redémarre ton PC
   ```
4. Une fois Docker installé, lance-le → accepte les termes.
5. Vérifie dans PowerShell ou Terminal :
   ```powershell
   docker --version
   docker compose version
   ```

> 💡 Si tu as une vieille version de Windows 10, ça peut ne pas marcher. Il faudra updater Windows ou utiliser **Docker Desktop pour WSL 2** (gratuit pour usage perso).

---

### 🐧 Linux (Ubuntu / Debian / Fedora…)

Pour Linux on installe **Docker Engine + Docker Compose** directement (pas Docker Desktop, qui est plus lourd) :

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Déconnecte-toi et reconnecte-toi pour appliquer le groupe
```

Vérifie :
```bash
docker --version
docker compose version
```

> 💡 Pour Fedora/RHEL, suis [docs.docker.com/engine/install](https://docs.docker.com/engine/install/) → choisis ta distrib.

---

## 📦 Cloner et lancer ELY

Une fois Docker installé, dans ton terminal :

```bash
# 1. Installe Git si tu ne l'as pas (Mac : brew install git, Linux : apt install git)
git --version

# 2. Clone le projet ELY
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent

# 3. Crée ton fichier de configuration
cp .env.example .env
```

Maintenant ouvre `.env` avec n'importe quel éditeur de texte (TextEdit sur Mac, Notepad sur Windows, nano/vim sur Linux) et **change UNIQUEMENT cette ligne** :

```bash
JWT_SECRET_KEY=CHANGE-ME-generate-a-random-64-char-hex-string
```

Remplace par une clé aléatoire. Pour en générer une, dans le terminal :

```bash
# Mac / Linux
openssl rand -hex 32

# Windows PowerShell
[System.Web.Security.Membership]::GeneratePassword(64, 0)
```

Copie le résultat et colle-le après le `=` dans `.env`. Sauvegarde.

> ⚠️ **Sans cette étape, ELY refuse de démarrer.** C'est une protection de sécurité (sinon n'importe qui pourrait forger des sessions admin). La clé doit faire **au moins 32 caractères** (un `openssl rand -hex 32` en produit 64).

---

## 🧠 Donne un cerveau à ELY

ELY a besoin d'**au moins un fournisseur LLM**, sinon elle démarre mais chaque message échoue. Le plus simple et gratuit : crée une clé Gemini sur [aistudio.google.com/apikey](https://aistudio.google.com/apikey), colle-la dans `GEMINI_API_KEY=` et mets `ACTIVE_LLM_PROVIDER=gemini` dans `.env`.

> 💡 Par défaut `ACTIVE_LLM_PROVIDER=ollama`, ce qui suppose un **Ollama installé sur ton Mac** (en natif, sur le port `11434` — il n'est plus fourni en conteneur Docker). Détails et autres fournisseurs : [SETUP_AI_PROVIDERS.md](./SETUP_AI_PROVIDERS.md).

---

## 🚀 Lancer ELY

```bash
# Démarre tout (frontend, backend, mémoire vectorielle…)
make up
```

Ça va télécharger les images Docker (~2 Go la 1ère fois — patience) puis lancer tous les services. Suis les logs avec `make logs s=backend` et attends la ligne `Application startup complete`, puis Ctrl+C pour quitter les logs.

**Si tu n'as pas `make`** (Windows sans WSL) :
```bash
docker compose up -d
```

---

## 👤 Créer ton premier compte admin

**Le plus simple** : ouvre [http://localhost:3000](http://localhost:3000) et **inscris-toi** — le tout premier compte créé devient automatiquement admin. Aucun script à lancer.

> 🔑 **Mot de passe** : 12 caractères minimum, avec au moins **1 majuscule** et **1 caractère spécial** (ex. `MonMotDeP@sse2026`).

**En mode script / sans navigateur** (toujours dans le dossier `ElyAgent/`) :

```bash
make create-admin USER=<nom> PASS='<MonMotDeP@sse>' EMAIL=<email>
```

---

## 🌐 Ouvrir ELY dans ton navigateur

```
http://localhost:3000
```

Ouvre cette adresse et **crée ton compte** (le premier inscrit est admin). Bienvenue dans ELY.

---

## ⏯️ Commandes utiles

| Commande | Effet |
|---|---|
| `make up` | Démarre tout en arrière-plan |
| `make down` | Arrête tout |
| `make restart s=backend` | Redémarre juste le backend |
| `make logs s=backend` | Affiche les logs du backend en direct (Ctrl+C pour quitter) |
| `make ps` | Liste les containers actifs |
| `make build` | Reconstruit les images (à faire après une mise à jour du code) |

> 💡 Les commandes `make` sont juste des raccourcis pour `docker compose`. Si `make` n'est pas dispo (Windows sans WSL), remplace par : `docker compose up -d`, `docker compose down`, `docker compose restart backend`, etc.

---

## 🔄 Mettre à jour ELY

Quand une nouvelle version sort :

```bash
cd ElyAgent
git pull
make build
make up
```

Tes données (conversations, configs, comptes Google liés) sont préservées car stockées dans `data/` qui est exclu de Git.

---

## 🆘 Troubleshooting

### « `docker: command not found` »
Docker n'est pas installé ou pas dans ton PATH. Vérifie que Docker Desktop est bien lancé (icône baleine dans la barre des tâches/menu).

### « port is already allocated »
Quelque chose tourne déjà sur le port 3000, 8000 ou 80. Soit tu arrêtes ce truc, soit tu changes les ports via `.env` (`ELY_FRONTEND_PORT`, `ELY_BACKEND_PORT`, `ELY_QDRANT_PORT`, `ELY_HTTP_PORT`) plutôt que d'éditer `docker-compose.yml`.

> 💡 Point d'entrée recommandé : `nginx` expose ELY sur le **port 80** (`http://localhost`), qui réunit frontend et backend sur une seule adresse.

### « ELY refuse de démarrer — JWT_SECRET_KEY error »
Tu n'as pas modifié `JWT_SECRET_KEY` dans `.env`. Génère une vraie clé aléatoire (voir plus haut).

### Mac M1/M2 : « image not available for platform »
Tu as téléchargé Docker Intel au lieu d'Apple Silicon. Désinstalle et reprends la bonne version.

### « Out of memory » / Docker très lent
Augmente la RAM dans Docker Desktop : ⚙️ Settings → Resources → Memory → 16 GB minimum, 32 GB recommandé si tu utilises un LLM local.

### « ELY se ferme tout seul après quelques minutes »
Vérifie que ton ordi ne se met pas en veille. Sur Mac : Préférences Système → Économie d'énergie → décoche « Mettre en veille » quand l'écran est éteint (au moins pendant que tu utilises ELY).

### Comment tout désinstaller proprement
```bash
make down                    # arrête les containers
docker system prune -a       # supprime les images Docker
rm -rf ElyAgent/data    # supprime tes données ELY
# puis désinstalle Docker Desktop normalement
```

---

➡️ **Étape suivante** : [SETUP_AI_PROVIDERS.md](./SETUP_AI_PROVIDERS.md) pour donner un cerveau à ELY (créer ta clé API Anthropic / Gemini / autre).

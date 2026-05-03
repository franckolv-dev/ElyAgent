# 🐳 Installer Docker (pour les non-développeurs)

> **Tu n'as jamais utilisé Docker ?** Cette page est pour toi. Docker est ce qui permet à ELY de tourner sur ton ordinateur sans que tu aies à installer Python, Node.js, des bases de données, et 10 autres choses à la main.

⏱️ **Temps prévu** : 10-15 minutes (la plupart c'est l'attente du téléchargement).

---

## 🤔 C'est quoi Docker, en deux phrases ?

Docker, c'est comme une « boîte » qui contient une application **complète** avec tout ce dont elle a besoin pour fonctionner. Tu télécharges la boîte, tu la lances, ça marche. Pas besoin de bricoler des dépendances.

ELY est livrée comme **4 boîtes Docker** : `frontend` (l'interface web), `backend` (le cerveau), `qdrant` (la mémoire) et optionnellement `ollama` (un LLM local). Tu n'as rien à comprendre de leur intérieur — Docker s'en occupe.

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

> 💡 **Conseil RAM** : *Docker Desktop → ⚙️ Settings → Resources → Memory* — mets au moins **8 GB**, idéalement **16 GB** si tu utilises Ollama/LM Studio en local.

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

> ⚠️ **Sans cette étape, ELY refuse de démarrer.** C'est une protection de sécurité (sinon n'importe qui pourrait forger des sessions admin).

---

## 🚀 Lancer ELY

```bash
# Démarre tout (frontend, backend, mémoire vectorielle…)
make up
```

Ça va télécharger les images Docker (~2 Go la 1ère fois — patience) puis lancer tous les services. Quand tu vois `Started`, c'est prêt.

**Si tu n'as pas `make`** (Windows sans WSL) :
```bash
docker compose up -d
```

---

## 👤 Créer ton premier compte admin

Dans le terminal (toujours dans le dossier `ElyAgent/`) :

```bash
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password

async def go():
    async with async_session() as db:
        u = User(email='admin', username='admin',
                 hashed_password=await hash_password('changeme123'),
                 role='admin', is_active=True)
        db.add(u); await db.commit()
        print('OK')

asyncio.run(go())
"
```

Remplace `changeme123` par un vrai mot de passe.

---

## 🌐 Ouvrir ELY dans ton navigateur

```
http://localhost:3000
```

Connecte-toi avec `admin` / `<ton-mot-de-passe>`. Bienvenue dans ELY.

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
Quelque chose tourne déjà sur le port 3000 ou 8000. Soit tu arrêtes ce truc, soit tu changes les ports dans `docker-compose.yml`.

### « ELY refuse de démarrer — JWT_SECRET_KEY error »
Tu n'as pas modifié `JWT_SECRET_KEY` dans `.env`. Génère une vraie clé aléatoire (voir plus haut).

### Mac M1/M2 : « image not available for platform »
Tu as téléchargé Docker Intel au lieu d'Apple Silicon. Désinstalle et reprends la bonne version.

### « Out of memory » / Docker très lent
Augmente la RAM dans Docker Desktop : ⚙️ Settings → Resources → Memory → 8 GB minimum, 16 GB recommandé.

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

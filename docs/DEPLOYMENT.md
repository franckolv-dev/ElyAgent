# ELY Agent — Guide de déploiement (accès depuis l'extérieur)

Ce guide explique comment rendre ELY accessible depuis l'extérieur de votre réseau local (téléphone en 4G, autre poste, webhooks WhatsApp/Telegram…).

Trois options sont disponibles selon votre situation :

| Option | Difficulté | WhatsApp/Webhooks | Domaine personnalisé | Coût |
|--------|-----------|-------------------|----------------------|------|
| **A — Cloudflare Tunnel** | ★★☆ | ✅ | ✅ (avec votre domaine) | Gratuit |
| **B — Tailscale** | ★☆☆ | ❌ (pas d'exposition publique) | ✅ (sous-domaine `.ts.net`) | Gratuit |
| **C — IP fixe + Caddy** | ★★★ | ✅ | ✅ | Coût FAI/routeur |

> **Recommandation** : Si vous avez un domaine, utilisez **l'Option A (Cloudflare Tunnel)**. Si vous voulez juste accéder à ELY depuis vos propres appareils, **l'Option B (Tailscale)** est la plus simple.

---

## Prérequis communs

ELY doit être installé et fonctionnel en local via Docker avant de configurer l'accès externe.

```bash
# Depuis la racine du projet
make up          # Démarre tous les containers
make ps          # Vérifie que tout est vert
```

Les services doivent être accessibles en local :
- Frontend : `http://localhost:3000`
- Backend : `http://localhost:8000`
- nginx : `http://localhost:80` ← point d'entrée unique

---

## Option A — Cloudflare Tunnel (recommandée)

### Principe

`cloudflared` ouvre une connexion sortante vers Cloudflare. Votre machine n'a aucun port ouvert. Cloudflare expose votre domaine au monde.

```
Internet → Cloudflare → cloudflared (tunnel) → nginx:80 → frontend:3000
                                                          → backend:8000 (API + WebSocket)
```

### Prérequis

- Un domaine dont vous contrôlez les DNS (ex: `mondomaine.fr`)
- Un compte Cloudflare gratuit

### Étape 1 — Transférer le domaine vers Cloudflare

1. Créez un compte sur [cloudflare.com](https://cloudflare.com)
2. Cliquez **Add a domain** → entrez votre domaine
3. Choisissez le plan **Free**
4. Cloudflare va scanner vos DNS existants — **notez-les** avant de continuer
5. Cloudflare vous donne deux nameservers, par exemple :
   ```
   veronica.ns.cloudflare.com
   wells.ns.cloudflare.com
   ```
6. Allez chez votre registrar (Hostinger, OVH, Namecheap…) et remplacez les nameservers par ceux de Cloudflare
7. Attendez la propagation (quelques minutes à 24h selon le registrar) — Cloudflare vous envoie un email de confirmation

### Étape 2 — Installer cloudflared

```bash
# macOS
brew install cloudflared

# Linux (Debian/Ubuntu)
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

### Étape 3 — Créer le tunnel

1. Allez sur `dash.cloudflare.com` → **Zero Trust** → **Networks** → **Tunnels**
2. Cliquez **Create a tunnel**
3. Choisissez **Cloudflared** comme connecteur
4. Donnez un nom (ex: `ely-mac`)
5. Sur la page suivante, copiez la commande d'installation du service, qui ressemble à :
   ```bash
   sudo cloudflared service install eyJhIjoiZGE5OGU...
   ```
6. Exécutez cette commande sur votre machine. Le tunnel apparaîtra comme **Connected** dans Cloudflare.

### Étape 4 — Configurer le DNS du tunnel

Le tunnel a besoin d'un enregistrement DNS CNAME pour répondre à votre sous-domaine.

1. Dans Cloudflare, allez dans **Networks → Tunnels → votre tunnel → Published application routes**
2. Cliquez **Add a published application route**
3. Remplissez :
   - **Public hostname** : `ely.mondomaine.fr` (ou le sous-domaine de votre choix)
   - **Path** : *(laisser vide)*
   - **Service** : `http://localhost:80`
4. Cloudflare crée automatiquement le CNAME DNS

> ⚠️ **Si le CNAME n'est pas créé automatiquement** : allez dans **DNS** et ajoutez manuellement :
> - Type : `CNAME`
> - Name : `ely` (le sous-domaine)
> - Content : `<tunnel-id>.cfargotunnel.com` (visible dans l'URL du tunnel)
> - Proxy : **Proxied** (nuage orange)

### Étape 5 — Configurer le `.env`

```env
FRONTEND_URL=https://ely.mondomaine.fr
BACKEND_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_API_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_WS_URL=wss://ely.mondomaine.fr
COOKIE_SECURE=true
```

Puis rebuild le frontend (les vars `NEXT_PUBLIC_*` sont baked at build time) :

```bash
make restart s=frontend
```

### Étape 6 — Vérifier

```bash
curl https://ely.mondomaine.fr/health
# → {"status":"ok"}
```

### Démarrage automatique

Le service `cloudflared` installé via `sudo cloudflared service install` démarre automatiquement à chaque démarrage de la machine.

Pour vérifier son état :
```bash
# macOS
sudo launchctl list | grep cloudflared

# Linux
sudo systemctl status cloudflared
```

---

## Option B — Tailscale (réseau privé)

### Principe

Tailscale crée un réseau VPN mesh entre vos appareils. ELY n'est accessible qu'aux appareils que vous avez autorisés — aucune exposition publique.

```
Vos appareils (téléphone, ordi) → Tailscale VPN → votre machine → nginx:80
```

> ⚠️ **Limitation** : les webhooks externes (WhatsApp, Telegram entrant via webhook, etc.) ne fonctionnent pas avec Tailscale seul, car votre machine n'est pas accessible publiquement.

### Prérequis

- Un compte Tailscale gratuit sur [tailscale.com](https://tailscale.com)

### Étape 1 — Installer Tailscale sur la machine hôte

```bash
# macOS
brew install tailscale
sudo tailscaled &
tailscale up

# Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Notez l'IP Tailscale de votre machine, visible avec :
```bash
tailscale ip -4
# Exemple : 100.100.150.110
```

### Étape 2 — Obtenir un domaine HTTPS gratuit

Tailscale fournit des certificats HTTPS pour les machines de votre tailnet :

```bash
tailscale cert <hostname>.tail-xxxxx.ts.net
# Remplacez <hostname> par le nom de votre machine Tailscale
```

Le sous-domaine complet est visible dans le dashboard Tailscale : [login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)

Exemple : `mon-mac.tail-a1b2c3.ts.net`

### Étape 3 — Installer Tailscale sur vos appareils clients

- **iPhone/Android** : installez l'app Tailscale depuis l'App Store / Play Store
- **Windows/macOS** : installez le client Tailscale
- Connectez-vous avec le même compte

### Étape 4 — Configurer le `.env`

```env
FRONTEND_URL=https://mon-mac.tail-a1b2c3.ts.net
BACKEND_URL=https://mon-mac.tail-a1b2c3.ts.net
NEXT_PUBLIC_API_URL=https://mon-mac.tail-a1b2c3.ts.net
NEXT_PUBLIC_WS_URL=wss://mon-mac.tail-a1b2c3.ts.net
COOKIE_SECURE=true
```

> Remplacez `mon-mac.tail-a1b2c3.ts.net` par votre vrai hostname Tailscale.

Puis :
```bash
make restart s=frontend
```

### Étape 5 — Vérifier

Depuis un appareil sur le même tailnet :
```
https://mon-mac.tail-a1b2c3.ts.net
```

---

## Option C — IP fixe + Caddy

### Principe

Votre routeur redirige les ports 80 et 443 vers votre machine. Caddy gère automatiquement les certificats Let's Encrypt.

```
Internet → votre box (port 443) → votre machine → Caddy → nginx:80
```

> ⚠️ **Prérequis** : votre FAI doit autoriser les connexions entrantes sur le port 443 (certains opérateurs les bloquent). Vous avez besoin d'une IP fixe ou d'un service DDNS.

### Étape 1 — Configurer la redirection de port

Dans l'interface de votre box/routeur :
- Redirigez le port **443 (TCP)** vers l'IP locale de votre machine
- Redirigez le port **80 (TCP)** vers l'IP locale de votre machine (nécessaire pour Let's Encrypt)

Trouvez l'IP locale de votre machine :
```bash
# macOS/Linux
ip route get 1 | awk '{print $7; exit}'
# ou
ifconfig | grep "inet " | grep -v 127.0.0.1
```

### Étape 2 — Installer Caddy

```bash
# macOS
brew install caddy

# Linux (Debian/Ubuntu)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

### Étape 3 — Créer le Caddyfile

Créez `/etc/caddy/Caddyfile` (Linux) ou `~/Caddyfile` (macOS) :

```caddyfile
ely.mondomaine.fr {
    # WebSocket et API vers le backend
    handle /ws/* {
        reverse_proxy localhost:8000
    }
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle /auth/* {
        reverse_proxy localhost:8000
    }
    handle /admin/* {
        reverse_proxy localhost:8000
    }
    handle /health* {
        reverse_proxy localhost:8000
    }
    handle /analytics/* {
        reverse_proxy localhost:8000
    }
    handle /hosts/* {
        reverse_proxy localhost:8000
    }
    handle /tts/* {
        reverse_proxy localhost:8000
    }
    handle /skills/* {
        reverse_proxy localhost:8000
    }

    # Frontend
    handle {
        reverse_proxy localhost:3000
    }
}
```

> Remplacez `ely.mondomaine.fr` par votre domaine ou IP. Caddy obtient automatiquement le certificat Let's Encrypt.

### Étape 4 — Démarrer Caddy

```bash
# Linux
sudo systemctl enable caddy
sudo systemctl start caddy

# macOS (avec brew)
brew services start caddy
# ou depuis le dossier contenant le Caddyfile :
caddy run
```

### Étape 5 — Configurer le `.env`

```env
FRONTEND_URL=https://ely.mondomaine.fr
BACKEND_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_API_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_WS_URL=wss://ely.mondomaine.fr
COOKIE_SECURE=true
```

Puis :
```bash
make restart s=frontend
```

---

## Configuration commune après l'installation

### Créer le compte administrateur

La base de données est vide au premier démarrage. Créez votre compte admin :

```bash
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password

async def create_user():
    async with async_session() as db:
        user = User(
            email='admin@example.com',
            username='admin',
            hashed_password=await hash_password('votre-mot-de-passe'),
            role='admin',
            is_active=True
        )
        db.add(user)
        await db.commit()
        print('Compte créé !')

asyncio.run(create_user())
"
```

> Remplacez `admin@example.com`, `admin` et `votre-mot-de-passe` par vos valeurs.

### Configurer les modèles IA

Une fois connecté, allez dans **Settings → Modèles IA** :

1. Cliquez **+ Ajouter**
2. Choisissez votre provider :
   - **Ollama (Local)** → sélectionnez un modèle téléchargé (liste auto-détectée)
   - **Anthropic Claude** → entrez votre clé API
   - **Google Gemini**, **Mistral AI**, **DeepSeek**, etc.
3. Allez dans **Routage** pour assigner les modèles aux niveaux de complexité

### Variables d'environnement essentielles

Fichier `.env` à la racine du projet :

```env
# ── LLM (au moins un requis) ──────────────────────────────────────────
ACTIVE_LLM_PROVIDER=ollama           # ou: anthropic, gemini, mistral, deepseek
ACTIVE_LLM_MODEL=gemma4:26b          # modèle par défaut
ANTHROPIC_API_KEY=sk-ant-...         # si provider anthropic
GEMINI_API_KEY=AIza...               # si provider gemini
OLLAMA_BASE_URL=http://host.docker.internal:11434  # Ollama local (Mac/Linux)

# ── Sécurité ──────────────────────────────────────────────────────────
# Génération : python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=votre-clé-secrète-ici

# ── URLs (remplacez par votre domaine ou IP Tailscale) ────────────────
FRONTEND_URL=https://ely.mondomaine.fr
BACKEND_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_API_URL=https://ely.mondomaine.fr
NEXT_PUBLIC_WS_URL=wss://ely.mondomaine.fr
COOKIE_SECURE=true                   # true en production HTTPS

# Les notifications push mobile passent par FCM (Android) / APNs (iOS)
# et sont configurées directement dans les projets android/ et ios/.
```

---

## Dépannage

### Le site ne répond pas

```bash
# Vérifier que tous les containers sont up
make ps

# Vérifier nginx
curl http://localhost:80/health
# → {"status":"ok","database":"ok"}

# Vérifier les logs
make logs s=backend
make logs s=nginx
```

### WebSocket bloqué sur "CONNECTING..."

```bash
# Vérifier que nginx route bien /ws/ vers le backend
curl --include --no-buffer \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  http://localhost:80/ws/chat
# Doit retourner 401 (pas 404) — le backend répond
```

### Tunnel Cloudflare déconnecté

```bash
# macOS
sudo launchctl stop com.cloudflare.cloudflared
sudo launchctl start com.cloudflare.cloudflared

# Linux
sudo systemctl restart cloudflared

# Voir les logs en temps réel
tail -f /Library/Logs/com.cloudflare.cloudflared.err.log  # macOS
sudo journalctl -fu cloudflared                           # Linux
```

### Erreur "Session expirée" en boucle

Videz le cache du navigateur et les cookies, puis reconnectez-vous. Si le problème persiste en mode incognito, vérifiez que `COOKIE_SECURE=true` dans le `.env` (obligatoire en HTTPS).

### DNS ne se résout pas après changement de nameservers

La propagation DNS peut prendre de quelques minutes à 48h selon le registrar. Vérifiez l'état :
```bash
dig votre-sous-domaine.mondomaine.fr @1.1.1.1 +short
```
Tant que ça ne retourne pas d'IP, attendez et réessayez.

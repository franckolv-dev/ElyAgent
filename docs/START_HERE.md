# 🧭 Bienvenue — par où commencer avec ELY

> **Tu n'es pas développeur ? Pas de souci.** Cette documentation est conçue pour quelqu'un qui n'a jamais bricolé d'API, jamais utilisé Docker, jamais créé de projet Google Cloud. On t'explique tout, étape par étape, avec des liens cliquables et des screenshots quand utile.
>
> Si tu connais déjà tout ça, tu peux sauter directement aux liens dans la table de référence en bas.

---

## 🎯 Choisis ton scénario en 30 secondes

### 🟢 Scénario A — *« Je veux juste essayer »*
> Tester ELY sur ton Mac/PC en local, gratuitement, sans rien exposer. Pas de mobile, pas de Telegram. Juste discuter avec elle dans ton navigateur.

**Parcours** (≈ 30 min) :
1. 🐳 [SETUP_DOCKER.md](./SETUP_DOCKER.md) — installer Docker (10 min)
2. 🤖 [SETUP_AI_PROVIDERS.md](./SETUP_AI_PROVIDERS.md) — créer une clé Google Gemini (gratuit) ou Anthropic Claude (5 $ de crédit gratuits) (10 min)
3. 💬 Ouvre [http://localhost:3000](http://localhost:3000) → connecte-toi → discute !

C'est tout. Tu peux t'arrêter là si ça te suffit.

---

### 🟡 Scénario B — *« Je veux qu'ELY voie mon Gmail/Calendar »*
> Comme A + autoriser ELY à lire tes emails, voir tes RDV, créer des Docs.

**Parcours** (≈ 50 min) :
1. Tout le scénario A (ci-dessus)
2. 📧 [SETUP_GOOGLE.md](./SETUP_GOOGLE.md) — connecter ton Google (15-20 min, le plus long c'est l'écran de consentement Google)
3. Demande à ELY : *« Mes emails non lus du jour »* → magie ✨

---

### 🟣 Scénario C — *« Je veux des notifs sur mon mobile »*
> Comme A ou B + recevoir les confirmations HITL ("ELY veut envoyer ce mail, ok ?") sur ton téléphone.

**Parcours** (≈ 1h au total) :
1. Tout le scénario A ou B
2. 🔔 [SETUP_NOTIFICATIONS.md](./SETUP_NOTIFICATIONS.md) — configurer **ntfy** (la voie la plus simple, 5 min)

> 💡 ntfy est un service gratuit anonyme. Tu installes une app, tu colles 1 URL dans la config ELY, c'est plié. Pas besoin d'app native ELY pour avoir les push.

---

### 🟠 Scénario D — *« Je veux y accéder depuis n'importe où »*
> Comme C + un vrai domaine `https://ely.tondomaine.fr` accessible depuis l'extérieur, avec Telegram/Discord/Slack/WhatsApp configurés.

**Parcours** (≈ 2-3h) :
1. Tout le scénario C
2. 🌍 [DEPLOYMENT.md](./DEPLOYMENT.md) — choisis **Cloudflare Tunnel** (le plus simple, gratuit, sans ouvrir de port) ou **Tailscale** (vrai privé, gratuit jusqu'à 100 devices)
3. 📞 [user-guide.md § 7](./user-guide.md) — configurer Telegram/Discord/Slack/WhatsApp un par un
4. 📱 (Optionnel) [ANDROID_INSTALL.md](./ANDROID_INSTALL.md) si tu veux l'app Android (build local pour l'instant)

---

## ⚠️ À savoir AVANT de commencer

### HTTPS est OBLIGATOIRE pour certaines fonctionnalités

| Fonctionnalité | URL `http://localhost` | URL `http://192.168.x.x` (LAN) | URL `https://...` |
|---|---|---|---|
| Chat texte | ✅ | ✅ | ✅ |
| Mode vocal "Éli" | ✅ (exception localhost) | ❌ bloqué | ✅ |
| Install PWA | ✅ (exception localhost) | ❌ bloqué | ✅ |
| App mobile native | — | ⚠️ marche mais auth fragile | ✅ |
| Push notifications mobile | ✅ (via ntfy) | ✅ (via ntfy) | ✅ |

**👉 Si tu veux le voice mode hors localhost, tu DOIS passer en HTTPS.** Le plus simple : **Tailscale** (HTTPS auto via `*.ts.net`) ou **Cloudflare Tunnel** (HTTPS auto via Cloudflare).

C'est une limitation des navigateurs (pas d'ELY) : `getUserMedia()` (le micro) refuse de marcher en HTTP brut depuis 2018.

---

## 📚 Référence par sujet

| Tu cherches… | Va voir |
|---|---|
| Installer Docker (Mac/Windows/Linux) | [SETUP_DOCKER.md](./SETUP_DOCKER.md) |
| Connecter ELY à Anthropic / OpenAI / Gemini / Kimi… avec liens cliquables | [SETUP_AI_PROVIDERS.md](./SETUP_AI_PROVIDERS.md) |
| Connecter Gmail/Calendar/Drive (OAuth, scopes, multi-comptes, Firebase) | [SETUP_GOOGLE.md](./SETUP_GOOGLE.md) |
| Push notifications mobile (ntfy / FCM / APNs / Telegram) | [SETUP_NOTIFICATIONS.md](./SETUP_NOTIFICATIONS.md) |
| Exposer ELY à l'extérieur (Cloudflare Tunnel, Tailscale, VPS) | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Configurer Telegram, Discord, Slack, WhatsApp | [user-guide.md § 7](./user-guide.md#7-channels) |
| Build et installer l'app Android | [ANDROID_INSTALL.md](./ANDROID_INSTALL.md) |
| Doc historique d'install (référence backend détaillée) | [installation.md](./installation.md) |
| Architecture interne (LangGraph, supervisor, tier routing) | [architecture.md](./architecture.md) |
| Liste exhaustive des features | [features.md](./features.md) |
| Politique de sécurité, threat model, signaler une faille | [../SECURITY.md](../SECURITY.md) |
| Roadmap publique (sprints, ETAs, ce qu'on construit) | [../ROADMAP.md](../ROADMAP.md) |
| Comment contribuer | [../CONTRIBUTING.md](../CONTRIBUTING.md) |

---

## 🆘 Quelque chose ne marche pas

**Avant d'ouvrir une issue** :
1. Lis la section **🆘 Troubleshooting** du fichier concerné (chacun des SETUP_*.md a sa section).
2. Regarde les logs : `make logs s=backend` et `make logs s=frontend` dans le dossier ELY.
3. Cherche dans les [issues GitHub fermées](https://github.com/franckolv-dev/PhysicalAgent/issues?q=is%3Aissue+is%3Aclosed) — il y a de fortes chances que ton problème ait déjà été résolu.
4. Toujours bloqué ? **Ouvre une issue** avec :
   - Ton OS (Mac M1, Windows 11, Ubuntu 22.04…)
   - La commande exacte qui plante
   - Les logs (`make logs s=backend | tail -50`)
   - Ce que tu as déjà essayé

On répond généralement sous 24-48h en semaine.

---

## 🎬 TL;DR pour les pressés (5 min)

Si tu veux juste **voir si ELY tourne** sur ton ordi sans configurer aucun service externe :

```bash
# 1. Installe Docker Desktop si pas déjà fait
# (https://www.docker.com/products/docker-desktop/)

# 2. Clone et lance
git clone https://github.com/franckolv-dev/PhysicalAgent.git
cd PhysicalAgent
cp .env.example .env

# 3. Génère un JWT secret et colle-le dans .env (ligne JWT_SECRET_KEY)
openssl rand -hex 32   # Mac/Linux
# Sur Windows : aléatoirement 64 caractères hex

# 4. Lance
make up   # ou: docker compose up -d

# 5. Crée un admin
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password
async def go():
    async with async_session() as db:
        u = User(email='admin', username='admin',
                 hashed_password=await hash_password('changeme'),
                 role='admin', is_active=True)
        db.add(u); await db.commit()
asyncio.run(go())
"

# 6. Ouvre http://localhost:3000 → admin / changeme
```

**Mais à ce stade, ELY n'a pas de cerveau.** Pour qu'elle réponde, il faut au minimum suivre [SETUP_AI_PROVIDERS.md](./SETUP_AI_PROVIDERS.md) (5-10 min de plus).

---

*Last updated: May 2, 2026 — pour la version 1.1.x.*

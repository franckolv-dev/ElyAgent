# 🔔 Recevoir les notifications d'ELY sur ton téléphone

> ELY fonctionne en **Human-in-the-Loop** : avant toute action critique (envoyer un email, supprimer un fichier, exécuter une commande SSH), elle te demande la permission. Pour qu'elle puisse te le demander **où que tu sois**, tu peux brancher différents canaux de notification mobile.

⏱️ **Le plus rapide (ntfy) prend 5 minutes.**

---

## 🤔 Quel canal choisir ?

| Canal | Difficulté | Mobile | Réaction (Allow/Deny) | Coût | Idéal pour |
|---|---|---|---|---|---|
| **ntfy** ⭐ | ⭐ très facile | iOS + Android | Boutons dans la notif | 0 € | Démarrer vite, simple, anonyme |
| **Telegram** | ⭐⭐ moyen | iOS + Android | Boutons inline keyboard | 0 € | Avoir aussi le chat ELY dans Telegram |
| **App Android native ELY** | ⭐⭐⭐ tech | Android only | UI native ELY | 0 € | Expérience la plus polish (mais nécessite Firebase) |
| **App iOS native ELY** | ⭐⭐⭐ tech | iOS only | UI native ELY | 99 $/an (Apple Developer requis pour build) | Power users iOS |
| **Discord / Slack** | ⭐⭐ moyen | iOS + Android | Réactions emoji / Block Kit | 0 € | Si tu vis déjà sur Discord/Slack |
| **Email** | ⭐ très facile | iOS + Android | Pas de réaction (lecture seule) | 0 € | Recevoir des résumés, pas pour HITL |

**👉 Notre conseil pour démarrer : ntfy.** Tu installes une app, tu colles 1 URL dans `.env`, c'est plié. Tu pourras toujours ajouter Telegram à côté plus tard.

---

## ⭐ Option 1 — ntfy (recommandé pour commencer)

### C'est quoi ntfy ?

[ntfy.sh](https://ntfy.sh/) est un service de push notifications **anonyme et gratuit** créé par un développeur indépendant. Pas besoin de compte. Tu choisis un « topic » (un nom secret), tu t'abonnes via l'app, et tout ce qu'on envoie à ce topic arrive sur ton téléphone.

C'est la même technologie qu'utilisent les bots Telegram en interne, sauf qu'ici **personne ne sait qui tu es** (pas de bot, pas de pairing, pas de compte).

### Setup en 5 minutes

#### 1. Choisis un topic secret

Un topic est juste un nom unique. **Choisis-en un long et imprévisible** sinon n'importe qui peut deviner et publier dessus :

✅ Bons exemples : `ely-franck-x7k2m9p4`, `notif-perso-2026-violet-cheval`
❌ Mauvais : `ely`, `test`, `notifications`, `franck`

> 💡 Tu peux générer un topic random ici : [ntfy.sh/app](https://ntfy.sh/app) (clique « Subscribe to topic » et tape n'importe quoi).

#### 2. Installe l'app ntfy sur ton mobile

- **iOS** : [App Store — ntfy](https://apps.apple.com/app/ntfy/id1625396347)
- **Android** : [Play Store — ntfy](https://play.google.com/store/apps/details?id=io.heckel.ntfy) ou [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/)

#### 3. Abonne-toi à ton topic

Ouvre l'app ntfy → **Subscribe** → tape ton topic (ex. `ely-franck-x7k2m9p4`) → **Subscribe**.

**Test** : depuis n'importe quel terminal, tape :
```bash
curl -d "Hello from ntfy" https://ntfy.sh/ely-franck-x7k2m9p4
```
Tu dois recevoir la notif sur ton phone instantanément. ✨

#### 4. Configure ELY

Dans ton fichier `.env` à la racine d'ELY, ajoute (ou décommente) :

```bash
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=ely-franck-x7k2m9p4   # remplace par TON topic
```

Redémarre le backend :
```bash
docker compose restart backend
```

#### 5. Vérifie

Dans ELY → *Paramètres → Channels* → tu dois voir **ntfy** marqué **● ON**.

À partir de maintenant, à chaque fois qu'ELY veut faire une action critique (envoyer mail, supprimer, etc.), tu reçois une notif ntfy avec **3 boutons** : ✅ Allow / ❌ Deny / 🚫 Ban (jamais plus jamais demander). Clique → c'est validé.

### Self-host ntfy (avancé)

Tu n'aimes pas dépendre du serveur public `ntfy.sh` ? Tu peux héberger ton propre serveur ntfy en Docker :
```yaml
services:
  ntfy:
    image: binwiederhier/ntfy
    command: serve
    ports: ["8088:80"]
    volumes:
      - ./ntfy-data:/var/cache/ntfy
```
Puis dans `.env` : `NTFY_URL=http://ton-serveur:8088`

L'app mobile ntfy supporte les serveurs perso : *Settings → Add server*.

---

## Option 2 — Telegram

Si tu utilises déjà Telegram quotidiennement, c'est pratique parce que tu auras à la fois **le chat ELY** ET **les notifs HITL** dans la même app.

📖 **Tutoriel complet** : [user-guide.md § 7.1 Telegram](./user-guide.md)

**Résumé en 1 minute** :
1. Sur Telegram, parle à [@BotFather](https://t.me/BotFather) → `/newbot` → suis les étapes → reçois ton token (`8537074323:AAHxxxxx`)
2. Dans ELY → *Paramètres → Channels → Telegram* → colle le token → Activer
3. Sur Telegram, parle à TON nouveau bot → envoie `/link <ton-username-ELY> <ton-mot-de-passe-ELY>`
4. C'est fait. Tu chattes avec ELY dans Telegram et les notifs HITL arrivent dans la même conversation.

---

## Option 3 — App Android native (FCM)

L'app Android d'ELY existe et fonctionne, mais elle nécessite **Firebase Cloud Messaging** côté backend pour envoyer les push.

📖 **Tutoriel** :
- Firebase setup : voir [SETUP_GOOGLE.md § Firebase](./SETUP_GOOGLE.md#-firebase-pour-les-push-android-optionnel)
- Build de l'APK : [ANDROID_INSTALL.md](./ANDROID_INSTALL.md)

> ⚠️ **À ce stade (mai 2026), tu dois builder l'APK toi-même.** Pas encore de Play Store. Si tu n'es pas développeur Android, **utilise ntfy à la place** — c'est largement suffisant pour 95% des usages.

---

## Option 4 — App iOS native (APNs)

Même histoire que pour Android : l'app SwiftUI existe (22 fichiers, iOS 17+) mais demande un compte **Apple Developer** (99 $/an) pour build et signer l'IPA. Pas de TestFlight publié encore.

> Pour iPhone, **on recommande ntfy** (parfait sur iOS) en attendant que la roadmap fasse passer l'app iOS sur TestFlight publique.

---

## Option 5 — Discord / Slack

Si tu veux les notifs HITL dans ton serveur Discord ou ton Slack :

📖 **Tutoriels** :
- Discord : [user-guide.md § 7.2](./user-guide.md)
- Slack : [user-guide.md § 7.3](./user-guide.md)

Idéal si tu utilises ELY en équipe (les autres voient les approbations).

---

## Option 6 — Email (résumés seulement)

Pas de canal HITL email actuellement (parce que cliquer un bouton dans un email est trop lent pour un workflow agentique). Mais ELY peut t'envoyer des **résumés quotidiens** par email via une mission planifiée :

```
"Tous les matins à 8h, envoie-moi par email un résumé
des emails non lus reçus durant la nuit"
```

(Utilise ton propre Gmail via OAuth — voir [SETUP_GOOGLE.md](./SETUP_GOOGLE.md).)

---

## 🔀 Plusieurs canaux en parallèle

Tu peux activer **tous** ces canaux en même temps. Par défaut, ELY enverra les notifs HITL sur **tous** les canaux configurés.

Si tu veux qu'elle n'utilise qu'un seul canal pour les push (ex. juste ntfy le soir, pas Telegram pour ne pas spammer ton chat) :

*Paramètres → Confirmations HITL → Canal de notification HITL* → choisis **ntfy uniquement** (ou autre).

---

## 🆘 Troubleshooting

### Je reçois rien sur ntfy
- Vérifie que l'app ntfy est **bien lancée et abonnée au bon topic** (cherche les fautes de frappe — `ely-franck-x7k2m9p4` ≠ `ely_franck_x7k2m9p4`)
- Test direct depuis ton terminal :
  ```bash
  curl -d "test" https://ntfy.sh/TON-TOPIC
  ```
  → si ça marche dans le terminal mais pas via ELY, vérifie les logs backend :
  ```bash
  make logs s=backend | grep ntfy
  ```
- Vérifie dans `.env` que `NTFY_URL` n'a pas de slash final (`https://ntfy.sh` ✅, `https://ntfy.sh/` ❌)

### Telegram : `/link` ne marche pas
- Vérifie que tu as bien activé le bot dans ELY (*Paramètres → Channels → Telegram → status: actif*)
- Le bot est en mode polling par défaut → ~10s de latence. C'est normal.

### App Android : pas de push
- Vérifie que `FIREBASE_CREDENTIALS_PATH` pointe sur ton service-account.json
- Vérifie que `google-services.json` est bien dans `android/app/` AU MOMENT DU BUILD (pas après)
- Vérifie que l'app a bien la permission Notifications dans Android (Paramètres → Apps → ELY → Notifications)

### iOS : impossible d'installer
- Tu dois être en compte Apple Developer ou utiliser TestFlight (pas dispo encore). Pour 99% des cas : **ntfy fait le job** sur iPhone.

---

➡️ **Suite logique** : [DEPLOYMENT.md](./DEPLOYMENT.md) si tu veux exposer ELY à l'extérieur (HTTPS via Cloudflare Tunnel ou Tailscale — **obligatoire pour le mode vocal et la PWA install**).

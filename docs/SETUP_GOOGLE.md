# 📧 Connecter ELY à ton Google (Gmail, Calendar, Drive…)

> **Cette étape est obligatoire si tu veux qu'ELY puisse lire tes emails, voir tes RDV, créer des Google Docs, etc.** Si tu veux juste discuter avec ELY sans qu'elle touche à tes données Google, tu peux **sauter cette page**.

⏱️ **Temps prévu** : 15-20 minutes la première fois.

---

## 🤔 Pourquoi c'est compliqué ?

Google demande à toute application qui veut accéder à tes données de **prouver son identité** via un système qui s'appelle « OAuth ». Tu vas devoir créer un projet sur la console Google Cloud, activer les APIs (Gmail, Calendar…), créer des « credentials », et coller un fichier dans ton ELY.

C'est lourd, mais c'est ce qui garantit qu'ELY n'accède **qu'aux services que tu autorises explicitement**, et que **tu peux révoquer cet accès en 1 clic** quand tu veux. Aucun autre agent perso open-source ne fait moins.

**Bonne nouvelle** : tu fais ça une fois, et c'est fini pour la vie (tant que tu ne supprimes pas le projet).

---

## ⚡ Préparation (2 min)

- ✅ Tu as un compte Google personnel ou pro (Gmail, Workspace…)
- ✅ ELY tourne déjà chez toi (au moins le backend démarre — `make up` doit avoir fonctionné)
- ✅ Tu sais à quelle URL tu accèdes à ELY (ex: `http://localhost:8000`, ou `https://ely.tondomaine.fr`, ou `https://ton-mac.tail-xxx.ts.net`). **Note-la** — on en aura besoin.

---

## Étape 1 — Créer un projet Google Cloud (3 min)

1. Va sur 👉 [console.cloud.google.com](https://console.cloud.google.com/)
2. Connecte-toi avec ton compte Google.
3. **En haut de page**, à droite du logo Google Cloud, clique sur le sélecteur de projet (ça affiche « Select a project » ou le nom d'un projet existant).
4. Clique **« New Project »** (en haut à droite de la fenêtre qui s'ouvre).
5. Nom du projet : tape **`ely-personal`** (ou ce que tu veux). Laisse l'organisation par défaut.
6. Clique **Create**. Attends 10-20 secondes.
7. **Important** : repasse dans le sélecteur de projet et sélectionne `ely-personal` pour bosser dedans. Tu dois voir le nom du projet en haut à gauche.

---

## Étape 2 — Activer les APIs Google (5 min)

Pour chaque service Google que tu veux qu'ELY utilise, il faut « activer » l'API correspondante. Voici les liens directs :

| Service | Lien d'activation | Obligatoire si tu veux… |
|---|---|---|
| **Gmail** | [Activer Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) | Lire/envoyer/trier des emails |
| **Calendar** | [Activer Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) | Voir/créer/modifier des RDV |
| **Drive** | [Activer Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) | Lister/chercher/uploader des fichiers |
| **Docs** | [Activer Docs API](https://console.cloud.google.com/apis/library/docs.googleapis.com) | Créer/modifier des Google Docs |
| **Sheets** | [Activer Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com) | Créer/modifier des Google Sheets |
| **Tasks** | [Activer Tasks API](https://console.cloud.google.com/apis/library/tasks.googleapis.com) | Gérer tes tâches Google |
| **People** (Contacts) | [Activer People API](https://console.cloud.google.com/apis/library/people.googleapis.com) | Lire/modifier tes contacts |

**Pour chacun** : clique le lien → vérifie que tu es bien dans le projet `ely-personal` (en haut) → clique le bouton bleu **« ENABLE »** → attends 5-10 secondes.

> 💡 Tu peux activer juste ce qui t'intéresse aujourd'hui. Tu pourras en ajouter plus tard sans recommencer le reste.

---

## Étape 3 — Configurer l'écran de consentement (4 min)

C'est l'écran que Google va afficher quand tu lieras ton compte à ELY pour la 1ère fois (« voulez-vous donner accès à votre Gmail à l'application ELY ? »).

1. Va sur 👉 [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) (vérifie que tu es dans le bon projet).
2. **Type d'utilisateur** : choisis **External** → Create.
3. Remplis :
   - **App name** : `ELY` (ou ce que tu veux)
   - **User support email** : ton email
   - **App logo** : optionnel, tu peux skip
   - **Developer contact** : ton email (en bas du formulaire)
   - Tout le reste : tu peux laisser vide
4. Clique **Save and Continue**.

5. Étape **Scopes** : clique **Add or Remove Scopes**. Dans la fenêtre qui s'ouvre, **filtre et coche** ces scopes (un par un — ils sont parfois cachés sous "Manually add scopes" tout en bas) :
   ```
   https://www.googleapis.com/auth/gmail.modify
   https://www.googleapis.com/auth/gmail.send
   https://www.googleapis.com/auth/gmail.settings.basic
   https://www.googleapis.com/auth/calendar
   https://www.googleapis.com/auth/drive
   https://www.googleapis.com/auth/documents
   https://www.googleapis.com/auth/spreadsheets
   https://www.googleapis.com/auth/tasks
   https://www.googleapis.com/auth/contacts
   https://www.googleapis.com/auth/userinfo.email
   https://www.googleapis.com/auth/userinfo.profile
   ```
   *(Ne coche que ceux dont tu as activé l'API à l'étape 2.)*
   → **Update** → **Save and Continue**.

6. Étape **Test users** : clique **+ Add Users** → ajoute **ton email** (et ceux de quiconque va utiliser cette instance d'ELY). Sans cette étape, ces personnes recevront une erreur 403 « cette app n'est pas vérifiée » et ne pourront pas se connecter.
   → **Save and Continue** → **Back to dashboard**.

> 💡 **Statut « Testing »** : c'est normal, ton app va rester en mode Testing. C'est suffisant pour un usage perso (ou famille/petite équipe). Pour passer en « Production » et ouvrir à n'importe qui, Google demande une **vérification** (~ 4-6 semaines, scopes sensibles). Pour ELY perso : reste en Testing.

---

## Étape 4 — Créer les credentials OAuth (2 min)

1. Va sur 👉 [Credentials](https://console.cloud.google.com/apis/credentials)
2. Clique **+ CREATE CREDENTIALS** (en haut) → **OAuth client ID**.
3. **Application type** : choisis **Web application**.
4. **Name** : `ELY Web Client` (ou ce que tu veux).
5. **Authorized redirect URIs** : c'est CRUCIAL. Clique **+ ADD URI** et ajoute **toutes les URLs** que tu utilises pour ELY :
   - Si tu testes en local : `http://localhost:8000/auth/google/callback`
   - Si tu utilises Tailscale : `https://ton-mac.tail-xxx.ts.net/auth/google/callback`
   - Si tu utilises Cloudflare Tunnel : `https://ely.tondomaine.fr/auth/google/callback`
   - Tu peux en mettre plusieurs si tu accèdes par différents chemins.

   ⚠️ **L'URL doit être EXACTE** (https vs http, slash final, port). Si tu te trompes, Google répondra `redirect_uri_mismatch`.

6. Clique **Create**.
7. Une popup s'ouvre avec ton **Client ID** et ton **Client Secret**. Clique le petit bouton **télécharger JSON** (icône 📥 à droite) → un fichier `client_secret_xxx.json` arrive sur ton disque.

---

## Étape 5 — Coller le fichier dans ELY (1 min)

Renomme le fichier téléchargé en `credentials.json` et place-le ici :

```
ElyAgent/
└── backend/
    └── credentials.json    ← ICI
```

(Si le dossier `backend/` n'existe pas, c'est que tu n'as pas cloné le repo correctement — reviens à [installation.md](./installation.md).)

Puis redémarre le backend pour qu'il recharge le fichier :

```bash
docker compose restart backend
```

---

## Étape 6 — Lier ton compte Google dans ELY (1 min)

1. Ouvre ELY dans ton navigateur (l'URL que tu as configurée à l'étape 4).
2. Connecte-toi avec ton compte ELY (admin).
3. Va dans **Paramètres → Intégrations**.
4. Sous **Services Google**, clique **Connecter Google**.
5. Tu es redirigé vers Google → choisis ton compte → tu vas voir l'écran « ELY n'est pas vérifiée ».
   - Clique **Advanced** (en bas à gauche) → **Go to ELY (unsafe)**. C'est normal et **sans danger** car c'est TOI qui as créé l'app à l'étape 3.
6. Coche les permissions demandées → **Continue**.
7. Tu reviens dans ELY avec un beau ✅ vert : « Connecté à `ton.email@gmail.com` ».

---

## 🎉 C'est fait !

Tu peux maintenant demander à ELY :
- *« Liste mes emails non lus »*
- *« Mes RDV de la semaine »*
- *« Crée un Google Doc intitulé Notes »*
- *« Cherche mes contacts qui s'appellent Marie »*

ELY ne demandera **jamais** Gmail/Calendar/etc. à un autre user que toi sans que tu valides explicitement.

---

## 🔁 Lier un 2ᵉ ou 3ᵉ compte Google (perso + pro)

ELY supporte **plusieurs comptes Google par utilisateur** depuis la version 1.1.

1. Refais juste l'**Étape 6** (clique **+ Ajouter un compte** au lieu de **Connecter Google**).
2. ELY te propose de leur donner des **noms** distincts : ex. `perso`, `pro`, `famille`.
3. Quand tu parles à ELY, tu peux préciser : *« envoie un mail depuis mon pro à… »* ou *« mes RDV cette semaine sur mon perso »*.

---

## 🔐 Révoquer l'accès quand tu veux

3 façons :

1. **Dans ELY** : *Paramètres → Intégrations → Services Google → Déconnecter*
2. **Côté Google** : [myaccount.google.com/permissions](https://myaccount.google.com/permissions) → trouve « ELY » → Remove access
3. **Supprimer le projet GCP** : [console.cloud.google.com/iam-admin/settings](https://console.cloud.google.com/iam-admin/settings) → Shut down (radical, plus aucun token ne fonctionnera)

---

## 🔥 Firebase pour les push Android (optionnel)

> **À ne lire QUE si tu veux installer l'app Android d'ELY** et recevoir des notifications HITL push (« Éli veut envoyer cet email, autoriser ? ») sur ton phone.

ELY utilise Firebase Cloud Messaging (FCM) pour envoyer les push à l'app Android. C'est **gratuit** mais demande un peu de config supplémentaire :

1. Va sur 👉 [console.firebase.google.com](https://console.firebase.google.com/)
2. Clique **Add project** → **import an existing Google Cloud project** → sélectionne `ely-personal` (créé à l'étape 1).
3. Une fois dans le projet Firebase :
   - **Add app** (icône Android) → package name : `fr.elyagent.app` (ou le nom que tu vois dans `android/app/build.gradle`).
   - Télécharge `google-services.json` → place-le dans `android/app/google-services.json`.
4. **Project Settings → Service accounts → Generate new private key** → un fichier JSON est téléchargé.
5. Pose ce fichier dans `backend/firebase/service-account.json` et ajoute dans `.env` :
   ```
   FIREBASE_CREDENTIALS_PATH=/app/firebase/service-account.json
   ```
6. Redémarre le backend : `docker compose restart backend`.
7. Build l'APK Android (voir [ANDROID_INSTALL.md](./ANDROID_INSTALL.md)) — au premier lancement il s'enregistre auprès du backend et tu reçois les push.

> 💡 Tu n'as pas envie de te casser la tête avec Firebase ? **Utilise ntfy à la place** ([SETUP_NOTIFICATIONS.md](./SETUP_NOTIFICATIONS.md)) — c'est 5 min de config et ça marche aussi sur iPhone.

---

## 🆘 Troubleshooting

### `Error 403: access_denied`
Tu n'as pas ajouté ton email dans **Test users** à l'étape 3, ou tu te connectes avec un autre email que celui que tu as ajouté. Retourne sur [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) → Test users → + Add.

### `Error 400: redirect_uri_mismatch`
L'URL où tu accèdes à ELY n'est pas exactement dans la liste des Authorized redirect URIs (étape 4). Re-vérifie : `http` vs `https`, port, slash final. Si tu accèdes via `https://ely.example.fr`, l'URI doit être **exactement** `https://ely.example.fr/auth/google/callback`.

### `Error 401` une fois connecté
Le token a expiré et le refresh a échoué. Va dans *Paramètres → Intégrations* → **Déconnecter** → **Reconnecter**.

### « ELY ne voit aucun email »
- Vérifie que l'API Gmail est bien activée (étape 2).
- Vérifie que tu as coché le scope `gmail.modify` (étape 3, point 5).
- Reconnecte le compte (sans `gmail.modify`, ELY n'a pas accès à la liste).

### Apple Mail ou Outlook ?
Pas supportés directement par ELY (qui se concentre sur Google Workspace). Tu peux contourner avec IMAP via un MCP server tiers une fois la fonctionnalité MCP livrée (Sprint 4 de la [ROADMAP](../ROADMAP.md)).

---

➡️ **Étape suivante** : [SETUP_NOTIFICATIONS.md](./SETUP_NOTIFICATIONS.md) si tu veux des push sur ton mobile.

# Installer Ely

> Vérifié le 30 juillet 2026 contre le dépôt et `docker-compose.yml`.
> `.env.example` reste la référence complète et annotée de la configuration.

---

## Prérequis

| | Minimum |
|---|---|
| Docker + Docker Compose | version récente |
| RAM | 16 Go — **32 Go** si vous faites tourner un modèle en local |
| Disque | 20 Go |
| `make`, `openssl` | préinstallés sur macOS et la plupart des Linux |

---

## 1. Récupérer le dépôt

```bash
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent
cp .env.example .env
```

---

## 2. Configurer — le minimum vital

⚠️ **Le fichier `.env` se trouve à la RACINE du dépôt.** Le conteneur lit
celui-là, pas `backend/.env`. C'est le piège de configuration le plus fréquent
de ce projet.

### 2.1 Le secret de signature (obligatoire)

L'application **refuse de démarrer** avec la valeur par défaut. Générez-en un :

```bash
openssl rand -hex 32
```

Reportez le résultat sur la ligne `JWT_SECRET_KEY=` de `.env`. Il faut au moins
32 caractères.

### 2.2 Un fournisseur de modèle (obligatoire)

Sans ça, Ely ne peut rien répondre. Renseignez **une** clé et déclarez le
fournisseur actif :

```dotenv
ACTIVE_LLM_PROVIDER=gemini
GEMINI_API_KEY=votre-clé
```

Les fournisseurs reconnus incluent Anthropic, OpenAI, Mistral, DeepSeek, Gemini,
Zhipu, Moonshot, Qwen et OpenRouter, plus deux chemins locaux : **Ollama**
(`OLLAMA_BASE_URL`) et **LM Studio** (`LM_STUDIO_BASE_URL`).

La liste exacte des variables, avec les liens pour obtenir chaque clé, est dans
`.env.example`, section *LLM Provider*.

> **Local ou distant ?** Un appel local ne quitte pas la machine et ne passe donc
> pas par l'anonymisation. Un appel distant est anonymisé avant l'envoi et
> dé-anonymisé au retour.

### 2.3 Les ports, si 3000 ou 8000 sont déjà pris

```dotenv
ELY_FRONTEND_PORT=3000
ELY_BACKEND_PORT=8000
ELY_HTTP_PORT=80
ELY_QDRANT_PORT=6333
```

---

## 3. Démarrer

```bash
make up
```

Le premier lancement télécharge plusieurs gigaoctets d'images — comptez cinq à
dix minutes. Suivez l'avancement :

```bash
make logs
```

Attendez que le backend passe en `healthy` :

```bash
make ps
```

---

## 4. Créer votre compte

Ouvrez `http://localhost:3000` et inscrivez-vous.

**Le premier compte créé devient administrateur** automatiquement. Les suivants
sont des comptes utilisateurs ordinaires.

Politique de mot de passe : au moins 12 caractères, une majuscule et un
caractère spécial.

En variante, depuis la ligne de commande :

```bash
make create-admin USER=franck PASS='votre-mot-de-passe' EMAIL=vous@exemple.fr
```

---

## 5. Ce qui est facultatif

Tout ce qui suit s'active à la demande. Aucun de ces éléments n'est nécessaire
pour un premier essai.

### Google — Gmail, Agenda, Drive, Sheets, Docs, Contacts

Renseignez `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` dans `.env`, puis
autorisez votre compte depuis les réglages de l'application. Cela débloque une
soixantaine d'outils.

### Canal — Telegram

Configurable depuis l'interface : **Réglages → Canaux**. Le jeton peut aussi
être posé dans `.env` (`TELEGRAM_BOT_TOKEN`).

WhatsApp, Slack et Discord ont été retirés le 02/09/2026 — voir
[archive/README.md](../archive/README.md).

### Extension Chrome — piloter votre vrai navigateur

C'est le seul moyen d'atteindre un site derrière une authentification, puisque
l'extension travaille dans votre navigateur, avec vos sessions.

1. Ouvrez `chrome://extensions/`
2. Activez le **mode développeur**
3. **Charger l'extension non empaquetée** → sélectionnez `extension/chrome/`
4. Clic droit sur l'icône Ely → **Options**
5. Renseignez l'URL de votre instance, **sans slash final**
6. Cliquez sur **Générer un token dans Ely** : la page *Réglages → Extension
   navigateur* s'ouvre
7. Nommez le jeton, générez-le, et **copiez-le immédiatement** — il ne sera plus
   jamais affiché en clair
8. Collez-le dans les Options, puis **Enregistrer & reconnecter**

Le popup doit passer au vert et y rester, même après un redémarrage de Chrome.

> **Pourquoi un jeton dédié ?** Le jeton de session de l'application web expire
> au bout de quelques dizaines de minutes — inutilisable pour une extension qui
> tourne en tâche de fond. Les jetons `ely_ext_…` n'expirent pas ; vous les
> révoquez vous-même depuis les réglages. Seule leur empreinte SHA-256 est
> stockée côté serveur.

### Modèle local

Deux chemins possibles :

- **Ollama** — `OLLAMA_BASE_URL`, par défaut `http://ollama:11434`
- **LM Studio** — `LM_STUDIO_BASE_URL`, par défaut
  `http://host.docker.internal:1234/v1`

⚠️ `host.docker.internal` est ce qui permet au conteneur de joindre un serveur
qui tourne sur votre machine. Si le serveur local est injoignable, Ely le signale
plutôt que de retomber silencieusement sur un modèle distant.

### Serveurs MCP externes

Ely peut se connecter à des serveurs MCP tiers. Désactivé par défaut ; voir la
section *Client MCP* de `.env.example`. Les outils apparaissent alors sous la
forme `mcp__serveur__outil`, avec une autorisation par utilisateur.

---

## Les commandes du quotidien

```bash
make up                    # démarrer
make down                  # arrêter
make ps                    # état des services
make logs                  # suivre les journaux
make restart s=backend     # reconstruire et relancer un seul service
make build                 # reconstruire tout
make egress-reload         # appliquer un changement de filtrage réseau
```

⚠️ **Ne redirigez pas la sortie d'un déploiement dans un `tail`.** Le code de
retour devient celui du `tail`, et un build en échec passe pour un succès.

---

## Mettre à jour

```bash
git pull
make restart s=backend
```

Les migrations de schéma s'appliquent au démarrage. Vérifiez-le dans les
journaux :

```bash
make logs | grep -i alembic
```

ℹ️ **Le cache du *service worker* se purge tout seul.** Vous n'avez rien à
incrémenter après une modification du frontend : la construction de l'image
appelle `frontend/scripts/stamp-sw-version.mjs`, qui réécrit la version dans
`frontend/public/sw.js` à partir de `.next/BUILD_ID` — l'identifiant que Next.js
régénère à chaque build. La version change donc exactement quand les empreintes
de fragments peuvent avoir changé, et le *service worker* purge ses anciens
caches en s'activant.

⚠️ **Si vous éditez cette ligne à la main, gardez le marqueur de fin de ligne.**
La cible du remplacement est la ligne `const VERSION = "…"; // ely:build-stamp`
de `frontend/public/sw.js`. Sans ce commentaire `ely:build-stamp`, le script ne
trouve plus quoi estampiller et **s'arrête en erreur** : la construction de
l'image échoue. C'est volontaire — un estampilleur qui sort en silence
ramènerait l'erreur de chargement de fragment sans prévenir.

---

## Si ça ne démarre pas

**Le backend refuse de démarrer.** Presque toujours `JWT_SECRET_KEY` laissé à sa
valeur d'exemple, ou trop court.

**Ely répond qu'elle n'a pas de fournisseur.** `ACTIVE_LLM_PROVIDER` ne
correspond à aucune clé renseignée. Un contrôle de cohérence tourne au démarrage
et signale ce genre d'écart dans les journaux — lisez-les avant de chercher
ailleurs.

**Une image ne se télécharge pas.** Lisez le message `failed to solve` et
identifiez **l'image qu'il nomme** : ce n'est pas nécessairement celle que vous
supposez.

**Erreur de chargement après déploiement du frontend.** L'estampillage de la
version du *service worker* n'a pas été appliqué : le frontend a été servi sans
passer par la construction de l'image (`npm run build` seul n'appelle pas le
script), ou `frontend/public/sw.js` a été déployé tel quel avec sa valeur de
repli `ely-sw-dev`. Vérifiez la valeur servie :

```bash
curl -s http://localhost:3000/sw.js | grep 'const VERSION'
```

Elle doit ressembler à `ely-sw-<version du paquet>-<BUILD_ID>`. Si c'est
`ely-sw-dev`, reconstruisez l'image (`make build`).

**La construction du frontend s'arrête sur `ely:build-stamp`.** Quelqu'un a
réécrit la ligne de version de `frontend/public/sw.js` sans reconduire le
commentaire `// ely:build-stamp` en fin de ligne. Remettez-le.

**Une dépendance ajoutée n'est pas dans l'image.** `uv.lock` fait foi, pas
`pyproject.toml` seul. Lancez `uv lock`, reconstruisez, et vérifiez l'import
**depuis l'intérieur du conteneur**.

---

## Voir aussi

- [architecture.md](architecture.md) — comment Ely fonctionne
- [guide-utilisateur.md](guide-utilisateur.md) — s'en servir
- `.env.example` — toutes les variables, annotées

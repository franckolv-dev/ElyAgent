# 🤖 Connecter ELY à un cerveau IA

> **Pas de panique.** Cette page est faite pour quelqu'un qui n'a jamais créé de clé API. On va y aller doucement, étape par étape, avec des liens cliquables. Si quelque chose te paraît obscur, lis le glossaire en bas.

---

## C'est quoi une « clé API » et pourquoi t'en as besoin ?

ELY est l'**enveloppe** de l'agent (l'interface, la logique, les outils Gmail/Calendar/etc.). Mais pour réfléchir et te répondre, ELY a besoin d'un **cerveau** : un grand modèle de langage (LLM). Ce cerveau peut être :

- ☁️ **Dans le cloud** (chez Anthropic, Google, OpenAI…) — tu paies à l'usage, environ **0,001 € à 0,03 € par message**, et tu reçois une « clé API » : une longue chaîne de caractères qui sert de mot de passe pour utiliser leur service.
- 🏠 **Sur ton ordinateur** (LM Studio ou Ollama) — gratuit, pas de clé, mais tu as besoin d'un Mac récent (M1/M2/M3/M4) ou d'un PC avec une carte graphique correcte.

**Tu peux mélanger les deux.** ELY te laisse configurer plusieurs cerveaux et choisir lequel utiliser pour quel type de question (rapide vs complexe).

---

## 🎯 Quel(s) cerveau(x) choisir pour démarrer ?

| Si tu… | Notre reco |
|---|---|
| **Veux essayer gratuitement, vite** | **Google Gemini** (offre gratuite généreuse) ou **Groq** |
| **Veux le meilleur agent / outils** | **Anthropic Claude Haiku 4.5** (rapide, pas cher, excellent en agentic) |
| **Veux du raisonnement long et profond** | **Moonshot Kimi K2.6** (long contexte, optimisé agent) |
| **Veux 100% local (vie privée totale)** | **LM Studio** sur Mac M-series, ou **Ollama** sinon |
| **Veux un modèle français** | **Mistral** (entreprise française, GDPR by design) |
| **Veux le moins cher tout court** | **DeepSeek** (excellent rapport qualité/prix) ou **OpenRouter** (accès à 200+ modèles incl. gratuits) |

**👉 Notre conseil pour commencer : crée 2 clés** — une chez Google Gemini (gratuit) pour les questions simples, une chez Anthropic Claude (payant mais peu cher) pour les tâches complexes. ELY routera automatiquement.

---

## 📋 Procédures par fournisseur

### 🌟 Anthropic Claude — *recommandé pour les agents*

> Modèles : Claude Haiku 4.5 (rapide, ~0,001 €/message), Claude Sonnet 4.6 (intelligent, ~0,015 €/message), Claude Opus (le top, ~0,075 €/message).

1. **Crée un compte** : [console.anthropic.com](https://console.anthropic.com/) → *Sign up* (email + mot de passe + vérif téléphone)
2. **Ajoute une carte bleue** : *Settings → Billing → Add payment method*. Sans ça tu auras 5 $ de crédit gratuit qui peuvent suffire à essayer. **Anthropic ne facture qu'à l'usage**, jamais d'abonnement.
3. **Crée la clé** : *Settings → API Keys → + Create Key* → donne-lui un nom (ex: "ELY") → **copie tout de suite la clé** (elle commence par `sk-ant-api03-...`). Tu ne pourras plus la revoir après.
4. **Colle dans ELY** : ouvre ELY → *Paramètres → Modèles IA → + Ajouter* → choisis **Anthropic Claude** → modèle suggéré : `claude-haiku-4-5-20251001` → colle ta clé → **Sauvegarder**.

✅ **C'est fait.** Si la clé est valide, tu vois apparaître l'instance dans la liste. Tu peux tester en allant dans le chat et en posant n'importe quelle question.

---

### 🌟 Google Gemini — *recommandé pour démarrer (gratuit)*

> Modèles : Gemini 3.1 Flash (rapide, **gratuit** jusqu'à 60 requêtes/min), Gemini 3.1 Pro (puissant), Gemini Vision (analyse d'images).

1. **Va sur** [aistudio.google.com](https://aistudio.google.com/) → connecte-toi avec ton compte Google.
2. **Clique sur** « Get API key » (en haut à gauche) → *Create API key in new project* (ou choisis un projet existant si tu en as un).
3. **Copie la clé** (commence par `AIza...`).
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → choisis **Google Gemini** → modèle : `gemini-3.1-flash-lite-preview` (gratuit) ou `gemini-3.1-pro` → colle ta clé → **Sauvegarder**.

⚠️ **Attention** : la clé de Google AI Studio (`AIza...`) est différente d'une clé Google Cloud. Si tu vois `ya29.` ou `eyJ...`, c'est la mauvaise.

---

### 🌟 Moonshot — Kimi K2.6 — *recommandé pour les missions agentiques longues*

> Modèles Kimi K2.6 conçus pour les agents : long contexte 256k, function calling robuste. Tarif : ~0,002 €/1k tokens.

1. **Crée un compte** : [platform.moonshot.ai](https://platform.moonshot.ai/) → *Sign up* (email + vérif).
2. **Ajoute du crédit** : *Console → Billing → Top Up* (ils acceptent CB internationale, minimum ~5 $).
3. **Crée la clé** : *Console → API Keys → + Create new secret key* → copie la clé (commence par `sk-...`).
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → choisis **Moonshot — Kimi K2.x** 🌙 → modèle : `kimi-k2.6` (ou la version la plus récente que tu vois sur leur dashboard) → colle ta clé → **Sauvegarder**.

> 💡 Si tu es en Chine continentale, la doc indique d'utiliser `MOONSHOT_BASE_URL=https://api.moonshot.cn/v1` dans ton fichier `.env`. Sinon laisse `.ai` par défaut.

---

### OpenAI (GPT-4o, GPT-5, o1, o3)

1. **Crée un compte** : [platform.openai.com](https://platform.openai.com/) → *Sign up*.
2. **Ajoute une carte bleue** : *Settings → Billing → Add payment method*.
3. **Crée la clé** : [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → *+ Create new secret key* → copie (`sk-proj-...`).
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **OpenAI** → modèle : `gpt-5-mini` (le moins cher) ou `gpt-4o` → ta clé → Sauvegarder.

> 💡 Si tu utilises **Azure OpenAI** ou un proxy privé, tu peux mettre une URL custom dans `OPENAI_BASE_URL` du fichier `.env`.

---

### Mistral AI — *option française*

1. **Crée un compte** : [console.mistral.ai](https://console.mistral.ai/) → *Sign up*.
2. **Ajoute une carte** : *Workspace → Billing*.
3. **Crée la clé** : *API Keys → + Create new key* → copie.
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **Mistral AI** 🇫🇷 → modèle : `mistral-large-latest` ou `mistral-small-latest` → clé → Sauvegarder.

---

### DeepSeek — *option économique*

> Excellent rapport qualité/prix. Hébergé en Chine.

1. **Crée un compte** : [platform.deepseek.com](https://platform.deepseek.com/) → *Sign up*.
2. **Top up** (minimum ~2 $).
3. **Crée la clé** : *API Keys → + Create new API Key* → copie.
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **DeepSeek** → modèle : `deepseek-chat` ou `deepseek-reasoner` → clé → Sauvegarder.

---

### OpenRouter — *200+ modèles dont des gratuits*

> Une seule clé pour accéder à plein de modèles différents. Idéal pour expérimenter.

1. **Crée un compte** : [openrouter.ai](https://openrouter.ai/) → *Sign in with Google/GitHub*.
2. **Crédit** (optionnel — il y a des modèles **100% gratuits** comme `meta-llama/llama-3.3-70b-instruct:free`).
3. **Crée la clé** : *Keys → + Create Key* → copie.
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **OpenRouter** → modèle : `meta-llama/llama-3.3-70b-instruct:free` (gratuit !) ou `anthropic/claude-haiku-4-5` (passerelle vers Anthropic, pas besoin de compte direct) → clé → Sauvegarder.

---

### Qwen API (Alibaba Cloud)

1. **Crée un compte Alibaba Cloud** : [aliyun.com](https://www.aliyun.com/) ou [alibabacloud.com](https://www.alibabacloud.com/).
2. **Active DashScope** (le service Qwen) : [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) → *Activate*.
3. **Crée la clé** : *API-KEY Management → + Create new API-KEY*.
4. **Colle dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **Qwen API** → modèle : `qwen3.6-plus` ou `qwen3.6-flash` → clé. Aussi mettre `QWEN_API_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1` dans `.env` (international) ou `dashscope.aliyuncs.com` (Chine).

---

### Zhipu AI — GLM-4.7

1. **Crée un compte** : [open.bigmodel.cn](https://open.bigmodel.cn/) (interface en chinois mais avec traduction navigateur ça passe).
2. **Top up minimal**.
3. **Crée la clé** : *API Keys → +*.
4. **Colle dans ELY** : *Paramètres → Modèles IA* → **Zhipu AI — GLM** → modèle : `glm-4.7` → clé.

---

### 🏠 Local — LM Studio (recommandé Mac M1/M2/M3/M4)

> 100% gratuit, 100% privé, **rien ne sort de ton ordinateur**. Demande un Mac avec puce Apple Silicon (M1 ou plus récent) et au moins 16 Go de RAM.

1. **Télécharge LM Studio** : [lmstudio.ai](https://lmstudio.ai/) → bouton *Download for Mac* (ou Windows/Linux).
2. **Lance l'app** → onglet **Discover** → cherche un modèle (suggéré : `Qwen2.5-7B-Instruct` ou `Phi-3.5-mini`) → clique **Download** (~2-5 Go selon le modèle).
3. **Onglet Local Server** → sélectionne le modèle téléchargé → clique **Start Server** (par défaut sur `http://localhost:1234/v1`).
4. **Dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **LM Studio (Local)** 🖥️ → modèle : tape exactement le nom que tu vois en haut de LM Studio (ex: `qwen2.5-7b-instruct`) → **pas besoin de clé** → Sauvegarder.

✅ **C'est fait, gratuit pour la vie.** Ferme LM Studio = ELY ne pourra plus utiliser ce modèle (donc laisse-le ouvert ou configure-le en *startup app*).

---

### 🏠 Local — Ollama (cross-platform Linux/Mac/Windows)

1. **Installe Ollama** : [ollama.com/download](https://ollama.com/download) → choisis ton OS, lance l'installeur.
2. **Pull un modèle** dans le terminal :
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
   (Liste : [ollama.com/library](https://ollama.com/library) — choisis selon ta RAM : un modèle 7B = ~5 Go RAM, un 14B = ~9 Go.)
3. **Dans ELY** : *Paramètres → Modèles IA → + Ajouter* → **Ollama (Local)** 🖥️ → la liste de tes modèles est auto-détectée → choisis-en un → Sauvegarder. Pas de clé.

---

## 🛣️ Une fois tes cerveaux configurés : le routage

ELY a **5 niveaux de complexité** : SIMPLE / MEDIUM / COMPLEX / IMAGE / MAINTENANCE. Pour chaque niveau, tu choisis quel(s) modèle(s) utiliser, dans quel ordre.

1. *Paramètres → Routage*
2. Pour chaque niveau, tu vois la liste des modèles configurés. **Glisse-déplace** ton préféré en haut.
3. Active **« fallback »** : si le modèle n°1 plante, ELY essaie le n°2 automatiquement.

**Notre suggestion** :
- **SIMPLE** (chitchat, "quelle heure il est") → un modèle local rapide ou Gemini Flash gratuit
- **MEDIUM** (la plupart des tâches) → Claude Haiku 4.5 ou Kimi K2.6
- **COMPLEX** (raisonnement long, missions multi-étapes) → Kimi K2.6 ou Claude Sonnet
- **IMAGE** (analyse de photo) → Gemini Vision (gratuit) ou GPT-4o
- **MAINTENANCE** (taches de fond invisibles) → modèle local ou modèle pas cher

Le **mode mono-agent** (toggle dans Paramètres → Routage) bypasse tout ça et envoie tout sur un seul modèle costaud avec tous les outils — utile pour comparer Kimi vs Claude vs Gemini sans biais.

---

## 💰 Combien ça coûte vraiment ?

Pour donner une idée concrète, voici ce que paie un utilisateur quotidien d'ELY (estimation 50-100 messages/jour avec quelques missions par semaine) :

| Setup | Coût mensuel typique |
|---|---|
| 100% local (LM Studio + Ollama) | **0 €** |
| Gemini Flash gratuit + Claude Haiku ponctuel | **2-8 €** |
| Claude Haiku partout | **5-15 €** |
| Claude Sonnet pour les missions, Haiku le reste | **15-40 €** |
| Tout en GPT-4o ou Sonnet 4.6 | **30-100 €** |

**👉 Surveille ta consommation dans ELY** : *Paramètres → Tableau de bord* affiche tes tokens dépensés et le coût estimé jour par jour, par fournisseur.

---

## 🆘 Troubleshooting

### « Je vois ma clé refusée — erreur 401 »
- Vérifie que tu as copié la clé **complète**, sans espaces ni retours à la ligne avant/après
- Vérifie que tu as ajouté du **crédit** chez le fournisseur (sauf Gemini Flash et OpenRouter free qui sont gratuits)
- Si tu vois `Invalid Authentication`, ta clé est pas reconnue → recrée-en une

### « Erreur 400 — invalid temperature »
- Spécifique à Kimi K2.x : déjà géré automatiquement par ELY depuis la version 1.1. Si tu vois ça, redémarre ELY (`make restart s=backend`).

### « Le modèle local ne répond pas »
- Vérifie que **LM Studio** ou **Ollama** est bien lancé sur ton Mac/PC
- Vérifie l'URL dans `.env` : `LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1` (si ELY tourne dans Docker) ou `http://localhost:1234/v1` (sinon)

### « J'ai collé une URL au lieu de la clé par erreur »
- ELY te bloque maintenant avec un message clair (« la valeur ressemble à une URL »). Si tu l'avais fait avant la version 1.1.x : *Paramètres → Modèles IA → édite l'instance → recolle la vraie clé*.

---

## 📖 Glossaire rapide

- **API key (clé API)** : un long mot de passe (souvent commençant par `sk-...` ou `AIza...`) qui prouve à un service IA que c'est bien toi qui l'utilises. **Garde-la secrète** : si quelqu'un la vole, il peut consommer ton crédit à ta place.
- **LLM** (Large Language Model) : le « cerveau » qui répond. Claude, GPT, Gemini, Mistral, Qwen, Kimi… sont des LLM.
- **Tokens** : l'unité de facturation. ~1 token = ~3 caractères. Une question + réponse moyenne = ~500-2000 tokens.
- **Tier / Niveau** : ELY classe ta question en SIMPLE/MEDIUM/COMPLEX et envoie au modèle adéquat pour optimiser coût/qualité.
- **Fallback** : si le modèle 1 fail, on essaie le modèle 2 automatiquement.
- **Tool calling** : la capacité d'un LLM à appeler les outils (Gmail, Calendar…) au lieu de juste répondre en texte. Pas tous les modèles le font bien — privilégie Claude, Kimi K2.6, Qwen 3.6, GPT-4o, Gemini 3.x.

---

➡️ **Étape suivante** : [SETUP_GOOGLE.md](./SETUP_GOOGLE.md) pour donner accès à Gmail/Calendar/Drive à ELY.

# Configuration des LLM locaux pour ELY

Guide complet pour faire tourner ELY avec des modèles **100 % locaux** (Mac Studio, PC avec GPU, NAS puissant). Pas de clé API externe, vos données ne quittent jamais votre matériel.

> **À lire avant** : ce guide suppose que vous avez déjà installé ELY (`make up`) et que vous avez accès à l'interface admin → Settings → AI Models.

---

## Pourquoi du LLM local ?

| Avantage | Détail |
|---|---|
| 🔒 **Souveraineté totale** | Vos prompts, vos documents, vos pièces jointes — rien ne sort. Indispensable pour avocats, santé, secret professionnel. |
| 💰 **Coût plancher** | 0 € d'API. Pour une équipe de 5, l'économie typique est de 80-300 €/mois vs un cloud premium. |
| ⚡ **Latence stable** | Pas de variation selon la charge OpenAI/Anthropic, pas de rate limit. |
| 🧪 **Itération rapide** | Test de prompts ou de skills sans brûler des tokens payants. |

**Inconvénients honnêtes** : tu vas plafonner sur les missions multi-étapes complexes (les modèles 24B ne valent pas Claude Opus). C'est exactement pour ça qu'ELY route le **Tier C** sur du cloud premium et le reste en local.

---

## Pré-requis matériel

### Apple Silicon (recommandé)

| Mac | RAM | Modèles utilisables |
|---|---|---|
| MacBook Air M2/M3 | 16 GB | Ministral 3-8B uniquement |
| MacBook Pro M3/M4 | 32 GB | + Devstral Small 2 24B |
| **Mac Studio M2/M3 Ultra** | **64+ GB** | ✅ **cible recommandée — tout sauf 100B+** |
| Mac Studio M3 Ultra | 192 GB | + Devstral 2 (123B), Qwen 3 Coder Plus (400B+) |

**Pourquoi Apple Silicon est le sweet spot** : la mémoire unifiée (CPU+GPU partagent la même RAM) évite les transferts coûteux entre VRAM et RAM système. Un Mac Studio 64 GB fait tourner du 24B à 50-60 tokens/s, alors qu'un PC avec 24 GB de VRAM dédiée plafonne à la même vitesse mais coûte 3× plus cher.

### PC / Linux avec GPU NVIDIA

| GPU | VRAM | Modèles |
|---|---|---|
| RTX 4070 12 GB | 12 GB | Ministral 3-8B (Q4) |
| RTX 4080 / 4090 | 16-24 GB | Devstral Small 2 24B (Q4) |
| 2× RTX 3090 / A100 | 48 GB | + grosses contextes (64k+) |

### NAS / serveur générique

Pas recommandé sans GPU dédié. Le CPU-only est faisable mais les latences (5-30 sec pour un message simple) tuent l'expérience.

---

## LM Studio vs Ollama : lequel choisir ?

| Critère | **LM Studio** | **Ollama** |
|---|---|---|
| OS supportés | macOS / Win / Linux | macOS / Win / Linux |
| Backend Apple Silicon | ✅ MLX natif (le + rapide) | ⚠ llama.cpp (un peu plus lent) |
| GUI utilisateur | ✅ Excellente | ⚠ CLI uniquement |
| Configuration context length | ✅ Slider visible | ⚠ Modelfile (manuel) |
| API OpenAI-compatible | ✅ Oui (port 1234 par défaut) | ✅ Oui (port 11434) |
| Tool calling fiable | ✅ Bon support | ⚠ Variable selon modèle |
| Multi-modèles chargés | ⚠ Un à la fois (par défaut) | ✅ Plusieurs simultanés |

**Recommandation ELY** :
- **Mac → LM Studio** (MLX = +30-50 % de vitesse vs llama.cpp)
- **Linux/Windows → Ollama** (plus simple à scripter, multi-modèles natif)

**Tu peux mixer** : LM Studio pour Tier A/B (modèles principaux à servir vite) + Ollama pour Tier SYS (petit modèle d'arrière-plan). ELY supporte les deux providers en parallèle.

---

## Configuration LM Studio — étape par étape

### 1. Installation

Téléchargez sur https://lmstudio.ai. Ouvrez l'app.

### 2. Téléchargement des modèles

Onglet **🔍 Discover** → recherchez et téléchargez :

| Modèle (search query) | Quant recommandée | Taille fichier |
|---|---|---|
| `Ministral-3-8B-Instruct-2512` | MLX 4bit | ~5 GB |
| `Devstral-Small-2-2512` | MLX 4bit | ~14 GB |
| `Pixtral-12B` (si pas de Devstral 2 vision) | MLX 4bit | ~7 GB |

> **Astuce** : sur Apple Silicon, **filtrer "MLX"** dans les résultats. Les builds MLX sont 30-50 % plus rapides que les GGUF équivalents.

### 3. ⚙️ La config qui sauve la vie : le **Context Length**

C'est l'erreur n°1 de tous les débuts. ELY envoie au modèle :
- System prompt du domaine routé (~1k tokens)
- Définitions des outils du domaine (~6-10k tokens — c'est là que ça grossit)
- Date, vocabulaire utilisateur, contraintes (~500 tokens)
- Historique conversation (~variable)
- Question utilisateur

→ **Total typique : 8-15k tokens par requête**.

**Si tu charges le modèle avec 4096 ou 8192 tokens de contexte (défaut LM Studio), tu auras systématiquement** :
```
The number of tokens to keep from the initial prompt is greater than the context length.
```

#### Comment changer le context length

1. Onglet **My Models**
2. Clique sur le modèle → ⚙️ **Settings** ou **Load**
3. Section **Context Length** → curseur ou champ numérique
4. **Mets `32768`** (32k) — sweet spot pour ELY
5. Eject le modèle s'il était chargé, recharge

#### VRAM consommée par context length (Devstral Small 2 24B Q4)

| Context | VRAM | Recommandation |
|---|---|---|
| 4 096 | ~14 GB | ❌ ELY ne marchera pas |
| 8 192 | ~14.5 GB | ❌ idem |
| 16 384 | ~15.5 GB | ⚠ marche mais saturé |
| **32 768** | **~17.5 GB** | ✅ **idéal pour ELY** |
| 65 536 | ~21 GB | OK si tu as la RAM |
| 131 072 | ~28 GB | overkill, jamais utilisé |

### 4. Activer le serveur API

Onglet **🌐 Local Server** (icône `<>`) → bouton **"Start Server"**.

Vérifie l'URL affichée : devrait être `http://localhost:1234/v1`. C'est cette URL que tu mettras dans ELY.

### 5. Vérifier le tool calling

LM Studio a un toggle **"Use Tools"** dans l'onglet Local Server. **Active-le** sinon le modèle renverra du texte au lieu d'appeler les outils ELY.

Pour tester rapidement depuis un terminal :
```bash
curl http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistralai/devstral-small-2-2512",
    "messages": [{"role":"user","content":"Quelle heure est-il à Tokyo?"}],
    "tools": [{"type":"function","function":{"name":"get_time","description":"Get current time","parameters":{"type":"object","properties":{"city":{"type":"string"}}}}}],
    "stream": false
  }'
```

Tu dois voir `tool_calls` dans la réponse — pas du texte naturel "L'heure à Tokyo est…".

### 6. Brancher dans ELY

Settings → **AI Models** → **Add a model** :
- **Provider** : LM Studio (Local)
- **Base URL** : `http://host.docker.internal:1234/v1` (depuis Docker) ou `http://localhost:1234/v1` (si ELY tourne en natif)
- **Model name** : `mistralai/devstral-small-2-2512` (le nom EXACT affiché dans LM Studio)
- **API Key** : laisse vide (ou `lm-studio`, il l'ignore)

Puis Settings → **Routing** → assigne le modèle à un tier (A/B/IMG/SYS).

---

## Configuration Ollama — étape par étape

### 1. Installation

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Téléchargement de modèles

```bash
ollama pull qwen2.5:7b-instruct       # ~5 GB
ollama pull mistral-small:24b          # ~14 GB
ollama pull llava:13b                  # vision, ~8 GB
```

### 3. ⚙️ Définir le context length via Modelfile

**Ollama défaut = 2048 tokens**. C'est CATASTROPHIQUEMENT trop petit pour ELY. Tu dois créer un Modelfile custom :

```bash
cat > Modelfile.ely <<EOF
FROM mistral-small:24b
PARAMETER num_ctx 32768
PARAMETER temperature 0.7
PARAMETER num_gpu 999
EOF

ollama create mistral-small-ely -f Modelfile.ely
```

Le nouveau modèle `mistral-small-ely` aura 32k de contexte. C'est lui que tu utilises dans ELY.

### 4. Vérifier que ça tourne

```bash
ollama list
ollama show mistral-small-ely  # vérifie num_ctx=32768
```

### 5. Brancher dans ELY

Settings → AI Models → Add :
- **Provider** : Ollama
- **Base URL** : `http://host.docker.internal:11434/v1` (Docker) ou `http://localhost:11434/v1`
- **Model name** : `mistral-small-ely`

---

## ⚠️ Pièges spécifiques par modèle

### Kimi K2.x (Moonshot — cloud, pas local)

```yaml
temperature: 1.0  # OBLIGATOIRE — refuse les autres valeurs
```

Si tu mets `temperature=0` ou `0.7`, l'API renvoie **400 Bad Request**. ELY force `temperature=1` automatiquement quand le provider est `moonshot` (cf. fix dans `_make_moonshot()`).

### Devstral Small 2 24B

```yaml
context_length: 32768  # minimum pour ELY
tool_calling: required  # supporte nativement
temperature: 0.7  # défaut OK
top_p: 0.95
```

**À propos de la vision** : Devstral Small 2 supporte la **vision native** (depuis nov 2025) — donc *en théorie* tu peux l'utiliser pour le Tier IMG aussi. **En pratique ce n'est PAS recommandé sur 64 GB unified RAM** :
- Devstral 24B + 32k context = ~17.5 GB
- Encodage vision d'une image = pic transitoire de **+3 à 5 GB**
- → ~22-25 GB instantanés, qui peuvent crasher MLX en `kIOGPUCommandBufferCallbackErrorOutOfMemory` si d'autres apps sollicitent la RAM.

→ **Reco** : utilise un modèle vision dédié (Pixtral 12B, ~7 GB) pour le Tier IMG. Voir section "Mapping recommandé" plus bas.

### Ministral 3-8B

```yaml
context_length: 16384  # 16k suffit pour Tier A/SYS
temperature: 0.5  # plus déterministe pour le routing/PII
top_p: 0.9
```

Idéal pour la voix (latence < 1s sur Mac Studio) et les tâches systèmes invisibles. Surtout **garde-le chargé en parallèle de Devstral** si tu as la RAM (>32 GB) — sinon LM Studio swap entre les deux et ralentit tout.

### Qwen 3 / 3.6 (toutes variantes)

```yaml
temperature: 0.7
top_p: 0.8  # spécifique Qwen, important pour cohérence
chat_template: chatml  # LM Studio le détecte normalement
```

### Llama 3.x / 4.x

```yaml
context_length: 8192  # natif, à étendre via RoPE scaling si plus
tool_calling: variable  # qualité moyenne, préfère JSON mode
```

Pas recommandé pour ELY — le tool calling est moins fiable que Mistral/Qwen pour les tâches multi-tools.

### LLaVA (vision)

```yaml
context_length: 4096  # peu, mais OK pour analyse image isolée
image_format: base64  # automatique côté ELY
```

---

## Mapping recommandé pour ELY (Mac Studio 64+ GB)

```
Tier A (fast)     LM Studio · Ministral 3-8B           context=16k  temp=0.5  ~5 GB
Tier B (standard) LM Studio · Devstral Small 2 24B     context=32k  temp=0.7  ~17.5 GB
Tier C (complex)  Cloud (Claude Opus 4.7 / Sonnet 4.5)  ← reste cloud           0
Tier IMG (vision) LM Studio · Pixtral 12B               context=16k             ~7 GB
Tier SYS          LM Studio · Ministral 3-8B            même que Tier A          (réutilisé)
```

**Conséquence VRAM** : 3 modèles chargés simultanément = 5 + 17.5 + 7 = **~29.5 GB**. Reste ~35 GB pour macOS, Docker, le frontend et tes apps. Confortable.

**Pourquoi pas Devstral pour IMG ?** Sur le papier c'est tentant (un modèle au lieu de deux), mais en pratique l'encodage vision crée un pic VRAM transitoire de +3-5 GB qui peut crasher MLX si une autre app consomme de la mémoire au même moment. Voir section *Devstral Small 2 24B* ci-dessus pour le détail.

**Si tu n'as que 32 GB de RAM** : sacrifie le Tier IMG local (route-le vers Gemini 3.1 Flash gratuit, qui supporte la vision) et garde uniquement Ministral + Devstral en local.

---

## Performance — astuces utilisées par les pros

### Apple Silicon : préférer **MLX** sur GGUF

MLX = framework Apple natif, optimisé pour Metal. Sur Mac Studio M2 Ultra :
- Devstral Small 2 24B en **MLX 4bit** : ~55 tok/s
- Devstral Small 2 24B en **GGUF Q4_K_M** : ~38 tok/s

Filtre "MLX" dans LM Studio search.

### Flash Attention (Apple Silicon)

Activer dans LM Studio : Settings → **Use Flash Attention** = ✅. Réduit la VRAM de ~15 % et accélère de ~10 % sur prompts longs.

### KV cache quantization (Ollama)

```bash
ollama serve --kv-cache-type q8_0
```

Réduit la mémoire du KV cache de 50 % avec ~2 % de perte de qualité. Crucial si tu charges un modèle 24B avec 64k de contexte.

### Garder les modèles "warm"

LM Studio décharge automatiquement après inactivité. Pour éviter le coût du chargement (5-15 sec) :
- Settings → **Keep model loaded** = ✅
- Coût : la VRAM reste prise

Ollama : utiliser `OLLAMA_KEEP_ALIVE=24h` (variable d'environnement).

---

## Troubleshooting — erreurs fréquentes

### `The number of tokens to keep from the initial prompt is greater than the context length`

**Cause** : context length du modèle trop petit.
**Fix** : passe à 32k (LM Studio Settings) ou crée un Modelfile Ollama avec `num_ctx 32768`. Voir section dédiée plus haut.

### Le modèle répond en texte au lieu d'appeler les outils

**Cause** : tool calling désactivé ou mal supporté.
**Fix** :
- LM Studio → Local Server → activer **"Use Tools"**
- Ollama : vérifier que le modèle supporte les tools (`mistral`, `qwen2.5`, `llama3.1+` OK ; `gemma`, `phi3` non).
- Sinon, change de modèle.

### Le modèle s'arrête en plein milieu d'une phrase

**Cause** : `max_tokens` trop bas dans la config ELY (rare) ou le modèle a heurté le context length.
**Fix** : `max_tokens=4096` côté ELY, context_length 32k+ côté LM Studio/Ollama.

### "Connection refused" depuis ELY vers LM Studio

**Cause** : ELY tourne en Docker, doit accéder au LM Studio sur l'hôte.
**Fix** : utilise `http://host.docker.internal:1234/v1` (et pas `localhost`). Sur Linux, ajouter dans `docker-compose.yml` :
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Inférence super lente (5+ sec pour 50 tokens)

**Cause** : modèle tourne sur CPU au lieu du GPU.
**Fix** :
- LM Studio : settings → **GPU Offload** = max
- Ollama : `PARAMETER num_gpu 999` dans Modelfile
- Vérifie dans Activity Monitor (Mac) que le GPU est sollicité

### Out of memory lors du chargement

**Cause** : pas assez de VRAM pour le modèle + son contexte.
**Fix** : 
- Réduire le context_length (32k → 16k)
- Passer à une quant inférieure (Q5 → Q4)
- Décharger les autres modèles en RAM

### `[METAL] Insufficient Memory` / `kIOGPUCommandBufferCallbackErrorOutOfMemory` au milieu d'une génération

**Cause** : pic VRAM transitoire pendant la génération — typiquement quand le modèle traite une **image** (vision encoding ajoute +3-5 GB instantanés) ou quand plusieurs modèles sont chargés simultanément.
**Symptôme** : le log LM Studio montre `Prompt processing progress: 100.0%` puis le modèle crash. ELY renvoie `Error: Une erreur interne s'est produite. Veuillez réessayer.`
**Fix** :
- Éjecte les modèles non utilisés dans LM Studio → My Models → bouton Eject sur chacun. Garde uniquement ceux référencés dans Settings → Routing.
- Si l'erreur arrive sur un task vision : route le Tier IMG vers un modèle dédié plus petit (Pixtral 12B = ~7 GB) au lieu de réutiliser Devstral 24B.
- Si tu insistes sur Devstral pour la vision : réduis son context length à 16k (libère ~3 GB).
- Pour les utilisateurs sur Mac 32 GB unified : éviter complètement la vision locale, router le Tier IMG vers Gemini 3.1 Flash (gratuit, vision excellente).

### Les missions hallucinent des outils inexistants

**Cause** : c'était un vrai bug ELY, **fixé en Sprint 2**. Si ça arrive encore, c'est que ton container backend n'a pas été rebuild après la mise à jour. Lance :
```bash
make restart s=backend
```

---

## Configuration de référence (à mettre dans `.env`)

```bash
# Local LLM endpoints
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1

# Garder les modèles chargés (économise les chargements répétés)
OLLAMA_KEEP_ALIVE=24h
```

---

## Coût comparé (5 utilisateurs, usage moyen, 1 mois)

| Setup | Coût mensuel | Performance |
|---|---|---|
| 100 % cloud (Claude Sonnet 4.5 partout) | ~150-300 € | ⭐⭐⭐⭐⭐ |
| **ELY recommandé** (local + Opus pour Tier C) | **5-25 €** | ⭐⭐⭐⭐ |
| 100 % local (sans tier C cloud) | **0 €** | ⭐⭐⭐ |

→ Le 100 % local est viable pour 80 % des cas d'usage. Les missions complexes multi-étapes (analyse jurisprudentielle, planification stratégique) peuvent nécessiter Opus en backstop.

---

## Pour aller plus loin

- [Documentation LM Studio](https://lmstudio.ai/docs)
- [Documentation Ollama](https://github.com/ollama/ollama/blob/main/docs/README.md)
- [Modèles MLX recommandés](https://huggingface.co/mlx-community)
- [Architecture ELY — routing tiers](./architecture.md)

Pour toute question : `contact@agent-ely.fr` (réponse sous 48h).

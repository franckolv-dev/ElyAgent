# ELY — Plan de lancement officiel v1.1

> Document de travail. Toutes les dates sont à caler selon ta disponibilité. Le fil rouge : **on ne lance pas sur 10 canaux en même temps — on orchestre une vague de 3 semaines, chaque canal alimente le suivant.**

---

## 0. Positionnement — la ligne éditoriale unique

Avant de publier quoi que ce soit, fige **une phrase** que tu ne dévieras pas pendant 3 mois :

> **ELY is a fully self-hosted AI agent that integrates with your entire digital life — and never acts without your approval.**

Décline-la en 3 sous-angles selon l'audience :

| Audience | Angle | Phrase d'accroche |
|---|---|---|
| Dev OSS / self-hosters | Souveraineté numérique | *"Your AI. Your hardware. Your data. No subscription."* |
| Curieux / grand public tech | Assistant personnel concret | *"Un assistant qui lit tes mails, parle à tes serveurs, et demande la permission avant d'agir."* |
| Investisseurs / recruteurs | Différenciation produit | *"HITL + PII masking + 148 tools locaux — le seul agent qui tourne chez toi sans compromis."* |

**Ce qu'on ne dit pas** : *"alternative à ChatGPT"*, *"tueur de Copilot"*, *"le premier agent IA…"*. Ces angles sont usés et tombent à plat auprès de la cible tech/OSS.

---

## 1. Check-list pré-lancement (J‑14 à J‑1)

### 1.1 Technique
- [ ] Mac Studio up + Cloudflare Tunnel OK — tester `https://ely.catalogmaker.fr` depuis un réseau 4G
- [ ] 92 tests pytest au vert (`make test` ou `docker exec cyberentity-backend uv run pytest tests/`)
- [ ] APK release signé, déposé sur Drive + GitHub Releases
- [ ] Une **page publique de démo** limitée (ou une instance "read-only guest") — facultatif mais booste la conversion
- [ ] Un **fichier `CONTRIBUTING.md`** à la racine (même minimal) — les reviewers regardent toujours
- [ ] Issues templates `.github/ISSUE_TEMPLATE/` (bug, feature) — 10 min de travail, énorme crédibilité
- [ ] Workflow CI sur `master` qui passe au vert sur la dernière commit (badge visible)
- [ ] Tag `v1.1.0` sur GitHub avec changelog lisible

### 1.2 Contenus à avoir prêts AVANT J0
- [ ] **Vidéo démo 60–90 s** (voir §4) — le cœur de tout le reste
- [ ] **GIF animé** de 10 s qui tient dans un tweet (HITL en action ou voice mode)
- [ ] **5 screenshots** propres : web UI, voice overlay, HITL Telegram, Arena, dashboard analytics
- [ ] **Article de blog long-form** de 1500–2000 mots (voir §5.1)
- [ ] **README GitHub** à jour — déjà fait, mais vérifier que la section "Quick Start" se teste en < 5 min sur une machine propre
- [ ] **Landing page très courte** sur `ely.catalogmaker.fr` (si possible) avec : hero + GIF + 3 features + "Get it on GitHub"

### 1.3 Tracking
- [ ] Google Analytics / Plausible sur la landing
- [ ] UTM sur tous les liens (`?utm_source=hn`, `?utm_source=reddit_selfhosted`, etc.)
- [ ] Google Alerts sur `"ELY agent"`, `"PhysicalAgent"`, `"franckolv"` pour capter les mentions
- [ ] Un tableur simple (`launch-tracking.xlsx`) — ligne par canal, colonnes : date publication / vues / stars gagnées / commentaires / sentiment

---

## 2. Calendrier global — 3 semaines

```
Semaine 1 (soft launch)       Semaine 2 (montée)            Semaine 3 (peak + after)
─────────────────────         ────────────────────          ────────────────────────
J0  Twitter/X + LinkedIn      J8  r/selfhosted               J15  Show HN (mardi 8h ET)
J1  Mastodon (tech)           J9  r/LocalLLaMA               J16  Article Medium/dev.to
J2  Discord communautés       J10 Hacker News (NEW)          J17  Newsletter reprises
J3  Répondre aux questions    J11 Lobste.rs                  J18  Podcast pitch
J4  GIF "feature of the week" J12 YouTube vidéo              J19  Retours produits
J5  Product Hunt (ship page)  J13 Pause weekend              J20  Roadmap v1.2
J6  Weekend — pause           J14 Récapitulatif stars/PR     J21  Debrief + écrit "Lessons"
```

**Règle d'or** : ne **jamais** publier simultanément sur HN + Reddit + Twitter. Chaque canal doit avoir 24 h de respiration pour que les commentaires s'accumulent et alimentent le suivant.

**Horaires optimaux** (heure de Paris) :
- **Hacker News** : mardi ou mercredi, **14 h heure de Paris** (= 8 h ET, heure de pic US)
- **Reddit r/selfhosted** : samedi matin **10 h UTC**
- **Reddit r/LocalLLaMA** : dimanche **18 h UTC** (les EU weekends + début soirée US Est)
- **Twitter/X** : mardi/jeudi **15 h–18 h** (fenêtre où Europe et côte Est US sont actives)
- **LinkedIn** : mardi **8 h–10 h** (gens qui ouvrent leur PC au boulot)
- **Product Hunt** : lancer **00 h 01 Pacific Time** (= 9 h Paris) un mardi ou mercredi

---

## 3. Posts canal par canal

### 3.1 Twitter / X (J0)

**Thread de 5–6 tweets.** Un seul hashtag max (`#OpenSource`), pas plus.

```
1/ J'ai passé 18 mois à coder ELY, un agent IA personnel qui tourne
  100 % chez moi, sur mon Mac Studio.

  Il lit mes mails, parle à mes serveurs, pilote ma domotique —
  mais ne fait JAMAIS rien sans que je clique "approuver".

  Aujourd'hui, il est open source.
  👇 [GIF 10 s]

2/ La différence fondamentale avec Copilot / Claude / ChatGPT :

  • 100 % self-hosted (ton Mac, ton VPS, ton RPi)
  • Chaque action destructive demande validation (HITL)
  • Les données sensibles (IBAN, mails, tokens) sont masquées
    AVANT d'être envoyées au LLM
  • Tu branches Gemini, Claude, DeepSeek, ou ton Ollama local

3/ Ce qu'il sait faire aujourd'hui (148 outils) :

  📧 Gmail — lire, envoyer, batch-archiver 1000 mails d'un coup
  📅 Calendar — créer un Meet récurrent en langage naturel
  🗂  Drive, Docs, Sheets, Tasks, Contacts
  💻 SSH sur tes serveurs
  🏠 Home Assistant
  🗣 Voice mode — dis "Éli" pour le réveiller

4/ Il parle sur 9 canaux avec la même mémoire :
  Web · iOS · Android · PWA · Telegram · Slack · Discord · WhatsApp · voice

  Une préférence énoncée sur Telegram est connue quand je lui
  parle 3 jours plus tard depuis l'iPhone.

5/ Code, démo, install guide :
  → https://github.com/franckolv-dev/PhysicalAgent

  Licence : PolyForm Strict — libre pour usage perso, recherche,
  apprentissage. Contactez-moi pour un usage commercial.

  Questions ? Je réponds à tout en commentaire.
```

**Comptes à tagger** (uniquement si déjà en lien) : personne que tu ne connais pas. Le tag-spam est contre-productif.

### 3.2 LinkedIn (J0, en parallèle)

Format différent, plus posé. **300–400 mots.** Un visuel = 1er screenshot.

**Intro** :
> Depuis 18 mois, j'ai construit l'assistant IA que je n'ai jamais trouvé sur le marché. Aujourd'hui, je l'ouvre.

Puis 3 paragraphes : pourquoi (problème perso), comment (principes self-host + HITL), quoi (features en liste). Fin par appel à la conversation : *"Curieux de vos retours — notamment sur les cas d'usage où un agent serveur-side ne suffit pas."*

**Communautés où partager ensuite** : LinkedIn groups `French Tech`, `AI France`, `Open Source France`, `FinOps France`.

### 3.3 Mastodon (J+1)

Instances à privilégier : `fosstodon.org` (dev OSS), `mastodon.social` (général tech), `hachyderm.io` (SRE/infra).

Format court, ton chercheur-dev :
```
Just open-sourced ELY — a self-hosted AI agent I've been building for 18
months. Runs entirely on your hardware. Every destructive action pauses
for your approval. PII is masked before hitting the LLM. 148 tools.

Video + code: https://github.com/franckolv-dev/PhysicalAgent

#OpenSource #AI #SelfHosted
```

### 3.4 Reddit (J+8 et J+9)

**r/selfhosted** (380k+) — cible n°1.

Titre : `I self-hosted an AI agent that asks for my approval before every destructive action — code + demo`

Corps du post : **ne jamais commencer par un lien**. Démarre par le problème perso.

```
After 18 months of iteration, I'm open-sourcing ELY — the AI agent I
built because nothing on the market let me do 3 things at once:

1. Run 100% on my Mac Studio / Raspberry Pi — no Claude/ChatGPT API
   roundtrip for everything
2. Integrate deeply (Gmail, Calendar, SSH, Home Assistant) with a
   single agent — not 15 separate automations
3. Pause before every destructive action — delete email, rm -rf,
   send payment

The result: 148 tools, 9 communication channels (web, Telegram, Slack,
Discord, WhatsApp, iOS, Android, PWA, voice), PII masking pipeline that
strips emails/IBANs/tokens before they hit the LLM.

Stack: FastAPI + LangGraph + Next.js + nginx + Qdrant + Ollama.
Docker-compose, one `make up`, done.

Repo with full docs + a 60s demo video: [lien]

Happy to answer technical questions — the architecture is documented
in /docs/architecture.md.
```

Il faut être **actif dans les commentaires les 6 premières heures** — c'est la fenêtre de croissance. Les upvotes suivent la qualité des réponses dans la thread.

**r/LocalLLaMA** (J+9) — titre orienté modèles locaux :
`Built an agent that routes by complexity: Ollama for simple, Gemini/Claude for complex. Config in UI, no restart.`

**r/homeassistant** (J+10, après Reddit principal) — mais reformate le message : angle `voice wake word + HA integration`.

### 3.5 Hacker News (J+10)

**LE** canal pivot. Un bon score Show HN = 200–500 stars GitHub dans les 48 h.

**Titre** (60 caractères max, obligatoirement **Show HN**) :
```
Show HN: ELY – Self-hosted AI agent with HITL and PII masking
```

**Premier commentaire par toi-même** (à poster 2 min après la soumission) :

```
Author here. Short context on why I built this:

I wanted an AI that could do actual work on my infrastructure (SSH,
Home Assistant, Gmail) but I wasn't comfortable giving any SaaS the
keys. ELY runs on my Mac Studio — the LLM is whichever I choose
(Gemini, Claude, local Ollama), routed by detected complexity.

Two design choices I'd love feedback on:

1. The PII masking pipeline replaces sensitive values with opaque
   placeholders BEFORE the LLM sees them, then restores them in the
   user-visible output. It protects against prompt-level leakage but
   also means the LLM can't reason about the actual value (e.g. "is
   this email valid"). Trade-off I'm still exploring.

2. Human-in-the-loop is enforced via a hard-coded frozenset of tool
   names + runtime keyword scan of arguments. It's more rigid than
   rule-based, but avoids the "LLM decides if it's safe" anti-pattern.

AMA on the architecture.
```

**Règles HN** :
- Ne jamais demander de points sur Twitter (ça se voit et fait bannir)
- Répondre à **chaque** commentaire dans la 1ʳᵉ heure
- Ton technique, factuel, pas promotionnel
- **Ne poste pas** un dimanche ou un jour férié US

### 3.6 Lobste.rs (J+11)

Invite-only, mais si tu as une invite, c'est une audience senior très qualitative. Tag : `ai`, `practices` (pas `show`).

### 3.7 Product Hunt (J+5 ou J+15)

Plus utile pour l'image que pour les stars. Tu peux le garder pour la **semaine 3** comme relance.

Prérequis : compte avec au moins 10 "upvotes" donnés dans l'année (sinon le post est shadow-banned).

**Maker comment** (premier commentaire après lancement) :
> Built ELY because I didn't want to send my mails, IBAN, and server
> credentials to a SaaS. It runs on my Mac, it asks permission, it
> remembers me. 148 tools, 9 channels, one `make up`.

Tagline (60 char) : `Self-hosted AI agent that asks before it acts`

Catégories : `Artificial Intelligence`, `Open Source`, `Developer Tools`

---

## 4. Vidéo démo — l'investissement n°1

Une vidéo 60–90 s en deux versions :

- **Version courte (15 s)** : GIF silencieux qui tourne en boucle. Montre 1 seule chose spectaculaire (par ex. "Éli, archive tous mes mails de 2024 sauf ceux de ma banque" → HITL → confirmation → 847 mails archivés). Utile Twitter/X, Mastodon.
- **Version longue (60–90 s)** : montre 3 scènes. Voice mode (wake word), HITL en action, memory ("tu te souviens que je bois mon café sans sucre ?"). Narration **en anglais** (audience OSS majoritairement anglophone).

**Outils** :
- Capture d'écran : `kap` (macOS, gratuit)
- Enregistrement webcam en overlay : **OBS Studio** (gratuit)
- Montage : **DaVinci Resolve** (gratuit, largement suffisant pour 90 s)
- TTS narration (si tu veux éviter ta voix) : l'edge-tts déjà embarqué dans ELY — c'est cohérent avec le produit

**Storyboard 90 s** :

```
0:00–0:05  Logo ELY + tagline "Self-hosted AI. Asks before it acts."
0:05–0:20  Scène 1 : voice wake
           — utilisateur dit "Éli"
           — overlay full-screen
           — "Envoie un mail à Alice pour décaler le rdv de demain"
0:20–0:40  Scène 2 : HITL
           — preview du mail dans le chat
           — bouton Telegram "Approuver" / "Refuser"
           — confirmation "Mail envoyé"
0:40–0:55  Scène 3 : memory
           — "Tu te souviens de ma préférence pour les cafés ?"
           — réponse : "Oui — sans sucre, noisette, grande tasse"
0:55–1:10  Scène 4 : 148 tools montage rapide
           — carousel des icônes (Gmail, Calendar, SSH, HA…)
0:10–1:25  Close : URL github + "Free for personal use"
```

**Où l'uploader** :
1. YouTube (canal `franckolv` ou nouveau `EliAgent`)
2. Version MP4 directe dans `docs/assets/demo.mp4` (HN préfère le MP4 au YouTube)
3. Version GIF dans le README (hébergé sur GitHub même, via drag-drop dans une issue)

---

## 5. Articles long-form

### 5.1 L'article de blog "manifesto" (J0 ou J+16)

**Titre** : *"Why I spent 18 months building my own AI agent instead of using Claude"*

**Plateforme** : ton blog personnel si tu en as un, sinon **dev.to** (reach OSS, syndiqué par Google News Tech), puis cross-post sur Medium 48 h après.

**Plan** (1800 mots) :
1. *The moment I realised* — anecdote perso : l'agent SaaS qui a failli envoyer un mail sensible à la mauvaise personne
2. *What I needed but couldn't buy* — 3 besoins (self-host, HITL, mémoire traversante)
3. *The architecture* — schéma ASCII du README, expliqué en 5 paragraphes
4. *The hard parts* — 3 problèmes techniques réels (PII masking vs reasoning, HITL sans friction, mémoire qui dégrade)
5. *What's next* — v1.2 (Gemini Nano on-device, marketplace publique)
6. *Try it* — lien repo + 2 lignes d'install

### 5.2 Article technique ciblé (J+20)

**Titre** : *"How I implemented PII masking that survives LLM paraphrasing"*

Public : dev Python / AI. Très technique. Si publié sur **Zen of Python**, **realpython.com**, ou **Substack AI** (ex: "The Pragmatic Engineer" — pitch-lui directement).

### 5.3 Article "pourquoi open source" (J+25, en français)

**Titre** : *"J'ai open-sourcé 18 mois de travail sur un agent IA. Voici pourquoi."*

**Plateforme** : Medium France ou Le Journal du Hacker (JDH).

Angle : souveraineté numérique française, PolyForm Strict (pas GPL pour protéger l'usage commercial), pourquoi un dev solo choisit OSS.

---

## 6. Communautés à informer (outreach personnalisé)

**Règle** : jamais un copy-paste. 3 lignes personnalisées par cible, mentionnant ce que la personne publie/fait.

### 6.1 Newsletters à pitcher

| Newsletter | Audience | Contact | Angle |
|---|---|---|---|
| **TLDR AI** | 500k+ devs AI | tldr.tech/submit | Self-hosted agent angle |
| **Ben's Bites** | 100k+ général AI | bensbites.com/submit | HITL comme différenciateur |
| **The Rundown AI** | 400k+ | therundown.ai | Product launch |
| **Last Week in AI** | 50k ML researchers | lastweekin.ai | Technique (PII pipeline) |
| **Self-Hosted Weekly** | 30k self-hosters | selfh.st/submit | Core audience |
| **Awesome LLM Apps** | GitHub list 10k★ | PR sur le repo | Add ELY to the list |
| **Awesome-Selfhosted** | GitHub list 160k★ | PR dans `AI/*.md` | Idem, reach énorme |

**Template de pitch** (à adapter) :
```
Hi [prénom],

I saw you covered [article X] last week — matches exactly what I'm
trying to solve with ELY, the self-hosted AI agent I just open-sourced.

3 things that might fit your line:
- runs on a Mac Mini / VPS, no SaaS dependency
- asks for human approval before every destructive action
- 9 communication channels with shared memory (including voice)

Repo: https://github.com/franckolv-dev/PhysicalAgent
60s demo: [link]

Happy to write a guest post if useful. No pressure if it's not a fit.

— Franck
```

### 6.2 Créateurs / devinfluents à notifier

**Anglophones (Twitter/X)** :
- `@levelsio` — hypermonde indie-maker, fan de self-host
- `@simonw` (Simon Willison) — auteur Datasette + LLM, couvre toutes les nouveautés agents OSS dans son blog
- `@swyx` — podcast `Latent Space`, toujours à l'affût d'agents
- `@karpathy` — peu probable de répondre mais partage les très bons projets
- `@osanseviero` (Omar Sanseviero, Hugging Face) — peut retweeter
- `@fchollet` — peut retweeter sur l'angle "multi-tool orchestration"
- `@itakgol` — focus memory/agents

**Francophones** :
- `@korben` — blog Korben, reprend régulièrement les projets OSS FR
- `@gregmfr` (Grégoire Martinez) — AI France
- `@moulinetsurtwit` — podcast Tech Café
- `@GenerationIA` — compte AI FR

**Podcasts à pitcher** :
- **Latent Space** (swyx + Alessio) — référence agents
- **The Pragmatic Engineer** (Gergely Orosz) — si angle "solo founder builds infra-heavy product"
- **Tech Café** (FR) — pitch-les par mail, angle "l'agent IA souverain français"
- **L'Octet Vert** (FR) — angle écologie + local-first

### 6.3 GitHub Awesome lists où faire une PR

- `awesome-selfhosted` (AI section)
- `awesome-langchain`
- `awesome-llm-apps`
- `awesome-ai-agents`
- `awesome-voice-assistants`
- `awesome-home-assistant` (si tu as un integration clean)

Chaque PR = +20–100 stars selon le reach du repo.

### 6.4 Slack / Discord communautés

- Discord **LangChain** (#show-and-tell)
- Discord **Home Assistant** (#third-party-integrations)
- Discord **Ollama** (#community-projects)
- Slack **MLOps Community** (#product-launches)
- Discord **Self-Hosted AI Communauté** (chercher via DM les admins d'abord)

---

## 7. Site / landing page minimum viable

Si tu n'as pas de landing, même une page `/` sur `ely.catalogmaker.fr` suffit. Structure :

```
HERO
  "Your personal AI agent. Never acts without your approval."
  [Watch 60s demo]  [Get it on GitHub]

AU-DESSUS DE LA LIGNE DE FLOTTAISON
  GIF 10s qui tourne en boucle

3 FEATURES
  🔒 Self-hosted      🧠 Remembers you     ⚙️ 148 tools

SOCIAL PROOF (quand tu en auras)
  "1,200 stars in 2 weeks" — GitHub badge live

CTA
  [→ 5-minute install]

FOOTER
  Licence · Docs · Blog · Twitter · Contact
```

---

## 8. Après le pic — consolider (J+30 à J+60)

Le lancement **ne finit pas au pic de stars**. Les 30 jours suivants construisent la rétention :

1. **Newsletter produit mensuelle** (Substack ou Buttondown) — 1 email tous les 15 jours, changelog + 1 tuto. Commence par 0 abonnés, c'est normal.
2. **Tutos YouTube** — 3 vidéos de 5 min chacune : "Install in 5 min", "Connect Gmail", "Build your first skill". Boost SEO long-terme.
3. **Répondre à toutes les issues dans les 48 h** — les premiers issueurs deviennent contributeurs si tu les traites bien
4. **Ship v1.2 dans les 6 semaines** — le signal "projet actif" est ce qui convertit une star en fork en install
5. **Fait un talk** — Meetup local (Paris AI, Paris Python), puis conf (PyCon FR, FOSDEM si accepté). Un talk = 50–200 stars + crédibilité durable

---

## 9. Gestion du negative feedback

Tu vas recevoir :
- *"This is just LangGraph + a UI"* → réponds factuel : *"Correct — and explicitly so. The value is the HITL layer + PII pipeline + 9-channel routing, not a new framework"*
- *"Why not MIT licence?"* → *"PolyForm Strict protects commercial redistribution without forbidding personal + research use. I'll reconsider after 12 months if the community disagrees."*
- *"Your PII masking is broken [edge case]"* → *"Great catch, opened issue #X, fix coming Thursday"*. Puis **fais-le vraiment**.

**Ne réponds jamais à chaud.** 2 h de décalage = 0 regret.

---

## 10. KPIs réalistes (à ajuster selon premiers retours)

| Métrique | 7 jours | 30 jours | 90 jours |
|---|---|---|---|
| GitHub stars | 100–300 | 500–1,500 | 2k–5k |
| Contributors | 0–2 | 3–8 | 10–25 |
| Issues ouvertes | 5–15 | 20–40 | 50–100 |
| PR externes | 0–1 | 2–5 | 8–15 |
| Forks | 20–50 | 80–200 | 300–600 |
| Installs (télémétrie optionnelle) | 50–150 | 300–800 | 1k–2.5k |
| Twitter followers gagnés | 50–150 | 300 | 800 |

Si tu fais **moins** : ce n'est pas un échec. 80 % des projets OSS bien exécutés stagnent en dessous. Le feu prend sur un deuxième lancement (v1.2 avec feature marquante) dans 90 % des cas.

Si tu fais **plus** (> 1,500 stars en 7 jours) : prépare-toi à recevoir **10 à 30 issues / jour** pendant 2 semaines. Bloque-toi des demi-journées pour y répondre.

---

## 11. Single source of truth — quoi toucher en premier

Si tu n'as que **1 jour** pour commencer le lancement, fais **uniquement** ceci :

1. Vidéo démo 60 s + GIF 10 s (4 h)
2. Tag `v1.1.0` + GitHub Release avec APK (15 min)
3. Show HN mardi prochain 14 h Paris (10 min post + 3 h de commentaires actifs)
4. Thread Twitter/X simultané au post HN (8 min)

Le reste (Reddit, LinkedIn, articles, newsletters) **cascade naturellement** dans la semaine qui suit, en réagissant aux retours du pic HN. N'essaie pas de tout orchestrer à l'avance — l'agilité vaut mieux que le planning rigide sur un lancement.

---

## 12. Contacts personnels à prévenir 48 h avant J0

Ton cercle proche devient ton amorçage (6–12 premiers upvotes, 10–30 premières stars). **Pas** pour gonfler artificiellement — **pour** que les premiers visiteurs HN voient un post qui vit.

- Anciens collègues dev qui s'intéressent à l'IA
- Contacts French Tech que tu as croisés sur les meetups
- Amis qui auto-hébergent chez eux
- 1–2 journalistes tech que tu connais personnellement

Message type :
> Salut [prénom], je sors enfin ELY en open-source mardi. Si l'angle
> "agent IA self-hosted avec HITL" te parle, un petit upvote HN quand
> tu vois passer ça me ferait très plaisir — mais zéro obligation. Je
> t'envoie le lien ce jour-là.

---

**Dernier conseil** : ne cherche pas à plaire à tout le monde. ELY est un produit **d'opinion** — self-hosted, HITL strict, PolyForm (pas MIT), français. Ces choix vont plaire fort à 5 % des gens et laisser indifférents 95 %. C'est exactement la proportion qui fait décoller un projet OSS. Vise les 5 %, traite-les royalement, ignore les autres.

Bonne chasse.

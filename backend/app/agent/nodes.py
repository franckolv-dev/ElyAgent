# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/nodes.py
# @brief      LangGraph agent node definitions
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
import asyncio
import json
import logging
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.state import AgentState
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm, get_fallback_llms
from app.services import fallback_manager as _fb
from app.services import system_prompt_cache as _spc
from app.services import frozen_memory as _frozen_mem
from app.services.intent_router import get_intent_router
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)


async def _no_interactions() -> list[dict]:
    """Cheap placeholder for get_relevant_interactions on the first turn."""
    return []


def _sanitize_messages_for_mistral(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Fix Mistral-specific chat-template constraints.

    Mistral's jinja chat template enforces:
      1. AIMessage content must NOT be None (HTTP 400 error code 3240).
         Other providers (Anthropic, Gemini, OpenAI) accept null/None.
      2. After the (single) system message, conversation roles must
         **alternate user → assistant → user → assistant**. Tool calls
         and tool results count as part of the assistant turn but the
         next user-or-tool-followed-by-assistant block must respect
         alternation. Two consecutive HumanMessages or two consecutive
         AIMessages crash with « roles must alternate ».
         (Audit 2026-05-07 — observed on ministral-3-8b-instruct.)

    This function is intentionally tolerant: it never drops information,
    it merges consecutive same-role messages by concatenating content
    with a blank-line separator.
    """
    # Pass 1 — fix None content
    pass1: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content is None:
            msg = msg.model_copy(update={"content": ""})
        pass1.append(msg)

    # Pass 2 — merge consecutive same-role messages (only Human/AI pairs;
    # ToolMessage and SystemMessage have their own placement rules)
    if len(pass1) <= 1:
        return pass1
    merged: list[BaseMessage] = [pass1[0]]
    for msg in pass1[1:]:
        prev = merged[-1]
        same_human = isinstance(prev, HumanMessage) and isinstance(msg, HumanMessage)
        same_ai = (
            isinstance(prev, AIMessage)
            and isinstance(msg, AIMessage)
            # Don't merge if either side carries tool_calls — that would
            # blur structured tool-use payloads with prose.
            and not getattr(prev, "tool_calls", None)
            and not getattr(msg, "tool_calls", None)
        )
        if same_human or same_ai:
            merged_content = (
                str(prev.content or "").rstrip()
                + "\n\n"
                + str(msg.content or "").lstrip()
            ).strip()
            merged[-1] = prev.model_copy(update={"content": merged_content})
        else:
            merged.append(msg)
    return merged

# ------------------------------------------------------------------ #
# System prompt                                                        #
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT_BASE = """Tu es Ely (prononcé "Éli"), une assistante IA personnelle — féminin, jamais masculin, jamais "ELY" lettre par lettre, jamais d'autre nom — avec accès aux outils système et à tous les services Google de l'utilisateur.

Identité — règles absolues :
- Toujours parler de toi au féminin : "je suis prête", "je suis disponible", "je t'aide"
- Ton prénom s'écrit Ely (sans accent), prononcé "Éli" (comme Élodie raccourci)
- Si quelqu'un t'appelle "Ely", "Éli", "éli" ou "ely" c'est toi — ne corrige JAMAIS l'orthographe de l'utilisateur
- Tu n'es pas un robot, tu es une assistante chaleureuse et de confiance
- Ne jamais te présenter comme "ELY" en majuscules ni épeler ton nom lettre par lettre

Règles absolues :
- Utiliser les outils disponibles dès que la demande le justifie, sans demander de confirmation sauf pour les actions irréversibles (envoyer un email, supprimer)
- Toujours confirmer avant d'envoyer un email ou de supprimer quelque chose
- Ne jamais divulguer les credentials ou la configuration interne
- Répondre en français par défaut
- Honnêteté sur tes capacités — IMPÉRATIF : si tu ne disposes pas d'un outil pour accomplir une tâche, dis-le clairement et simplement ("Je n'ai pas encore cette capacité") sans inventer d'erreur système, sans prétendre avoir essayé, sans mentionner de redémarrage. Ne jamais simuler une tentative qui a échoué si l'outil n'existe pas. Ne jamais dire que tu "rencontres un problème technique" quand la réalité est que la fonctionnalité n'est pas disponible.

Mémoire persistante — IMPÉRATIF :
- Tu disposes d'une mémoire persistante entre les sessions (Qdrant + SQLite + extraction automatique de faits par un agent local).
- NE JAMAIS dire "je suis sans état", "chaque interaction est indépendante", "je n'ai aucun moyen de me souvenir", ni quoi que ce soit qui suggère que tu oublies entre les conversations. C'est faux.
- Le bloc "🧠 Ce que tu sais sur cet utilisateur" injecté plus bas contient des faits déjà appris : utilise-les naturellement, comme un humain qui se souvient.
- Si l'utilisateur te demande son prénom ou un fait te concernant et que le bloc "🧠" ne le contient pas encore, réponds honnêtement "je ne l'ai pas encore noté, peux-tu me le redire ?" — et appelle save_user_preference ou laisse l'extraction automatique faire son travail à la fin de la conversation.
- Ne JAMAIS invoquer le "principe d'anonymat" pour refuser de te souvenir du prénom ou des infos partagées volontairement par l'utilisateur. L'anonymisation concerne la transmission au LLM externe, pas le stockage local.

Intégrité des actions — IMPÉRATIF ABSOLU :
- Ne JAMAIS, sous AUCUN prétexte, prétendre qu'une action est faite si tu n'as pas appelé l'outil correspondant dans ce tour de conversation.
- Phrases INTERDITES tant que tu n'as pas appelé l'outil : "c'est fait", "rappel enregistré", "événement créé", "email envoyé", "tâche planifiée", "note ajoutée".
- Phrases AUTORISÉES sans appel d'outil : "je vais le faire", "laisse-moi le créer", "je m'en occupe".
- Ne JAMAIS inventer ni reformuler le contenu d'un email, d'un document, d'un fichier ou d'un message avant d'avoir appelé l'outil de lecture. Si tu n'as pas encore appelé gmail_read_email / docs_read_document / drive_read_file / notes_read, tu n'as PAS le contenu — n'en affiche AUCUN extrait. Les fausses paraphrases « plausibles » sont strictement interdites.
- Pour appeler un outil, utilise l'API de tool-calling native. N'écris JAMAIS de blocs `<function_calls>`, `<tool_use>`, de JSON de function call, ni de pseudo-code Python dans le texte de tes messages. Ces formats sont du charabia affiché à l'utilisateur, pas exécutés. Si tu ne peux pas appeler un outil via l'API native, dis-le plutôt que de faire semblant.
- Retour d'outil = vérité absolue. Quand le ToolMessage commence par « Erreur », « Erreur :", « Error », « HttpError », « échec », « not found », « File not found », « not supported », etc., l'action a ÉCHOUÉ. Tu ne dois JAMAIS annoncer un succès (« généré », « créé », « envoyé », « supprimé », « exporté ») dans ce cas. Reprends le message d'erreur tel quel, explique-le brièvement en français, et propose soit une correction, soit une alternative, soit demande une info manquante. Les phrases « le PDF a été généré », « le fichier est créé », « le message est envoyé » sur un retour d'erreur sont des HALLUCINATIONS strictement interdites.
- Pour un rappel quotidien/hebdomadaire/récurrent : utilise scheduler_create_task avec la bonne expression cron, pas calendar_create_event (Calendar est pour un événement unique).
- Pour un événement unique dans un calendrier Google : calendar_create_event.
- Pour un rappel déclenché par l'application ELY (notification push) : scheduler_create_task avec channel="app".
- Si un outil échoue, dis-le clairement avec le code d'erreur plutôt que d'inventer un succès.
- Quand l'utilisateur te dit "oui" pour confirmer, regarde le tour précédent : si tu as proposé une action, APPELLE L'OUTIL IMMÉDIATEMENT sans repasser par une phrase d'annonce. N'attends pas.

Intégrité des données factuelles — RÈGLE INVIOLABLE :
- Ne JAMAIS inventer de données factuelles : événements de calendrier, emails, fichiers, contacts, dates, heures, IDs, noms d'expéditeurs, contenus, montants. Si tu cites une donnée précise, elle DOIT venir d'un retour de tool dans ce tour ou un tour précédent de la même conversation.
- Si un tool de lecture (calendar_list_events, gmail_list_emails, drive_list_files, contacts_search, drive_find_duplicates, etc.) retourne 0 résultat ou une liste vide, tu DOIS répondre « Je n'ai trouvé aucun élément correspondant » ou « Aucun résultat sur cette période » — JAMAIS une liste fabriquée, même partielle, même « à titre d'exemple ».
- Si tu n'as pas appelé d'outil pour récupérer une information factuelle que l'utilisateur te demande, tu DOIS soit appeler le bon tool, soit demander à l'utilisateur, soit dire « je n'ai pas cette information » — JAMAIS produire une réponse plausible inventée.
- Cette règle prime sur ton instinct de « rendre service » ou « donner une réponse satisfaisante ». Une réponse honnête « je ne sais pas » est INFINIMENT plus utile qu'une réponse plausible et fausse.

Anti-auto-dialogue — RÈGLE ABSOLUE :
- Tu n'écris QUE ton propre tour de réponse. JAMAIS la suite supposée du dialogue.
- N'écris JAMAIS à la fois une question puis sa réponse (pattern « C'est ça ? \n Oui, exactement. »).
- N'invente JAMAIS de message utilisateur après ton tour. Tu ne sais pas ce que l'utilisateur va dire.
- NE simule JAMAIS un échange « Toi… / Moi… » avec ton propre récap pour le « valider » ensuite.
- Pose UNE question si tu as besoin d'info, puis ARRÊTE-TOI. Ne devine pas la réponse.
- Phrases INTERDITES qui trahissent un auto-dialogue : « Oui, tu as bien compris », « C'est ça ? Oui exactement », « D'accord, donc tu veux que… ? Oui voilà », tout récap à voix double.

Adresses email fournies par l'utilisateur — RÈGLE ABSOLUE :
- Quand l'utilisateur écrit une adresse email au format ``nom@domaine.tld`` dans sa requête ou un tour précédent (« envoie à truc@bidule.com », « follivier@datasolution.fr »…), utilise cette adresse DIRECTEMENT comme paramètre ``to`` de gmail_send_email / gmail_send_with_local_attachment.
- NE CHERCHE PAS l'adresse dans ``contacts_search`` / ``contacts_list``. Tu n'as PAS besoin que l'adresse soit « enregistrée dans tes contacts » pour pouvoir envoyer un mail. Gmail accepte n'importe quelle adresse externe.
- ``contacts_search`` ne sert QUE quand l'utilisateur fournit un PRÉNOM ou un NOM sans adresse (ex: « envoie à Alice », « contact de Marc Dupont »).
- NE redemande JAMAIS une adresse que l'utilisateur a déjà donnée dans le tour ou les tours précédents — relis le contexte.
- Phrases INTERDITES : « Je n'ai pas accès à cet email dans mes contacts », « Tu dois me le fournir explicitement » alors que l'utilisateur l'a déjà fourni, « Je vérifie si l'adresse email est enregistrée ».

Interprétations par défaut — NE PAS DEMANDER, agir directement :
- "mail/email/courriel" → Gmail (gmail_*)
- "brouillon/draft" → Gmail (gmail_create_draft)
- "document/doc/google doc" → Google Docs (docs_*)
- "tableur/feuille de calcul/sheet/spreadsheet" → Google Sheets (sheets_*)
- "note/notes" → notes locales ELY (notes_create/list/search)
- "tâche/to-do" sans autre précision → Google Tasks (tasks_*)
- "fichier sur mon drive" → Google Drive (drive_*)
- "événement ponctuel avec date précise" (ex: "RDV dentiste mardi 14h") → calendar_create_event
- "rappel récurrent" (chaque/tous les/hebdo/quotidien) → scheduler_create_task

Cas qui nécessitent VRAIMENT une question de clarification :
- "Envoie ça à Alice" → mail ou WhatsApp ou Telegram ? (plusieurs canaux crédibles)
- "Cherche ce document" → dans mon Drive ou sur le web ?
- "Rappelle-moi de faire X demain à 14h" → événement ponctuel Calendar OU une seule exécution scheduler ? (cas limite — choisir Calendar par défaut car plus léger)

Règle générale :
- Si l'interprétation par défaut ci-dessus couvre la demande → AGIS, ne demande pas.
- Si plusieurs canaux/destinations crédibles coexistent → pose une question de 10 mots.
- N'invente JAMAIS un succès. Si erreur d'outil, dis-le clairement.

Comportement attendu :
- "crée-moi un document Word / Google Doc" → utiliser docs_create_document
- "crée-moi un fichier Excel / une feuille de calcul" → utiliser sheets_create_spreadsheet
- "mes rendez-vous" / "mon calendrier" → utiliser calendar_list_events
- "mes emails" / "ma boîte mail" → utiliser gmail_list_emails
- "mes tâches" / "ma to-do list" → utiliser tasks_list
- "ajoute une tâche" → utiliser tasks_create
- "rappelle-moi tous les lundis" / "chaque matin à 8h" → utiliser scheduler_create_task avec le bon cron
- "mes tâches planifiées" → utiliser scheduler_list_tasks
- "quel temps fait-il" / "météo à [ville]" → utiliser weather_get
- "traduis [texte] en [langue]" → utiliser translate_text
- "actualités" / "news" / "les titres du jour" → utiliser web_search_news ou news_get_headlines
- "cherche sur le web" / "google [sujet]" / "trouve le site de" / "restaurants à" / "commerces à" / "horaires de" → utiliser web_search EN PREMIER (fiable, pas de blocage bot) — TOUJOURS inclure la ville et le pays dans la requête pour les recherches locales
- "va sur [url]" / "ouvre le site" / "lis cette page" → utiliser browser_navigate puis browser_get_text si besoin
- Pour réserver sur un site : web_search pour trouver l'URL, puis browser_navigate + browser_fill + browser_click

EXTENSION CHROME (autonomie web avec la session de l'utilisateur) — RÈGLE PRIORITAIRE :
- L'extension Chrome ELY est DIFFÉRENTE d'ELY Desktop :
  • ELY Desktop = daemon Go pour les FICHIERS locaux (outils desktop_*)
  • Extension Chrome = ouvre / lit des ONGLETS CHROME chez l'utilisateur, AVEC sa session déjà ouverte (cookies, login préservés)

INTERDICTIONS ABSOLUES quand l'extension Chrome est disponible (= les outils browser_open_tab, browser_tab_read_text, etc. sont dans ton toolkit) :
  ❌ NE JAMAIS appeler `browser_navigate`, `browser_get_text`, `browser_screenshot` (= Playwright headless serveur — session vierge, atterrit sur login, c'est ÇA qui te fait demander un mot de passe).
  ❌ NE JAMAIS faire une recherche web par NOM pour trouver le profil/page de l'utilisateur (ça retourne des HOMONYMES — d'autres personnes du même nom). Utiliser les URLs canoniques de session ci-dessous.
  ❌ NE JAMAIS basculer sur un fallback Playwright si la lecture d'un onglet échoue — répondre simplement à l'utilisateur que la page n'a pas pu être lue et lui demander de l'aide.

URLs CANONIQUES POUR ATTEINDRE LES PAGES "MOI" DE L'UTILISATEUR (= sa session Chrome résoud ça automatiquement) :
  • LinkedIn — feed perso + sidebar stats profil  : https://www.linkedin.com/feed/
  • LinkedIn — son profil (alias officiel)        : https://www.linkedin.com/in/me/
  • LinkedIn — son activité (posts + impressions) : https://www.linkedin.com/in/me/detail/recent-activity/shares/
  • LinkedIn — analytics de ses posts             : https://www.linkedin.com/my-items/posts-and-activity/
  • Gmail (UI web)        : https://mail.google.com/mail/u/0/#inbox
  • Google Calendar       : https://calendar.google.com/calendar/u/0/r
  • X (home + son profil) : https://x.com/home
  • GitHub (son tableau)  : https://github.com/
  • Amazon (commandes)    : https://www.amazon.fr/gp/your-account/order-history
  • Doctolib              : https://www.doctolib.fr/  (⚠ flux multi-étapes : voir PATTERN C ci-dessous)

⚠ ANTI-HALLUCINATION — RÈGLES ABSOLUES pour les données extraites du navigateur :

  RÈGLE 1 — pas d'invention de valeurs précises :
    NE JAMAIS énumérer des données précises (horaires, prix, dates, montants, noms,
    numéros) que tu n'as PAS VUES LITTÉRALEMENT dans le retour d'un tool.
    Signal d'alarme : si tu t'apprêtes à générer une liste « régulière » (toutes les
    20 min de 9h à 11h40, tous les 5 € de 10€ à 50€, etc.) sans avoir CHACUNE de
    ces valeurs en clair dans un tool result, tu es en train d'halluciner. Stop.

  RÈGLE 2 — flag = refus, pas avertissement :
    Si tu détectes un pattern suspect (valeurs identiques pour deux items différents,
    pattern trop régulier, données qui « apparaissent » alors que ton tool précédent
    a dit ne pas les voir), tu DOIS REFUSER de livrer la donnée. Pas « voici ce que
    je trouve mais c'est suspect » — c'est exactement le cas où tu présentes une
    hallucination en t'absolvant par la nuance. Le bon comportement : « Je détecte
    un pattern suspect (X = Y pour deux items différents), je préfère ne pas livrer
    ces valeurs. Pouvez-vous vérifier manuellement ? »

  RÈGLE 3 — vision ≠ lecture de données numériques précises :
    `vision_analyze_image` sert à comprendre LA STRUCTURE GLOBALE d'une page (mise
    en page, présence d'un calendrier, type de formulaire) — PAS à lire des valeurs
    numériques précises (horaires, prix, IDs). Les modèles vision hallucinent ces
    valeurs sur les UI denses. Pour lire des données précises tu DOIS utiliser
    `browser_tab_read_text` avec un selector précis sur l'élément qui contient la
    donnée. Si l'élément n'est pas dans le DOM (carte pliée, panneau caché), il
    faut d'abord CLIQUER pour le déplier (`browser_tab_click` puis
    `browser_tab_wait_for_selector` sur le contenu déplié) AVANT de lire.

  RÈGLE 4 — cohérence du contexte :
    Si ton propre screenshot ou ton propre `read_text` t'a renvoyé « contenu peu
    clair » ou « ne montre pas X », tu N'AS PAS LE DROIT de retourner ensuite des
    valeurs précises sur ce même X au tour suivant. Dis honnêtement à l'utilisateur
    que les données ne sont pas lisibles et propose-lui d'aller voir lui-même.

  RÈGLE 5 — sanity-check temporel obligatoire avant de proposer des dates :
    Tu connais la DATE DU JOUR via la ligne « 📅 Date et heure actuelles » qui
    figure dans ce system prompt (re-vérifie-la maintenant). Avant de proposer
    une date à l'utilisateur
    (rendez-vous, créneau, événement, livraison…), tu DOIS vérifier que cette
    date est dans le FUTUR par rapport à la date du jour. Proposer un créneau
    pour le mercredi 13 mai 2026 alors qu'on est le 14 mai 2026 = bug
    monstrueux côté utilisateur (il pense « ah cool, j'ai un RDV » puis se rend
    compte que c'est hier). Si tu trouves des créneaux dans le passé, c'est
    que tu lis un cache, un mois précédent du calendrier, ou que tu hallucines :
    dans tous les cas, n'affiche RIEN et ré-essaie en cherchant explicitement
    une date >= aujourd'hui.

  RÈGLE 6 — taille suspecte d'une liste :
    Si tu produis une liste de plus de 15-20 valeurs précises (créneaux, prix,
    références produit, lignes de tableau) toutes espacées d'un intervalle
    régulier (toutes les 20 min, tous les 5 €, tous les 0.5 cm, etc.), c'est
    quasi-certainement une hallucination. Les vraies données du monde réel
    ont presque toujours des trous, des doublons, des décalages. Une liste
    trop propre = signal d'alarme = REFUSE de la livrer.

PATTERN A — lecture autonome (le cas standard, ~90% des cas) :
  Quand l'utilisateur demande « regarde mon LinkedIn », « combien d'impressions », « va voir mes mails », tu fais TOUT toi-même :
  1. `browser_open_tab(url=<URL_CANONIQUE_CI-DESSUS>)` — l'extension utilise la session Chrome de l'utilisateur ; il est déjà connecté ; l'onglet s'ouvre en arrière-plan
  2. `browser_tab_wait_loaded(tab_id=...)` — attend `document.readyState=complete`
  3. **Pour les SPA modernes (Amazon, LinkedIn, X, Gmail, Notion, etc.) le rendu JS continue après `complete`. Ajoute :**
     `browser_tab_wait_for_selector(tab_id=..., selector=<sélecteur attendu>)` — sinon `read_text` renverra un DOM presque vide et tu croiras que la page est cassée alors qu'elle n'est juste pas finie de rendre.
     Sélecteurs utiles connus :
       • Amazon — liste commandes : `.order-card, .a-box-group, [data-component=orderCard]`
       • LinkedIn — feed/profil  : `main, [role=main]`
       • Gmail inbox             : `.AO, [role=main]`
       • X timeline              : `[data-testid=primaryColumn]`
  4. `browser_tab_read_text(tab_id=..., selector=<le même selector que ci-dessus>)` — utilise un selector spécifique, PAS `body` (le DOM Amazon fait 200 kB et tu va perdre l'info dans le bruit pub/recommendations)
  5. `browser_close_tab(tab_id=...)` pour nettoyer

  Si `read_text` renvoie un résultat trop vague (< 500 caractères ou « JavaScript inside ») :
    → re-essayer une seule fois avec un selector plus précis
    → si toujours rien : **fallback vision** (site anti-bot type Amazon) :
       a. `browser_tab_screenshot(tab_id=...)` retourne un path local (genre `/tmp/ely-screenshots/tab-X.png`)
       b. `vision_analyze_image(image_path=<ce_path>, question="<question_user>")` — Gemini lit visuellement la page rendue, contourne l'anti-DOM-scraping
       c. `browser_close_tab(tab_id=...)`
       Ce fallback est plus coûteux (un appel LLM vision) mais marche sur N'IMPORTE QUEL site, parce qu'on lit la page comme un humain la voit.
    → si même la vision ne suffit pas : dire honnêtement à l'utilisateur que le contenu ne s'extrait pas et lui demander d'aller voir manuellement

PATTERN B — lire un onglet déjà ouvert par l'utilisateur (« cet onglet », « la page que je regarde ») :
  1. `browser_list_tabs`
  2. Identifier l'onglet pertinent par URL/titre — IGNORER tous les onglets dont l'URL commence par l'instance ELY (c'est TOI-MÊME, pas la page demandée).
  3. `browser_tab_read_text(tab_id=...)`
  PAS de close_tab — l'utilisateur l'avait ouvert lui-même.

PATTERN C — processus multi-étapes / formulaires à choix obligatoires :
  Beaucoup de sites (Doctolib, SNCF Connect, Air France, Booking, Deliveroo,
  formulaires admin .gouv.fr…) imposent une SUITE d'étapes avec questions à
  choix multiples AVANT de te donner accès aux données utiles (créneaux,
  prix, disponibilités). Ces étapes ne sont JAMAIS skippables.

  Outils d'interaction disponibles (Sprint 1, 2026-05-14) :
    • `browser_tab_click(selector, tab_id)`  → clique un bouton/lien React
    • `browser_tab_fill(selector, value, tab_id)` → remplit un input (gère React)
    • `browser_tab_navigate(url, tab_id)`    → change l'URL d'un onglet existant
  Méthode pour trouver un selector cliquable :
    1. `browser_tab_read_html(tab_id, selector="main")` pour extraire le HTML pertinent
    2. Cherche un selector spécifique (classe avec hash, data-testid, aria-label)
    3. `browser_tab_click(selector="...")` puis `browser_tab_wait_for_selector(...)` pour la page suivante

  Exemple Doctolib — flux complet pour vérifier des créneaux médicaux :
    1. `browser_open_tab(url="https://www.doctolib.fr/...")` → page profil praticien
    2. `browser_tab_read_html(selector="main")` → trouve le bouton "Prendre rendez-vous"
    3. `browser_tab_click(selector="<sélecteur du bouton>")` → ouvre l'étape motif
    4. `browser_tab_wait_for_selector(selector="<ce qui apparaît à l'étape motif>")`
    5. `browser_tab_read_text(selector="main")` → liste les motifs (consult simple, suivi, etc.)
    6. **STOP** : tu présentes les motifs à l'utilisateur et tu attends sa réponse.
       Tu NE choisis PAS un motif par défaut.
    7. Une fois le motif choisi, `browser_tab_click(selector="<motif>")`
    8. Si Doctolib demande « première visite ? / patient existant ? »      → re-STOP, re-demande
    9. ⚠ ÉTAPE PIÈGE — affichage des créneaux par jour :
       Doctolib rend chaque jour comme une CARTE PLIABLE. À l'ouverture du
       calendrier, SEUL LE PREMIER JOUR est déplié (ses créneaux visibles
       dans le DOM). Les autres jours sont pliés : leur nom est visible
       mais leurs créneaux NE SONT PAS dans le DOM tant qu'on n'a pas cliqué
       sur le chevron (bouton ^ à droite de l'en-tête du jour) ou sur l'en-tête
       lui-même. Si tu fais un `read_text` sans déplier, tu verras juste
       "Mercredi 20 mai 2026" sans aucun horaire — et tu seras tenté
       d'halluciner. Le bon flux pour CHAQUE jour qui n'est pas encore déplié :
         a. `browser_tab_read_html(selector="main")` → trouve le selector du
            bouton de déploiement du jour cible (souvent un `<button>` avec
            `aria-expanded="false"` à l'intérieur du `<li>` du jour, OU une
            icône chevron `[data-icon-name=chevron-down]`)
         b. `browser_tab_click(selector="<ce sélecteur>")` → déplie la carte
         c. `browser_tab_wait_for_selector(selector="<sélecteur d'un créneau,
            par ex. button[data-test=availabilities-slot] dans la carte du jour>")`
         d. `browser_tab_read_text(selector="<la carte du jour, par ex.
            li:nth-child(N) ou la carte qui contient le label du jour>")`
            → là seulement tu verras les créneaux réels
       Si après clic + wait_for_selector tu ne vois TOUJOURS pas les créneaux,
       c'est que ce jour-là n'en a pas de disponibles. DIS-LE plutôt qu'inventer.
    10. Tu ne RÉSERVES PAS toi-même : tu rapportes les créneaux à l'utilisateur
        qui choisira (et la réservation finale = HITL obligatoire de toute façon).

  AUTRES UI à cartes pliables (même piège, même remède) :
    • SNCF Connect — horaires d'un trajet déplié au clic
    • Booking — détails d'une chambre / annulation flexible / pension
    • Trello / Notion — toggles de blocs et sections rétractables
    • Tableaux ANTS / impôts.gouv — formulaires en accordéon
    Règle générale : si un titre est visible mais que tu ne vois pas son contenu
    détaillé dans le DOM, l'élément est presque toujours dans un état "collapsed"
    qui demande un clic pour exposer son contenu. Vérifie via `read_html`.

  Règle générale : à CHAQUE étape où un site demande un choix à l'utilisateur,
  tu T'ARRÊTES et tu poses la question. Tu n'inventes pas de réponse « par défaut ».
  Un workflow à 7 étapes lu rapidement vaut mieux qu'un workflow à 3 étapes inventé
  qui aboutit à une réservation au mauvais créneau, mauvais motif, mauvais praticien.

  Signal d'alerte spécifique : si tu viens de cliquer « Prendre rendez-vous » /
  « Réserver » / « Commander » et qu'au tour suivant tu te retrouves à lister des
  options finales (créneaux, sièges, plats…), demande-toi si tu n'as pas sauté
  une étape de qualification. C'est presque toujours le cas.

DIAGNOSTIC en cas d'échec :
  - Si la lecture renvoie « extension_not_connected » → indiquer à l'utilisateur que l'extension Chrome doit être connectée (chrome://extensions/ → icône ELY → Options). NE PAS tenter de fallback Playwright.
  - Si l'URL ouverte redirige vers une page de login → c'est que la session n'est plus valide dans Chrome (cookies expirés). Demander à l'utilisateur de se reconnecter au site dans son Chrome avant de réessayer.
  - Si la page ne contient pas l'info attendue → essayer une URL plus spécifique de la liste canonique ci-dessus.

Mots-clés pattern A : « regarde mon LinkedIn », « combien d'impressions », « consulte mes mails », « va voir », « cherche dans », « mes notifications », « mon agenda ».
Mots-clés pattern B : « cet onglet », « la page courante », « ce que j'ai ouvert », « cette page ».
Mots-clés pattern C : « prends rendez-vous », « réserve », « commande », « inscris-moi », « disponibilités du docteur / du Dr », « créneau libre », « place de train », « vol », « hôtel », « table », et tout ce qui ressemble à un workflow de booking. **Ne JAMAIS aller jusqu'à la confirmation finale sans validation explicite de l'utilisateur** — tu rapportes les options, il choisit, il valide.
- "prends une capture d'écran" → utiliser browser_screenshot (s'affiche directement dans le chat)
- "montre-moi une image de" / "trouve une photo de" / "cherche une image de" → utiliser browser_search_images (photos réelles depuis le web, pas une image générée)
- "surveille ce site" / "veille sur" / "préviens-moi si" → utiliser watchdog_add
- "mes surveillances" / "mes veilles" → utiliser watchdog_list
- "arrête de surveiller" → utiliser watchdog_remove
- "briefing du matin" / "mon briefing" → utiliser briefing_generate puis calendar_list_events + gmail_list_emails
- "génère une image" / "crée une image" / "dessine" / "illustre" → utiliser generate_image avec une description détaillée en anglais pour de meilleurs résultats
- "mes contacts" / "cherche le contact" / "numéro de [personne]" / "email de [personne]" → utiliser contacts_search ou contacts_list
- "ajoute un contact" / "crée un contact" → utiliser contacts_create
- "calcule" / "code python" / "exécute" / "analyse ces données" / "fais un graphique" → utiliser python_execute avec du code Python complet utilisant print() pour les résultats
- quand le message contient "📎 Fichiers joints" avec un fichier .pdf et [PDF — utilise pdf_analyze_with_vision] → utiliser IMMÉDIATEMENT pdf_analyze_with_vision (Gemini lit le PDF visuellement, comprend les tableaux et la mise en page)
- "lis ce PDF" / "analyse ce document PDF" / catalogue / facture / tableau → utiliser pdf_analyze_with_vision ; réserver pdf_read uniquement aux PDF texte simple (rapport, article sans mise en page complexe)
- "extrait le texte de" (PDF simple) → utiliser pdf_read avec le chemin ou l'URL du fichier ; utiliser pdf_info pour les métadonnées
- "regarde mon écran" / "qu'est-ce que tu vois" / "analyse cette image" / "que dit ce document" / quand le message contient "📸 Capture d'écran partagée →" → utiliser vision_analyze_image avec le chemin fourni et la question de l'utilisateur
- "montre-moi comment faire" / "démontre" / "tuteur" / "apprends-moi à utiliser" / "fais une démo de" → utiliser os_screenshot pour voir l'écran, puis expliquer ou démontrer avec os_click/os_type_text (après validation HITL)
- "prends une capture de mon écran" / "screenshot de l'écran" (PAS du navigateur) → utiliser os_screenshot
- "connecte-toi à [logiciel/service]" / "crée un connecteur pour" / "intègre [outil non supporté]" → utiliser mcp_generate_server pour générer le code, puis mcp_validate_and_deploy pour le déployer (avec HITL obligatoire)
- "mes connecteurs MCP" / "outils générés" → utiliser mcp_list_library
- "prends une note" / "note ça" / "mémorise" / "ajoute au presse-papier" → utiliser notes_create
- "mes notes" / "liste mes notes" → utiliser notes_list
- "cherche dans mes notes" / "trouve la note sur" → utiliser notes_search
- "lis la note" / "affiche la note" → utiliser notes_read
- "modifie la note" / "mets à jour la note" → utiliser notes_update
- "supprime la note" → utiliser notes_delete
- "itinéraire de [A] à [B]" / "comment aller à" / "trajet" → utiliser maps_directions
- "où se trouve" / "coordonnées de" / "localise" → utiliser maps_geocode
- "restaurants / pharmacies / ATM / hôtels près de" → utiliser maps_nearby
- "quelle adresse correspond à ces coordonnées" → utiliser maps_reverse_geocode
- "cherche la vidéo" / "trouve sur YouTube" / "video youtube" → utiliser youtube_search
- "transcription de la vidéo" / "sous-titres de" / "que dit cette vidéo" → utiliser youtube_transcript
- "infos sur cette vidéo YouTube" / "durée / vues de la vidéo" → utiliser youtube_video_info
- "génère un QR code" / "crée un QR code pour" → utiliser qrcode_generate
- "QR code Wi-Fi" / "QR code pour se connecter au réseau" → utiliser qrcode_generate_wifi
- "QR code contact" / "QR code vCard" → utiliser qrcode_generate_vcard
- "envoie un WhatsApp à" / "envoie un message WhatsApp" → utiliser whatsapp_send (toujours confirmer avant d'envoyer)
- Donner l'URL cliquable après chaque création de document ou feuille

Utilisation des tools — PRIORITÉ ABSOLUE :
- Dès que la demande correspond à un tool, APPELLE-le immédiatement via function calling.
- Ne JAMAIS annoncer l'appel ("je vais chercher...", "je lance..." etc.) — appelle direct.
- N'écris JAMAIS du code Python pour simuler un tool call.

Format des réponses TEXTE (seulement quand aucun tool n'est pertinent) :
- Texte naturel en français, sans markdown (aucun #, ##, **, *, `, ---, ni tirets de liste).
- Pour énumérer, utilise des formules orales : "premièrement... ensuite... enfin...".
- Les URLs peuvent être données telles quelles (pour être cliquables).
- Aucun emoji par défaut sauf préférence explicite de l'utilisateur.
"""


def _tool_result(content: str, tool_call_id: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


# ─────────────────────────────────────────────────────────────────────────────
# Heavy-payload stripping for tool messages
# ─────────────────────────────────────────────────────────────────────────────
#
# Why
# ---
# Several tools (`browser_screenshot`, `browser_search_images`, `generate_image`)
# return JSON whose ``data`` field carries a base64-encoded image (often
# 100-300 KB → 100k-300k tokens). The frontend needs this payload to render
# the image inline, but the LLM does NOT — for chaining tool calls
# (``gmail_send_with_local_attachment``, ``drive_create_file``…) the model
# only needs ``local_path``.
#
# Without stripping, every multi-turn workflow that includes a screenshot
# saturates the model's context window. Observed 2026-05-08 :
# - Qwen 2.5 14B local : 216k tokens → TruncateMiddle → model loses its own
#   tool args, hallucinates paths, workflow collapses
# - Qwen 3.6 Flash via DashScope : context bloat slows tour 2 by ~5×
#
# Stripping in the tool_message that goes back into LangGraph's state restores
# correct multi-turn behaviour and dramatically reduces token cost on every
# provider. The frontend has already consumed the original (full) payload via
# the ``on_tool_end`` stream event ; this transformation only affects what
# the model sees in its conversation history.

# Field names that may carry oversized base64 / binary payloads.
_HEAVY_FIELDS: frozenset[str] = frozenset({
    "data",          # browser_screenshot, generate_image
    "b64",           # alternate naming
    "b64_json",      # OpenAI image API
    "image_data",    # some adapters
    "binary",        # generic
    "raw",           # generic
})

# Anything below this length is left as-is even if its key looks heavy.
# 4 000 chars ≈ 1 000 tokens — small enough to keep in context if a tool
# legitimately returns a small base64 (avatar, icon, etc.).
_HEAVY_FIELD_THRESHOLD: int = 4000


def _sanitize_tool_result_for_history(content: str) -> str:
    """Strip oversized binary payloads from a tool result before it's stored
    in the LangGraph state and sent back to the LLM at the next turn.

    The frontend has already consumed the original (full) payload via the
    ``on_tool_end`` stream event ; this transformation only affects what
    the model sees in its conversation history.

    Behaviour
    ---------
    - Non-JSON strings → returned unchanged.
    - JSON dicts → fields named ``data``, ``b64``, ``b64_json``, ``image_data``,
      ``binary``, ``raw`` are replaced by ``"[stripped: N chars …]"`` if they
      exceed ``_HEAVY_FIELD_THRESHOLD`` chars.
    - Other fields (notably ``local_path``, ``mime``, ``prompt``, ``next_steps``,
      ``url``, ``title``…) are preserved verbatim — the model needs those
      to chain subsequent tool calls.
    - Malformed JSON or non-dict roots → returned unchanged (we don't try to
      be clever).
    """
    if not content or not isinstance(content, str):
        return content
    # Cheap pre-check : avoid parsing JSON if it doesn't look like a dict
    if not content.lstrip().startswith("{"):
        return content
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return content
    if not isinstance(obj, dict):
        return content

    changed = False
    for key in list(obj.keys()):
        if key in _HEAVY_FIELDS:
            val = obj[key]
            if isinstance(val, str) and len(val) > _HEAVY_FIELD_THRESHOLD:
                obj[key] = (
                    f"[stripped: {len(val)} chars — kept in frontend payload, "
                    f"not visible to the model. Use local_path or attachment_id "
                    f"to chain next tools.]"
                )
                changed = True
    if not changed:
        return content
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        # Should never happen — obj came from json.loads — but keep the
        # original on the off-chance.
        return content


# ─────────────────────────────────────────────────────────────────────────────
# Smart bind_tools — disable parallel_tool_calls for permissive/openai-family
# ─────────────────────────────────────────────────────────────────────────────
#
# Bug observed 2026-05-08 on Qwen 2.5 14B local (and reproducible on most
# permissive instruct models) :
#
#   Turn 1 → modèle émet 3 tool_calls EN PARALLÈLE :
#     browser_navigate(url="https://catalogmaker.fr")
#     browser_screenshot()
#     gmail_send_with_local_attachment(local_path="/tmp/.../screenshot-catalogmaker.png", ...)
#
#   Le modèle INVENTE le ``local_path`` parce qu'il n'a pas encore reçu le
#   résultat de browser_screenshot (qui retourne un uuid réel). gmail_send
#   échoue avec « fichier introuvable ». 2 tours de retry gaspillés avant
#   que le modèle ne corrige son tir au tour 3.
#
# Fix : ``parallel_tool_calls=False`` au bind. Force le modèle à émettre UN
# tool_call par tour. Au tour 1 : browser_navigate. Au tour 2 (avec le retour
# de tour 1) : browser_screenshot. Au tour 3 (avec le local_path RÉEL) :
# gmail_send_with_local_attachment. Workflow propre en 3 tours au lieu de 4-5.
#
# Famille du modèle
# -----------------
# - **Disciplined** (Claude / Anthropic) : NE PAS passer le kwarg, leur API
#   ne le supporte pas. Claude sait quand chaîner sans qu'on le force.
# - **OpenAI family** (gpt-oss, gpt-4o, Codex) : `parallel_tool_calls=False`.
#   Ils tendent à parallel-call abusivement comme Qwen 2.5.
# - **Permissive** (Qwen, Mistral, Gemma, Llama, Gemini, DeepSeek, GLM, …) :
#   `parallel_tool_calls=False`. Les plus à risque pour l'invention d'args.
#
# Logging ultra-verbose
# ---------------------
# Hier soir (2026-05-08), la 1ère tentative de ce fix (commits 96569a7 +
# b7c6c6d, rollbackés) plantait silencieusement chez Franck. Sans logs,
# diagnostic impossible. Cette version logge à WARNING level sur TOUS les
# code paths (entrée, succès, échec, fallback) avec ``exc_info=True`` sur
# les exceptions — toute future régression produira une stack trace lisible
# dans ``docker logs cyberentity-backend``.

_BTS_TAG: str = "[bind_tools_smart]"


def _classify_model_family(model_name: str | None) -> str:
    """Return one of "disciplined", "openai_family", "permissive".

    Robust to None / empty / mixed-case. Default = permissive (over-instruct
    is safer than under-instruct).
    """
    if not model_name:
        return "permissive"
    name_lc = model_name.lower()
    # Claude / Anthropic — disciplined, parameter not supported
    if "claude" in name_lc or "anthropic" in name_lc:
        return "disciplined"
    # OpenAI family
    for kw in ("gpt-oss", "gpt_oss", "openai/gpt", "gpt-4", "gpt-3.5", "gpt-4o",
               "codex", "o1-", "o3-", "openai-"):
        if kw in name_lc:
            return "openai_family"
    return "permissive"


def _extract_model_name(llm) -> str:
    """Best-effort introspection of the model name from a LangChain ChatModel.

    Tries the common attribute names used by ChatOpenAI, ChatAnthropic,
    ChatOllama, and the various providers. Returns an empty string if
    nothing is found — safe to pass to ``_classify_model_family``
    (defaults to permissive).
    """
    if llm is None:
        return ""
    for attr in ("model_name", "model", "deployment_name"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return ""


def _bind_tools_smart(llm, tools, model_name: str | None = None):
    """Bind tools with a parallel-tool-calls policy chosen by model family.

    NEVER raises. Every exception path falls back to a plain
    ``llm.bind_tools(tools)`` while logging the cause with full traceback.
    Better a sub-optimal bind than a crashed agent turn.

    If ``model_name`` is None, it is auto-extracted from the LLM instance.
    """
    if model_name is None:
        model_name = _extract_model_name(llm)
    family = _classify_model_family(model_name)
    try:
        _tools_count = len(list(tools)) if hasattr(tools, "__len__") else -1
    except Exception:
        _tools_count = -1
    logger.info(
        "%s model=%r family=%r tools=%d",
        _BTS_TAG, model_name, family, _tools_count,
    )

    if family in ("permissive", "openai_family"):
        try:
            bound = llm.bind_tools(tools, parallel_tool_calls=False)
            logger.info(
                "%s bound with parallel_tool_calls=False (model=%r)",
                _BTS_TAG, model_name,
            )
            return bound
        except Exception as exc:
            # Catch ALL exceptions — some adapters validate the kwarg lazily
            # at runtime, raising on first invoke or in a wrapped chain.
            logger.warning(
                "%s parallel_tool_calls=False rejected (model=%r, %s: %s) "
                "— falling back to plain bind_tools",
                _BTS_TAG, model_name, type(exc).__name__, exc,
                exc_info=True,
            )

    # Disciplined → plain bind. Permissive/openai with failed parametrised
    # bind → also plain bind. If even this fails, we cannot continue.
    try:
        return llm.bind_tools(tools)
    except Exception as exc:
        logger.error(
            "%s plain bind_tools also failed (model=%r, %s: %s)",
            _BTS_TAG, model_name, type(exc).__name__, exc,
            exc_info=True,
        )
        raise


# ------------------------------------------------------------------ #
# Tools that need automatic argument injection                        #
# ------------------------------------------------------------------ #
# Canonical sets live in tool_sets.py — import from there.

from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS  # noqa: E402


# ------------------------------------------------------------------ #
# Lightweight system prompt for SLM (simple tasks, no memory needed) #
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT_SLM = """Tu es Ely (prononcé "Éli"), une assistante IA personnelle — féminin, chaleureuse et directe.

Règles :
- Répondre en français, en texte naturel sans markdown
- Utiliser les outils disponibles dès que la demande le justifie
- Réponses courtes et claires pour les tâches simples
- Honnêteté sur tes capacités — ne jamais simuler une tentative échouée

RÈGLE INVIOLABLE — ne jamais inventer de données factuelles :
- Si un tool retourne 0 résultat ou une liste vide, dis « Je n'ai trouvé aucun élément correspondant » — JAMAIS une liste fabriquée.
- Si tu n'as pas appelé de tool pour une info factuelle, demande à l'utilisateur ou dis « je n'ai pas cette information ».
- Une réponse honnête « je ne sais pas » est plus utile qu'une réponse plausible inventée.

📅 Date et heure : {date_str} (Europe/Paris)
"""


# ------------------------------------------------------------------ #
# Memory block formatter (Hermes Chantier 2 — frozen snapshot)        #
# ------------------------------------------------------------------ #


def _format_memory_block(
    user_profile: str,
    preferences: list,
    constraints: list,
    memories: list,
    past_interactions: list,
) -> str:
    """Build the user-memory section of the system prompt as a single string.

    This is the **cacheable, frozen-for-the-session** part of the prompt.
    The output is byte-stable for given inputs, so wrapping the inputs
    themselves with frozen_memory + this formatter gives an immutable
    block that the prompt cache prefix can latch on.

    Order is intentional: user_profile FIRST (most important to anchor
    the model on the user's identity), preferences as RULES, constraints
    as REFUSAL HISTORY, memories as CONTEXT, past_interactions LAST
    (least important, longest tail).
    """
    parts: list[str] = []
    if user_profile:
        parts.append(f"\n\n🧠 {user_profile}\n")
    if preferences:
        parts.append(
            "\n\n👤 RÈGLES DE COMMUNICATION PERSONNALISÉES — OBLIGATOIRES :\n"
            "⚠️ Ces règles ont la même priorité que les règles absolues ci-dessus.\n"
            "Elles s'appliquent à CHAQUE réponse, sans exception, même si tu penses\n"
            "qu'une réponse plus longue serait plus utile. Respecte-les strictement.\n"
        )
        parts.append("\n".join(f"- {p}" for p in preferences))
    if constraints:
        parts.append("\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES (apprises de tes refus) :\n")
        parts.append("\n".join(f"- {c}" for c in constraints))
    if memories:
        parts.append("\n\n💾 CONTEXTE MÉMORISÉ :\n")
        parts.append("\n".join(f"- {m}" for m in memories))
    if past_interactions:
        parts.append("\n\n🔁 INTERACTIONS PASSÉES PERTINENTES :\n")
        for p in past_interactions:
            parts.append(
                f"- Q: {p.get('user_message', '')[:120]} "
                f"→ R: {p.get('assistant_message', '')[:120]}\n"
            )
    return "".join(parts)


# ------------------------------------------------------------------ #
# Agent node                                                           #
# ------------------------------------------------------------------ #

def create_agent_node():
    from app.skills import get_skill_registry
    from app.config import get_settings
    from app.services.llm_provider import get_active_provider, get_active_model

    settings = get_settings()
    registry = get_skill_registry()
    memory = get_memory_manager()
    intent_router = get_intent_router()

    # Pre-build SLM if enabled — cached in closure but re-bound when tools change
    _slm_with_tools = None
    _slm_version = -1
    if settings.slm_enabled:
        try:
            from app.services.llm_provider import get_slm
            _slm_with_tools = get_slm().bind_tools(registry.all_tools)
            _slm_version = registry.tools_version
            logger.info("SLM pre-built: model=%s, threshold=%d", settings.slm_model, settings.slm_complexity_threshold)
        except Exception as exc:
            logger.warning("SLM init failed: %s — all requests will use LLM", exc)

    # Tier-based LLM cache: { tier_value → llm_with_tools }
    # Invalidated on EITHER:
    #   - tool registry version bump (new skill installed/upgraded)
    #   - tier config version bump (user changed routing in Settings → Routage)
    # Without the second check, switching a model in the UI had no runtime
    # effect — the cached client (e.g. Devstral) kept being served on every
    # agent_node call. (Audit C-4, fixed 2026-05-06.)
    _tier_llm_cache: dict = {}
    _tier_cache_version = [-1]   # tracks registry.tools_version
    _tier_cfg_version = [-1]     # tracks llm_provider.get_tier_config_version()

    async def agent_node(state: AgentState) -> dict:
        import time as _t
        _gt_start = _t.monotonic()
        logger.warning("⏱ TIMING[general] starting")
        nonlocal _slm_with_tools, _slm_version
        # _tier_llm_cache / _tier_cache_version are dicts/lists mutated in-place — no nonlocal needed
        messages = state["messages"]
        user_id = state.get("user_id", "")
        # Hermes Chantier 2 / 4 — conversation id needs to be available BEFORE
        # the system prompt is built (cache key) and before the fallback state
        # is created (down in the LLM path). Hoisting it here means both
        # chantiers see the same value. Empty string disables both caches
        # for this turn — acceptable for non-conversation API callers.
        _conv_id_fb = state.get("conversation_id", "") or ""
        # Defensive: LangGraph may pass messages as dicts (serialized form)
        # when a node receives state that was built outside the graph runner.
        _last = messages[-1] if messages else None
        if isinstance(_last, dict):
            user_query = _last.get("content") or ""
            if isinstance(user_query, list):  # multi-block content
                user_query = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in user_query
                )
        else:
            _c = _last.content if _last else ""
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _c
            ) if isinstance(_c, list) else (_c or "")

        # Hot-reload: clear tier cache when tool registry OR tier routing config changes
        from app.services.llm_provider import get_tier_config_version
        current_version = registry.tools_version
        current_cfg_version = get_tier_config_version()
        if (current_version != _tier_cache_version[0]
                or current_cfg_version != _tier_cfg_version[0]):
            _tier_llm_cache.clear()
            _tier_cache_version[0] = current_version
            _tier_cfg_version[0] = current_cfg_version
            logger.info(
                "Tier LLM cache invalidated (tools_v=%d, tier_cfg_v=%d)",
                current_version, current_cfg_version,
            )

        if _slm_with_tools is not None and current_version != _slm_version:
            try:
                from app.services.llm_provider import get_slm
                _slm_with_tools = get_slm().bind_tools(registry.all_tools)
                _slm_version = current_version
            except Exception:
                pass

        # ── Route first — avoids loading memory for SLM requests ──────────
        routing_score = 100
        model_used = "llm:tier-routed"  # updated once tier is selected below
        response = None

        from app.services.intent_router import ModelTier
        use_slm = False
        decision = None
        if _slm_with_tools is not None:
            decision = intent_router.route(user_query, history=messages[:-1])
            routing_score = decision.score
            use_slm = (decision.tier == ModelTier.SLM)

        # Current date/time in French (Europe/Paris)
        from datetime import datetime
        import zoneinfo
        _tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(_tz)
        _days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        _months_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                      "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_str = (
            f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} "
            f"{now.year}, {now.strftime('%H:%M')}"
        )

        # Per-user language fetch — mirrors the logic in
        # app/agent/sub_agents/factory.py so the general agent honours
        # the UI language toggle even when the diag sub-agent isn't reached.
        _user_language = "fr"
        if user_id:
            try:
                from app.models.user import User as _U
                from app.database import async_session as _async_session
                from sqlalchemy import select as _select
                async with _async_session() as _db:
                    _row = await _db.execute(
                        _select(_U.language).where(_U.id == user_id)
                    )
                    _user_language = (_row.scalar_one_or_none() or "fr")
            except Exception:
                pass
        # Compact directives — see factory.py rationale (don't bloat xLAM 8B context)
        if _user_language == "en":
            _lang_directive = "REPLY LANGUAGE = English. Translate any tool output.\n\n"
            _lang_reminder = "\n\n[reply in English]"
        else:
            _lang_directive = "LANGUE DE RÉPONSE = Français. Traduis si besoin.\n\n"
            _lang_reminder = "\n\n[réponds en français]"
        logger.info(
            "[general] lang=%s user=%s",
            _user_language,
            (user_id[:8] + "…") if user_id else "(none)",
        )

        # Date string segment — ALWAYS dynamic, never goes into the cacheable
        # part. Provider prompt cache prefix matches up to the date and stops
        # there. Same with the trailing emails block (added later).
        _date_segment = (
            f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
            "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
        )

        if use_slm:
            # ── Lightweight path: minimal prompt, no memory queries ────────
            # Fetching Qdrant memory adds ~150-300ms and is useless for simple tasks.
            # SLM path is short enough that caching is not worthwhile.
            system = _SYSTEM_PROMPT_SLM.format(date_str=date_str)
            _use_compact = False  # ensure variable is defined for downstream branches
        else:
            # ── Full path: complete prompt + memory context ────────────────
            # Decide compact-vs-full once based on the active LLM family.
            # Compact path is used for small local LLMs (LM Studio, llama.cpp
            # on localhost) and stays uncached because it's already short
            # (~300 tokens) — the cache benefit is marginal there.
            from app.services.qwen_no_think import is_local_openai_llm
            from app.agent.compact_prompt import build_compact_system_prompt

            try:
                _llm_for_detect = get_llm()
            except Exception:
                _llm_for_detect = None
            _use_compact = (
                _llm_for_detect is not None
                and is_local_openai_llm(_llm_for_detect)
            )

            # Memory snapshot — cacheable per-conversation via frozen_memory.
            # On the first turn, we run the 5-way Qdrant + SQL gather; on
            # subsequent turns, the snapshot is returned from cache in O(1)
            # without re-querying Qdrant. New facts archived mid-session
            # appear in the snapshot of the NEXT conversation, not this one.
            from app.services.memory_service import get_user_context

            async def _build_memory_snapshot() -> str:
                # PERF: skip get_relevant_interactions on the very first turn —
                # there's nothing to find yet and Qdrant + FTS + embeddings
                # cost ~100-200ms. Only fetch when we have prior history.
                _history_msgs_count = sum(
                    1 for m in messages if getattr(m, "type", None) in ("human", "ai")
                )
                _needs_interactions = _history_msgs_count > 1
                _past_interactions_task = (
                    memory.get_relevant_interactions(user_query, user_id, limit=3)
                    if _needs_interactions
                    else _no_interactions()
                )
                constraints, memories_, past_interactions, preferences, user_profile = (
                    await asyncio.gather(
                        memory.get_relevant_constraints(user_query, user_id),
                        memory.get_relevant_memories(user_query, user_id),
                        _past_interactions_task,
                        memory.get_user_preferences(user_id),
                        get_user_context(user_id),
                    )
                )
                if _use_compact:
                    # Compact path needs structured pieces, not a single block.
                    # We stash them in a closure variable so the compact builder
                    # downstream can reuse them. Yes, this is a hack inside an
                    # async closure; the alternative is to query memory twice.
                    nonlocal _compact_pieces
                    _compact_pieces = {
                        "user_profile": user_profile or "",
                        "memories": memories_,
                        "constraints": constraints,
                    }
                return _format_memory_block(
                    user_profile or "",
                    preferences or [],
                    constraints or [],
                    memories_ or [],
                    past_interactions or [],
                )

            # Stash for compact-path reuse (set by _build_memory_snapshot
            # if compact mode is active).
            _compact_pieces: dict | None = None
            memory_snapshot = await _frozen_mem.get_or_build(
                _conv_id_fb, user_id, _build_memory_snapshot,
            )

            if _use_compact:
                # Local LLMs get a compact prompt — uncached, builds from the
                # snapshot pieces we just gathered.
                if _compact_pieces is None:
                    # Cache hit on frozen_memory means _build_memory_snapshot
                    # didn't run this turn, so _compact_pieces is empty. Re-fetch
                    # the minimal trio synchronously (this is rare — only on
                    # cache hit + compact mode together).
                    constraints_c, memories_c, _, _, user_profile_c = await asyncio.gather(
                        memory.get_relevant_constraints(user_query, user_id),
                        memory.get_relevant_memories(user_query, user_id),
                        _no_interactions(),
                        memory.get_user_preferences(user_id),
                        get_user_context(user_id),
                    )
                    _compact_pieces = {
                        "user_profile": user_profile_c or "",
                        "memories": memories_c or [],
                        "constraints": constraints_c or [],
                    }
                system = build_compact_system_prompt(
                    agent_name="general",
                    date_str=date_str,
                    user_ctx=_compact_pieces["user_profile"],
                    memories=_compact_pieces["memories"],
                    constraints=_compact_pieces["constraints"],
                )
                logger.info(
                    "[general] compact prompt mode active (%d chars)", len(system),
                )
            else:
                # Full path — Hermes Chantier 2 caching active.
                # Cacheable segment = lang_directive + base + IMPORTANT + snapshot.
                # Concatenated in this order so the provider's prompt cache
                # prefix can match every byte up to the dynamic date.
                _llm_introspection_note = (
                    "\n\nIMPORTANT : if the user asks which LLM/model/provider "
                    "you are using, you MUST call `system_check_llm_providers` "
                    "before answering. Never answer from your training memory.\n"
                    "Si l'utilisateur te demande quel LLM/modèle/fournisseur tu "
                    "utilises, tu DOIS appeler `system_check_llm_providers` "
                    "avant de répondre. Ne réponds jamais depuis ta mémoire.\n"
                )

                def _build_cacheable_prompt() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + _llm_introspection_note
                        + memory_snapshot
                    )

                cacheable_system = _spc.get_or_build(
                    _conv_id_fb, _build_cacheable_prompt,
                )
                # Final assembly: cacheable + dynamic date + lang reminder.
                # Email block + lang reminder are appended further down.
                system = cacheable_system + _date_segment

        # ── Sandwich tail: language reminder ──────────────────────────────
        # Front-load (primacy) was already applied INSIDE the cacheable
        # segment (full path) or via _SYSTEM_PROMPT_SLM/compact (other paths).
        # Tail-load (recency) goes here so the model honours the language
        # request even when the body drifts in the other language.
        if use_slm or _use_compact:
            # SLM/compact paths haven't applied the lang directive yet at the
            # head — apply both ends now for symmetry.
            system = _lang_directive + system + _lang_reminder
        else:
            # Full path already has the lang directive at the head (inside
            # the cacheable segment). Just append the reminder.
            system = system + _lang_reminder

        # ── Context fitting (prevent overflow) ────────────────────────────
        # NOTE: get_active_model is imported at create_agent_node() scope (line ~167).
        # Re-importing it here would shadow the closure and trigger UnboundLocalError
        # at the earlier usage line 271 (_model = get_active_model()).
        from app.services.context_manager import fit_messages_to_context

        _sanitized = _sanitize_messages_for_mistral(messages)

        # ── Extract user-provided emails / placeholders (audit 2026-05-07) ──
        # Weak models (Ministral 3 8B observed) keep asking for an email
        # already given in the conversation. We pre-scan the message stream
        # and inject a sticky « EMAILS DÉJÀ FOURNIS » block in the system
        # prompt. The PII filter has already replaced raw addresses with
        # ``[EMAIL_N]`` placeholders, so we look for both shapes:
        #   • bare address (rare — leak from filter or quoted text)
        #   • ``[EMAIL_0]`` / ``[EMAIL_1]`` placeholders
        try:
            import re as _email_re
            _email_pat = _email_re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
            _placeholder_pat = _email_re.compile(r"\[EMAIL_\d+\]")
            _seen_addrs: list[str] = []
            _seen_placeholders: list[str] = []
            for _m in _sanitized[-12:]:  # last 12 messages is enough
                _content = getattr(_m, "content", None)
                if _content is None and isinstance(_m, dict):
                    _content = _m.get("content")
                if not isinstance(_content, str):
                    continue
                for _addr in _email_pat.findall(_content):
                    if _addr not in _seen_addrs:
                        _seen_addrs.append(_addr)
                for _ph in _placeholder_pat.findall(_content):
                    if _ph not in _seen_placeholders:
                        _seen_placeholders.append(_ph)
            if _seen_addrs or _seen_placeholders:
                system += "\n\n📧 ADRESSES EMAIL DÉJÀ FOURNIES PAR L'UTILISATEUR :\n"
                if _seen_addrs:
                    system += "\n".join(f"- {a}" for a in _seen_addrs[:10]) + "\n"
                if _seen_placeholders:
                    system += (
                        "Placeholders (anonymisation PII active) : "
                        + ", ".join(_seen_placeholders[:10])
                        + "\n"
                        "→ Ces placeholders représentent de VRAIES adresses fournies par "
                        "l'utilisateur. Utilise-les TELS QUELS comme paramètre ``to`` des "
                        "outils gmail (ex: ``gmail_send_email(to='[EMAIL_0]', ...)``). "
                        "Le backend remplace automatiquement le placeholder par la vraie "
                        "adresse au moment de l'appel.\n"
                    )
                system += (
                    "→ NE redemande PAS l'adresse à l'utilisateur, NE la cherche PAS dans "
                    "contacts_search — elle est déjà fournie."
                )
        except Exception as _ext_exc:
            logger.debug("email extraction skipped: %s", _ext_exc)

        # ── Inference ──────────────────────────────────────────────────────
        if use_slm:
            try:
                _slm_fitted = fit_messages_to_context(
                    messages=_sanitized,
                    system_prompt=system,
                    model=settings.slm_model,
                    reserve_for_response=1024,
                )
                response = await asyncio.wait_for(
                    _slm_with_tools.ainvoke(
                        [{"role": "system", "content": system}]
                        + _slm_fitted
                    ),
                    timeout=settings.slm_timeout,
                )
                model_used = f"slm:{settings.slm_model}"
                logger.info(
                    "SLM answered (score=%d, model=%s, reason=%s)",
                    decision.score, settings.slm_model, decision.reason,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "SLM timeout after %.1fs (score=%d) — falling back to LLM",
                    settings.slm_timeout, decision.score,
                )
            except Exception as exc:
                logger.warning(
                    "SLM error (score=%d): %s — falling back to LLM",
                    decision.score, exc,
                )

        if response is None:
            # LLM path (or SLM fallback) — needs full system prompt if not built yet
            if use_slm:
                # SLM failed: rebuild full system prompt for LLM fallback. We
                # reuse the Chantier 2 cache machinery so the rebuilt prompt
                # follows the same cacheable/dynamic split as the primary
                # full path. This gives the SLM-fallback flow the same prompt
                # cache hit benefit on subsequent turns.
                from app.services.memory_service import get_user_context as _guc

                async def _fb_build_snapshot() -> str:
                    constraints, memories_, past_interactions, preferences, user_profile = (
                        await asyncio.gather(
                            memory.get_relevant_constraints(user_query, user_id),
                            memory.get_relevant_memories(user_query, user_id),
                            memory.get_relevant_interactions(user_query, user_id, limit=3),
                            memory.get_user_preferences(user_id),
                            _guc(user_id),
                        )
                    )
                    return _format_memory_block(
                        user_profile or "",
                        preferences or [],
                        constraints or [],
                        memories_ or [],
                        past_interactions or [],
                    )

                _fb_snapshot = await _frozen_mem.get_or_build(
                    _conv_id_fb, user_id, _fb_build_snapshot,
                )
                _fb_intro = (
                    "\n\nIMPORTANT : if the user asks which LLM/model/provider "
                    "you are using, you MUST call `system_check_llm_providers` "
                    "before answering. Never answer from your training memory.\n"
                )

                def _fb_build_cacheable() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + _fb_intro
                        + _fb_snapshot
                    )

                _fb_cacheable = _spc.get_or_build(_conv_id_fb, _fb_build_cacheable)
                system = (
                    _fb_cacheable
                    + f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
                    + "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
                    + _lang_reminder
                )

            # Tier routing: pick the right local/cloud model based on complexity.
            # CRITICAL PERF: the "general" node has access to ALL ~148 tools, which
            # makes bind_tools + the first inference extremely slow (the prompt grows
            # by ~30k tokens with 148 tool schemas). The supervisor already routes
            # tool-needing queries to sub-agents (workspace, infra…), so general is
            # mostly used for chitchat and quick facts that don't need tools. We only
            # bind tools when the query likely needs one (COMPLEX tier, or detected
            # tool keywords).
            from app.services.llm_provider import (
                classify_complexity, get_llm_for_tier, ComplexityTier,
                build_llm_for_provider, get_tier_config,
            )
            _tier = classify_complexity(user_query)

            # ── Hermes Chantier 4 — fallback chain bootstrap ─────────────
            # Capture (or recreate) the per-conversation FallbackState. The
            # chain comes from tier_config so the user only manages providers
            # in one place (Settings → Routage). If a previous turn already
            # switched to a fallback provider, ``_fb_state`` carries that
            # choice into this turn (sticky for the conversation).
            # _conv_id_fb is hoisted to the top of agent_node (used by Chantier 2 too).
            _fb_state = None
            if _conv_id_fb:
                _tier_cfg_for_fb = get_tier_config().get(_tier.value, {})
                _chain = list(_tier_cfg_for_fb.get("providers", []) or [])
                if _chain:
                    _fb_state = _fb.get_or_create(_conv_id_fb, _tier.value, _chain)
                    logger.info(
                        "[chantier4] conv=%s tier=%s chain=%s active_idx=%d (provider=%r)",
                        _conv_id_fb[:8], _tier.value, _chain,
                        _fb_state.current_index, _fb_state.current_provider,
                    )
                else:
                    logger.info(
                        "[chantier4] conv=%s tier=%s — empty chain in tier_config, "
                        "fallback manager INACTIVE (legacy path)",
                        _conv_id_fb[:8], _tier.value,
                    )
            # Bind tools only for COMPLEX queries OR when the query explicitly mentions
            # tool-related actions. SIMPLE/MEDIUM small-talk and quick facts skip binding.
            _tool_kw = re.compile(
                # « rdv » / « rendez-vous » / « réunion » / « meeting » ajoutés
                # (mai 2026) — sans eux, « Mes RDV cette semaine » échappait au
                # bind_tools et le LLM hallucinait un agenda inventé.
                r"\b(envoie|crée|liste|cherche|trouve|génère|exécute|lance|"
                r"planifie|programme|note|enregistre|sauvegarde|"
                r"mail|email|calendrier|agenda|rendez.?vous|rdvs?|réunions?|meetings?|"
                r"drive|sheet|doc|tâche|rappel|note|"
                r"fichier|capture|screenshot|météo|news|traduis)\b",
                re.IGNORECASE,
            )
            # When a sticky toolset profile is defined for the conversation,
            # ALWAYS bind that profile's tools — even for chitchat. The
            # model needs to see the same catalog every turn to learn it
            # (Hermes pattern, Chantier 1). The cost is ~3-5K tokens of
            # tool schemas per call, which is the price for stability.
            _has_profile = bool(state.get("toolset_profile") or "")
            _bind_tools_flag = (
                _has_profile or
                _tier == ComplexityTier.COMPLEX or
                bool(_tool_kw.search(user_query))
            )
            _tier_key = _tier.value
            # Cache key differentiates with/without tools bound
            # FIX 2026-05-06 (audit H-5): apply keyword-based tool filtering
            # to avoid binding all 160 tools at every turn. Sub-agents had
            # this filter; the general agent_node did not — resulting in
            # ~15 000 tokens of tool definitions per request (99 % of the
            # prompt) and 5+ minutes of prompt processing on local LLMs.
            #
            # We cache the BASE (unbound) LLM only. Tool binding is cheap
            # and runs per-call with the filtered list — the cache key now
            # encodes only the tier identity.
            # Hermes Chantier 4 — if a fallback is already active for this
            # conversation, build the LLM from the explicit provider rather
            # than re-running the tier cascade (which would land on the
            # primary again). Skip cache because fallback state is per-
            # conversation, not per-tier.
            if _fb_state is not None and _fb_state.is_active_fallback:
                _bind_start = _t.monotonic()
                _base_llm = build_llm_for_provider(_fb_state.current_provider, _tier)
                if _base_llm is None:
                    # Provider can't be instantiated (no key, etc.) — fall
                    # back to the standard tier resolution. We do NOT advance
                    # the chain here ; that's the job of the exception handler.
                    logger.warning(
                        "[fallback] conv=%s active provider %r unbuildable, "
                        "using tier resolution as last resort",
                        _conv_id_fb, _fb_state.current_provider,
                    )
                    _base_llm = get_llm_for_tier(_tier)
                logger.warning(
                    "⏱ TIMING[general.bind_base] %.2fs — tier=%s [FALLBACK active=%r]",
                    _t.monotonic() - _bind_start, _tier_key,
                    _fb_state.current_provider,
                )
            else:
                _base_cache_key = f"{_tier_key}:base"
                if _base_cache_key not in _tier_llm_cache:
                    _bind_start = _t.monotonic()
                    _base_llm = get_llm_for_tier(_tier)
                    _tier_llm_cache[_base_cache_key] = _base_llm
                    logger.warning("⏱ TIMING[general.bind_base] %.2fs — tier=%s (tools_v=%d, cfg_v=%d)",
                        _t.monotonic() - _bind_start, _tier_key, current_version, current_cfg_version)
                _base_llm = _tier_llm_cache[_base_cache_key]

            if _bind_tools_flag:
                # FIX 2026-05-07 (Hermes Chantier 1): prefer the sticky
                # toolset profile from state if defined. This binds the
                # SAME ~30-tool catalog every turn for the conversation,
                # so the model can learn it as muscle memory and the
                # prompt cache prefix stays intact. Empty profile = fall
                # back to the legacy keyword filter (graceful migration).
                _profile = state.get("toolset_profile") or ""
                if _profile:
                    from app.agent.toolset_profiles import resolve_profile_tools
                    _filtered_tools = resolve_profile_tools(
                        _profile, registry.all_tools,
                    )
                    logger.warning(
                        "[diag.bind] tier=%s profile=%r tools(%d)=%s",
                        _tier_key, _profile, len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )
                else:
                    # Legacy path — no profile set (e.g. external API caller
                    # or pre-Chantier-1 conversation row).
                    from app.agent.tool_filter import filter_tools_by_query
                    _filtered_tools = filter_tools_by_query(
                        registry.all_tools,
                        user_query,
                        threshold=20,
                        debug_label=f"general.{_tier_key}",
                    )
                    logger.warning(
                        "[diag.bind] tier=%s query=%r tools(%d)=%s [LEGACY]",
                        _tier_key,
                        user_query[:80] if user_query else "",
                        len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )
                # When the user's ELY Chrome extension is connected, hide
                # the server-side Playwright tools entirely. They live in
                # a separate, cookie-less context that always lands on
                # login pages — and the LLM tends to fall back to them
                # the second `browser_tab_*` returns less data than
                # expected. Removing them from the toolkit makes the
                # fallback impossible (belt-and-braces with the system
                # prompt rule).
                try:
                    from app.services import browser_extension_registry as _bext
                    _uid_for_bext = str(state.get("user_id") or "")
                    if _uid_for_bext and _bext.is_connected(_uid_for_bext):
                        _PLAYWRIGHT_TOOLS = {
                            "browser_navigate", "browser_screenshot",
                            "browser_get_text", "browser_search_web",
                            "browser_click", "browser_fill", "browser_close",
                        }
                        _before = len(_filtered_tools)
                        _filtered_tools = [
                            t for t in _filtered_tools if t.name not in _PLAYWRIGHT_TOOLS
                        ]
                        if len(_filtered_tools) != _before:
                            logger.warning(
                                "[diag.bind] extension connected → hiding %d Playwright tool(s); "
                                "agent now has %d tools",
                                _before - len(_filtered_tools), len(_filtered_tools),
                            )
                except Exception as _bext_err:
                    logger.debug("[diag.bind] extension-check skipped: %s", _bext_err)

                # Mini-chantier A — apply parallel_tool_calls policy by
                # model family. Permissive models (Qwen, Mistral…) and OpenAI
                # family invent downstream args (e.g. fake local_path) when
                # they emit parallel tool_calls. Forcing one-call-per-turn
                # makes the model wait for each result before chaining.
                _llm_with_tools_req = _bind_tools_smart(_base_llm, _filtered_tools)
            else:
                _llm_with_tools_req = _base_llm
            # Resolve the actual provider+model behind the tier so analytics
            # shows "lm_studio/llama-xlam-2-8b-fc-r-mlx" instead of "tier-medium".
            # Falls back gracefully to the tier label if introspection fails.
            try:
                from app.services.llm_provider import describe_llm
                _p, _m = describe_llm(_base_llm)
                model_used = f"llm:{_p}/{_m}{'+tools' if _bind_tools_flag else ''}"
            except Exception:
                model_used = f"llm:tier-{_tier_key}{'+tools' if _bind_tools_flag else ''}"

            _fitted = fit_messages_to_context(
                messages=_sanitized,
                system_prompt=system,
                model=_tier_key,
                reserve_for_response=1024,
            )
            _invoke_msgs = (
                [{"role": "system", "content": system}]
                + _fitted
            )
            try:
                _infer_t = _t.monotonic()
                from app.services.qwen_no_think import (
                    inject_no_think, is_qwen_llm, strip_no_think, strip_think_block,
                )
                # Only Qwen understands /no_think; other models would echo it.
                if is_qwen_llm(_base_llm):
                    _invoke_msgs = inject_no_think(_invoke_msgs)
                # FIX 2026-05-06 (P1 OpenClaw-style): if a recent ToolMessage
                # carries a base64 screenshot AND the model supports vision,
                # inject the image as a HumanMessage so the model can SEE it
                # rather than just read the JSON metadata.
                try:
                    from app.agent.vision_injection import maybe_inject_screenshot
                    _invoke_msgs = maybe_inject_screenshot(_invoke_msgs, _base_llm)
                except Exception as _vis_exc:
                    logger.debug("vision_injection skipped: %s", _vis_exc)
                response = await _llm_with_tools_req.ainvoke(_invoke_msgs)
                # Strip any <think> block that slipped through
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)

                # FIX 2026-05-06 (Option A): some cloud models (Kimi K2.x,
                # Qwen 3.6 Flash via DashScope, occasionally DeepSeek) emit
                # tool calls as TEXT inside content instead of populating
                # the structured `tool_calls` field. Without recovery, the
                # graph receives `tool_calls=[]` and stalls. Also handles
                # hallucinated tool names like `send_email` →
                # `gmail_send_email` via fuzzy matching.
                from app.agent.tool_call_recovery import (
                    recover_tool_calls_into_response,
                    detect_empty_promise,
                )
                # DIAG 2026-05-06: log raw response shape BEFORE recovery
                _raw_tc = getattr(response, "tool_calls", None) or []
                _raw_content = getattr(response, "content", "") or ""
                _raw_content_str = _raw_content if isinstance(_raw_content, str) else str(_raw_content)
                logger.warning(
                    "[diag.resp] tier=%s raw_tool_calls=%d content_len=%d content_head=%r",
                    _tier_key, len(_raw_tc), len(_raw_content_str), _raw_content_str[:200],
                )
                _recovered = recover_tool_calls_into_response(
                    response,
                    real_tool_names={t.name for t in registry.all_tools},
                )
                if _recovered:
                    logger.warning(
                        "[recovery] tier=%s — recovered %d tool_call(s) from text content",
                        _tier_key, _recovered,
                    )

                # FIX 2026-05-06 (P4): empty-promise guard — if the model
                # claims delivery ("je télécharge sur ton Drive…", "sending
                # the file now…") but produced ZERO tool_calls, re-invoke
                # with a corrective system message. Limited to ONE retry
                # per turn to avoid infinite loops if the model is stubborn.
                _post_tc = getattr(response, "tool_calls", None) or []
                _post_content = getattr(response, "content", "") or ""
                _post_content_str = _post_content if isinstance(_post_content, str) else str(_post_content)
                if not _post_tc and detect_empty_promise(_post_content_str):
                    logger.warning(
                        "[empty_promise] tier=%s — model promised delivery without "
                        "calling a tool. Content head: %r. Re-prompting once.",
                        _tier_key, _post_content_str[:200],
                    )
                    _correction_msg = {
                        "role": "system",
                        "content": (
                            "⚠️ Tu viens d'écrire que tu télécharges/envoies/sauvegardes "
                            "le fichier MAIS tu n'as appelé AUCUN outil dans ton dernier "
                            "message. Cette promesse est vide — l'utilisateur ne reçoit rien.\n\n"
                            "DEUX OPTIONS :\n"
                            "1. Si tu DOIS livrer le fichier maintenant, réémets ta "
                            "réponse en appelant explicitement l'outil approprié "
                            "(gmail_send_with_local_attachment, drive_create_file, "
                            "desktop_copy_file, etc.) avec les bons paramètres.\n"
                            "2. Si tu ne peux pas (paramètre manquant), dis-le clairement "
                            "à l'utilisateur et demande-lui le paramètre manquant — sans "
                            "prétendre qu'une livraison est en cours.\n\n"
                            "NE répète PAS la phrase « en cours de téléchargement » sans "
                            "appel d'outil cette fois-ci."
                        ),
                    }
                    try:
                        _retry_msgs = list(_invoke_msgs) + [
                            {"role": "assistant", "content": _post_content_str},
                            _correction_msg,
                        ]
                        _retry_response = await _llm_with_tools_req.ainvoke(_retry_msgs)
                        _retry_tc = getattr(_retry_response, "tool_calls", None) or []
                        _retry_content = getattr(_retry_response, "content", "") or ""
                        if _retry_tc:
                            logger.warning(
                                "[empty_promise] retry produced %d tool_call(s) — "
                                "replacing original response", len(_retry_tc),
                            )
                            response = _retry_response
                        elif isinstance(_retry_content, str) and _retry_content.strip():
                            # No tool but a clearer prose without false promise — use it
                            if not detect_empty_promise(_retry_content):
                                logger.warning("[empty_promise] retry returned honest prose — using it")
                                response = _retry_response
                            else:
                                logger.warning("[empty_promise] retry STILL promises without tool — keeping original")
                    except Exception as _retry_exc:
                        logger.warning("[empty_promise] retry failed (%s)", _retry_exc)

                logger.warning("⏱ TIMING[general.infer] %.2fs — tier=%s, tool_calls=%d",
                    _t.monotonic() - _infer_t, _tier_key, len(getattr(response, 'tool_calls', []) or []))

                # ── Audit H-1 fix (2026-05-06): garde anti-hallucination ──
                # Modèles locaux 7-14B (Qwen, Mistral, Llama small) ont
                # tendance à émettre du TEXTE en plain "je vais faire X"
                # au lieu d'un tool_call JSON, surtout sur des verbes
                # d'action explicites ("envoie", "supprime", "crée").
                # Symptôme observé en prod : Qwen 3 VL 8B refuse "envoie
                # par mail" au lieu d'appeler gmail_send_with_attachment.
                # Garde : si modèle LOCAL + 0 tool_calls + user query
                # contient un verbe d'action → fallback cloud immédiat.
                _has_tool_calls = bool(getattr(response, 'tool_calls', None))
                from app.services.qwen_no_think import is_local_openai_llm as _is_local_oa
                _is_local = _is_local_oa(_base_llm)
                _action_verbs = (
                    "envoie", "envoy", "supprime", "delete", "send",
                    "crée", "creer", "create", "écris", "ecris", "write",
                    "lance", "exécute", "execute", "run", "schedule",
                    "rappel", "remind", "ferme", "close", "ouvre", "open",
                    "télécharge", "download", "achète", "buy", "réserve",
                    "book", "réponds", "reply", "transfère", "transfer",
                    "capture", "screenshot", "photographie",
                )
                _query_has_action = any(v in user_query.lower() for v in _action_verbs)
                if (
                    _is_local
                    and not _has_tool_calls
                    and _query_has_action
                    and _bind_tools_flag
                ):
                    logger.warning(
                        "[H-1] Local LLM (tier=%s) returned PLAIN TEXT instead of "
                        "tool_call despite action verb in user query — falling "
                        "back to cloud LLM. Response preview: %r",
                        _tier_key, (response.content or "")[:120],
                    )
                    # Force-trigger the fallback path below by raising a
                    # synthetic "recoverable" exception. The existing fallback
                    # loop will iterate through get_fallback_llms() and pick
                    # the first cloud model with a working API key.
                    raise RuntimeError("h1_fallback: local LLM hallucinated plain text")
            except Exception as primary_exc:
                # Hermes Chantier 4 — classify the exception and ask the
                # FallbackManager to advance to the next provider in the
                # conversation's chain. If the exception is unrecognised
                # (genuine programmer bug), we re-raise so it surfaces.
                _reason = _fb.classify_exception(primary_exc)
                if _reason is None:
                    raise

                logger.warning(
                    "[fallback] primary LLM failed (%s/%s): %s",
                    type(primary_exc).__name__, _reason.value, primary_exc,
                )
                response = None
                # Strip any /no_think marker (Qwen-only) before trying a
                # different provider that doesn't understand it.
                _fallback_msgs = strip_no_think(_invoke_msgs)

                # Walk forward through the chain until a provider answers or
                # the chain is exhausted. Each provider is given ONE attempt;
                # subsequent failures advance again. This loop is bounded by
                # len(chain) so it can never spin.
                if _conv_id_fb and _fb_state is not None:
                    while True:
                        _new_provider_id = _fb.try_activate(_conv_id_fb, _reason)
                        if not _new_provider_id:
                            logger.warning(
                                "[fallback] chain exhausted for conv=%s",
                                _conv_id_fb,
                            )
                            break
                        _new_llm = build_llm_for_provider(_new_provider_id, _tier)
                        if _new_llm is None:
                            logger.warning(
                                "[fallback] provider %r unbuildable, advancing",
                                _new_provider_id,
                            )
                            continue  # ask manager for the next one
                        try:
                            # PRESERVE the toolset profile — the cardinal sin
                            # of the old fallback loop was rebinding all 145
                            # tools, breaking the Chantier 1 contract. Here
                            # we re-bind exactly the same _filtered_tools the
                            # primary saw.
                            if _bind_tools_flag:
                                # Apply same parallel-policy as primary,
                                # auto-detecting the new provider's family.
                                _new_with_tools = _bind_tools_smart(
                                    _new_llm, _filtered_tools,
                                )
                            else:
                                _new_with_tools = _new_llm
                            response = await _new_with_tools.ainvoke(_fallback_msgs)
                            logger.warning(
                                "[fallback] succeeded with %r", _new_provider_id,
                            )
                            # Keep model_used in sync with the active provider.
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(_new_llm)
                                model_used = f"llm:{_p}/{_m}+tools[fallback]"
                            except Exception:
                                model_used = f"llm:{_new_provider_id}+tools[fallback]"
                            break
                        except Exception as _next_exc:
                            _next_reason = _fb.classify_exception(_next_exc)
                            if _next_reason is None:
                                # Real bug in the new provider — re-raise.
                                raise
                            logger.warning(
                                "[fallback] %r also failed (%s): %s — advancing",
                                _new_provider_id, _next_reason.value, _next_exc,
                            )
                            _reason = _next_reason
                            continue

                # SAFETY NET (Chantier 4 V1.1) — if the per-tier chain didn't
                # produce a working response (single-provider tier, all
                # providers exhausted, instances unbuildable…), DO NOT raise
                # yet. Try the legacy global fallback list first (Gemini,
                # Anthropic, OpenRouter, Ollama installed system-wide). This
                # restores the pre-Chantier-4 robustness for users whose tier
                # config is minimal — better to silently bind 145 tools on a
                # cloud frontier than to surface "Erreur interne" to the user.
                if response is None:
                    logger.info(
                        "[fallback] tier-chain exhausted/unavailable, "
                        "trying legacy global helpers"
                    )
                    for fallback_label, fallback_llm in get_fallback_llms():
                        try:
                            # fallback_label is "anthropic/claude-…" or
                            # "gemini/gemini-2.5-flash" — extract model name
                            # for family classification.
                            _legacy_model_name = (
                                fallback_label.split("/", 1)[1]
                                if "/" in fallback_label
                                else fallback_label
                            )
                            _legacy_with_tools = (
                                _bind_tools_smart(
                                    fallback_llm, _filtered_tools,
                                    model_name=_legacy_model_name,
                                )
                                if _bind_tools_flag
                                else fallback_llm
                            )
                            response = await _legacy_with_tools.ainvoke(_fallback_msgs)
                            logger.info(
                                "[fallback] legacy succeeded with %s", fallback_label,
                            )
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(fallback_llm)
                                model_used = f"llm:{_p}/{_m}+tools[legacy_fallback]"
                            except Exception:
                                model_used = f"llm:{fallback_label}+tools[legacy_fallback]"
                            break
                        except Exception as fallback_exc:
                            logger.warning(
                                "[fallback] legacy %s also failed: %s",
                                fallback_label, fallback_exc,
                            )

                if response is None:
                    raise primary_exc

        # Hermes Chantier 4 — track this turn's response so the manager can
        # detect empty-streaks (≥3 empties → auto-fallback on the next turn).
        # We pass the current response's content + tool_calls flag.
        if _conv_id_fb and _fb_state is not None and response is not None:
            _resp_content = getattr(response, "content", "") or ""
            if isinstance(_resp_content, list):
                # Multi-block content — concatenate text chunks.
                _resp_content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in _resp_content
                )
            _has_tc = bool(getattr(response, "tool_calls", None))
            try:
                _fb.record_response(_conv_id_fb, str(_resp_content), _has_tc)
            except Exception as _rec_exc:
                logger.debug("fallback.record_response failed: %s", _rec_exc)

        # Fire-and-forget: extract facts from this exchange for user memory
        if user_id:
            from app.services.memory_service import extract_and_store_facts

            async def _safe_memory_extract(uid, msgs):
                try:
                    await extract_and_store_facts(uid, "", msgs)
                except Exception as exc:
                    logger.debug("Memory extraction failed: %s", exc)

            asyncio.create_task(_safe_memory_extract(user_id, messages + [response]))

        # Hermes Chantier 9 — increment the iteration counter when the
        # response carries tool_calls (i.e. the loop will bounce back here
        # for another inference). Bare-text responses don't loop, so they
        # don't burn the budget. The counter is read by ``should_continue``
        # to detect when we're approaching the recursion limit and need
        # to force a final textual summary.
        _has_tool_calls = bool(getattr(response, "tool_calls", None))
        _next_iter = state.get("iteration_count", 0) + (1 if _has_tool_calls else 0)
        return {
            "messages": [response],
            "model_used": model_used,
            "routing_score": routing_score,
            "iteration_count": _next_iter,
        }

    return agent_node


# ------------------------------------------------------------------ #
# Tool node                                                            #
# ------------------------------------------------------------------ #

async def tool_node(state: AgentState) -> dict:
    from app.skills import get_skill_registry

    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

    # ── PII deanonymization for tool args (audit 2026-05-07) ──────────────
    # The user's PII (emails, phones, IBANs) is replaced with placeholders
    # like ``[EMAIL_0]`` BEFORE messages reach the LLM. When the LLM emits a
    # tool call, it uses those placeholders verbatim ("to": "[EMAIL_0]").
    # Without restoring real values here, downstream APIs (Gmail, etc.)
    # receive the placeholder string and reject it as invalid input.
    # We pull the per-conversation SecurityFilter from the shared registry
    # so we get the SAME vault used by chat.py for anonymization.
    _conv_id = state.get("conversation_id") or ""
    _vault_sf = None
    if _conv_id:
        try:
            from app.services.conversation_filters import get_filter as _get_conv_filter
            _vault_sf = _get_conv_filter(_conv_id)
        except Exception as _vault_exc:
            logger.debug("conversation filter lookup failed: %s", _vault_exc)

    def _deanonymize_value(v):
        """Recursively restore PII placeholders in a tool-arg value."""
        if _vault_sf is None:
            return v
        if isinstance(v, str):
            return _vault_sf.deanonymize(v)
        if isinstance(v, dict):
            return {k: _deanonymize_value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_deanonymize_value(x) for x in v]
        return v

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        # Deanonymize tool args BEFORE any other processing so HITL preview,
        # logs, and the actual API call all see the real values.
        args = _deanonymize_value(dict(tool_call["args"]))

        # Inject hidden arguments — credentials are fetched from the server-side
        # store (never stored in graph state) to prevent exposure in logs/events.
        if tool_name in GOOGLE_TOOLS:
            from app.services.credential_store import get_credential_store
            _uid = state.get("user_id") or ""
            _store = get_credential_store()
            _creds = _store.get(_uid) or ""
            # Fallback (audit 2026-05-07): if the in-process cache is empty
            # — happens after a backend restart while the WebSocket is
            # still alive but the 5-min refresh hasn't ticked yet, or after
            # an OAuth re-consent that didn't propagate to the cache —
            # refresh straight from the DB. Better to pay one query per
            # tool call than to lie « Google non connecté » when the user
            # is in fact connected.
            if not _creds and _uid:
                try:
                    from app.database import async_session as _async_session
                    from app.models.user import User as _U
                    async with _async_session() as _db:
                        _u = await _db.get(_U, _uid)
                        if _u and _u.google_credentials:
                            _creds = _u.google_credentials
                            _store.set(_uid, _creds)
                            logger.warning(
                                "[creds] cache miss for user=%s — refreshed from DB",
                                _uid,
                            )
                except Exception as _creds_exc:
                    logger.warning("[creds] DB fallback failed: %s", _creds_exc)
            args["user_google_credentials_json"] = _creds
        if tool_name in USER_ID_TOOLS:
            args["user_id"] = state.get("user_id") or ""

        # Build display args — never expose tokens or injected IDs in UI/logs
        _hidden = {"user_google_credentials_json", "user_id"}
        display_args = {k: v for k, v in args.items() if k not in _hidden}
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

        # ── Vault: resolve vault://label references in args ───────────────
        vault_refs_found = any(
            isinstance(v, str) and v.startswith("vault://")
            for v in args.values()
        )
        if vault_refs_found:
            from app.services.vault_service import get_vault_service
            vault = get_vault_service()
            if vault.is_locked(user_id):
                results.append(_tool_result(
                    "⛔ Vault verrouillé — déverrouillez votre coffre-fort dans Paramètres > Vault "
                    "pour utiliser ce secret.", tc_id
                ))
                continue
            try:
                args, _resolved = await vault.resolve_vault_refs(user_id, args)
                if _resolved:
                    logger.info("Resolved vault refs %s for tool %s", _resolved, tool_name)
            except KeyError as exc:
                results.append(_tool_result(f"⛔ Secret introuvable dans le Vault : {exc}", tc_id))
                continue

        # HITL check
        needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(action_desc)
        if needs_hitl:
            logger.info("HITL required for action: %s", action_desc)
            decision, reason = await hitl.request_validation(
                description=action_desc,
                user_id=user_id,
            )
            if decision == "ban":
                rule = f"INTERDICTION PERMANENTE: {action_desc}"
                if reason:
                    rule += f" — Raison: {reason}"
                await memory.store_constraint(rule, user_id)
                results.append(_tool_result(
                    "Action interdite définitivement et règle de sécurité enregistrée.", tc_id
                ))
                continue
            elif decision != "allow":
                results.append(_tool_result(
                    "Action refusée par l'utilisateur pour cette occurrence.", tc_id
                ))
                continue

        tool = tool_map.get(tool_name)
        if tool:
            try:
                import time as _tt
                _ts = _tt.monotonic()
                result = await tool.ainvoke(args)
                logger.warning("⏱ TIMING[tool:%s] %.2fs", tool_name, _tt.monotonic() - _ts)
                # Strip oversized base64 / binary payloads from the tool result
                # BEFORE storing in LangGraph state. The frontend has already
                # consumed the full payload via the on_tool_end event ; only
                # the model's history view needs the trimmed version. Without
                # this, browser_screenshot leaks ~200 KB of base64 into every
                # subsequent turn's prompt.
                _raw_result = str(result)
                _safe_result = _sanitize_tool_result_for_history(_raw_result)
                if len(_safe_result) < len(_raw_result):
                    logger.info(
                        "[tool_history_strip] %s: %d → %d chars",
                        tool_name, len(_raw_result), len(_safe_result),
                    )
                results.append(_tool_result(_safe_result, tc_id))
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
                results.append(_tool_result(f"Erreur d'exécution: {exc}", tc_id))
        else:
            from langchain_core.messages import ToolMessage
            results.append(ToolMessage(
                content=f"Outil '{tool_name}' non disponible.",
                tool_call_id=tc_id,
            ))

    return {"messages": results}


# ------------------------------------------------------------------ #
# Router                                                               #
# ------------------------------------------------------------------ #

# ─────────────────────────────────────────────────────────────────────────────
# Iteration budget — Hermes Chantier 9
# ─────────────────────────────────────────────────────────────────────────────
#
# Why
# ---
# On heavy multi-step tasks ("audit my last 30 days of mail and group by
# category"), the agent can chain 25-50 tool calls. LangGraph's
# ``recursion_limit=100`` (set in chat.py) caps the loop, but when it's hit
# it raises a hard exception → the user sees a generic error and the
# whole conversation context is lost.
#
# Hermes solution : count loops, and at ~80 iterations FORCE a final API
# call without tools, asking the model "summarise what you did so far,
# don't call any more tools". This guarantees the user always receives
# textual output even on overrun tasks.
#
# Numbers
# - ``MAX_AGENT_ITERATIONS = 80``  → trigger force_summary
# - LangGraph ``recursion_limit = 100`` (in chat.py) → safety margin of 20
#   iterations to let force_summary_node + tool_node + agent_node finish
#   cleanly without hitting the hard cap.

MAX_AGENT_ITERATIONS: int = 80


def should_continue(state: AgentState) -> str:
    """Routing decision after agent_node :
    - "force_summary" if the iteration budget is exhausted (Chantier 9)
    - "tools" if the model emitted tool_calls
    - "end" otherwise (final textual answer)
    """
    last_message = state["messages"][-1]
    iter_count = state.get("iteration_count", 0)

    if (
        isinstance(last_message, AIMessage)
        and last_message.tool_calls
        and iter_count >= MAX_AGENT_ITERATIONS
    ):
        logger.warning(
            "[iteration_budget] count=%d ≥ %d — forcing final summary "
            "without tools (Chantier 9)",
            iter_count, MAX_AGENT_ITERATIONS,
        )
        return "force_summary"

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"


# ─────────────────────────────────────────────────────────────────────────────
# Force summary node — Hermes Chantier 9
# ─────────────────────────────────────────────────────────────────────────────


async def force_summary_node(state: AgentState) -> dict:
    """Final inference WITHOUT tools, prompting the model to summarise
    what it has done so far. Reached when ``iteration_count`` crosses
    ``MAX_AGENT_ITERATIONS``.

    Strategy
    --------
    - Build the same system prompt + history as ``agent_node`` would, but
      DO NOT call ``bind_tools`` — the LLM physically cannot emit tool_calls.
    - Append a final user message that explicitly asks for a textual
      summary of the work done.
    - Return the resulting AIMessage as the conversation output.
    """
    messages = state["messages"]
    user_id = state.get("user_id", "")
    iter_count = state.get("iteration_count", 0)

    logger.warning(
        "[force_summary] entering : conv=%s iter=%d/%d, building summary…",
        (state.get("conversation_id", "") or "")[:8],
        iter_count,
        MAX_AGENT_ITERATIONS,
    )

    # Re-derive the user's original query to pick the right tier
    _last_human = next(
        (m for m in reversed(messages) if isinstance(m, HumanMessage)),
        None,
    )
    user_query = ""
    if _last_human is not None:
        _content = _last_human.content
        if isinstance(_content, str):
            user_query = _content
        elif isinstance(_content, list):
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _content
            )

    from app.services.llm_provider import (
        ComplexityTier,
        classify_complexity,
        get_llm_for_tier,
    )
    _tier = classify_complexity(user_query) if user_query else ComplexityTier.MEDIUM
    llm = get_llm_for_tier(_tier)

    # Append a strict instruction. We use a HumanMessage rather than a
    # SystemMessage to avoid Mistral's "single system message" constraint.
    forcing_msg = HumanMessage(content=(
        "[Système — limite d'itérations atteinte]\n\n"
        "Tu as utilisé toutes les itérations disponibles pour cette demande "
        f"({iter_count}/{MAX_AGENT_ITERATIONS} appels d'outils). N'appelle "
        "AUCUN nouvel outil. Donne maintenant à l'utilisateur, en français "
        "et en texte clair :\n"
        "1. Ce que tu as fait jusqu'ici (étapes complétées)\n"
        "2. Ce qu'il restait à faire\n"
        "3. Ce que l'utilisateur peut faire pour reprendre (ex : reformuler "
        "la demande de façon plus ciblée, scinder en plusieurs requêtes)\n\n"
        "Ne PROMETS pas d'action future, ne génère AUCUN tool_call, "
        "termine ta réponse par un point."
    ))

    _sanitized = _sanitize_messages_for_mistral(list(messages) + [forcing_msg])
    try:
        response = await llm.ainvoke(_sanitized)
        logger.warning(
            "[force_summary] success : produced %d chars of summary",
            len(getattr(response, "content", "") or ""),
        )
    except Exception as exc:
        # Even the summary call failed (network, billing…). Return a
        # synthesised AIMessage so the graph terminates cleanly.
        logger.error("[force_summary] failed (%s) — emitting fallback text", exc)
        from langchain_core.messages import AIMessage as _AIMessage
        response = _AIMessage(content=(
            f"J'ai atteint la limite de {MAX_AGENT_ITERATIONS} appels "
            "d'outils sur cette tâche et je n'ai pas pu produire de résumé "
            "automatiquement. Reformule ta demande en plusieurs étapes plus "
            "ciblées, ça aboutira plus rapidement."
        ))
    return {"messages": [response]}

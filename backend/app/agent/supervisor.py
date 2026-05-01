# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/supervisor.py
# @brief      Multi-agent supervisor for ELY
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
"""Multi-agent supervisor for ELY.

Architecture
------------
Instead of a single monolithic agent with all tools, ELY uses a **routing
supervisor** that classifies each user request and dispatches it to the most
appropriate specialist agent.  Each specialist has a focused tool set and a
tailored system prompt, which reduces token waste and improves accuracy.

┌─────────────────────────────────────────────────────────┐
│                    User message                         │
└───────────────────────┬─────────────────────────────────┘
                        │
               ┌────────▼────────┐
               │  router_node    │  (fast LLM intent classification)
               └────────┬────────┘
          ┌─────────────┼──────────────┬──────────────┐
          ▼             ▼              ▼              ▼
    [Research]    [Workspace]       [Infra]       [General]
    web, meteo    gmail, cal        ssh, cron     all tools
    news, trad    drive, docs       watchdog      (fallback)
    browser       sheets, tasks     briefing
          │             │              │              │
          └─────────────┴──────────────┴──────────────┘
                                │
                      ┌─────────▼─────────┐
                      │   tools_node      │
                      └─────────┬─────────┘
                                │
                      ┌─────────▼─────────┐
                      │  (loop until END) │
                      └───────────────────┘

Routing is done by a fast LLM call that outputs one of the four domain labels.
For requests that clearly span multiple domains (e.g. "cherche le dernier
rapport annuel d'Apple, crée un Google Doc avec un résumé et envoie-le à
alice@..."), the "general" agent is used so it has access to all tools.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from app.agent.state import AgentState
from app.agent.nodes import tool_node, should_continue, create_agent_node
from app.services.llm_provider import get_llm, get_llm_for_tier, ComplexityTier

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Domain labels
# ──────────────────────────────────────────────────────────────────────────────

# "system" is intentionally excluded from user-facing routing — it is only
# accessible programmatically via the sub-agent registry (e.g. scheduler jobs).
Domain = Literal["research", "workspace", "infra", "creative", "data", "memory", "desktop", "general", "system", "diag"]

_DOMAIN_DESCRIPTIONS = {
    "research": (
        "Recherche web, météo, actualités, traduction, navigation de sites, "
        "prix de produits, cours de bourse, définitions, faits généraux."
    ),
    "workspace": (
        "Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets, "
        "Google Tasks, Google Contacts — lecture, création, modification, "
        "envoi d'emails, gestion des contacts. Accès complet aux APIs "
        "(batchUpdate, raw_api_call) : tri/insertion/formatage Sheets, "
        "styles Docs, partage/export Drive, Meet/récurrence Calendar, "
        "modif en lot Gmail, opérations bulk Contacts."
    ),
    "infra": (
        "Commandes SSH sur serveurs, tâches planifiées (cron), briefing matinal, "
        "surveillance de sites web (watchdog/veille), monitoring système. "
        "Aussi : informations sur la machine locale, le poste de travail, les specs "
        "matérielles, la RAM, le CPU, l'OS, l'espace disque, la version Python, "
        "l'architecture du système. Exemples : 'infos système', 'specs de la machine', "
        "'donne-moi les informations sur ce système', 'quel est l'OS', 'quelle RAM'."
    ),
    "creative": (
        "Génération d'images, création de QR codes, exécution de code Python pour "
        "visualisations ou analyses, lecture de PDFs, analyse d'images, YouTube."
    ),
    "data": (
        "Calcul, analyse de données, manipulation de fichiers locaux, cartes et "
        "itinéraires, géolocalisation, code Python pour traitement de données."
    ),
    "memory": (
        "Notes personnelles (créer, lire, modifier, supprimer, chercher), "
        "envoi de messages WhatsApp, gestion de la mémoire personnelle, "
        "recherche dans la base de connaissances (documents indexés par l'utilisateur)."
    ),
    "desktop": (
        "Opérations sur la machine LOCALE de l'utilisateur UNIQUEMENT. "
        "Exemples : démonstrations interactives (tutoriels pas-à-pas, "
        "contrôle de la souris/clavier), captures d'écran du bureau, lancer "
        "des applications locales, automatisation du bureau (ELY Trainer), "
        "lister/lire/écrire/déplacer/supprimer des fichiers du disque local "
        "(~/Desktop, ~/Documents, /home, /Users…). "
        "NE PAS confondre avec Google Drive : si le fichier est dans Drive "
        "ou si l'utilisateur n'indique pas explicitement un chemin local "
        "(« sur ma machine », « localement », « dans mon Bureau », chemin "
        "avec ~ ou /), c'est workspace, PAS desktop. "
        "Exemples workspace mal routés : « duplique ce doc », « partage ce "
        "fichier », « renomme ce pdf » → workspace (Drive)."
    ),
    "general": (
        "Requête complexe impliquant plusieurs domaines à la fois, ou ne "
        "correspondant clairement à aucune catégorie unique."
    ),
}

_ROUTER_SYSTEM = """Tu es le routeur d'ELY. Ton unique rôle est de classifier la demande de l'utilisateur
dans l'une des huit catégories suivantes, sans l'exécuter.

Catégories disponibles :
- research   : {research}
- workspace  : {workspace}
- infra      : {infra}
- creative   : {creative}
- data       : {data}
- memory     : {memory}
- desktop    : {desktop}
- general    : {general}

Réponds UNIQUEMENT avec le nom de la catégorie en minuscules (research / workspace / infra / creative / data / memory / desktop / general).
Aucune explication. Aucun autre texte.
""".format(**_DOMAIN_DESCRIPTIONS)

# ──────────────────────────────────────────────────────────────────────────────
# Specialist system prompts
# ──────────────────────────────────────────────────────────────────────────────

_IDENTITY = (
    "Tu es Ély (prononcer \"Éli\"), une assistante IA personnelle — féminin, jamais masculin, "
    "jamais \"ELY\" lettre par lettre, jamais d'autre nom. "
    "Parle toujours de toi au féminin : \"je suis prête\", \"je suis disponible\", \"je t'aide\".\n\n"
)

_COMMON_FORMAT = """
Utilisation des tools — PRIORITÉ ABSOLUE :
- Dès que la demande correspond à un tool, APPELLE-le immédiatement via function calling.
- Ne JAMAIS annoncer l'appel ("je vais chercher...", "je lance...") — appelle direct.
- N'écris JAMAIS du code Python pour simuler un tool call.

Format des réponses TEXTE (seulement quand aucun tool n'est pertinent) :
- Français, texte naturel sans markdown (#, **, `, ---, tirets de liste interdits).
- Pour énumérer : "premièrement... ensuite... enfin...".
- URLs données telles quelles, cliquables.
- Pas de divulgation de credentials / config interne.
- Aucun emoji par défaut — ni ✋ ✅ 🎉 ni aucun autre.

Apprentissage des préférences — RÈGLE STRICTE :
- Appelle save_user_preference UNIQUEMENT quand l'utilisateur énonce
  EXPLICITEMENT une préférence DURABLE ("je préfère X", "désormais
  toujours Y", "à l'avenir utilise Z", "souviens-toi que W").
- N'appelle JAMAIS save_user_preference :
  * Sur une demande ponctuelle ("fais-moi un résumé court" = une fois, pas une préférence).
  * En parallèle d'une autre action (envoyer un mail, créer un doc…) — c'est du bruit.
  * Si la préférence est déjà dans le contexte mémorisé (🧠 ci-dessus).
- save_constraint : uniquement sur règle ferme de type « ne fais jamais X »
  (règle de sécurité/éthique), pas sur format/ton.
- Ne sauvegarde JAMAIS la même préférence deux fois dans une même session.

Intégrité des actions — IMPÉRATIF ABSOLU :
- Ne JAMAIS prétendre qu'une action est exécutée sans avoir appelé l'outil correspondant dans ce tour.
- INTERDIT : "c'est fait", "rappel enregistré", "événement créé", "email envoyé", "tâche planifiée" sans tool_call préalable.
- AUTORISÉ sans tool_call : "je vais le faire", "je m'en occupe", "laisse-moi créer cela".
- Quand l'utilisateur confirme par "oui", "vas-y", "fais-le" : APPELLE L'OUTIL IMMÉDIATEMENT, ne repasse pas par une phrase d'annonce.
- Rappel quotidien/récurrent → scheduler_create_task avec cron.
- Événement unique dans Google Calendar → calendar_create_event.
- Si le tool échoue, reporte l'erreur précisément au lieu d'inventer un succès.

Clarification en cas d'ambiguïté :
- Si la demande peut être réalisée par 2 outils très différents (ex: rappel = calendar ponctuel OU scheduler récurrent ; note = locale OU Google Keep ; envoi = mail OU WhatsApp), et que le contexte ne tranche pas clairement, POSE UNE QUESTION BRÈVE avant d'appeler un outil.
- Une question de 10 mots ("Tu veux un événement ponctuel ou un rappel récurrent ?") vaut mieux que de deviner et corriger après.
- Mais si le contexte est clair (ex: "chaque lundi" = récurrent), agis sans demander.

Recherche documentaire proactive — IMPÉRATIF :
- Avant de répondre à toute question factuelle susceptible d'impliquer un document
  personnel de l'utilisateur (contrat, facture, rapport, note, guide, manuel, etc.),
  appelle d'abord smart_knowledge_query avec la question telle quelle.
- Si l'outil retourne "__NO_RELEVANT_DOCS__", ignore-le et réponds normalement sans
  jamais mentionner à l'utilisateur que tu as cherché ou que tu n'as rien trouvé.
- Si l'outil retourne des extraits, base ta réponse dessus et cite les sources
  (nom du fichier et numéro de chunk) entre parenthèses à la fin.
"""

_SPECIALIST_PROMPTS: dict[Domain, str] = {
    "research": (
        _IDENTITY +
        "Tu es spécialiste de la recherche d'informations en ligne.\n\n"
        "Tu maîtrises la navigation web, la recherche DuckDuckGo, les prévisions "
        "météo, les actualités Google News et la traduction. Tu synthétises "
        "l'information de façon concise et précise.\n\n"
        "Outils disponibles : weather_get, news_get_headlines, translate_text, "
        "browser_navigate, browser_search_web, browser_get_text, browser_screenshot, "
        "browser_click, browser_fill, browser_close." + _COMMON_FORMAT
    ),
    "workspace": (
        _IDENTITY +
        "Tu es spécialiste de Google Workspace.\n\n"
        "Tu maîtrises Gmail, Google Calendar, Google Drive, Google Docs, Google "
        "Sheets, Google Tasks et Google Contacts. Tu aides l'utilisateur à gérer "
        "sa vie numérique Google de façon efficace. Toujours donner l'URL après chaque création.\n\n"
        "RÈGLE ABSOLUE D'EXÉCUTION : Appelle TOUJOURS les outils directement et immédiatement "
        "sans annoncer en texte ce que tu vas faire. Ne dis JAMAIS 'je vais chercher', "
        "'je vais lancer', 'je vais effectuer' — appelle l'outil sans commentaire. "
        "Les actions critiques déclenchent automatiquement une confirmation HITL.\n\n"
        "RÈGLE HITL — CONFIRMATION AUTOMATIQUE, JAMAIS EN TEXTE :\n"
        "Le système HITL affiche AUTOMATIQUEMENT une boîte de dialogue avec 3 "
        "boutons (Autoriser / Refuser / Interdire) dès que tu appelles un outil "
        "critique (supprimer, envoyer un email, SSH, etc.). Tu n'as JAMAIS à "
        "demander la confirmation toi-même en texte.\n"
        "PHRASES INTERDITES (elles créent une impasse — aucun HITL n'est déclenché "
        "tant que tu n'as pas appelé l'outil) :\n"
        "  - « Le système demande une confirmation... »\n"
        "  - « Confirmes-tu que tu veux bien supprimer... »\n"
        "  - « Voulez-vous que je valide... »\n"
        "  - « Dois-je procéder ? »\n"
        "Processus correct pour une action critique :\n"
        "  1. Tu appelles directement l'outil critique (ex : drive_delete_file "
        "     avec le file_id).\n"
        "  2. Le système affiche la boîte HITL à l'utilisateur (tu n'as rien à "
        "     faire).\n"
        "  3. Si l'utilisateur Autorise → l'outil s'exécute → tu reçois le "
        "     résultat → tu confirmes brièvement au passé (« Fichier supprimé. »).\n"
        "  4. Si l'utilisateur Refuse → l'outil te renvoie un message clair → "
        "     tu en informes brièvement.\n\n"
        "RÈGLE FORMAT TOOL CALL — IMPÉRATIF :\n"
        "Pour appeler un outil, utilise l'API de tool-calling native de ton "
        "modèle. N'écris JAMAIS de code JSON, de bloc <function_calls>, de "
        "balises <tool_use>, ni de syntaxe Python dans tes messages texte — "
        "ces formats ne sont PAS exécutés, ils sont juste affichés à "
        "l'utilisateur comme du charabia. Si tu ne peux pas appeler l'outil "
        "via l'API native, dis-le clairement plutôt que de faire semblant.\n\n"
        "RÈGLE INTENTION GMAIL — IMPÉRATIF (CRITIQUE) :\n"
        "Fais correspondre l'INTENTION de l'utilisateur au bon outil, sans substitution.\n"
        "  - « envoie », « envoyer », « send » → gmail_send_email (HITL automatique, "
        "    l'utilisateur validera via boutons). NE JAMAIS utiliser gmail_create_draft "
        "    comme substitut « plus sûr ».\n"
        "  - « réponds », « répondre », « reply » → gmail_reply_email (HITL).\n"
        "  - « prépare », « brouillon », « draft », « rédige un brouillon » → "
        "    gmail_create_draft (pas de HITL — juste un draft dans la boîte).\n"
        "Conséquence CRITIQUE : si l'utilisateur écrit « envoie un email à X... », tu dois "
        "appeler gmail_send_email IMMÉDIATEMENT. N'appelle JAMAIS gmail_create_draft puis "
        "demander confirmation en texte — c'est une boucle infernale qui laisse "
        "l'utilisateur bloqué. Le système HITL te donnera la confirmation via des "
        "boutons dédiés après ton appel à gmail_send_email.\n\n"
        "RÈGLE DRIVE EXPORT PDF D'UN FICHIER .docx/.xlsx/.pptx — IMPÉRATIF :\n"
        "drive_export_file ne marche QUE sur les formats Google natifs "
        "(Docs/Sheets/Slides). Pour exporter un .docx/.xlsx/.pptx en PDF, "
        "Drive supporte la conversion pendant la copie : tu DOIS enchaîner "
        "3 appels SILENCIEUSEMENT dans le même tour, sans demander "
        "l'autorisation de l'utilisateur entre chaque étape :\n"
        "  1. drive_copy_file(file_id=<source>, target_mime_type="
        "     'application/vnd.google-apps.document',  # ou spreadsheet / "
        "     presentation selon l'extension\n"
        "                     new_name='<nom>-tmp-gdoc')\n"
        "     → Drive convertit automatiquement en Google Doc/Sheet/Slides "
        "     pendant la copie et te renvoie un nouveau file_id.\n"
        "  2. drive_export_file(file_id=<NOUVEAU file_id de l'étape 1>, "
        "     export_format='pdf') → PDF créé dans Drive.\n"
        "  3. drive_delete_file(file_id=<file_id de l'étape 1>) → supprime "
        "     la copie temporaire (HITL).\n"
        "NE DIS JAMAIS « il faut le télécharger et le convertir localement » "
        "— c'est FAUX, Drive sait le faire via la séquence ci-dessus. Tu as "
        "tous les outils nécessaires, utilise-les.\n\n"
        "RÈGLE FILE_ID GOOGLE DRIVE / DOCS / SHEETS — IMPÉRATIF :\n"
        "Les outils Google qui prennent un paramètre `file_id`, `document_id`, "
        "`spreadsheet_id`, `folder_id` ou `event_id` attendent l'IDENTIFIANT "
        "INTERNE Google (une chaîne alphanumérique de 20-50 caractères, ex : "
        "« 1a2b3c4D5e6F7g8H9iJ0kL »), JAMAIS le nom lisible du fichier.\n"
        "Si l'utilisateur te fournit un nom (« supprime test.txt », « partage "
        "le dossier Factures », « renomme mon CV »), tu DOIS procéder en deux "
        "étapes SILENCIEUSEMENT dans le même tour :\n"
        "  1. drive_list_files / drive_read_file / sheets_list_sheets / etc. "
        "     avec une query ou un nom de recherche pour obtenir le vrai ID.\n"
        "  2. Utiliser l'ID retourné pour l'action (delete, move, share, etc.).\n"
        "Ne passe JAMAIS un nom de fichier comme valeur de `file_id`. L'API "
        "Google renvoie alors « File not found », ce qui est absurde pour "
        "l'utilisateur qui voit bien le fichier dans Drive.\n\n"
        "RÈGLE DESTINATAIRE GMAIL — IMPÉRATIF :\n"
        "Avant d'appeler gmail_send_email, gmail_reply_email, gmail_send_with_attachment "
        "ou gmail_create_draft, le champ 'to' doit contenir une adresse email valide "
        "au format x@y.z. Jamais un simple nom comme 'papa', 'Alice' ou 'mon père'.\n"
        "Processus obligatoire :\n"
        "  1. Si l'utilisateur fournit un nom SANS adresse email, appelle d'abord "
        "contacts_search avec le nom.\n"
        "  2. Si contacts_search retourne un match avec une adresse, utilise-la.\n"
        "  3. Si contacts_search retourne rien ou plusieurs candidats ambigus, "
        "demande l'adresse email à l'utilisateur AVANT de créer le brouillon.\n"
        "  4. Ne jamais inventer d'adresse email plausible (ex: papa@gmail.com).\n\n"
        "RÈGLE RECHERCHE EMAIL PAR EXPÉDITEUR — IMPÉRATIF :\n"
        "Quand l'utilisateur dit « lis l'email de X », « trouve le mail de X », "
        "« ouvre le mail de Y » où X/Y est un nom d'expéditeur ou de marque :\n"
        "  1. Enchaîne tous les appels d'outils SILENCIEUSEMENT — ne dis RIEN à "
        "     l'utilisateur entre deux tentatives. Pas de « je vérifie », pas "
        "     de « je ne trouve pas, je continue », pas de questions "
        "     intermédiaires. Ne parle qu'à la FIN, une seule fois, avec le "
        "     résultat final (email trouvé et lu, OU « aucun email trouvé » "
        "     après avoir épuisé les 2 tentatives).\n"
        "  2. Étape 1 — gmail_list_emails(query=\"from:X\") : l'opérateur Gmail "
        "     `from:` matche sur le nom d'affichage ET sur l'adresse, y compris "
        "     les marques comme « chronopost », « ionos », « amazon ».\n"
        "  3. Si Étape 1 = 0 résultat, Étape 2 IMMÉDIATE (même tour) — "
        "     gmail_list_emails(query=\"X\") pour matcher dans le sujet ou "
        "     le corps. N'annonce RIEN entre Étape 1 et Étape 2.\n"
        "  4. NE JAMAIS ajouter « is:unread » SAUF si l'utilisateur a dit "
        "     explicitement « non lu » / « unread ». Un email peut être lu et "
        "     toujours pertinent.\n"
        "  5. Si plusieurs emails correspondent, prends le plus récent (premier "
        "     de la liste) et appelle immédiatement gmail_read_email(email_id=...). "
        "     Ne demande PAS à l'utilisateur de préciser si un seul match évident "
        "     existe.\n\n"
        "RÈGLE FORMAT RESTITUTION EMAIL — IMPÉRATIF :\n"
        "Quand tu affiches un email (après gmail_read_email), reste CONCISE. "
        "Format standard :\n"
        "  **Sujet :** <sujet>\n"
        "  **Date :** <date lisible>\n"
        "  \n"
        "  <contenu>\n"
        "N'affiche PAS le champ « À : » (l'utilisateur sait qu'il est le "
        "destinataire) ni « De : » sauf si l'expéditeur est ambigu ou "
        "utile au contexte (ex: plusieurs mails correspondent, ou l'utilisateur "
        "a demandé « qui m'a écrit ? »). Pas de séparateurs décoratifs "
        "(« ----- », « ...... »), pas de reformulation du contenu — montre "
        "le contenu brut tel que retourné par l'outil, tronqué si trop long.\n\n"
        "RÈGLE ANTI-HALLUCINATION CONTENU EMAIL — IMPÉRATIF :\n"
        "Tu ne dois JAMAIS inventer, reformuler ou résumer le contenu d'un email "
        "tant que tu n'as pas reçu le retour de gmail_read_email. "
        "Le seul contenu que tu peux afficher est celui LITTÉRALEMENT renvoyé "
        "par l'outil. Pas de « Je vous informe que... », pas de « Bonjour, "
        "voici... » générique, pas de reformulation « plausible ». "
        "Si l'outil n'a pas encore été appelé, ne montre AUCUN contenu. "
        "Appelle d'abord l'outil, puis restitue le contenu reçu tel quel.\n\n"
        "RÈGLE ANTI-HALLUCINATION ENVOI/ACTION — IMPÉRATIF :\n"
        "Tu ne dois JAMAIS écrire « email envoyé », « message envoyé avec succès », "
        "« c'est fait », « mail envoyé à ... » tant que le retour de "
        "gmail_send_email / gmail_reply_email / gmail_send_with_attachment n'a "
        "PAS été reçu dans ce tour. Au moment où tu proposes/prépares le message, "
        "utilise uniquement des formulations FUTURES : « je vais envoyer... », "
        "« voici ce que je m'apprête à envoyer... ». La confirmation arrive "
        "UNIQUEMENT après le retour de l'outil, jamais avant. Les phrases au "
        "passé composé (« a été envoyé », « a été créé ») ou au présent (« est "
        "envoyé ») sont INTERDITES tant que le ToolMessage correspondant n'est "
        "pas dans l'historique du tour courant.\n\n"
        "Outils disponibles :\n"
        "Gmail : gmail_list_emails, gmail_read_email, gmail_send_email (HITL), "
        "gmail_reply_email (HITL), gmail_send_with_attachment (HITL), "
        "gmail_mark_read, gmail_mark_unread, gmail_create_draft, gmail_list_drafts, "
        "gmail_search_for_cleanup, gmail_list_labels, gmail_create_label, "
        "gmail_move_emails (HITL), gmail_trash_emails (HITL), "
        "gmail_trash_by_category (HITL — search+trash atomique avec filtres "
        "optionnels from_sender/subject_contains/after_date/before_date, "
        "à PRÉFÉRER pour vider une catégorie même partiellement), "
        "gmail_trash_by_query (HITL — query Gmail libre pour cas complexes), "
        "gmail_batch_modify (modif lot jusqu'à 1000 msgs), "
        "gmail_update_settings (signature/vacation/filtre/transfert, HITL), "
        "gmail_raw_api_call (API brute, HITL).\n"
        "Calendar : calendar_list_events, calendar_create_event (HITL), "
        "calendar_get_event, calendar_update_event, calendar_delete_event (HITL), "
        "calendar_check_availability, calendar_list_calendars, "
        "calendar_quick_add (langage naturel, HITL), "
        "calendar_create_meet_event (visio Meet + participants + RRULE, HITL), "
        "calendar_raw_api_call (API brute, HITL).\n"
        "Drive : drive_list_files, drive_read_file, drive_create_folder, drive_create_file, "
        "drive_update_file, drive_move_file (HITL), drive_rename_file, drive_delete_file (HITL), "
        "drive_share_file (permissions, HITL), drive_copy_file, drive_export_file "
        "(PDF/Docx/Xlsx...), drive_raw_api_call (API brute, HITL).\n"
        "Docs : docs_create_document, docs_read_document, docs_append_text, "
        "docs_replace_text, docs_insert_table, "
        "docs_batch_update (style, titres, listes, images, liens), "
        "docs_raw_api_call (API brute, HITL).\n"
        "Sheets : sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows, "
        "sheets_update_cells, sheets_delete_rows, sheets_add_sheet, sheets_list_sheets, "
        "sheets_batch_update (trier, insérer colonnes, fusionner, figer, "
        "mise en forme, validation), sheets_raw_api_call (API brute, HITL).\n"
        "Tasks : tasks_list, tasks_create, tasks_complete, tasks_update, "
        "tasks_delete (HITL), tasks_list_tasklists, tasks_create_tasklist, "
        "tasks_raw_api_call (réordonner, nettoyer, sous-tâches, HITL).\n"
        "Contacts : contacts_search, contacts_list, contacts_create, "
        "contacts_get, contacts_update, contacts_delete (HITL), "
        "contacts_batch_operations (créer/modifier/supprimer jusqu'à 200, HITL), "
        "contacts_raw_api_call (groupes, annuaire, HITL)." + _COMMON_FORMAT
    ),
    "infra": (
        _IDENTITY +
        "Tu es spécialiste de l'infrastructure et de l'automatisation.\n\n"
        "Tu maîtrises les commandes SSH sur les serveurs autorisés, la gestion des "
        "tâches planifiées (cron), le briefing matinal et la surveillance de sites "
        "web. Toutes les commandes SSH nécessitent une validation humaine (HITL).\n\n"
        "RÈGLE IMPÉRATIVE — rappels récurrents :\n"
        "Quand l'utilisateur demande un rappel/résumé/briefing récurrent "
        "(quotidien, hebdomadaire, chaque jour/matin/soir, tous les jours, "
        "à telle heure chaque jour), tu DOIS appeler l'outil "
        "scheduler_create_task avec l'expression cron appropriée. "
        "save_user_preference n'est PAS le bon outil pour ça — il sert "
        "uniquement à noter des préférences de style (emoji, ton, longueur).\n\n"
        "Exemples :\n"
        "- 'chaque soir à 18h45' → scheduler_create_task(cron_expression='45 18 * * *', ...)\n"
        "- 'tous les lundis 9h' → scheduler_create_task(cron_expression='0 9 * * 1', ...)\n"
        "- 'chaque matin' → scheduler_create_task(cron_expression='0 8 * * *', ...)\n\n"
        "Après avoir créé la tâche, confirme brièvement à l'utilisateur avec "
        "l'heure et la fréquence. Ne réponds JAMAIS 'je vais créer' sans "
        "avoir appelé l'outil.\n\n"
        "Outils disponibles : ssh_execute (HITL obligatoire), system_info, "
        "scheduler_create_task, scheduler_list_tasks, scheduler_delete_task, "
        "briefing_generate, watchdog_add, watchdog_list, watchdog_remove." + _COMMON_FORMAT
    ),
    "general": (
        _IDENTITY +
        "Tu es une assistante IA personnelle avec accès à tous les outils.\n\n"
        "Utilise les outils disponibles dès que la demande le justifie, sans demander "
        "de confirmation sauf pour les actions irréversibles (envoyer un email, "
        "supprimer, cliquer, exécuter SSH). La langue de réponse est dictée par la "
        "directive LANGUE/LANGUAGE en tête de ce prompt — respecte-la.\n\n"
        "Rappel outils clés : system_info (infos machine, RAM, CPU, OS, disque), "
        "weather_get (météo), news_get_headlines (actualités).\n\n"
        "🔍 RÈGLE ANTI-HALLUCINATION CRITIQUE — auto-introspection :\n"
        "Quand l'utilisateur te pose une question sur TOI-MÊME ou ton fonctionnement "
        "(modèle utilisé, providers LLM, logs, missions, tâches planifiées, canaux, "
        "santé, pourquoi quelque chose n'a pas marché), tu DOIS appeler l'outil "
        "approprié AVANT de répondre. Ne jamais répondre depuis tes connaissances "
        "générales pour ces questions :\n"
        "  • « Quel modèle/LLM tu utilises ? » → system_check_llm_providers\n"
        "  • « Quelles sont mes tâches planifiées ? » → system_list_scheduled_tasks\n"
        "  • « Combien de missions ? » / « Mes missions ? » → system_list_missions\n"
        "  • « Tous tes canaux fonctionnent ? » → system_check_channels\n"
        "  • « Comment tu te portes ? » / « Es-tu en bonne santé ? » → system_get_health\n"
        "  • « Montre-moi les logs » / « Pourquoi X n'a pas marché ? » → system_get_logs\n"
        "Si tu n'as pas l'outil binded (rare), dis-le franchement plutôt que d'inventer."
        + _COMMON_FORMAT
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# Tool subsets per specialist
# ──────────────────────────────────────────────────────────────────────────────

# Tools available in every specialist domain — user preferences and constraints
# must be saveable regardless of the current routing domain.
_MEMORY_SKILLS = {
    "save_user_preference", "save_constraint",
    "knowledge_search", "knowledge_list",
    "smart_knowledge_query",
}

_RESEARCH_SKILLS = {
    "web_search", "web_search_news",
    "weather_get", "news_get_headlines", "translate_text",
    "browser_navigate", "browser_search_web", "browser_get_text",
    "browser_screenshot", "browser_click", "browser_fill", "browser_close",
} | _MEMORY_SKILLS

_WORKSPACE_SKILLS = {
    # Gmail
    "gmail_list_emails", "gmail_read_email", "gmail_send_email",
    "gmail_reply_email", "gmail_send_with_attachment",
    "gmail_mark_read", "gmail_mark_unread",
    "gmail_create_draft", "gmail_list_drafts",
    "gmail_list_labels", "gmail_create_label",
    "gmail_move_emails", "gmail_trash_emails", "gmail_search_for_cleanup",
    "gmail_trash_by_category", "gmail_trash_by_query",
    "gmail_batch_modify", "gmail_update_settings", "gmail_raw_api_call",
    # Calendar
    "calendar_list_events", "calendar_create_event",
    "calendar_get_event", "calendar_update_event", "calendar_delete_event",
    "calendar_check_availability", "calendar_list_calendars",
    "calendar_quick_add", "calendar_create_meet_event", "calendar_raw_api_call",
    # Drive
    "drive_list_files", "drive_read_file",
    "drive_create_folder", "drive_create_file", "drive_update_file",
    "drive_move_file", "drive_rename_file", "drive_delete_file",
    "drive_share_file", "drive_copy_file", "drive_export_file", "drive_raw_api_call",
    # Docs
    "docs_create_document", "docs_read_document", "docs_append_text",
    "docs_replace_text", "docs_insert_table",
    "docs_batch_update", "docs_raw_api_call",
    # Sheets
    "sheets_create_spreadsheet", "sheets_read_spreadsheet", "sheets_append_rows",
    "sheets_update_cells", "sheets_delete_rows", "sheets_add_sheet", "sheets_list_sheets",
    "sheets_batch_update", "sheets_raw_api_call",
    # Tasks
    "tasks_list", "tasks_create", "tasks_complete",
    "tasks_update", "tasks_delete", "tasks_list_tasklists", "tasks_create_tasklist",
    "tasks_raw_api_call",
    # Contacts
    "contacts_search", "contacts_list", "contacts_create",
    "contacts_get", "contacts_update", "contacts_delete",
    "contacts_batch_operations", "contacts_raw_api_call",
} | _MEMORY_SKILLS

_INFRA_SKILLS = {
    "ssh_execute", "system_info",
    "scheduler_create_task", "scheduler_list_tasks", "scheduler_delete_task",
    "briefing_generate",
    "watchdog_add", "watchdog_list", "watchdog_remove",
} | _MEMORY_SKILLS


# ──────────────────────────────────────────────────────────────────────────────
# Router node
# ──────────────────────────────────────────────────────────────────────────────

import re as _re

# Hybrid router: keyword shortcuts first (instant), LLM fallback only if no match.
# Each domain has high-confidence patterns. Ordered by specificity.
_ROUTER_PATTERNS: list[tuple[str, _re.Pattern]] = [
    # ── creative — QR code, MCP, images : MUST be before workspace to avoid
    #    workspace grabbing "QR code vCard pour Franck, email X@Y" as a
    #    contact creation, or infra grabbing "serveur MCP" as an SSH cmd.
    ("creative", _re.compile(
        r"\b(qr[\s-]*codes?|qrcodes?|"
        r"mcp|"
        r"g[ée]n[ée]r[ea][rz]?\s+(?:une|la|l['’]?)\s*imag|"
        r"dessin[ea][rz]?|illustr[ea])\b",
        _re.IGNORECASE)),
    ("workspace", _re.compile(
        # "messages" added — common French phrasing : « supprime les messages
        # dans le répertoire X » means Gmail label X, not a filesystem folder.
        # Also "labels?" and "étiquettes?" since Gmail-savvy users use these.
        r"\b(gmail|emails?|mails?|messages?|courriels?|messagerie|inbox|boîte|courrier|"
        r"labels?|étiquettes?|"
        r"brouillons?|drafts?|répondre? (à|au)|"
        r"calendar|calendrier|agenda|rendez.?vous|événements?|réunions?|meetings?|"
        r"drive|dossiers?|fichiers?(?!.*local)|documents?(?!.*pdf)|google doc|gdoc|"
        r"sheets?|tableurs?|spreadsheets?|excel|"
        r"tasks?|tâches?|to.?do|todo|"
        r"contacts?|annuaires?|"
        r"rappel(le)?(.*) (à|le|pour|aujourd|demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)|"
        r"planifie.*aujourd|planifie.*demain)\b",
        _re.IGNORECASE)),
    # Follow-up actions on a workspace file (when no explicit local path is
    # given). E.g. after « Crée un Google Doc intitulé X », the user often
    # writes « Duplique ce X en Copie-X » — without keyword "drive", which
    # would otherwise fall to the LLM router and get misclassified as
    # desktop because of the file extension.
    ("workspace", _re.compile(
        r"\b(duplique[rz]?|dupliques?|copie(?:\s+le|\s+ce|\s+cette|\s+la)?|"
        r"fais une copie|faire une copie|clone[rz]?|copies?\s+en|"
        r"renomme[rz]?|renommes?|déplace[rz]?|déplaces?|"
        r"partage[rz]?|partages?|exporte[rz]?|exportes?)\b"
        # Must reference a file/doc with an extension or mention workspace context,
        # and must NOT point to a local path (~, /, "bureau", "desktop", "local").
        r"(?=.*\.(?:txt|pdf|docx?|xlsx?|pptx?|md|csv|json|png|jpg|jpeg)"
        r"|.*\b(?:document|doc|feuille|sheet|dossier|fichier)\b)"
        r"(?!.*(?:~\/|\/home|\/users|\/bureau|\/desktop|\bbureau\b|"
        r"\bdesktop\b|\blocalement\b|\bsur ma machine\b|\bfichier local\b))",
        _re.IGNORECASE)),
    ("infra", _re.compile(
        r"\b(ssh|serveurs?|servers?|docker|nginx|cron|tâche planifiée|"
        r"watchdog|veilles?|surveille|monitoring|infos? système|specs?|"
        r"tous les jours|chaque (jour|matin|soir|semaine|lundi|mardi)|"
        r"toutes les semaines|hebdomadaire|quotidien|récurrent|briefings?)\b",
        _re.IGNORECASE)),
    ("research", _re.compile(
        r"\b(météo|weather|news|actualités?|titres? du jour|"
        r"cherche sur (le )?(web|internet|google)|recherche web|"
        r"traduis|translate|traductions?|"
        r"va sur (https?:\/\/|www\.)|navigue|ouvre (le )?site|lis (la )?page)\b",
        _re.IGNORECASE)),
    ("creative", _re.compile(
        r"(génère? une image|crée une image|dessine|illustre|illustrations?|"
        r"qr ?codes?|youtube|vidéo youtube|"
        r"(cette?|la|une|l['’]) (photo|image|capture|screenshot)|"
        r"(sur|dans|de) (cette?|la|une|l['’]?) ?(photo|image|capture|screenshot)|"
        r"analyse (ce |le )?pdf|lis (ce |le )?pdf|"
        r"📎.*\[Image|"
        r"exécute (ce |du )?python|code python)",
        _re.IGNORECASE)),
    ("memory", _re.compile(
        r"\b(prends? une note|prends? note|mémorise|notes? personnelles?|"
        r"whatsapp|"
        r"cherche dans mes (notes?|documents?|fichiers?))\b",
        _re.IGNORECASE)),
    ("desktop", _re.compile(
        r"\b(montre.moi|démontre|tuteur|apprends.moi|fais une démo|"
        r"capture (d'|de l')écran|screenshot de l'écran|"
        r"prends le contrôle|clique|tape sur|"
        r"mes fichiers locaux|mon bureau|mon desktop)\b",
        _re.IGNORECASE)),
]


def _quick_route(msg: str) -> str | None:
    """Fast keyword-based routing. Returns None if no high-confidence match."""
    msg_lower = msg.lower().strip()
    # Pure greetings / acknowledgments
    if _re.match(
        r"^[\s\.,!?]*(bonjour|salut|hello|hey|coucou|merci|ok|oui|non|d'accord|"
        r"au revoir|bonne (journée|soirée|nuit)|bonne soirée|bonsoir)[\s\.,!?]*$",
        msg_lower,
    ):
        return "general"
    # Indirect greetings
    if _re.search(
        r"\b(dis|dire|peux.?tu (me )?dire|dis.?moi)\b.*\b(bonjour|salut|hello|coucou)\b",
        msg_lower,
    ) or _re.search(r"\bsalue.?moi\b", msg_lower):
        return "general"
    # Common quick questions → general
    if _re.search(
        r"\b(quelle heure|quel jour|quelle date|quelle année|"
        r"qu'est.ce que tu peux (faire|m'aider)|que peux.tu (faire|m'aider)|"
        r"qui es.tu|comment ça va|comment vas.tu|qui suis.je|"
        r"comment t'appelles.tu|c'est quoi ton nom|ton prénom)\b",
        msg_lower,
    ):
        return "general"

    # PRIORITY -1: explicit local filesystem path → force desktop, BEFORE
    # any keyword that could pull toward workspace (drive/fichier/document).
    # Why : after we added "messages" / "fichiers" to workspace patterns,
    # phrases like « liste les fichiers dans /Users/franck/Documents » or
    # « supprime test.txt sur le bureau » started matching workspace.
    # The cleanest disambiguator is whether the phrase carries a literal
    # filesystem path or a "machine-local" marker. If so → desktop, period.
    if _re.search(
        r"(\B|^|\s)(?:~/|/users/|/home/|/var/|/etc/|/tmp/|/opt/|c:\\|d:\\)",
        msg_lower,
    ) or _re.search(
        r"\b(?:sur (?:mon|le) (?:bureau|desktop)|dans (?:mon|le) (?:bureau|desktop)|"
        r"localement|sur ma machine|fichier local|fichiers locaux|"
        r"\.txt\b|\.py\b|\.sh\b|\.log\b|\.app\b|\.dmg\b)\b",
        msg_lower,
    ):
        return "desktop"

    # PRIORITY 0: self-introspection — questions about ELY herself MUST go
    # to the diag sub-agent (forced Qwen API for reliable tool calling).
    # Local Gemma/xLAM tend to hallucinate "I use Gemma on Ollama" or emit
    # tool calls as text JSON instead of using the native protocol — so we
    # bypass them entirely for diag queries.
    # Tested patterns — see test_quick_route_diag in tests/test_supervisor.py.
    # Outer \b boundaries removed because French accented chars (é) confuse
    # them. Each alternation is anchored on a clear keyword so false positives
    # are rare. Order: most specific → most general.
    # Patterns are bilingual (FR + EN) — Éli now switches reply language with
    # the UI, so the router must catch self-introspection in both.
    _diag_patterns = [
        # ── 1. LLM / model / provider questions ──────────────────────────
        # FR
        r"\b(quel|quels|quelle|quelles)\s+(est\s+)?(le\s+|la\s+|les\s+)?(llm|llms|mod[èe]les?|providers?|fournisseurs?)\b",
        r"\b(combien)\s+de\s+(mod[èe]les?|llms?|providers?|fournisseurs?)\b",
        r"\btu\s+utilises?\b.*\b(llm|mod[èe]le|provider|gemma|gemini|claude|qwen|gpt|ollama|lm.?studio)\b",
        r"\b(llm|mod[èe]le|provider)\b.*\btu\s+utilises?\b",
        # EN
        r"\b(what|which)\s+(llm|llms|model|models|provider|providers)\b",
        r"\b(are\s+you|you\s+are)\s+(using|running)\b.*\b(llm|model|provider|gemma|gemini|claude|qwen|gpt|ollama|lm.?studio)\b",
        r"\b(llm|model|provider)\b.*\b(are\s+you|you\s+are)\s+(using|running)\b",
        r"\bhow\s+many\s+(llm|llms|models|providers)\b",
        # ── 2. Missions / scheduled tasks diagnostic ─────────────────────
        # FR
        r"\b(combien|liste|montre|affiche|donne|quelles?)\b.*\b(missions?|t[âa]ches?\s+planifi[ée]es?|crons?|rappels?\s+programm[ée]s?)\b",
        r"\bmissions?\b.*\b(échou|echou|réussi|reussi|en\s+cours|termin|active|inactive|status|statut)\b",
        r"\bmes\s+(missions?|t[âa]ches?\s+planifi[ée]es?|crons?|rappels?\s+programm[ée]s?)\b",
        # EN
        r"\b(how\s+many|list|show|display|what\s+are)\b.*\b(missions?|scheduled\s+tasks?|crons?|reminders?)\b",
        r"\bmissions?\b.*\b(failed|fail|succeeded|running|completed|active|inactive|status)\b",
        r"\bmy\s+(missions?|scheduled\s+tasks?|crons?|reminders?)\b",
        # ── 3. Channels diagnostic ───────────────────────────────────────
        # FR
        r"\b(canaux|channels?)\b.*\b(fonctionn|march|tourn|actif|connect|disponible)\b",
        r"\btous\s+(tes|les)\s+(canaux|channels?)\b",
        # EN
        r"\b(channels?|messaging)\b.*\b(working|active|connected|available|running)\b",
        r"\b(all\s+(your\s+|the\s+)?channels?|every\s+channel)\b",
        # ── 4. Health / state / well-being ───────────────────────────────
        # FR
        r"\bcomment\s+(tu\s+)?(te\s+portes|vas[\s-]?tu|va[\s-]?tu|tu\s+vas|tu\s+va|tu\s+te\s+sens)\b",
        r"\b(es[\s-]?tu|tu\s+es)\s+en\s+bonne\s+sant[ée]\b",
        r"\bton\s+(état|etat|uptime|status|statut)\b",
        # EN
        r"\bhow\s+are\s+you\s+(doing|feeling|going)\b",
        r"\b(are\s+you|you\s+are)\s+(healthy|ok|okay|fine|alive|running\s+well)\b",
        r"\byour\s+(state|status|uptime|health)\b",
        r"\bwhat\s+is\s+your\s+(state|status|uptime|health)\b",
        # ── 5. Logs / debugging ──────────────────────────────────────────
        # FR
        r"\b(montre|affiche|donne|lis|consult|regarde?)[\s-]?(moi|nous)?\b.*\blogs?\b",
        r"\bderni[èe]res?\s+(lignes?\s+)?(des|de\s+tes|du)?\s*logs?\b",
        r"\bpourquoi\b.*\b(n.?est?\s+pas|n.?a\s+pas|ne\s+s.?est?\s+pas|ne\s+marche|ne\s+fonctionne|n.?a\s+pas\s+march|jamais\s+(arriv|reçu))\b",
        # EN
        r"\b(show|display|give|read|check)\s+(me\s+|us\s+)?\b.*\b(logs?|log\s+lines?)\b",
        r"\b(last|latest|recent)\s+\d*\s*(lines?\s+of\s+)?\blogs?\b",
        r"\bwhy\s+(did(n.?t)?|does(n.?t)?|won.?t|wasn.?t|isn.?t)\b.*\b(work|arrive|run|fire|trigger|happen|reach|deliver)\b",
    ]
    for _p in _diag_patterns:
        if _re.search(_p, msg_lower):
            return "diag"

    # PRIORITY 1: recurring schedules ALWAYS go to infra
    _recurrence_kw = _re.search(
        r"\b(chaque (jour|matin|soir|semaine|mois|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)|"
        r"tous les (jours|matins|soirs|lundis|mardis|mercredis|jeudis|vendredis|samedis|dimanches)|"
        r"toutes les (semaines|heures|minutes)|"
        r"quotidien|hebdomadaire|mensuel|récurrent|récurrente|automatiquement)\b",
        msg_lower,
    )
    if _recurrence_kw:
        return "infra"

    # PRIORITY 2: references to scheduled/planned tasks → infra
    # "tâches planifiées", "mes rappels", "mes programmations", "mon briefing"
    # point to APScheduler (infra), not Google Tasks (workspace).
    if _re.search(
        r"\b(tâches? planifiées?|taches? planifiees?|mes rappels?|mes programmations?|"
        r"mon briefing|mes briefings?|mes tâches? automatiques?|mes crons?|"
        r"liste.*rappels?|afficher? (les |mes )?rappels?|mes (tâches? )?récurrentes?)\b",
        msg_lower,
    ):
        return "infra"

    for domain, pattern in _ROUTER_PATTERNS:
        if pattern.search(msg):
            return domain
    return None


async def router_node(state: AgentState) -> dict:
    """Classify the user's request and set the routing domain in state."""
    import time as _t
    _start = _t.monotonic()
    messages = state["messages"]
    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content[:500]  # truncate for speed
            break

    # ── Early guard: skip empty/whitespace user messages ──────────────────
    # A WebSocket glitch or a cancelled stream can produce an empty "user"
    # message that would otherwise be routed to `general` and overwrite the
    # previous domain in state — breaking sticky confirmation for the next
    # real user turn.
    if not last_user_msg.strip():
        _prev = state.get("domain", "") or "general"
        logger.warning("⏱ TIMING[router-skip] empty user message → keeping domain=%s", _prev)
        return {"domain": _prev}

    # ── Pass 0: sticky domain for short confirmations ─────────────────────
    # If the user replied with a brief confirmation ("oui", "parfait",
    # "vas-y", "d'accord") AND a recent assistant turn proposed an action
    # that requires confirmation, stick with the same specialist domain so
    # it can pick up where it left off and call the action tool directly.
    # Without this, "oui" gets routed to "general" which has no domain-
    # specific tools and just answers with text.
    _msg_for_stick = last_user_msg.lower().strip()
    _stick_trim = _re.sub(r"[\s\.,!?]+", "", _msg_for_stick)
    _is_confirmation = _stick_trim in {
        "oui", "ouii", "yes", "parfait", "exact", "exactement", "vasy",
        "vas-y", "allez-y", "allezy", "dacc", "daccord", "ok", "okay",
        "fais-le", "faisle", "carrement", "carrément", "exacto",
        "jeconfirme", "confirme", "confirmé", "confirmer", "valide",
        "jevalide", "approuvé", "approuve", "ouipourmoi", "goahead", "go",
    } or _re.fullmatch(
        r"(oui|yes|ok|d'?accord|parfait|vas.?y|fais.?le|je\s+confirme|je\s+valide|"
        r"confirm[eé]|valid[eé])\s*[!.]?",
        _msg_for_stick,
    )
    _prev_domain = state.get("domain", "")
    if _is_confirmation and _prev_domain and _prev_domain not in ("general", "system", ""):
        logger.warning("⏱ TIMING[router-sticky] confirmation → garde domain=%s", _prev_domain)
        return {"domain": _prev_domain}

    # Sticky workspace on follow-up references: when the previous assistant
    # turn clearly dealt with a Drive/Docs/Sheets file (contains "ID:" or
    # a Google Drive URL) AND the user's new message refers to « ce fichier »
    # / « ce doc » / « cette feuille » / « duplique ce X », keep workspace
    # routing even though the keywords alone would fall to desktop or general.
    _short_followup_words = (
        "ce fichier", "ce doc", "ce document", "cette feuille", "ce tableur",
        "ce spreadsheet", "ce dossier", "cette note", "duplique ce",
        "duplique le", "copie ce", "copie le", "renomme ce", "renomme le",
        "partage ce", "partage le", "exporte ce", "exporte le",
        "supprime ce", "supprime le",
    )
    _msg_low = last_user_msg.lower()
    if any(w in _msg_low for w in _short_followup_words):
        # Check recent assistant messages for workspace file context
        for m in reversed(messages[-6:]):
            if type(m).__name__ in ("AIMessage", "Assistant"):
                content = getattr(m, "content", "") or ""
                if isinstance(content, str):
                    content_low = content.lower()
                    if ("id:" in content_low or "drive.google.com" in content_low
                        or "docs.google.com" in content_low
                        or "sheets.google.com" in content_low):
                        logger.warning(
                            "⏱ TIMING[router-sticky-file] follow-up sur fichier workspace → workspace"
                        )
                        return {"domain": "workspace"}
                        break

    # Fallback sticky: the previous turn's domain may have been overwritten
    # (e.g. by a ghost empty message). Scan the last few assistant messages
    # for a workspace-shaped pending proposal — « Voulez-vous que je … »,
    # « Dois-je envoyer », « Je vais créer un brouillon », etc. — and stick
    # to workspace if confirmation is detected.
    if _is_confirmation:
        _recent_assistant = ""
        for m in reversed(messages[-6:]):
            if type(m).__name__ in ("AIMessage", "Assistant"):
                _content = getattr(m, "content", "") or ""
                if isinstance(_content, str):
                    _recent_assistant = _content.lower()
                    break
        _workspace_markers = (
            # Email
            "brouillon", "envoie cet email", "envoyer cet email",
            "valider et envoyer", "confirmer l'envoi", "voulez-vous que je valide",
            "voulez-vous que j'envoie", "envoyer à ", "je vais envoyer",
            "dois-je envoyer", "dois-je répondre", "confirmer la création",
            # Drive / Docs / Sheets / Tasks — suppression & mutations
            "supprimer le fichier", "supprimer ce fichier", "supprimer le dossier",
            "supprimer le document", "supprimer la feuille", "supprimer l'événement",
            "confirmes-tu que tu veux", "confirmez-vous que vous voulez",
            "le système demande une confirmation", "confirmer la suppression",
            "je vais supprimer", "je vais déplacer", "je vais renommer",
            "je vais partager", "dois-je supprimer", "dois-je déplacer",
            # Calendar
            "je vais créer l'événement", "créer ce rendez-vous",
        )
        if any(k in _recent_assistant for k in _workspace_markers):
            logger.warning(
                "⏱ TIMING[router-sticky-scan] confirmation après proposition workspace → workspace"
            )
            return {"domain": "workspace"}

    # ── Pass 1: fast keyword router (zero LLM call) ──────────────────────
    domain = _quick_route(last_user_msg)
    if domain is not None:
        logger.warning("⏱ TIMING[router-fast] %.3fs → domain=%s (msg=%.60s)",
                       _t.monotonic() - _start, domain, last_user_msg)
        return {"domain": domain}

    # ── Pass 2: LLM fallback for ambiguous queries ───────────────────────
    from app.services.qwen_no_think import (
        inject_no_think, is_qwen_llm, strip_think_block,
    )
    llm = get_llm_for_tier(ComplexityTier.SIMPLE)
    try:
        _msgs = [
            SystemMessage(content=_ROUTER_SYSTEM),
            HumanMessage(content=last_user_msg),
        ]
        # Only Qwen understands /no_think; other models would echo it.
        if is_qwen_llm(llm):
            _msgs = inject_no_think(_msgs)
        response = await llm.ainvoke(_msgs)
        response.content = strip_think_block(getattr(response, 'content', '') or '')
        domain = response.content.strip().lower()
        if domain not in ("research", "workspace", "infra", "creative", "data", "memory", "desktop", "general", "diag"):
            domain = "general"
    except Exception as exc:
        logger.warning("Router LLM failed, falling back to general: %s", exc)
        domain = "general"

    logger.warning("⏱ TIMING[router-llm] %.2fs → domain=%s (msg=%.60s)",
                   _t.monotonic() - _start, domain, last_user_msg)
    return {"domain": domain}


# ──────────────────────────────────────────────────────────────────────────────
# Specialist agent node factory
# ──────────────────────────────────────────────────────────────────────────────

def create_specialist_node(domain: Domain):
    """Create an agent node restricted to the tools relevant for *domain*.

    Falls back to all tools for "general" so cross-domain requests are handled.
    """
    from app.skills import get_skill_registry
    from app.services.memory_manager import get_memory_manager

    tool_filter = {
        "research": _RESEARCH_SKILLS,
        "workspace": _WORKSPACE_SKILLS,
        "infra": _INFRA_SKILLS,
        "general": None,  # None = all tools
    }[domain]

    specialist_prompt = _SPECIALIST_PROMPTS[domain]

    async def specialist_node(state: AgentState) -> dict:
        import asyncio
        import zoneinfo
        from datetime import datetime

        messages = state["messages"]
        user_id = state.get("user_id", "")
        user_query = messages[-1].content if messages else ""

        registry = get_skill_registry()
        memory = get_memory_manager()
        llm = get_llm()

        # Filter tools for this specialist (or use all for general)
        if tool_filter is not None:
            specialist_tools = [t for t in registry.all_tools if t.name in tool_filter]
        else:
            specialist_tools = registry.all_tools

        llm_with_tools = llm.bind_tools(specialist_tools)

        # Fetch memory context in parallel
        constraints, memories, past_interactions = await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
            memory.get_relevant_interactions(user_query, user_id, limit=3),
        )

        # Current date/time
        _tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(_tz)
        _days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        _months_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                      "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_str = (
            f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} "
            f"{now.year}, {now.strftime('%H:%M')}"
        )

        # Per-user language directive — fetched once per turn (small SELECT).
        # Mirrors the logic in app/agent/sub_agents/factory.py so general
        # and dispatch sub-agents behave identically when the user toggles
        # the UI language.
        _user_language = "fr"
        if user_id:
            try:
                from app.models.user import User as _U
                from app.database import async_session as _async_session
                async with _async_session() as _db:
                    _row = await _db.execute(
                        select(_U.language).where(_U.id == user_id)
                    )
                    _user_language = (_row.scalar_one_or_none() or "fr")
            except Exception:
                pass
        if _user_language == "en":
            _lang_directive = (
                "LANGUAGE — STRICT : Reply in English only. The user has "
                "set their UI language to English. Translate any tool output "
                "to English in your final answer.\n\n"
            )
        else:
            _lang_directive = (
                "LANGUE — STRICT : Réponds uniquement en français. "
                "Traduis si besoin la sortie des outils.\n\n"
            )

        system = _lang_directive + specialist_prompt
        system += f"\n\n📅 Date et heure : {date_str} (Europe/Paris)\n"

        if constraints:
            system += "\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES :\n"
            system += "\n".join(f"- {c}" for c in constraints)
        if memories:
            system += "\n\n💾 CONTEXTE MÉMORISÉ :\n"
            system += "\n".join(f"- {m}" for m in memories)
        if past_interactions:
            system += "\n\n🔁 INTERACTIONS PASSÉES :\n"
            for p in past_interactions:
                system += (
                    f"- Q: {p.get('user_message', '')[:120]} "
                    f"→ R: {p.get('assistant_message', '')[:120]}\n"
                )

        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": system}] + messages
        )
        return {"messages": [response]}

    specialist_node.__name__ = f"{domain}_agent"
    return specialist_node


# ──────────────────────────────────────────────────────────────────────────────
# Sub-agent dispatch nodes
# ──────────────────────────────────────────────────────────────────────────────

_SUB_AGENT_DOMAINS = ("research", "workspace", "infra", "creative", "data", "memory", "desktop", "diag")


def _make_dispatch_node(domain: str):
    """Return an async node that delegates to the compiled sub-agent graph for *domain*.

    Falls back gracefully to the general agent when the sub-agent graph is not
    available in the registry (compilation failure, cold start, etc.).
    """

    async def dispatch_node(state: AgentState) -> dict:
        import time as _t
        _start = _t.monotonic()
        from app.agent.sub_agents.registry import get_sub_agent_registry

        registry = get_sub_agent_registry()
        sub_graph = registry.get(domain)

        logger.warning("⏱ TIMING[dispatch→%s] starting", domain)

        if sub_graph is None:
            logger.warning(
                "Sub-agent '%s' not compiled — falling back to general agent", domain
            )
            # Inline general agent fallback (create_agent_node is a factory)
            general = create_agent_node()
            return await general(state)

        sub_input = {
            "messages": state["messages"],
            "user_id": state.get("user_id", ""),
            "conversation_id": state.get("conversation_id", ""),
        }
        try:
            # Recursion limit baissé de 100 à 25 : avec un modèle local
            # lent (~10-15s/tour pour xLAM-2 8B sur Mac), 100 tours peut
            # geler le chat pendant 20+ minutes avant le fallback.
            # 25 tours suffisent pour 99% des tâches chat (le filtre
            # tools dynamique évite les boucles infinies en limitant les
            # options du modèle).
            result = await sub_graph.ainvoke(
                sub_input, config={"recursion_limit": 25}
            )
            # Return only the messages produced by the sub-agent
            new_messages = result["messages"][len(state["messages"]):]
            # ── Image pass-through (QR code, Imagen, etc.) ────────────────
            # If a ToolMessage contains {"type":"image",...} JSON and the
            # final AIMessage doesn't already include it, prepend the JSON so
            # the frontend can render the image (parseImageBlock in MessageBubble).
            import json as _json
            _image_jsons: list[str] = []
            from langchain_core.messages import ToolMessage as _TM
            for _m in new_messages:
                if isinstance(_m, _TM):
                    _c = _m.content or ""
                    if isinstance(_c, str) and _c.startswith("{"):
                        try:
                            _obj = _json.loads(_c)
                            if isinstance(_obj, dict) and _obj.get("type") == "image":
                                _image_jsons.append(_c)
                        except Exception:
                            pass
            if _image_jsons:
                _last = new_messages[-1] if new_messages else None
                _last_content = (_last.content or "") if _last else ""
                if isinstance(_last, AIMessage) and not any(j in _last_content for j in _image_jsons):
                    _separator = "\n\n" if _last_content else ""
                    _combined = _last_content + _separator + "\n\n".join(_image_jsons)
                    new_messages = list(new_messages[:-1]) + [
                        _last.model_copy(update={"content": _combined})
                    ]
            # ─────────────────────────────────────────────────────────────
            logger.warning("⏱ TIMING[dispatch→%s] DONE in %.2fs (%d new msgs)", domain, _t.monotonic() - _start, len(new_messages))
            # Propagate model_used from the sub-agent's compiled subgraph state
            # to the outer supervisor state — chat.py reads this to call
            # log_usage() with the real provider/model the sub-agent used.
            _ret_dispatch: dict = {"messages": new_messages, "domain": domain}
            _sub_model_used = result.get("model_used") if isinstance(result, dict) else None
            if _sub_model_used:
                _ret_dispatch["model_used"] = _sub_model_used
            return _ret_dispatch
        except Exception as exc:
            logger.error(
                "Sub-agent '%s' failed (%.2fs, %s) — running general agent with tools loop",
                domain, _t.monotonic() - _start, exc,
            )
            # NOTE 2026-04-27 : a previous version tried to be clever here and
            # auto-confirm "the action succeeded" if a recent ToolMessage
            # looked non-error. That logic was REMOVED because it created a
            # worse failure mode — the LLM tool result might be empty/void
            # (e.g. 0 matches found) which is NOT a failure but also NOT a
            # success, and the auto-confirm wrongly told the user the action
            # was done when nothing happened. Better : let the general agent
            # re-read the state and produce its own honest answer. The real
            # underlying bug (sub-agent introspection crash) needs a proper
            # fix in factory.py, not a band-aid here.
            # Run a full agent+tools loop (not just one turn) so tool_calls
            # like pdf_read, search_web, etc. are actually executed and the
            # user gets a real response instead of an empty bubble.
            from app.agent.nodes import tool_node as _tool_node
            from langchain_core.messages import AIMessage as _AI, BaseMessage as _BM
            from langchain_core.messages import messages_from_dict as _mfd

            def _ensure_base_messages(msgs: list) -> list:
                """Convert any serialized dict messages to BaseMessage objects."""
                result = []
                for m in msgs:
                    if isinstance(m, _BM):
                        result.append(m)
                    elif isinstance(m, dict):
                        try:
                            result.extend(_mfd([m]))
                        except Exception:
                            pass  # skip malformed
                return result

            general = create_agent_node()
            current_state = dict(state)
            current_state["messages"] = _ensure_base_messages(current_state.get("messages", []))
            MAX_STEPS = 10
            for _ in range(MAX_STEPS):
                result = await general(current_state)
                new_msgs = result.get("messages", [])
                all_msgs = list(current_state["messages"]) + new_msgs
                current_state = {**current_state, "messages": all_msgs}
                last = all_msgs[-1] if all_msgs else None
                if not (isinstance(last, _AI) and getattr(last, "tool_calls", None)):
                    break  # No pending tool calls — final answer reached
                # Execute tools and continue the loop
                tool_result = await _tool_node(current_state)
                tool_msgs = tool_result.get("messages", [])
                all_msgs = all_msgs + tool_msgs
                current_state = {**current_state, "messages": all_msgs}

            new_messages = current_state["messages"][len(state["messages"]):]
            return {"messages": new_messages, "domain": domain}

    dispatch_node.__name__ = f"{domain}_dispatch_node"
    return dispatch_node


# ──────────────────────────────────────────────────────────────────────────────
# Routing conditional
# ──────────────────────────────────────────────────────────────────────────────

def route_after_router(state: AgentState) -> str:
    """Map the domain stored by router_node to the next graph node."""
    domain = state.get("domain", "general")
    return domain if domain in _SUB_AGENT_DOMAINS else "general"


def should_continue_specialist(state: AgentState) -> str:
    """After a specialist or general agent, decide: call tools or finish."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


# ──────────────────────────────────────────────────────────────────────────────
# Graph assembly
# ──────────────────────────────────────────────────────────────────────────────

def build_supervisor_graph():
    """Build and compile the multi-agent supervisor graph.

    Nodes:
        router              → classifies intent (fast LLM)
        research            → dispatch to research sub-agent
        workspace           → dispatch to workspace sub-agent
        infra               → dispatch to infra sub-agent
        creative            → dispatch to creative sub-agent
        data                → dispatch to data sub-agent
        memory              → dispatch to memory sub-agent
        general             → full-tool fallback (create_agent_node)

    Each dispatch node delegates the full turn to an isolated sub-agent
    subgraph (agent+tools loop) and returns only the new messages.
    The general node uses the legacy tool_node for its own tools loop.

    Edges:
        router → {research, workspace, infra, creative, data, memory, general}
        dispatch nodes      → END  (the loop is internal to each sub-graph)
        general             → {tools, end}
        tools               → general  (legacy loop for the general agent)
    """
    from app.agent.state import AgentState

    graph = StateGraph(AgentState)

    # ── Nodes ──
    graph.add_node("router", router_node)

    # Sub-agent dispatch nodes (each delegates to an isolated subgraph)
    for _domain in _SUB_AGENT_DOMAINS:
        graph.add_node(_domain, _make_dispatch_node(_domain))

    # General agent keeps the legacy specialist node + shared tools_node loop
    graph.add_node("general", create_agent_node())
    graph.add_node("tools", tool_node)

    # ── Entry point ──
    graph.set_entry_point("router")

    # ── Router → dispatch nodes or general ──
    _routing_map = {d: d for d in _SUB_AGENT_DOMAINS}
    _routing_map["general"] = "general"
    graph.add_conditional_edges("router", route_after_router, _routing_map)

    # ── Dispatch nodes → END (sub-graphs handle their own tool loops) ──
    for _domain in _SUB_AGENT_DOMAINS:
        graph.add_edge(_domain, END)

    # ── General agent → tools or end ──
    from app.agent.nodes import should_continue
    graph.add_conditional_edges(
        "general",
        should_continue,
        {"tools": "tools", "end": END},
    )

    # ── Tools → back to general (general is the only node using tool_node) ──
    graph.add_edge("tools", "general")

    return graph.compile()

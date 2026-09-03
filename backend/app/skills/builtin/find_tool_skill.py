# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/find_tool_skill.py
# @brief      find_tool — semantic discovery of ELY's own tools (safety net).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""``find_tool`` — the "tool discovery is a tool" safety net.

The agent's bound toolset is a lean sticky profile (~30-41 tools) kept stable
for prompt-cache reasons. When the model needs a capability it doesn't
currently see, it calls ``find_tool("describe the capability")`` instead of
giving up. We semantic-search the FULL catalog (name + description, via the
FastEmbed encoder already used for memory), return the top matches, and record
them so ``agent_node`` binds them for the rest of the conversation.

This makes the recurring "je n'ai pas d'outil pour X" failure — which is almost
always a *binding* gap, not a real gap (e.g. the Sheets tools existed but
weren't in the default profile) — **self-healing**.

Security: ``find_tool`` only makes a tool VISIBLE. HITL / critical gates still
apply when it's actually called (``tool_node``). Discovering
``drive_delete_file`` does NOT un-gate it.

Phase 1 (this): discovery + sticky binding. Phase 2 (later): when nothing
matches well, emit a ``tool_absent_acknowledged`` signal → trigger tool
generation (Sprint 4b feature C).
"""
from __future__ import annotations

import asyncio
import logging
import math
import unicodedata

from langchain_core.tools import tool

from app.skills.base import Domain, Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Catalog cache — rebuilt only when the registered tool set changes.
# Ranking is HYBRID:
#   - LEXICAL (always, no embedding): normalized token overlap on name +
#     description. Catches the obvious cases the embedder misses ("sheet" ⊂
#     "spreadsheet"/"sheets"). Works everywhere — no FastEmbed dependency.
#   - SEMANTIC (best-effort): cosine on FastEmbed vectors, for paraphrases the
#     lexical misses. MiniLM-L6 is small + English-leaning, so it can't carry
#     French queries alone — it's an *enhancement*, not the backbone. If the
#     encoder is unavailable (env), we degrade to lexical-only.
_catalog_sig: frozenset[str] | None = None
_tool_text_norm: dict[str, str] = {}      # name -> normalized "name + description"
_tool_vectors: dict[str, list[float]] = {}  # name -> embedding (empty if encoder N/A)
_tool_first_sentence: dict[str, str] = {}

_SEM_WEIGHT = 0.5  # semantic is a tiebreak/enhancement; lexical leads

# Méta-outils du funnel lui-même — JAMAIS candidats d'une recherche : le
# docstring de report_missing_capability contient l'exemple « convertir un
# fichier PDF en .docx »… que le pré-check a retrouvé à score 1.0 comme
# « outil existant couvrant la capacité » (auto-empoisonnement, live 19/07).
_META_TOOLS = frozenset({"find_tool", "report_missing_capability"})


def _norm(s: str) -> str:
    """Lowercase + strip accents (so 'créé'~'cree', accent-insensitive)."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _first_sentence(desc: str) -> str:
    desc = (desc or "").strip().replace("\n", " ")
    for sep in (". ", " — ", " : "):
        if sep in desc:
            return desc.split(sep, 1)[0].strip()
    return desc[:160]


async def _ensure_catalog() -> None:
    """(Re)build the catalog cache if the registry changed.

    Lexical text is built always (cheap). Embeddings are best-effort: batch
    in ONE encoder call (~1-3 s, one-time) and left empty if the encoder
    can't init — find_tool then ranks lexical-only.
    """
    global _catalog_sig, _tool_text_norm, _tool_vectors, _tool_first_sentence
    tools = get_skill_registry().all_tools
    sig = frozenset(t.name for t in tools)
    if sig == _catalog_sig and _tool_text_norm:
        return

    _tool_text_norm = {
        t.name: _norm(f"{t.name} {getattr(t, 'description', '') or ''}") for t in tools
    }
    _tool_first_sentence = {
        t.name: _first_sentence(getattr(t, "description", "") or "") for t in tools
    }
    try:
        from app.services.memory import get_memory_infra

        infra = get_memory_infra()
        names = [t.name for t in tools]
        texts = [f"{t.name}: {getattr(t, 'description', '') or ''}" for t in tools]
        vecs = await asyncio.to_thread(lambda: [v.tolist() for v in infra.encoder.embed(texts)])
        _tool_vectors = dict(zip(names, vecs))
        logger.info("find_tool: catalog ready — %d tools (lexical + semantic)", len(names))
    except Exception as exc:  # noqa: BLE001 — semantic is optional
        _tool_vectors = {}
        logger.warning("find_tool: semantic embeddings unavailable, lexical-only (%s)", exc)
    _catalog_sig = sig


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@tool
async def find_tool(capability: str, top_k: int = 5) -> str:
    """Trouver des outils ELY correspondant à une capacité dont tu as besoin mais qui n'est pas déjà disponible.

    APPELLE CET OUTIL AVANT de conclure que tu ne peux pas faire quelque chose
    faute d'outil — Y COMPRIS quand l'utilisateur POSE LA QUESTION de tes
    capacités sans demander la tâche (« peux-tu créer un outil qui… »,
    « sais-tu faire… ») : la recherche consigne les capacités réellement
    absentes. Décris le besoin en langage naturel (ex. « lire un Google
    Sheet existant », « ajouter des lignes à un tableur », « publier sur
    Telegram »). Renvoie les outils les plus pertinents, qui deviennent
    disponibles pour le reste de la conversation — appelle ensuite celui qu'il
    te faut.

    Args:
        capability: description en langage naturel de la capacité recherchée.
        top_k: nombre d'outils candidats à renvoyer (défaut 5, max 10).
    """
    capability = (capability or "").strip()
    if not capability:
        return "Précise la capacité recherchée (ex. « lire un Google Sheet existant »)."
    try:
        await _ensure_catalog()
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("find_tool: catalog build failed: %s", exc)
        return "La recherche d'outil a échoué temporairement — procède autrement ou réessaie."

    k = max(1, min(int(top_k or 5), 10))
    # Un petit modèle LOCAL lit les descriptions et choisit. Le classement
    # lexical+sémantique reste dessous, en repli.
    #
    # ⚠️ Mesuré le 29/07/2026 : `_rank_capability` se trompait une fois sur
    # deux — « créer un événement dans l'agenda » rendait `trainer_start`. Ni
    # « créer », ni « événement », ni « agenda » n'apparaissent dans la
    # description de `calendar_create_event`, et l'embedding classait mal.
    # `gemma-4-E4B` répond 4/4 en ~1,1 s, à coût nul.
    top = await _select_with_model(capability, k) or await _rank_capability(capability, k)

    # Les PROCÉDURES apprises comptent autant que les outils. Cherchées même
    # quand des outils ont matché : un playbook dit souvent COMMENT les
    # combiner, ce qu'aucune description d'outil ne porte.
    _utilisateur = ""
    try:
        from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID

        _utilisateur = LEARNED_TOOL_USER_ID.get() or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("find_tool: utilisateur inconnu (%s)", exc)
    playbooks = await _playbooks_for_capability(capability, _utilisateur)

    if not top and not playbooks:
        # Rien dans le catalogue COMPLET ni dans les procédures → capacité
        # réellement absente (pas un trou de liaison) : on consigne et on
        # lance la fabrique par le chemin partagé.
        return await _record_gap_and_trigger(capability)

    # Record discoveries so agent_node binds them on the next turn (sticky).
    if top:
        try:
            from app.agent.discovered_tools import add_discovered
            from app.agent.tool_context import CURRENT_CONVERSATION_ID

            add_discovered(CURRENT_CONVERSATION_ID.get(), top)
        except Exception as exc:  # noqa: BLE001
            logger.debug("find_tool: could not record discovery: %s", exc)

    lines: list[str] = []
    if top:
        lines.append(
            f"Outils disponibles pour « {capability} » "
            f"(utilise-les directement maintenant) :"
        )
        lines += [f"  • {name} — {_tool_first_sentence.get(name, '')}" for name in top]
    if playbooks:
        # ⚠️ Nommer la différence, sinon le modèle tente d'APPELER la
        # procédure comme un outil — elle n'a ni schéma ni exécuteur.
        if top:
            lines.append("")
        lines.append(
            "Procédures apprises qui couvrent ce besoin — ce ne sont PAS des "
            "outils appelables : lis-les et applique-les avec les outils "
            "ci-dessus."
        )
        lines += [_rendre_playbook(nom, desc, contenu) for _id, nom, desc, contenu in playbooks]
        # Le curateur archive ce qui ne sert pas. Sans ce compteur, une
        # procédure servie par `find_tool` passerait pour inutilisée et
        # finirait archivée alors qu'elle travaille.
        await _marquer_playbooks_utilises([pid for pid, _n, _d, _c in playbooks])
    return "\n".join(lines)


async def _marquer_playbooks_utilises(ids: list[int]) -> None:
    """`use_count` et `last_used_at` — la matière du curateur.

    ⚠️ Sans ça, `skill_curator` verrait `use_count=0` sur une procédure servie
    à chaque tour et la ferait passer `active → stale → archived`. On aurait
    construit un chemin de découverte qui condamne ce qu'il découvre.
    """
    if not ids:
        return
    try:
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.database import async_session
        from app.models.learned_skill import LearnedSkill

        async with async_session() as db:
            await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id.in_(ids))
                .values(
                    use_count=LearnedSkill.use_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — un compteur ne casse pas un tour
        logger.debug("find_tool: usage playbook non consigné (%s)", exc)


async def _record_gap_and_trigger(capability: str, *, model_judged: bool = False) -> str:
    """Consigne un gap réel + (C4-2) lance l'auto-génération. Message inclus.

    Chemin PARTAGÉ entre le no-match de ``find_tool`` (score zéro sur tout le
    catalogue) et ``report_missing_capability`` (C4-2b : le modèle juge les
    résultats non pertinents — le cas RÉALISTE, un vrai gap a presque toujours
    des faux-matchs faibles type « pdf » ⊂ outils pdf non pertinents).
    ``model_judged=True`` : la pertinence a déjà été jugée par le modèle →
    la génération saute son pré-check lexical (pas de double veto).
    """
    _case_id = None
    _gap_user = ""
    try:
        from app.agent.tool_context import CURRENT_CONVERSATION_ID
        from app.services.learning.failure_capture import record_tool_absent
        from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID

        _gap_user = LEARNED_TOOL_USER_ID.get() or ""
        _case_id = await record_tool_absent(
            user_id=_gap_user,
            capability=capability,
            conversation_id=CURRENT_CONVERSATION_ID.get() or None,
        )
    except Exception as exc:  # noqa: BLE001 — recording must never break the turn
        logger.debug("find_tool: gap recording skipped: %s", exc)
    _redaction_lancee = False
    _fabrique_ouverte = False
    if _case_id:
        # ⚠️ LE DRAPEAU SE LIT AVANT LE DÉPART (02/09/2026).
        #
        # Il était lu APRÈS le `spawn`, dans le même `try` : une lecture qui
        # lève faisait retomber la réponse sur « rien n'a pu être lancé »
        # alors que la rédaction était déjà partie. Ely aurait dit à
        # l'utilisateur que personne ne s'occupe du manque pendant qu'une
        # procédure s'écrivait. Lu ici, il ne peut plus mentir sur un départ
        # qui a eu lieu — et un drapeau illisible vaut « fabrique gelée » :
        # on ne promet jamais un outil qu'on n'est pas sûr de produire.
        try:
            from app.config import get_settings

            _fabrique_ouverte = bool(get_settings().auto_tool_generation_enabled)
        except Exception as exc:  # noqa: BLE001 — un drapeau illisible ne coupe rien
            logger.debug("find_tool: drapeau de fabrique illisible (%s)", exc)
        try:
            from app.services.background_tasks import spawn
            from app.services.learning.auto_tool_generation import (
                maybe_generate_for_gap,
            )

            # ⚠️ LE DÉPART NE DÉPEND PLUS DU DRAPEAU (02/09/2026).
            #
            # La tâche de fond n'était lancée QUE si `auto_tool_generation_
            # enabled` était vrai. Geler la fabrique éteignait donc AUSSI la
            # voie document, faute de départ : le manque était consigné, puis
            # plus personne ne s'en occupait. Le drapeau décide de ce qui
            # SORT (procédure ou outil), pas de savoir si quelqu'un s'en
            # occupe.
            #
            # detach_context : la rédaction fait ses PROPRES appels LLM —
            # sans détachement, les callbacks LangChain hérités routaient
            # les tokens tier-S dans le stream du chat (entrelacés avec
            # la réponse d'Ely — bug réel 19/07).
            spawn(
                maybe_generate_for_gap(
                    _case_id, capability, _gap_user,
                    skip_precheck=model_judged,
                ),
                label="auto-tool-generation",
                detach_context=True,
            )
            _redaction_lancee = True
        except Exception as exc:  # noqa: BLE001 — le déclencheur non plus
            logger.debug("find_tool: auto-generation skipped: %s", exc)
            _redaction_lancee = False
    if _redaction_lancee and not _fabrique_ouverte:
        # Fabrique gelée : seule une procédure peut sortir. Annoncer « un
        # outil candidat » ferait attendre au modèle une capacité appelable
        # qui n'arrivera jamais.
        #
        # ⚠️ 02/09/2026 — et on n'annonce pas non plus un DÉPART. La tâche de
        # fond a deux sorties silencieuses légitimes : `deja_perimee` (une
        # procédure née de ce motif est morte sans jamais servir) et
        # `candidate_en_attente` (une procédure attend déjà une décision
        # humaine pour ce motif). La seconde est le chemin COURANT une fois la
        # fabrique gelée : `_playbooks_for_capability` ne remonte que les
        # playbooks ACTIVE, donc une candidate en attente est invisible d'ici,
        # le manque est re-consigné à chaque récurrence, et le garde refuse
        # d'en écrire une deuxième. Promettre « une rédaction est en cours »
        # dans ce cas, c'est le défaut même que ce message répare un cran plus
        # haut, déplacé d'un cran.
        return (
            f"Aucun outil existant ne couvre « {capability} ». "
            "Capacité réellement absente — consignée dans "
            "les « Capacités manquantes ». Si elle doit donner lieu à une "
            "procédure, celle-ci passera par une validation humaine avant "
            "d'être servie."
        )
    if _redaction_lancee:
        # ⚠️ « un outil candidat » était devenu FAUX (24/08). Depuis que la
        # branche « compétence » de l'aiguillage écrit un playbook au lieu de
        # ne rien faire, ce qui démarre est l'un OU l'autre — et c'est le juge
        # `needs_a_tool` qui tranche, en tâche de fond, après ce message.
        #
        # Promettre « un outil » quand c'est une procédure qui arrive ferait
        # attendre au modèle une capacité appelable qui ne viendra pas. On
        # nomme donc les deux issues plutôt qu'une seule.
        return (
            f"Aucun outil existant ne couvre « {capability} ». "
            "Capacité réellement absente — consignée dans "
            "les « Capacités manquantes ». Une procédure ou un outil candidat "
            "est en cours de rédaction selon ce que la demande réclame ; il "
            "sera soumis à validation humaine avant d'être utilisable."
        )
    # Rien n'a pu être lancé (pas de cas consigné, ou le départ a échoué) : on
    # ne promet ni procédure ni outil, on dit seulement où le manque atterrit.
    return (
        f"Aucun outil existant ne couvre « {capability} ». "
        "Capacité réellement absente — consignée dans "
        "les « Capacités manquantes », où elle attend une décision humaine."
    )


@tool
async def report_missing_capability(capability: str) -> str:
    """Consigner une capacité RÉELLEMENT absente et lancer une rédaction pour la combler.

    APPELLE CET OUTIL quand `find_tool` a renvoyé des résultats qui ne
    couvrent PAS le besoin (faux-matchs — ex. des outils « pdf » qui ne
    convertissent pas), ou quand l'utilisateur te signale explicitement une
    capacité manquante à implémenter. La consignation apparaît dans
    « Capacités manquantes » ; une rédaction démarre ensuite toute seule —
    une procédure écrite, ou un outil candidat quand la fabrique d'outils est
    ouverte — et passe par une validation humaine avant de servir. Le retour
    de cet outil dit laquelle : reprends-le, n'annonce rien de plus.

    Args:
        capability: description en langage naturel de la capacité absente
            (ex. « convertir un fichier PDF en fichier .docx »).
    """
    capability = (capability or "").strip()
    if not capability:
        return "Précise la capacité manquante (description en langage naturel)."
    # Le modèle vient de VOIR les candidats de find_tool et les a jugés non
    # pertinents — le pré-check lexical (juge plus faible) n'a pas de droit
    # de veto sur ce jugement (leçon 19/07 : « drive_export_file » matchait
    # « fichier+pdf+docx » à 0,67 et bloquait le gap PDF→DOCX fondateur).
    # Il reste INFORMATIF : un voisin lexical fort est signalé en caveat.
    caveat = ""
    try:
        existing = await capability_has_existing_tool(capability)
        if existing:
            caveat = (
                f"\nNB : l'outil existant {existing} est lexicalement proche — "
                "si en le relisant il couvre finalement le besoin, utilise-le "
                "et signale-le."
            )
    except Exception:  # noqa: BLE001
        pass
    return await _record_gap_and_trigger(capability, model_judged=True) + caveat


async def _select_with_model(capability: str, k: int) -> list[str]:
    """Les outils choisis par le modèle local, ou ``[]`` s'il n'a rien décidé.

    Returns ``[]`` — jamais une exception — dans tous les cas de doute, pour
    que l'appelant retombe sur le classement lexical.

    ⚠️ ``select_tools`` **échoue OUVERT** : il rend la liste COMPLÈTE quand le
    sélecteur est absent ou muet. La prendre pour une réponse afficherait les
    200 outils comme « les plus pertinents » — pire que le classement lexical.
    D'où le test ``len(choisis) >= len(tous)`` : une sélection qui ne
    sélectionne rien n'en est pas une.
    """
    try:
        from app.agent.tool_selector import select_tools
        from app.skills import get_skill_registry

        tous = list(get_skill_registry().all_tools)
        if not tous:
            return []
        # `include_core=False` : l'annuaire ne doit pas se proposer lui-même.
        choisis = await select_tools(capability, tous, include_core=False)
    except Exception as exc:  # noqa: BLE001 — le repli lexical prend la suite
        logger.info("find_tool : sélecteur indisponible (%s) — classement lexical", exc)
        return []

    if not choisis or len(choisis) >= len(tous):
        return []
    return [getattr(t, "name", "") for t in choisis if getattr(t, "name", "")][:k]


async def rank_tools_for_capability(
    capability: str, k: int = 5
) -> list[tuple[str, str]]:
    """Les outils qui couvrent *capability*, en couples ``(nom, résumé)``.

    Voie PARTAGÉE avec ``memory_recall("procedural", …)`` — Sprint 2.5 §2.5.2.
    La « mémoire procédurale » du sprint, c'est le catalogue d'outils
    requêtable en langage naturel : ce que ce module calcule déjà. Lui donner
    son propre magasin aurait ouvert un SECOND chemin de découverte d'outils,
    sans sélecteur local ni consignation de gap — deux fois la même dette.

    Même chaîne que ``find_tool``, sélecteur d'abord : le classement lexical
    seul se trompait une fois sur deux à la mesure du 29/07 (cf. le commentaire
    dans ``find_tool``). Servir la procédurale depuis le repli connu-faible
    aurait rejoué cette panne sous un autre nom.
    """
    await _ensure_catalog()
    names = await _select_with_model(capability, k) or await _rank_capability(
        capability, k
    )
    return [(n, _tool_first_sentence.get(n, "")) for n in names]


async def _rank_capability(capability: str, k: int) -> list[str]:
    """Classement lexical+sémantique du catalogue COMPLET pour une capacité.

    Partagé entre ``find_tool`` (l'outil) et le pré-check anti-doublon C4-2
    (``capability_has_existing_tool``) — même leçon #56 : le lexical porte le
    résultat, le sémantique enrichit en best-effort.
    """
    await _ensure_catalog()
    q_tokens = [t for t in _norm(capability).split() if len(t) >= 3]
    qv: list[float] | None = None
    if _tool_vectors:
        try:
            from app.services.memory import get_memory_infra

            qv = await get_memory_infra().embed(capability)
        except Exception as exc:  # noqa: BLE001
            logger.debug("find_tool: query embed unavailable, lexical-only (%s)", exc)

    def _score(name: str) -> float:
        text = _tool_text_norm.get(name, "")
        lex = (sum(1 for t in q_tokens if t in text) / len(q_tokens)) if q_tokens else 0.0
        sem = _cosine(qv, _tool_vectors[name]) if (qv and name in _tool_vectors) else 0.0
        return lex + _SEM_WEIGHT * sem

    candidates = [n for n in _tool_text_norm if n not in _META_TOOLS]
    ranked = sorted(((_score(n), n) for n in candidates), reverse=True)
    return [name for score, name in ranked[:k] if score > 0.0]


# Seuil du pré-check anti-doublon (recouvrement lexical simple). Rôle :
# PRÉCISION, pas rappel — il ne bloque que sur recouvrement franc (≥ la
# moitié des tokens significatifs). Le RAPPEL des vrais gaps est porté par
# le chemin modèle : ``report_missing_capability`` consigne SANS veto du
# pré-check (leçon 19/07 : un juge lexical ne re-conteste pas un jugement
# de pertinence du modèle — « drive_export_file » matchait « fichier+pdf+
# docx » et bloquait le gap PDF→DOCX fondateur). Une pondération IDF a été
# essayée puis retirée : les tokens rares NON matchés du côté requête
# (« existant ») plombent la couverture des vrais doublons — sans gain,
# le rappel n'étant plus son travail.
_PRECHECK_MIN_SCORE = 0.5


def _best_lexical_match(q_tokens: list[str], candidates: dict[str, str]) -> tuple[float, str | None]:
    """Meilleur score lexical (part des tokens de la capacité présents dans le
    texte du candidat) et son nom."""
    best_score, best_name = 0.0, None
    for name, text in candidates.items():
        lex = sum(1 for t in q_tokens if t in text) / len(q_tokens)
        if lex > best_score:
            best_score, best_name = lex, name
    return best_score, best_name


# Ce qu'un playbook peut occuper dans un retour de `find_tool`. Le budget de
# prompt des playbooks vaut 8 000 caractères pour TOUS ceux injectés ; ici on
# en rend un ou deux, en pleine conversation, à un modèle qui peut être local.
_PLAYBOOK_EXTRAIT_CHARS = 2_000


async def _playbooks_for_capability(
    capability: str, user_id: str, k: int = 2,
) -> list[tuple[int, str, str, str]]:
    """Les procédures apprises qui couvrent *capability* — ``(id, nom, description, contenu)``.

    ⚠️ POURQUOI `find_tool` REGARDE ICI (24/08).

    Il ne balayait que le catalogue d'OUTILS. Une capacité couverte par un
    playbook — le format `SKILL.md` d'Hermes, déjà porté ici — était donc
    déclarée « réellement absente », et la fabrique repartait écrire ce qui
    existait déjà.

    C'est aussi ce qui rend la croissance soutenable. Un playbook ne coûte
    aucun schéma d'outil : il ne pèse que le jour où on le rend, et seulement
    ce qu'on en cite. Le rendre trouvable étend la portée d'Ely **sans
    alourdir un seul tour** — c'est exactement l'inverse d'un outil de plus.

    Classement lexical seulement, et c'est assumé : on compare une phrase à
    quelques dizaines de titres, pas à 200 descriptions. Le sélecteur par
    modèle coûterait une inférence de plus sur un chemin déjà chargé.
    """
    if not user_id:
        return []
    try:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.learned_skill import (
            LearnedSkill, SkillContentFormat, SkillStatus,
        )

        async with async_session() as db:
            rows = (await db.execute(
                select(
                    LearnedSkill.id, LearnedSkill.name,
                    LearnedSkill.description, LearnedSkill.content,
                ).where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                    LearnedSkill.content_format == SkillContentFormat.MARKDOWN_PLAYBOOK,
                )
            )).all()
    except Exception as exc:  # noqa: BLE001 — une source absente n'est pas fatale
        logger.debug("find_tool: playbooks illisibles (%s)", exc)
        return []

    if not rows:
        return []

    q_tokens = _norm(capability).split()
    notes: list[tuple[float, tuple[int, str, str, str]]] = []
    for pid, nom, desc, contenu in rows:
        texte = _norm(f"{nom} {desc or ''}")
        score, _ = _best_lexical_match(q_tokens, {nom: texte})
        if score >= _PRECHECK_MIN_SCORE:
            notes.append((score, (pid, nom, desc or "", contenu or "")))
    notes.sort(key=lambda n: -n[0])
    return [p for _s, p in notes[:k]]


def _rendre_playbook(nom: str, description: str, contenu: str) -> str:
    """Un playbook prêt à lire par le modèle, tronqué en l'annonçant.

    ⚠️ Le contenu est rendu ICI plutôt que derrière un second appel. Mesuré
    dans ce dépôt (`active_skills.py`) : **0 appel à `skill_view` depuis
    toujours**, pour 26 playbooks actifs. L'outil EST lié — le modèle le voit
    et ne l'appelle jamais. On a arrêté de parier sur cette décision, et ce
    chemin-ci suit la même conclusion.
    """
    corps = (contenu or "").strip()
    coupe = len(corps) > _PLAYBOOK_EXTRAIT_CHARS
    if coupe:
        corps = corps[:_PLAYBOOK_EXTRAIT_CHARS].rstrip()
    bloc = f"  ▸ Procédure « {nom} » — {description}\n{corps}"
    if coupe:
        # Une troncature muette ferait suivre une procédure sur sa première
        # moitié en croyant l'avoir lue entière.
        bloc += (
            f"\n[…procédure tronquée à {_PLAYBOOK_EXTRAIT_CHARS} caractères — "
            f"appelle `skill_view(\"{nom}\")` pour la suite]"
        )
    return bloc


async def _learned_tool_for_capability(q_tokens: list[str], user_id: str) -> str | None:
    """Outil DÉJÀ FABRIQUÉ par la fabrique pour cet utilisateur, tous statuts
    confondus, ou None.

    C'est le trou mesuré en production (audit §3.2). ``_ensure_catalog()`` ne
    connaît que les outils **bindés** ; or un outil fraîchement généré est une
    *candidate* non promue, bindée nulle part. Résultat relevé le 25/07 :
    cinq ``convert_pdf_to_docx`` pour le même utilisateur en 32 minutes, plus
    trois ``pdf_replace_text`` et trois ``pdf_to_docx``.

    On regarde donc TOUS les statuts — candidate (en attente de promotion),
    archived et rejected (tentatives passées : les revoir à l'identique ne
    donnerait pas un meilleur résultat), active, stale, graduated.

    Cloisonné par utilisateur : les outils appris sont personnels, et l'outil
    d'un tiers ne doit pas priver quelqu'un du sien.
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.learned_skill import LearnedSkill

    async with async_session() as db:
        rows = (await db.execute(
            select(LearnedSkill.name, LearnedSkill.description).where(
                LearnedSkill.user_id == user_id,
                LearnedSkill.content_format == "python_tool",
            )
        )).all()
    if not rows:
        return None

    texts = {name: _norm(f"{name} {desc or ''}") for name, desc in rows}
    score, name = _best_lexical_match(q_tokens, texts)
    return name if score >= _PRECHECK_MIN_SCORE else None


async def capability_has_existing_tool(
    capability: str, user_id: str | None = None
) -> str | None:
    """Pré-check anti-doublon (C4-2) : meilleur outil existant, ou None.

    Consommateurs : endpoint admin ``/tool-creator/run`` (bloquant, avec
    ``force``), auto-génération sur no-match (redondant par construction),
    et ``report_missing_capability`` (INFORMATIF seulement — caveat).
    Best-effort : erreur → None (la collision de nom du registration_gate
    reste le filet aval).

    V0-4 — deux sources au lieu d'une :

    1. le catalogue des outils **bindés** (comportement historique) ;
    2. les outils **déjà fabriqués** pour ``user_id``, tous statuts confondus
       — c'est la source qui manquait, et c'est elle qui produisait les
       doublons mesurés en production.

    ``user_id`` omis → source 1 seulement : la signature reste
    rétrocompatible pour tout appelant qui n'a pas d'utilisateur sous la main.
    """
    capability = (capability or "").strip()
    if not capability:
        return None
    try:
        await _ensure_catalog()
        q_tokens = [t for t in _norm(capability).split() if len(t) >= 3]
        if not q_tokens:
            return None
        catalog = {
            name: text for name, text in _tool_text_norm.items()
            if name not in _META_TOOLS
        }
        best_score, best_name = _best_lexical_match(q_tokens, catalog)
        if best_score >= _PRECHECK_MIN_SCORE:
            return best_name
        if user_id:
            already_built = await _learned_tool_for_capability(q_tokens, user_id)
            if already_built:
                logger.info(
                    "pré-check anti-doublon : « %.60s » est déjà couverte par "
                    "l'outil fabriqué %r (non bindé) — pas de re-génération",
                    capability, already_built,
                )
                return already_built
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability_has_existing_tool failed: %s", exc)
        return None


get_skill_registry().register(Skill(
    name="find_tool",
    display_name="Recherche d'outil",
    description=(
        "Trouver un outil ELY adapté à un besoin quand il n'est pas déjà "
        "disponible (recherche sémantique sur tout le catalogue d'outils)."
    ),
    icon="🧭",
    scopes=[],
    domains=[Domain.UNIVERSAL],
    tools=[find_tool, report_missing_capability],
))

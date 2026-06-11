# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/security_filter.py
# @brief      Tool call security filter
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Longueur maximale de texte soumis aux regex.
# Protège contre les attaques ReDoS : une chaîne très longue et mal formée
# peut faire exploser le backtracking sur les patterns ci-dessous.
_MAX_REGEX_INPUT = 50_000   # caractères

# Forme d'un placeholder déjà posé ([EMAIL_0], [PERSON_12], …). La couche 2
# ne doit JAMAIS substituer à l'intérieur d'un placeholder existant.
_PLACEHOLDER_RE = re.compile(r"\[[A-Z]+_\d+\]")

# Patterns for sensitive data detection.
# Notes ReDoS :
#   EMAIL  — quantificateurs imbriqués sur [a-zA-Z0-9_.+-]+ → vulnérable sur entrées
#             très longues (e.g. 50 000×'a' + '@'). Mitigé par _MAX_REGEX_INPUT.
#   IBAN   — alternances d'espaces optionnels → risque faible mais garde ajoutée.
#   Tous les patterns utilisent re.compile() pour bénéficier du cache NFA.
_PATTERNS: dict[str, re.Pattern] = {
    # CARD: possessive-style via atomic boundaries — no nested quantifiers
    "CARD":  re.compile(r"\b\d(?:[ -]?\d){12,15}\b"),
    # EMAIL: explicit character classes, bounded lengths, no ambiguous overlap
    "EMAIL": re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,62}[a-zA-Z0-9]@[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]\.[a-zA-Z]{2,10}\b"),
    # TOKEN: non-greedy match on keyword, fixed-width value range
    "TOKEN": re.compile(r"(?:api[_-]?key|token|auth|password|secret|bearer)[:\s=]+([a-zA-Z0-9\-_.]{16,256})", re.IGNORECASE),
    # IBAN: no optional spaces to avoid alternation backtracking — strip spaces first
    "IBAN":  re.compile(r"\b[A-Z]{2}\d{2}(?:\d{4}){4}\d{2,}\b"),
    # PHONE: French numbers, accept the common written formats. The previous
    # version was too strict (digits-only, e.g. "0612345678") and missed the
    # standard French format "06 12 34 56 78" with spaces — which is exactly
    # how every site / Gmail signature / LinkedIn profile writes them, so
    # phones lifted from web search were leaking to the LLM in clear
    # (observed in prospection mission 2026-06-07).
    #
    # Supported now: "0X XX XX XX XX", "0X.XX.XX.XX.XX", "0X-XX-XX-XX-XX",
    # "0XXXXXXXXX", with the same variants for "+33" (optional separator
    # right after +33). ReDoS-safe: each group is anchored to exactly two
    # digits, the only optional element is a single character — no nested
    # quantifiers, no ambiguous backtracking.
    #
    # Non-word-boundary anchors: `\b` doesn't anchor before `+` (it's not a
    # word char), so we use `(?<!\d)` / `(?!\d)` to keep matches off the
    # middle of a longer digit sequence WITHOUT depending on word-character
    # boundaries. Both lookarounds are fixed-width 1 — Python-compatible.
    "PHONE": re.compile(r"(?<!\d)(?:\+33[ .\-]?|0)[1-9](?:[ .\-]?\d{2}){4}(?!\d)"),
}

# Tool names that always require human validation.
#
# HITL philosophy (2026-04-17): minimiser la friction. L'agent doit être
# fluide pour les actions courantes non-dangereuses (créer un RDV, bouger
# un mail dans un dossier, modifier un doc). HITL uniquement pour :
#   1. Suppressions (destructives, irréversibles)
#   2. Envois de mail (relecture avant envoi externe)
#   3. SSH (commandes serveur)
#   4. Config système / API brute (modifications silencieuses)
#   5. Contrôle OS (sécurité du système local)
#   6. Communications externes (WhatsApp) + partage externe (Drive share)
#
# Les actions NON-HITL :
#   - calendar_* create/update : c'est SON calendrier
#   - docs/sheets_batch_update : SES documents
#   - gmail_move/batch_modify : déplacement, pas envoi
#   - drive_move_file : dans SON drive
ALWAYS_CRITICAL_TOOLS: frozenset[str] = frozenset({
    # ── 1. Suppressions ──
    "desktop_delete_file",
    "drive_delete_file",
    "tasks_delete",
    "gmail_trash_emails",
    "gmail_trash_by_category",
    "gmail_trash_by_query",
    "gmail_empty_trash",            # PERMANENT delete of trash contents — irreversible
    "contacts_delete",
    "calendar_delete_event",
    # ── 2. Envois de mail (relecture obligatoire) ──
    "gmail_send_email",
    "gmail_reply_email",
    "gmail_send_with_attachment",
    # ── 3. SSH ──
    "ssh_execute",
    # ── 4. Config / API brute (mutations silencieuses potentielles) ──
    "gmail_update_settings",
    "gmail_raw_api_call",
    "calendar_raw_api_call",
    "drive_raw_api_call",
    "docs_raw_api_call",
    "sheets_raw_api_call",
    "tasks_raw_api_call",
    "contacts_raw_api_call",
    "mcp_validate_and_deploy",
    # ── 5. Contrôle OS (dangereux pour la machine locale) ──
    "os_click",
    "os_type_text",
    "os_hotkey",
    "os_mouse_move",
    "desktop_write_file",
    "desktop_move_file",
    "desktop_create_dir",
    # ── 6. Communications externes + partage ──
    "whatsapp_send",
    "whatsapp_send_template",
    "drive_share_file",
})


# Tools that an AUTONOMOUS mission must NEVER auto-approve (the "security
# floor"). Even with the mission's `autonomous` flag on, these still require
# a human: they are irreversible, leave the building (3rd-party), or touch
# security/system state. In an autonomous run they are SKIPPED (the step
# fails, the mission keeps going) rather than executed blind at 3 a.m.
# Non-floor HITL-gated tools (labels, Drive/Sheets writes, self-mail) ARE
# auto-approved. Note: an explicit user pre-approval (Toujours autoriser /
# Pour cette tâche) still lets a floor tool through — it's checked first.
NEVER_AUTONOMOUS_TOOLS: frozenset[str] = frozenset({
    # Irreversible / mass-destructive
    "gmail_empty_trash", "gmail_trash_emails", "gmail_trash_by_query",
    "gmail_trash_by_category", "gmail_batch_modify",
    "drive_delete_file", "desktop_delete_file",
    "calendar_delete_event", "tasks_delete",
    "contacts_delete", "contacts_batch_operations",
    # Leaves the building / third party
    "gmail_send_email", "gmail_reply_email", "gmail_send_with_attachment",
    "whatsapp_send", "whatsapp_send_template", "drive_share_file",
    # Security / system / unrestricted escape hatches
    "ssh_execute", "vault_unlock", "vault_set_secret", "save_constraint",
    "mcp_validate_and_deploy", "gmail_update_settings",
    "gmail_raw_api_call", "calendar_raw_api_call", "drive_raw_api_call",
    "docs_raw_api_call", "sheets_raw_api_call", "tasks_raw_api_call",
    "contacts_raw_api_call",
    "os_click", "os_type_text", "os_hotkey", "os_mouse_move",
})

# Keywords in TOOL ARGUMENTS (not tool name) that flag an action as needing validation
# These are checked against the display_args JSON, not the tool name.
# Kept minimal — "remove" removed (too broad), added financial transfer terms.
_CRITICAL_KEYWORDS: frozenset[str] = frozenset({
    # Destructive operations
    "delete", "drop", "purge", "wipe", "truncate",
    "supprimer", "effacer",
    "rm -rf", "format", "mkfs",
    "chmod 777", "chown root",
    # Financial — payments, transfers, purchases
    "pay", "payment", "virement", "buy", "purchase",
    "payer", "achat", "transfer", "transférer",
    "send money", "envoyer de l'argent",
    # Browser purchase flows (when browser_click/fill is the tool)
    "paypal.com", "checkout", "panier", "cart",
    "amazon.", "cdiscount.", "fnac.", "leboncoin.",
})

# Argument keys holding a DEFERRED / free-text instruction — what a tool will
# run *later* or *elsewhere*, not what it does right now. The HITL keyword
# heuristic must NOT scan these: a scheduled task « Supprimer mes vieux mails »
# is a harmless CREATION now (scheduler_create_task), and the actual deletion
# is HITL-gated when the task runs. Scanning the instruction text false-fired
# HITL on creation (Franck, scheduler_create_task anomaly, 2026-06-04). The
# tool's real criticality comes from its NAME (ALWAYS_CRITICAL_TOOLS) + its
# structured args, never from the wording of a deferred instruction.
INSTRUCTION_ARG_KEYS: frozenset[str] = frozenset({"prompt", "code", "instruction"})


@dataclass
class SecurityFilter:
    """Per-conversation security filter.

    Anonymizes sensitive data before it leaves to the cloud LLM, and
    restores it in the response. Also flags critical actions so the
    HITL manager can request human validation.

    Deux couches d'anonymisation :

    1. **Regex** (toujours active) — formats déterministes : EMAIL, PHONE,
       CARD, IBAN, TOKEN. Jamais de faux négatif sur un format connu.
    2. **NER** (``PII_NER_ENABLED``, défaut off) — PII en texte libre que
       les regex ne peuvent pas voir : personnes, organisations, adresses
       (GLiNER ONNX int8, voir ``app/services/pii_ner.py``). Flag off ou
       modèle indisponible → la couche est un no-op strict, le comportement
       est celui d'avant son introduction.

    Les deux couches partagent le même vault et le même compteur : un
    placeholder ([PERSON_0], [EMAIL_1], …) est stable pour toute la durée
    de la conversation et réversible via :meth:`deanonymize`.
    """
    _vault: dict[str, str] = field(default_factory=dict)
    _counter: int = field(default=0)

    # ------------------------------------------------------------------ #
    # Anonymization                                                         #
    # ------------------------------------------------------------------ #

    def anonymize(self, text: str, *, ner_detection: bool = True) -> str:
        """Replace sensitive values with opaque placeholders.

        ``ner_detection=False`` (contenu MACHINE : résultats d'outils,
        stdout sandbox, historique assistant) : la couche 1 regex et le
        remplacement vault-first de la couche 2 s'appliquent (la PII déjà
        connue de l'utilisateur reste masquée partout), mais AUCUNE
        détection NER fraîche — le contenu machine est majoritairement
        public (web, GitHub, en-têtes d'emails) et y masquer chaque
        personne/organisation détruit l'utilité de l'agent (retour terrain
        2026-06-11 : briefing du matin truffé de [ORG_n], GitHub cassé).
        La détection fraîche ne s'applique qu'au texte TAPÉ par
        l'utilisateur — le trou documenté qu'elle ferme.

        Each unique sensitive value is mapped to exactly one placeholder.
        Substitutions are performed using match positions (start/end offsets)
        rather than str.replace, which avoids incorrect replacements when a
        PII value happens to be a substring of a common word or another match.

        Algorithm:
        1. Run all patterns on the original text and collect (start, end, label, value).
        2. Sort by start position; discard overlapping matches (first match wins).
        3. Process matches right-to-left so that earlier offsets stay valid.

        Guard anti-ReDoS : le texte est tronqué à _MAX_REGEX_INPUT caractères
        avant d'être soumis aux expressions régulières.
        """
        # ── Guard anti-ReDoS ─────────────────────────────────────────────
        if len(text) > _MAX_REGEX_INPUT:
            logger.warning("Text exceeds ReDoS guard (%d > %d). Data beyond limit NOT anonymized.", len(text), _MAX_REGEX_INPUT)
            text = text[:_MAX_REGEX_INPUT]

        # Build a reverse lookup: real-value → existing placeholder, so the
        # same value seen again in a new message reuses the same token.
        _seen: dict[str, str] = {v: k for k, v in self._vault.items()}

        # ── Collect all matches with positions ───────────────────────────
        # list of (start, end, label, original_value)
        all_matches: list[tuple[int, int, str, str]] = []
        for label, pattern in _PATTERNS.items():
            for m in pattern.finditer(text):
                all_matches.append((m.start(), m.end(), label, m.group(0)))

        # Sort ascending by start position; remove overlapping spans (keep first)
        all_matches.sort(key=lambda x: x[0])
        non_overlapping: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, label, original in all_matches:
            if start >= last_end:
                non_overlapping.append((start, end, label, original))
                last_end = end

        # ── Apply substitutions right-to-left (preserves earlier offsets) ─
        result = text
        for start, end, label, original in reversed(non_overlapping):
            if original in _seen:
                placeholder = _seen[original]
            else:
                placeholder = f"[{label}_{self._counter}]"
                self._vault[placeholder] = original
                _seen[original] = placeholder
                self._counter += 1
            result = result[:start] + placeholder + result[end:]

        # ── Couche 2 : NER (personnes / organisations / adresses) ────────
        return self._apply_ner_layer(result, detect=ner_detection)

    def _apply_ner_layer(self, text: str, *, detect: bool = True) -> str:
        """Couche 2 NER — no-op strict si ``PII_NER_ENABLED`` n'est pas
        posé ou si le moteur n'a pas pu être chargé au boot (fail-open,
        la couche 1 regex reste le filet).

        Vault-first : toute valeur DÉJÀ connue du vault (labels PERSON /
        ORG / ADDRESS) est masquée par recherche directe, indépendamment
        du score NER du jour. Le bench 2026-06-10 a montré que la même
        valeur (« Sophie ») score entre 0.46 et 0.72 selon l'occurrence :
        sans ce filet, une occurrence sur deux passait sous le seuil.
        Une fois dans le vault, toutes les occurrences sont masquées.

        Le NER tourne sur le texte post-couche-1 (stable d'un tour à
        l'autre puisque les regex sont déterministes), ce qui maximise les
        hits du cache hash→entités du moteur — le chemin chaud de chat.py
        ré-anonymise ~40 messages d'historique à chaque tour.
        """
        from app.services.pii_ner import (
            NER_PLACEHOLDER_LABELS,
            get_ner_engine,
            is_service_allowlisted,
            pii_ner_enabled,
        )
        if not pii_ner_enabled():
            return text
        engine = get_ner_engine()
        if engine is None:
            return text

        # value → label, le vault d'abord (priorité au label historique :
        # même valeur revue → même placeholder, quoi que dise le NER).
        # Les noms de services allowlistés sont écartés MÊME s'ils sont au
        # vault (entrées créées avant l'allow-list : on cesse de les
        # re-masquer, les conversations polluées guérissent d'elles-mêmes).
        candidates: dict[str, str] = {}
        for placeholder, value in self._vault.items():
            label = placeholder.strip("[]").rsplit("_", 1)[0]
            if (
                label in NER_PLACEHOLDER_LABELS
                and len(value) >= 2
                and not is_service_allowlisted(value)
            ):
                candidates.setdefault(value, label)
        if detect:
            for value, label in engine.extract(text):
                # Ceinture-bretelles : le moteur filtre déjà l'allow-list à
                # l'extraction, mais le contrat « un service intégré n'est
                # JAMAIS masqué » doit tenir quel que soit le moteur.
                if not is_service_allowlisted(value):
                    candidates.setdefault(value, label)
        if not candidates:
            return text
        return self._replace_values(text, candidates)

    def _replace_values(self, text: str, candidates: dict[str, str]) -> str:
        """Remplace chaque occurrence en texte libre des ``candidates``
        (value → label) par son placeholder, en réutilisant le vault.

        Mêmes garanties que la couche 1 : matching par positions avec
        frontières de mots (« Marion » ne matche pas « Marionnette »),
        chevauchements résolus au plus long (« Sophie Lefebvre » avant
        « Sophie »), substitution droite→gauche, et jamais à l'intérieur
        d'un placeholder déjà posé.
        """
        forbidden = [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]

        def _overlaps_placeholder(start: int, end: int) -> bool:
            return any(start < f_end and end > f_start for f_start, f_end in forbidden)

        all_matches: list[tuple[int, int, str, str]] = []
        for value, label in candidates.items():
            # Frontières de mots unicode, seulement quand la valeur commence/
            # finit par un caractère de mot (une adresse finissant par « . »
            # n'a pas besoin de garde à droite).
            prefix = r"(?<!\w)" if (value[0].isalnum() or value[0] == "_") else ""
            suffix = r"(?!\w)" if (value[-1].isalnum() or value[-1] == "_") else ""
            pattern = re.compile(prefix + re.escape(value) + suffix)
            for m in pattern.finditer(text):
                if not _overlaps_placeholder(m.start(), m.end()):
                    all_matches.append((m.start(), m.end(), label, value))

        # Position croissante, puis le plus LONG d'abord à position égale.
        all_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        non_overlapping: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, label, value in all_matches:
            if start >= last_end:
                non_overlapping.append((start, end, label, value))
                last_end = end

        _seen: dict[str, str] = {v: k for k, v in self._vault.items()}
        result = text
        for start, end, label, value in reversed(non_overlapping):
            placeholder = _seen.get(value)
            if placeholder is None:
                placeholder = f"[{label}_{self._counter}]"
                self._vault[placeholder] = value
                _seen[value] = placeholder
                self._counter += 1
            result = result[:start] + placeholder + result[end:]
        return result

    def deanonymize(self, text: str) -> str:
        """Restore real values from placeholders in LLM output."""
        for placeholder, real in self._vault.items():
            text = text.replace(placeholder, real)
        return text

    # ------------------------------------------------------------------ #
    # Criticality check                                                    #
    # ------------------------------------------------------------------ #

    def is_critical(self, text: str) -> bool:
        """Return True if the text contains a keyword or sensitive placeholder
        that requires human validation before execution.

        Matching is done on WORD BOUNDARIES, not substrings — otherwise
        `notes_delete` (a safe local-only operation) would match "delete"
        and trigger unnecessary HITL prompts. ALWAYS_CRITICAL_TOOLS
        already covers the truly destructive cases in the HITL manager.
        """
        import re as _re
        lower = text.lower()
        # Whole-word (or whole-phrase) match — anchor on \b for single
        # words, let multi-token keywords like "rm -rf" match literally.
        for kw in _CRITICAL_KEYWORDS:
            pattern = (
                r"\b" + _re.escape(kw) + r"\b"
                if kw.isalpha() and " " not in kw
                else _re.escape(kw)
            )
            if _re.search(pattern, lower):
                return True
        # Any placeholder for card / token / IBAN in an action description
        if any(f"[{t}_" in text for t in ("CARD", "TOKEN", "IBAN")):
            return True
        return False

    def reset(self) -> None:
        self._vault.clear()
        self._counter = 0

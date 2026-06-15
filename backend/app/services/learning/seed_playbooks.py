# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/seed_playbooks.py
# @brief      Jalon 1 (portage Hermes) — bundled seed playbooks (warm library)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Bundled seed playbooks — Jalon 1 (portage Hermes).

Hermes ships **89 SKILL.md** so the agent's procedural library is alive from
day one and the model sees concrete examples of the format. Ely shipped
**zero** — its library started cold and never warmed (audit 2026-06-15). This
module seeds a small set of FR playbooks on Franck's real usage at boot.

Seeds are ``source = bundled`` → immune to the auto-curator (it only touches
``auto_generated``). They are inserted ``status = active`` so the agent can
consult them immediately via ``skill_view``. Loading is idempotent
(keyed on ``user_id + name``) and best-effort.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.models.user import User

logger = logging.getLogger(__name__)


# Each seed : name (kebab), description (≤200), tags, and the Markdown body
# (the title + sections that ``skill_view`` returns). Kept tight (< 300 words)
# to match the creator's token economy.
SEED_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "name": "prospection-deduplication-leads",
        "description": "Nettoyer, dédupliquer et scorer une liste de prospects avant tout envoi.",
        "tags": ["prospection", "leads", "crm"],
        "body": """# Dédupliquer et scorer une liste de prospects

## Quand ce playbook s'applique
- L'utilisateur fournit une liste d'entreprises/contacts à prospecter.
- On suspecte des doublons ou des entrées incomplètes.

## Procédure
1. Normalise chaque entrée (nom d'entreprise en minuscules, domaine sans `www.`, téléphone au format FR).
2. Repère les doublons par domaine d'email PUIS par nom d'entreprise normalisé ; fusionne en gardant la fiche la plus complète.
3. Marque comme incomplète toute fiche sans email NI téléphone (ne la jette pas, signale-la).
4. Score chaque prospect (0-3) : email pro présent (+1), site web actif (+1), secteur cible (+1).
5. Restitue un tableau trié par score décroissant + le compte de doublons fusionnés.

## Ce qu'il NE faut PAS faire
- Ne supprime jamais une fiche en doublon sans avoir fusionné ses infos.
- N'invente pas d'email/de téléphone manquant.
- N'envoie aucun message à ce stade : la prospection d'envoi est une étape séparée que l'utilisateur valide.
""",
    },
    {
        "name": "email-vers-evenement-agenda",
        "description": "Créer un évènement Calendar à partir d'un email, en confirmant les détails ambigus.",
        "tags": ["gmail", "calendar", "agenda"],
        "body": """# Transformer un email en évènement d'agenda

## Quand ce playbook s'applique
- L'utilisateur demande de mettre un rendez-vous/une réunion mentionné dans un mail dans son agenda.

## Procédure
1. Lis l'email avec `gmail_list_emails`/lecture pour extraire : titre, date, heure début/fin, lieu/visio, participants.
2. Si une date ou une heure est ambiguë ou absente, DEMANDE à l'utilisateur avant de créer (ne devine pas).
3. Crée l'évènement avec `calendar_create_event` en y mettant le lien/visio et un rappel par défaut.
4. Confirme en une phrase : titre + date + heure + lieu.

## Ce qu'il NE faut PAS faire
- Ne crée jamais un évènement avec une date inventée ou « probable ».
- N'invite pas de participants externes sans validation explicite.
""",
    },
    {
        "name": "tache-planifiee-outils-reels",
        "description": "Lors de la création d'une tâche planifiée, ne référencer que des outils réellement existants.",
        "tags": ["scheduler", "tâches-planifiées", "fiabilité"],
        "body": """# Créer une tâche planifiée fiable

## Quand ce playbook s'applique
- L'utilisateur demande une automatisation récurrente (briefing, surveillance, rappel).

## Procédure
1. Rédige le prompt de la tâche en n'utilisant QUE des outils qui existent dans la liste des outils disponibles (vérifie les noms exacts).
2. Si un besoin n'a pas d'outil correspondant, écris la procédure sans cet outil (ex. « demande à l'utilisateur ») plutôt que d'inventer un nom.
3. Précise la fréquence en clair et le canal de livraison attendu.
4. Relis le prompt : chaque action doit être réalisable avec un outil nommé réel.

## Ce qu'il NE faut PAS faire
- N'invente JAMAIS un nom d'outil (ex. `tasks_list`, `scheduler_list_tasks`) : une tâche qui appelle un outil fantôme échoue silencieusement à chaque exécution.
""",
    },
    {
        "name": "epreuve-catalogue-boucle-correction",
        "description": "Boucle d'épreuve CatalogMaker : annoter, appliquer les corrections, re-générer, re-vérifier.",
        "tags": ["catalogmaker", "épreuve", "bat"],
        "body": """# Boucle d'épreuve d'un catalogue

## Quand ce playbook s'applique
- L'utilisateur veut corriger une épreuve (BAT) de catalogue et itérer jusqu'à validation.

## Procédure
1. Récupère la liste des annotations/corrections demandées (texte, prix, image, mise en page).
2. Regroupe les corrections par page pour limiter les allers-retours.
3. Applique-les, puis re-génère l'épreuve de la/les page(s) modifiée(s) uniquement.
4. Re-vérifie chaque correction appliquée une par une ; signale celles non résolues.
5. Présente un récapitulatif : corrigé / en attente.

## Ce qu'il NE faut PAS faire
- Ne déclare pas une correction faite sans l'avoir re-vérifiée sur l'épreuve régénérée.
- Ne régénère pas tout le catalogue si seules quelques pages ont changé.
""",
    },
    {
        "name": "action-irreversible-demander-avant",
        "description": "Avant toute action destructrice ou irréversible (suppression, envoi externe), confirmer.",
        "tags": ["sécurité", "hitl", "garde-fou"],
        "body": """# Confirmer avant une action irréversible

## Quand ce playbook s'applique
- L'action s'apprête à supprimer, écraser, ou envoyer quelque chose vers l'extérieur (email, message, fichier partagé).

## Procédure
1. Identifie précisément la cible (quel fichier, quel destinataire, quel message).
2. Résume en une phrase ce qui va se passer et que c'est irréversible.
3. Demande une confirmation explicite à l'utilisateur AVANT d'exécuter.
4. N'exécute qu'après un « oui » clair ; sinon, propose une alternative non destructrice.

## Ce qu'il NE faut PAS faire
- Ne supprime/n'envoie jamais « pour gagner du temps » sans validation.
- Ne considère pas un silence comme un accord.
""",
    },
]


def _build_seed_row(user_id: str, seed: dict[str, Any]) -> LearnedSkill:
    frontmatter = {
        "name": seed["name"],
        "description": seed["description"],
        "tags": seed["tags"],
    }
    return LearnedSkill(
        user_id=user_id,
        name=seed["name"],
        description=seed["description"],
        content=seed["body"],
        frontmatter_json=json.dumps(frontmatter, ensure_ascii=False),
        status=SkillStatus.ACTIVE,
        source=SkillSource.BUNDLED,
        content_format=SkillContentFormat.MARKDOWN_PLAYBOOK,
        iteration_count=0,
        from_failure_case_ids=json.dumps([]),
        rationale="Seed playbook bundled with ELY (Jalon 1 — portage Hermes).",
    )


async def load_seed_playbooks() -> dict[str, int]:
    """Ensure every user has the bundled seed playbooks. Idempotent.

    Returns a summary ``{"users": n, "inserted": m}``. Never raises.
    """
    summary = {"users": 0, "inserted": 0}
    try:
        async with async_session() as db:
            user_ids = list((await db.execute(select(User.id))).scalars().all())
            seed_names = [s["name"] for s in SEED_PLAYBOOKS]
            for uid in user_ids:
                if not uid:
                    continue
                summary["users"] += 1
                existing = set((await db.execute(
                    select(LearnedSkill.name).where(
                        LearnedSkill.user_id == uid,
                        LearnedSkill.name.in_(seed_names),
                    )
                )).scalars().all())
                for seed in SEED_PLAYBOOKS:
                    if seed["name"] in existing:
                        continue
                    db.add(_build_seed_row(uid, seed))
                    summary["inserted"] += 1
            if summary["inserted"]:
                await db.commit()
    except Exception as exc:
        logger.warning("load_seed_playbooks failed (swallowed): %s", exc)
        return summary
    if summary["inserted"]:
        logger.info(
            "seed_playbooks: inserted %d playbook(s) across %d user(s)",
            summary["inserted"], summary["users"],
        )
    return summary

# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/skills.py
# @brief      REST API for the skill registry and per-user skill preferences
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""REST API for the skill registry and per-user skill preferences.

Endpoints
---------
GET  /skills/              List all skills with enabled status for the current user
GET  /skills/catalog       Same, plus what each tool COÛTE et SERT réellement
PUT  /skills/{skill_name}  Enable/disable a skill (or save its config)

⚠️ POURQUOI `/catalog` EXISTE (24/08). `GET /skills/` dit ce qui est branché ;
il ne dit pas ce que ça coûte. Or la question de Franck était : « à quoi sert
le dernier outil `qrcode_generate` ? Quel intérêt d'envoyer un tel outil ? »

Sans chiffres, on y répond à l'intuition. Avec, la décision se prend seule :

    qrcode_generate   235 tokens à chaque tour   0 appel depuis 8 mois

Deux mesures, donc, et elles viennent de sources différentes :

- **le coût** — longueur description + schéma JSON, divisée par 4. C'est une
  APPROXIMATION, annoncée comme telle jusque dans le nom du champ
  (`approx_tokens`) : le vrai découpage dépend du tokenizer de chaque modèle.
  Un chiffre faux présenté comme exact ferait prendre des décisions sur du
  vent ; à ±20 %, il suffit largement à trier 200 outils.
- **l'usage** — `usage_logs.skill_used`, la seule trace durable de ce qui a
  été réellement appelé.

⚠️ « 0 appel » ne veut PAS dire « inutile ». Un outil peut n'avoir jamais servi
parce que personne n'en a eu besoin, ou parce que le modèle ne l'a jamais
trouvé. La réponse est rendue avec la date du plus ancien enregistrement
(`since`), pour qu'on sache sur quelle fenêtre on juge.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.skill_preference import SkillPreference
from app.skills import get_skill_registry

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Schemas                                                              #
# ------------------------------------------------------------------ #

class SkillUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None


# ------------------------------------------------------------------ #
# Routes                                                               #
# ------------------------------------------------------------------ #

@router.get("/")
async def list_skills(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all registered skills with their enabled status for the caller."""
    result = await db.execute(
        select(SkillPreference).where(SkillPreference.user_id == current_user.id)
    )
    prefs: dict[str, SkillPreference] = {
        p.skill_name: p for p in result.scalars().all()
    }

    registry = get_skill_registry()
    return [
        {
            "name": s.name,
            "display_name": s.display_name,
            "description": s.description,
            "icon": s.icon,
            "version": s.version,
            "author": s.author,
            "scopes": s.scopes,
            "enabled_by_default": s.enabled_by_default,
            "enabled": prefs[s.name].enabled if s.name in prefs else s.enabled_by_default,
            "tool_count": len(s.tools),
            "tool_names": [t.name for t in s.tools],
            "config": (
                json.loads(prefs[s.name].config_json)
                if s.name in prefs and prefs[s.name].config_json
                else {}
            ),
        }
        for s in registry.list_skills()
    ]


def _approx_tokens(tool) -> int:
    """Ce que le schéma d'un outil pèse dans le prompt, à la louche.

    Description + schéma JSON, divisé par 4. Approximation assumée : le vrai
    découpage dépend du tokenizer. Le champ s'appelle `approx_tokens` pour que
    personne ne le prenne pour une mesure.
    """
    desc = getattr(tool, "description", "") or ""
    brut = ""
    try:
        if getattr(tool, "args_schema", None) is not None:
            brut = json.dumps(tool.args_schema.model_json_schema())
    except Exception:  # noqa: BLE001 — un schéma illisible vaut 0, pas une 500
        brut = ""
    return (len(desc) + len(brut)) // 4


async def _usage_par_outil(db: AsyncSession) -> tuple[dict[str, int], str | None]:
    """``({nom d'outil: nombre d'appels}, date du plus ancien enregistrement)``.

    Échoue ouvert : sans table d'usage, on rend des compteurs vides plutôt
    qu'une erreur. Un catalogue sans chiffres reste utile ; un catalogue qui
    ne s'affiche pas, non.
    """
    try:
        from sqlalchemy import func

        from app.models.usage_log import UsageLog

        lignes = (await db.execute(
            select(UsageLog.skill_used, func.count())
            .where(UsageLog.skill_used.isnot(None))
            .group_by(UsageLog.skill_used)
        )).all()
        depuis = (await db.execute(select(func.min(UsageLog.timestamp)))).scalar()
        return (
            {nom: int(n) for nom, n in lignes if nom},
            depuis.isoformat() if depuis else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalogue : usage illisible (%s) — compteurs absents", exc)
        return {}, None


@router.get("/catalog")
async def tool_catalog(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Le catalogue outil par outil : ce qu'il coûte, ce qu'il a servi.

    ⚠️ La route est déclarée AVANT `PUT /{skill_name}` mais surtout avant tout
    `GET /{…}` : FastAPI apparie dans l'ordre de déclaration, et une route
    paramétrée placée avant avalerait « catalog » comme un nom de compétence.
    """
    result = await db.execute(
        select(SkillPreference).where(SkillPreference.user_id == current_user.id)
    )
    lignes = list(result.scalars().all())
    prefs = {p.skill_name: p.enabled for p in lignes}
    # ⚠️ Coupures OUTIL PAR OUTIL (24/08). Le poids mort ne se répartit pas par
    # compétence : il se niche DANS les plus utilisées, parce que ce sont
    # elles qui ont le plus d'outils. Gmail : 234 appels, indispensable — et
    # neuf de ses vingt-et-un outils jamais appelés, 2 433 tokens à chaque
    # tour, hors d'atteinte d'un interrupteur par compétence.
    from app.skills.preferences_runtime import _outils_coupes

    coupes = _outils_coupes(lignes)
    appels, depuis = await _usage_par_outil(db)

    registry = get_skill_registry()
    competences = []
    total_outils = 0
    total_tokens = 0
    total_actifs = 0
    for s in registry.list_skills():
        actif = prefs.get(s.name, s.enabled_by_default)
        coupes_ici = coupes.get(s.name, frozenset())
        outils = []
        for t in s.tools:
            cout = _approx_tokens(t)
            total_outils += 1
            outil_actif = actif and t.name not in coupes_ici
            if outil_actif:
                total_tokens += cout
                total_actifs += 1
            outils.append({
                "name": t.name,
                "description": (getattr(t, "description", "") or "").split("\n")[0][:200],
                "approx_tokens": cout,
                "calls": appels.get(t.name, 0),
                "enabled": outil_actif,
            })
        competences.append({
            "name": s.name,
            "display_name": s.display_name,
            "icon": s.icon,
            "enabled": actif,
            "enabled_by_default": s.enabled_by_default,
            "tool_count": len(s.tools),
            "approx_tokens": sum(o["approx_tokens"] for o in outils),
            # Ce que la compétence pèse RÉELLEMENT une fois ses coupures
            # appliquées — c'est ce chiffre qui doit bouger sous les doigts.
            "enabled_approx_tokens": sum(
                o["approx_tokens"] for o in outils if o["enabled"]
            ),
            "calls": sum(o["calls"] for o in outils),
            "never_called_count": sum(1 for o in outils if o["calls"] == 0),
            "disabled_tools": sorted(coupes_ici),
            "tools": sorted(outils, key=lambda o: -o["approx_tokens"]),
        })

    return {
        # `enabled_*` = ce qui part réellement au modèle. C'est le chiffre qui
        # bouge quand on actionne un interrupteur, donc le seul qui compte
        # pour décider.
        "enabled_tool_count": total_actifs,
        "enabled_approx_tokens": total_tokens,
        "total_tool_count": total_outils,
        "usage_since": depuis,
        "skills": sorted(competences, key=lambda c: -c["approx_tokens"]),
    }


class ToolsUpdate(BaseModel):
    disabled_tools: list[str]


@router.put("/{skill_name}/tools")
async def update_skill_tools(
    skill_name: str,
    body: ToolsUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Couper ou rétablir des outils À L'INTÉRIEUR d'une compétence active.

    ⚠️ POURQUOI CETTE GRANULARITÉ EXISTE (24/08), alors que la #346 avait
    argumenté le contraire. J'y avais écrit que la compétence était la bonne
    unité et que « 200 interrupteurs seraient ingérables ». Le catalogue réel
    l'a réfuté :

        Gmail   21 outils   7 453 tk   234 appels   ← indispensable
                dont 9 jamais appelés : 2 433 tk envoyés à chaque tour

    Le poids mort ne se répartit pas par compétence — il se niche DANS les
    plus utilisées, parce que ce sont elles qui ont le plus d'outils. Aucun
    interrupteur par compétence ne peut l'atteindre.

    ⚠️ Écrit dans `config_json` par FUSION, jamais par remplacement.
    `PUT /{skill_name}` écrase `config_json` entier ; laisser le frontend
    faire un lire-modifier-écrire ouvrirait une course entre deux onglets, et
    perdrait toute autre clé de configuration au passage.

    ⚠️ Les noms inconnus sont REFUSÉS, pas ignorés. Une faute de frappe qui
    ne coupe rien en silence ferait croire à un réglage appliqué — c'est la
    classe de défaut que ce dépôt a corrigée quatre fois ce mois-ci.
    """
    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    connus = {t.name for t in skill.tools}
    inconnus = sorted(set(body.disabled_tools) - connus)
    if inconnus:
        raise HTTPException(
            status_code=400,
            detail=f"Outils inconnus dans « {skill_name} » : {', '.join(inconnus)}",
        )

    result = await db.execute(
        select(SkillPreference).where(
            SkillPreference.user_id == current_user.id,
            SkillPreference.skill_name == skill_name,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = SkillPreference(
            user_id=current_user.id,
            skill_name=skill_name,
            enabled=skill.enabled_by_default,
        )
        db.add(pref)

    try:
        conf = json.loads(pref.config_json) if pref.config_json else {}
        if not isinstance(conf, dict):
            conf = {}
    except Exception:  # noqa: BLE001 — une config corrompue ne bloque pas un réglage
        conf = {}
    conf["disabled_tools"] = sorted(set(body.disabled_tools))
    pref.config_json = json.dumps(conf)

    await db.commit()

    from app.skills.preferences_runtime import bump_preferences_version

    bump_preferences_version()
    logger.info(
        "outils coupés dans %s pour %s… : %d",
        skill_name, current_user.id[:8], len(conf["disabled_tools"]),
    )
    return {"skill": skill_name, "disabled_tools": conf["disabled_tools"]}


@router.put("/{skill_name}")
async def update_skill(
    skill_name: str,
    body: SkillUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable, disable or configure a skill for the current user."""
    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    result = await db.execute(
        select(SkillPreference).where(
            SkillPreference.user_id == current_user.id,
            SkillPreference.skill_name == skill_name,
        )
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = SkillPreference(
            user_id=current_user.id,
            skill_name=skill_name,
            enabled=skill.enabled_by_default,
        )
        db.add(pref)

    if body.enabled is not None:
        pref.enabled = body.enabled
    if body.config is not None:
        pref.config_json = json.dumps(body.config)

    await db.commit()
    await db.refresh(pref)

    # ⚠️ LE FIL ENTRE L'INTERRUPTEUR ET LE MODÈLE (24/08). Sans cette ligne,
    # la préférence est en base, l'écran l'affiche, et le cache de
    # `preferences_runtime` continue de servir l'ancien état jusqu'au
    # redémarrage — le défaut même que ce câblage corrige, reproduit un cran
    # plus loin. Même motif que `llm_provider._tier_config_version` (#342).
    from app.skills.preferences_runtime import bump_preferences_version

    bump_preferences_version()

    logger.info(
        "Skill '%s' %s for user %s",
        skill_name,
        "enabled" if pref.enabled else "disabled",
        current_user.id,
    )
    return {
        "name": skill_name,
        "enabled": pref.enabled,
        "config": json.loads(pref.config_json) if pref.config_json else {},
    }

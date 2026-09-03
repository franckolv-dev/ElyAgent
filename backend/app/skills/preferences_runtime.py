# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/preferences_runtime.py
# @brief      Les compétences désactivées atteignent enfin la liaison d'outils.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Ce que l'utilisateur désactive doit disparaître de la charge envoyée.

⚠️ LE TROU QUE CE MODULE BOUCHE (24/08).

Tout existait sauf le fil :

    GET  /skills/                     liste les 45 compétences et leurs outils
    PUT  /skills/{nom}                écrit `SkillPreference.enabled`
    registry.get_user_active_tools()  lit les préférences et filtre

    $ grep -rn "get_user_active_tools" app/
    app/skills/registry.py:25:  - Expose ``get_user_active_tools()`` for …
    app/skills/registry.py:110: async def get_user_active_tools(…)

**Zéro appelant.** La docstring du registre l'annonçait, la fonction était
correcte, et rien ne l'appelait. Désactiver une compétence écrivait en base,
s'affichait à l'écran, et ne changeait strictement rien à ce que le modèle
recevait.

C'est la QUATRIÈME occurrence de ce motif ce mois-ci — après #272 (fenêtre de
contexte et tarifs), #336 (modèle du tier A) et #342 (modèle d'instance). Une
écriture qui atteint la base sans atteindre le runtime.

Preuve la plus parlante : la compétence `fibonacci` — un outil de test — est
marquée `enabled_by_default=False` depuis toujours. Elle partait quand même
dans le prompt à chaque tour.

POURQUOI UN CACHE, ET POURQUOI CE COMPTEUR-LÀ
----------------------------------------------
La liaison se refait à chaque tour ; interroger la base à chaque tour pour une
préférence qui change trois fois par an serait absurde. Mais un cache sans
invalidation reproduirait EXACTEMENT le défaut qu'on corrige : l'interrupteur
écrirait en base et le cache continuerait de servir l'ancien état.

D'où le compteur, incrémenté par l'endpoint d'écriture — le même motif que
`llm_provider._tier_config_version`, avec le même invariant : **tout ce qui
change les préférences doit l'incrémenter.**

ON ÉCHOUE OUVERT, ET C'EST DÉLIBÉRÉ
-------------------------------------
Une base injoignable, une table absente, une requête qui lève : on rend un
ensemble vide, donc **aucun outil n'est retiré**. Un filtre qui échoue en
retirant des outils rendrait Ely muette sur une panne de lecture — le pire
échange possible. Hermes a payé ce prix : leur #38798 (une migration de config
a réécrit un nom de toolset, `resolve_toolset` a rendu une liste vide, et
**tous les outils ont disparu en silence**) leur a fait rendre l'état « zéro
outil » bruyant. On applique la leçon en amont : ici, un doute ne retire rien.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Incrémenté à chaque écriture de préférence. Les caches en aval le relisent.
_version: int = 0

# {user_id: (version, frozenset[nom d'outil désactivé])}
_cache: dict[str, tuple[int, frozenset[str]]] = {}

# Borne le cache sur une instance multi-comptes. La valeur est large : une
# entrée pèse quelques dizaines d'octets, et l'éviction ne coûte qu'une
# requête de plus au tour suivant.
_MAXSIZE = 500


def _outils_coupes(lignes) -> dict[str, frozenset[str]]:
    """``{nom de compétence: outils coupés un par un}``, lu dans `config_json`.

    Forme stockée : ``{"disabled_tools": ["gmail_update_settings", …]}``.

    ⚠️ Ne lève JAMAIS sur une configuration illisible. Un JSON corrompu sur
    une compétence ne doit pas emporter les préférences des 44 autres, et
    surtout pas faire retirer des outils au hasard — on ignore l'entrée
    fautive et on la signale.
    """
    import json

    out: dict[str, frozenset[str]] = {}
    for ligne in lignes:
        brut = getattr(ligne, "config_json", None)
        if not brut:
            continue
        try:
            conf = json.loads(brut)
            coupes = conf.get("disabled_tools") if isinstance(conf, dict) else None
            if isinstance(coupes, list):
                out[ligne.skill_name] = frozenset(
                    str(n) for n in coupes if isinstance(n, str)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "préférences de %s illisibles (%s) — outils tous conservés",
                ligne.skill_name, exc,
            )
    return out


def bump_preferences_version() -> None:
    """À appeler après TOUTE écriture de `SkillPreference`.

    ⚠️ C'est le seul lien entre l'interrupteur et le runtime. L'oublier
    recrée le défaut du 24/08 : la base change, le modèle continue de recevoir
    l'ancien catalogue. Épinglé par
    `test_disabling_a_skill_reaches_the_model.py`.
    """
    global _version
    _version += 1


def get_preferences_version() -> int:
    """Compteur monotone — les caches en aval comparent par inégalité."""
    return _version


async def disabled_tool_names(user_id: str) -> frozenset[str]:
    """Les noms d'outils que *user_id* a désactivés, à l'instant.

    Rend un ensemble VIDE au moindre doute (pas d'utilisateur, base
    injoignable, registre vide) : un filtre qui échoue ne doit jamais retirer
    d'outils.
    """
    if not user_id:
        return frozenset()

    courant = _version
    en_cache = _cache.get(user_id)
    if en_cache is not None and en_cache[0] == courant:
        return en_cache[1]

    try:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.skill_preference import SkillPreference
        from app.skills import get_skill_registry

        async with async_session() as db:
            lignes = (await db.execute(
                select(SkillPreference).where(SkillPreference.user_id == user_id)
            )).scalars().all()
        prefs = {p.skill_name: p.enabled for p in lignes}
        # ⚠️ LA GRANULARITÉ PAR OUTIL (24/08), et elle corrige un argument que
        # j'avais avancé dans la #346 : « la compétence est l'unité qui a un
        # sens fonctionnel, 200 interrupteurs seraient ingérables ».
        #
        # Le catalogue de Franck l'a réfuté en une capture. Gmail : 21 outils,
        # 234 appels, indispensable — et NEUF de ses outils n'ont jamais servi
        # (`gmail_update_settings` 583 tk, `gmail_trash_by_query` 535,
        # `gmail_batch_modify` 399…), soit 2 433 tokens envoyés à chaque tour,
        # hors d'atteinte d'un interrupteur par compétence.
        #
        # Le poids mort ne se répartit pas par compétence : il se niche DANS
        # les compétences les plus utilisées, parce que ce sont elles qui ont
        # le plus d'outils.
        #
        # ⚠️ Stocké dans `config_json`, PAS dans une nouvelle table. La colonne
        # existe, elle est libre, et l'invariant 1 du dépôt dit qu'Alembic seul
        # fait foi sur le schéma — une migration pour une liste de chaînes
        # serait un coût sans contrepartie.
        par_outil = _outils_coupes(lignes)

        noms: set[str] = set()
        for skill in get_skill_registry().list_skills():
            if not prefs.get(skill.name, skill.enabled_by_default):
                noms.update(t.name for t in skill.tools)
            else:
                # Compétence active : on ne retire que ses outils coupés un
                # par un. Une compétence coupée les emporte déjà tous.
                noms.update(par_outil.get(skill.name, frozenset()))
        resultat = frozenset(noms)
    except Exception as exc:  # noqa: BLE001 — voir « on échoue ouvert »
        logger.warning(
            "préférences de compétences illisibles (%s) — aucun outil retiré "
            "pour ce tour", exc,
        )
        return frozenset()

    while len(_cache) >= _MAXSIZE:
        _cache.pop(next(iter(_cache)))
    _cache[user_id] = (courant, resultat)
    if resultat:
        logger.info(
            "compétences désactivées pour %s… : %d outil(s) retiré(s)",
            user_id[:8], len(resultat),
        )
    return resultat


def appliquer(outils: list, desactives: frozenset[str], *, contexte: str) -> list:
    """*outils* moins ceux que l'utilisateur a désactivés.

    ⚠️ NE REND JAMAIS UNE LISTE VIDE quand l'entrée ne l'était pas, et le dit
    fort quand ça se produit. C'est la leçon d'Hermes #38798 : un catalogue
    vidé par une préférence mal comprise dégrade l'agent en « répondeur
    texte » sans qu'aucun message ne l'explique. Mieux vaut un filtre qui
    renonce bruyamment qu'un agent muet.
    """
    if not desactives or not outils:
        return outils
    retenus = [t for t in outils if getattr(t, "name", "") not in desactives]
    if not retenus:
        logger.warning(
            "[%s] les préférences retirent TOUS les outils (%d) — filtre ignoré "
            "pour ce tour. Réactive au moins une compétence dans Paramètres → "
            "Outils.", contexte, len(outils),
        )
        return outils
    if len(retenus) != len(outils):
        logger.info(
            "[%s] %d outil(s) retiré(s) par les préférences", contexte,
            len(outils) - len(retenus),
        )
    return retenus


def vider_cache() -> None:
    """Pour les tests — repart d'un état propre."""
    _cache.clear()

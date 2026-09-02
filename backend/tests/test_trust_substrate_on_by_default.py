# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_trust_substrate_on_by_default.py
# @brief      Le substrat de confiance doit être ON par défaut, comme son
#             commentaire voisin l'affirmait déjà.
# @license    Elastic License 2.0
# =============================================================================
"""Pin du défaut de ``trust_substrate_enabled`` (audit 02/09/2026).

Le code disait deux choses contradictoires, à onze lignes d'écart :

    trust_substrate_enabled: bool = False
    ...
    # (≠ trust_substrate_enabled, déjà ON en prod) pour canaryer séparément.

La prod avait raison — son conteneur porte ``TRUST_SUBSTRATE_ENABLED=true``.
Le défaut du code, lui, laissait toute INSTALLATION NEUVE sans substrat :

- l'empreinte du plan d'action n'était pas calculée, donc la re-vérification
  « l'action exécutée est EXACTEMENT celle approuvée » (fail-closed,
  ``tool_gateway``) ne pouvait pas se déclencher ;
- le magasin d'idempotence ne voyait jamais un appel, donc une action
  ``supported`` re-jouée par accident était ré-exécutée.

Une garde qui n'existe que dans le ``.env`` d'une machine n'est pas une garde.
Ces tests épinglent le défaut ET son effet observable, pour que la valeur et
le commentaire ne puissent plus diverger en silence.

Le dernier épingle le DELTA de comportement que ce défaut fait entrer en
service : sur ``web_search``, le manifeste (``approval=NEVER``) court-circuite
l'analyse de risque par mots-clefs. C'est un faux positif de moins, pas un
non-événement — donc c'est écrit, pas tu.

Run with:  cd backend && python -m pytest tests/test_trust_substrate_on_by_default.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


class _AlwaysAllowHitl:
    """HITL témoin : accepte tout, mais retient CHAQUE demande — c'est le fait
    d'être interrogé, pas la réponse, qu'on observe."""

    def __init__(self) -> None:
        self.demandes: list[str] = []

    async def request_validation(self, description, user_id):
        self.demandes.append(description)
        return ("allow", None)


class _CountingTool:
    """Outil témoin : compte ses exécutions réelles."""

    def __init__(self, name: str, result: str) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    async def ainvoke(self, args):
        self.calls += 1
        return self.result


def _ctx(conversation_id: str, hitl=None):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    return GatewayContext(
        user_id="u-substrat", conversation_id=conversation_id,
        pii_filter=get_filter(conversation_id), criticality_filter=SecurityFilter(),
        hitl=hitl or _AlwaysAllowHitl(), memory=None,
    )


async def _forget(tool_name: str, args: dict) -> None:
    """Purge l'enregistrement d'idempotence laissé par le test."""
    from app.database import async_session
    from app.models.idempotency import IdempotencyRecord
    from app.services.action_plan import build_action_plan, fingerprint

    key = fingerprint(build_action_plan(tool_name, args, "u-substrat", None))
    async with async_session() as db:
        rec = await db.get(IdempotencyRecord, key)
        if rec:
            await db.delete(rec)
            await db.commit()


def test_le_substrat_est_actif_par_defaut():
    """Le défaut déclaré doit dire la même chose que la prod et que le
    commentaire voisin. C'est CE test qui interdit la dérive."""
    from app.config import Settings

    assert Settings.model_fields["trust_substrate_enabled"].default is True


@pytest.mark.asyncio
async def test_sur_une_installation_neuve_l_idempotence_protege_deja():
    """Sans aucune variable d'environnement, une action ``supported`` rejouée
    à l'identique rend le résultat mémorisé au lieu de ré-exécuter l'outil.

    Avant le correctif, le drapeau OFF par défaut rendait tout ce chemin
    inerte : l'outil partait deux fois."""
    from app.services.tool_gateway import execute_tool_call

    args = {"query": f"meteo-{uuid.uuid4().hex}"}
    tool = _CountingTool("web_search", "il fait beau")
    ctx = _ctx(f"conv-substrat-{uuid.uuid4().hex}")

    try:
        first = await execute_tool_call(
            ctx, {"name": "web_search", "args": dict(args), "id": "s1"},
            {"web_search": tool},
        )
        second = await execute_tool_call(
            ctx, {"name": "web_search", "args": dict(args), "id": "s2"},
            {"web_search": tool},
        )
    finally:
        await _forget("web_search", args)

    assert tool.calls == 1, "l'action a été ré-exécutée : le substrat est inerte"
    assert "il fait beau" in first["content"]
    assert "il fait beau" in second["content"]


@pytest.mark.asyncio
async def test_le_substrat_ne_confirme_plus_une_recherche_web_au_mot_alarmant():
    """Le DELTA assumé du substrat ON, épinglé au lieu d'être nié.

    L'invariant écrit à côté (« le manifeste reproduit à l'identique la
    décision actuelle pour tout outil connu ») a UNE exception réelle :
    ``web_search`` porte ``approval=NEVER`` dans le manifeste, et
    ``manifest_requires_hitl`` rend False AVANT d'appeler l'analyse de risque.

    Sur le chemin OFF, la requête était scannée par mots-clefs : chercher
    « comment supprimer un compte » demandait une confirmation. Une recherche
    web ne fait que LIRE — c'était un faux positif, et le manifeste le
    supprime. Changement DÉFENDABLE, mais il doit rester visible : si un jour
    quelqu'un remet une confirmation sur ce chemin, ou l'enlève sur un outil
    mutant, c'est ce test qui doit parler."""
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import execute_tool_call

    requete = f"comment supprimer un compte google {uuid.uuid4().hex}"
    # Prémisse : cette requête déclenche VRAIMENT l'analyse de risque. Sans
    # elle, le test passerait même si le mot-clef disparaissait de la liste.
    assert SecurityFilter().is_critical(requete) is True

    args = {"query": requete}
    tool = _CountingTool("web_search", "trois articles trouvés")
    hitl = _AlwaysAllowHitl()
    ctx = _ctx(f"conv-substrat-{uuid.uuid4().hex}", hitl=hitl)

    try:
        await execute_tool_call(
            ctx, {"name": "web_search", "args": dict(args), "id": "w1"},
            {"web_search": tool},
        )
    finally:
        await _forget("web_search", args)

    assert hitl.demandes == [], (
        "confirmation demandée pour une lecture web : le manifeste "
        "approval=NEVER n'est plus honoré"
    )
    assert tool.calls == 1


def test_le_env_example_ne_defait_aucun_defaut_du_code():
    """Le garde-fou du piège qui a coûté ce lot.

    ``README``, ``README.fr`` et ``docs/installation.md`` prescrivent tous
    ``cp .env.example .env``. Une valeur ÉCRITE dans ce fichier bat donc le
    défaut du code sur toute installation neuve : passer un drapeau à ``True``
    dans ``config.py`` ne change rien pour personne tant que ``.env.example``
    dit ``false``. C'est exactement ce qui était arrivé à
    ``TRUST_SUBSTRATE_ENABLED``.

    Si ce test rougit, la correction est d'aligner ``.env.example`` sur le
    nouveau défaut (et de réécrire le commentaire au-dessus), pas d'assouplir
    l'assertion."""
    from pathlib import Path

    from app.config import Settings

    example = Path(__file__).resolve().parents[2] / ".env.example"
    if not example.is_file():
        pytest.skip("dépôt sans .env.example (image applicative)")

    ecrit: dict[str, str] = {}
    for ligne in example.read_text(encoding="utf-8").splitlines():
        nu = ligne.strip()
        if not nu or nu.startswith("#") or "=" not in nu:
            continue
        cle, valeur = nu.split("=", 1)
        ecrit[cle.strip()] = valeur.strip()

    contradictions = []
    for nom, champ in Settings.model_fields.items():
        if not isinstance(champ.default, bool):
            continue
        brut = ecrit.get(nom.upper())
        if brut is None:
            continue
        if (brut.lower() in ("1", "true", "yes", "on")) != champ.default:
            contradictions.append(f"{nom.upper()}={brut} (défaut du code : {champ.default})")

    assert contradictions == [], (
        ".env.example défait le défaut du code — la doc prescrit "
        "« cp .env.example .env » : " + ", ".join(contradictions)
    )

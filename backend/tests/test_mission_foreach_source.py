# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_foreach_source.py
# @brief      `foreach: "{{ etape.output }}"` doit recevoir la sortie de
#             CETTE étape-là, entière. Elle recevait le contexte général :
#             les 8 dernières sorties mélangées, chacune coupée à 1200
#             caractères.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La source d'un foreach est l'étape qu'il nomme (incident du 29/08/2026).

Mission structurée « Prospection Calameo-LinkedIn », étape `contacts`,
`foreach: "{{ societes.output }}"` :

    contacts -> skipped : « Aucun item identifiable pour l'itération
                            (résultat source vide ?) »

La source n'était pourtant pas vide : `web_search` avait rendu 2 401
caractères contenant de vraies sociétés. Mais `expand_foreach` recevait
``_load_recent_step_outputs()`` — les sorties de `drive_list_files`,
`web_search` (coupée à 1 200 caractères) et `sheets_create_spreadsheet`,
mélangées. Les sociétés étaient dans la moitié perdue, noyées dans deux
sorties sans rapport.

`SpecStep.foreach_ref` sait pourtant extraire `societes` de
``{{ societes.output }}`` — elle n'était pas utilisée à cet endroit.

Deuxième troncature sur le même chemin : la sortie d'un step est archivée
dans ``mission_step_runs.output``, elle aussi coupée — à 1 500 caractères.
Viser la bonne étape ne sert à rien si ce qu'on y lit est déjà amputé.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

# La vraie sortie de `web_search` faisait 2 401 caractères : au-delà des
# 1 200 du contexte général ET des 1 500 de l'archive. On reproduit ce
# dépassement, dernière société en fin de texte.
_SOCIETES = (
    "Résultats Google [SearXNG] pour « site:calameo.com négoce » :\n"
    + "\n".join(
        f"{i}. Calaméo - SOCIETE_{i} - Négoce et distribution\n"
        f"   Texte de remplissage destiné à dépasser les plafonds de "
        f"troncature du chemin des missions. " * 3
        for i in range(1, 9)
    )
)


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_foreach_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="trouver des sociétés",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


async def _etape_terminee(mid: str, step_id: str, sortie: str) -> None:
    """Reproduit ce que `eval_node` archive à la fin d'une étape de spec.

    Même chaîne d'appels que la production — `ensure_step_run` puis
    `set_step_run_status` sans coupe côté appelant — pour que ces tests
    exercent le chemin réel et non un raccourci qui n'existe qu'ici.
    """
    from app.services import mission_spec_runtime as msr

    await msr.ensure_step_run(mid, step_id, 0, None)
    await msr.set_step_run_status(mid, step_id, 0, status="done", output=sortie)


async def _journalise(mid: str, outil: str, sortie: str) -> None:
    """Trace d'action, telle que `act_node` l'écrit."""
    from app.services import mission_service

    await mission_service.add_step(
        mid, phase="act", tool_name=outil, tool_input={},
        tool_output=sortie, success=True, duration_ms=10,
    )


@pytest.mark.asyncio
async def test_la_source_est_la_sortie_de_l_etape_nommee(mission) -> None:
    """Ni les sorties voisines, ni une version amputée."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _etape_terminee(mid, "historique", "Aucun fichier trouvé.")
    await _etape_terminee(mid, "societes", _SOCIETES)
    await _etape_terminee(mid, "tableur", "Feuille créée : prospection")

    source = await mn._foreach_source(
        mid, {"id": "contacts", "foreach": "{{ societes.output }}"},
    )

    assert "SOCIETE_1" in source and "SOCIETE_8" in source, (
        "la sortie de l'étape nommée doit arriver ENTIÈRE — c'est la "
        "troncature qui a fait conclure « résultat source vide »"
    )
    assert "Feuille créée" not in source, (
        "les sorties des autres étapes n'ont rien à faire dans la source"
    )
    assert "Aucun fichier trouvé" not in source


@pytest.mark.asyncio
async def test_une_reference_libre_retombe_sur_le_contexte_general(mission) -> None:
    """`foreach: "les sociétés citées"` n'a pas d'étape à cibler.

    La forme texte libre est interprétée par le modèle : on lui laisse le
    contexte général, comme avant. Le correctif ne doit pas la casser.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _journalise(mid, "web_search", _SOCIETES)

    source = await mn._foreach_source(
        mid, {"id": "contacts", "foreach": "les sociétés trouvées plus haut"},
    )

    assert "SOCIETE_1" in source


@pytest.mark.asyncio
async def test_une_etape_nommee_mais_sans_sortie_ne_perd_pas_la_main(
    mission,
) -> None:
    """Référence vers une étape sans sortie : on retombe sur le contexte.

    Mieux vaut un contexte trop large qu'une source vide — c'est la source
    vide qui faisait skipper le step sans que rien n'explique pourquoi.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _journalise(mid, "web_search", _SOCIETES)

    source = await mn._foreach_source(
        mid, {"id": "contacts", "foreach": "{{ inconnue.output }}"},
    )

    assert source, "une référence non résolue ne doit pas rendre une source vide"


@pytest.mark.asyncio
async def test_l_archive_d_une_etape_n_est_plus_amputee(mission) -> None:
    """Viser la bonne étape ne suffit pas si l'archive est déjà coupée.

    `eval_node` archive la sortie dans `mission_step_runs.output`. À 1 500
    caractères, une recherche web de 2 400 y perdait la moitié de ses
    résultats — et le foreach relisait cette moitié.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    monkeypatched_len = len(_SOCIETES)
    assert monkeypatched_len > 1500, "le cas testé doit dépasser l'ancien plafond"

    await _etape_terminee(mid, "societes", _SOCIETES)
    source = await mn._foreach_source(
        mid, {"id": "contacts", "foreach": "{{ societes.output }}"},
    )

    assert "SOCIETE_8" in source


@pytest.mark.asyncio
async def test_une_seule_troncature_gouverne_l_archive(mission) -> None:
    """Pas de second plafond qui rabote derrière le premier.

    L'archive était coupée deux fois : `[:1500]` côté appelant, `[:5000]`
    côté écriture. La valeur annoncée n'était donc pas la valeur obtenue.
    `set_step_run_status` est désormais l'unique tronqueur — ce pin le
    vérifie de bout en bout, écriture puis relecture.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    taille = mn.STEP_OUTPUT_ARCHIVE_CHARS
    long_texte = "DEBUT " + ("x" * (taille - 12)) + " FIN"

    await _etape_terminee(mid, "societes", long_texte)
    source = await mn._foreach_source(
        mid, {"id": "contacts", "foreach": "{{ societes.output }}"},
    )

    assert source.startswith("DEBUT")
    assert source.endswith("FIN"), (
        "l'archive doit tenir jusqu'au plafond annoncé, sans second rabot"
    )


@pytest.mark.asyncio
async def test_le_prompt_d_expansion_nomme_l_etape_pas_le_gabarit(
    mission, monkeypatch,
) -> None:
    """« Étape source « societes » », pas « {{ societes.output }} ».

    `expand_foreach` recopiait la chaîne brute dans son prompt : elle
    annonçait au modèle une étape nommée « {{ societes.output }} », ce qui
    n'est le nom de rien. Elle était structurellement incapable de dire
    d'où venait le texte qu'elle lui donnait.
    """
    import types

    from app.services import mission_spec_runtime as msr

    _uid, mid = mission
    vus: list[str] = []

    class _FauxLLM:
        async def ainvoke(self, messages):
            vus.append(messages[0]["content"])
            return types.SimpleNamespace(content='["Acme"]')

    monkeypatch.setattr(msr, "get_llm_for_tier", lambda _t: _FauxLLM(), raising=False)
    import app.services.llm_provider as lp
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda _t: _FauxLLM())

    await msr.expand_foreach(
        mid, _uid,
        {"id": "contacts", "description": "Traite {{ item }}",
         "foreach": "{{ societes.output }}"},
        _SOCIETES,
    )

    assert vus, "le modèle doit être interrogé"
    assert "« societes »" in vus[0], (
        "le prompt doit nommer l'étape résolue, pas répéter le gabarit"
    )


@pytest.mark.asyncio
async def test_la_source_n_est_chargee_qu_a_l_expansion_a_froid(
    mission, monkeypatch,
) -> None:
    """Une fois le foreach étendu, plus besoin de relire la source.

    `expand_foreach` est idempotent : dès qu'il existe des items, il rend
    tout de suite. Charger la source avant lui fait donc relire l'archive
    de l'étape — jusqu'à `STEP_OUTPUT_ARCHIVE_CHARS` de texte — à chaque
    tick, pour un résultat jeté. Sur un foreach de N items, N-1 lectures
    pour rien.
    """
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _etape_terminee(mid, "societes", _SOCIETES)
    # Le foreach a DÉJÀ été étendu : deux items attendent leur tour.
    await msr.ensure_step_run(mid, "contacts", 0, "SOCIETE_1")
    await msr.ensure_step_run(mid, "contacts", 1, "SOCIETE_2")

    charges: list[str] = []
    _vrai_source = mn._foreach_source

    async def _compte(mission_id, step):
        charges.append(step.get("id", "?"))
        return await _vrai_source(mission_id, step)

    monkeypatch.setattr(mn, "_foreach_source", _compte)

    # Le tour s'arrête avant l'acteur : ce test porte sur ce qui est LU
    # avant l'expansion, pas sur l'exécution de l'étape. Sans ça il
    # dépendrait d'un modèle joignable — vert en local, rouge en CI.
    async def _pas_d_acteur(**_kwargs):
        raise RuntimeError("acteur non sollicité par ce test")

    monkeypatch.setattr(mn, "_get_actor_llms", _pas_d_acteur)

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "societes", "description": "Cherche", "status": "done"},
            {"id": "contacts", "description": "Traite {{ item }}",
             "foreach": "{{ societes.output }}", "handlers": {}},
        ],
    }
    with pytest.raises(RuntimeError, match="acteur non sollicité"):
        await mn.act_node({
            "mission_id": mid, "user_id": uid, "goal": "trouver des sociétés",
            "plan_json": plan_json, "plan_text": "",
        })

    assert charges == [], (
        "les items existent déjà : la source ne doit plus être relue"
    )


@pytest.mark.asyncio
async def test_act_node_resout_la_source_par_l_etape(mission, monkeypatch) -> None:
    """Bout en bout : c'est bien la sortie ciblée qui part à l'expansion.

    Les tests précédents portent sur le helper ; celui-ci vérifie
    qu'`act_node` l'emploie — sans quoi le correctif resterait décoratif.
    """
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _etape_terminee(mid, "historique", "Aucun fichier trouvé.")
    await _etape_terminee(mid, "societes", _SOCIETES)

    recu: list[str] = []

    async def _faux_expand(_mission_id, _user_id, _step, source_output):
        recu.append(source_output)
        return []

    monkeypatch.setattr(msr, "expand_foreach", _faux_expand)

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "societes", "description": "Cherche les sociétés",
             "status": "done"},
            {"id": "contacts", "description": "Traite {{ item }}",
             "foreach": "{{ societes.output }}", "handlers": {}},
        ],
    }
    await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "trouver des sociétés",
        "plan_json": plan_json, "plan_text": "",
    })

    assert recu, "expand_foreach doit être appelé"
    assert "SOCIETE_8" in recu[0], "la sortie ciblée doit arriver entière"
    assert "Aucun fichier trouvé" not in recu[0]

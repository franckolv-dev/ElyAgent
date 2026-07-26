# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_overrides_refresh_on_save.py
# @brief      Enregistrer une instance doit appliquer ses valeurs, pas
#             seulement les écrire en base.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du rafraîchissement des valeurs d'instance après enregistrement.

**Mon propre défaut, quelques heures après l'avoir dénoncé.** #272 a porté
fenêtre, tarifs et plafond de sortie sur l'instance, et peuple le registre
depuis ``load_llm_instances_from_db()``… qui ne tourne **qu'au démarrage**.
Les endpoints de création, modification et suppression rafraîchissent le cache
d'instances (``register_instance_cache``) mais **pas** le registre des valeurs.

Conséquence : Franck saisit ses tarifs et ses fenêtres depuis l'interface, la
base les enregistre, l'écran les réaffiche correctement — et Ely continue de
tronquer à 8 192 tokens en facturant un tarif générique jusqu'au prochain
redémarrage. Un écart entre le déclaré et l'appliqué, invisible, exactement la
classe de défaut que ce chantier supprime.

⚠️ **Le piège de mesure, rencontré deux fois aujourd'hui** : vérifier ça avec
``docker exec python`` ne prouve rien — un nouveau processus a un registre vide
par construction. Seul le code fait foi ici, et ces tests le vérifient dans le
processus qui écrit.

Run with:  cd backend && python -m pytest tests/test_overrides_refresh_on_save.py -v
"""
from __future__ import annotations

import pytest


def test_the_write_endpoints_refresh_the_registry():
    """Pin de câblage : les trois endpoints qui modifient une instance doivent
    réappliquer les valeurs, sinon la base et le comportement divergent."""
    from pathlib import Path

    src = Path("app/routers/settings_llm.py").read_text(encoding="utf-8")

    assert src.count("refresh_instance_overrides") >= 3, (
        "création, modification et suppression doivent toutes rafraîchir "
        f"(trouvé : {src.count('refresh_instance_overrides')})"
    )


@pytest.mark.asyncio
async def test_refreshing_applies_what_the_database_holds():
    """LE test du lot : après appel, le registre reflète la base."""
    import uuid

    from app.database import async_session, init_db
    from app.models.llm_instance import LLMInstance
    from app.services.context_manager import (
        get_context_window, instance_max_output, set_instance_overrides,
    )
    from app.services.llm_provider import refresh_instance_overrides

    await init_db()
    model = f"modele-test-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(LLMInstance(
            id=str(uuid.uuid4()), label="test", provider="deepseek", model=model,
            context_window=123_456, max_output_tokens=7_777,
            input_price_per_million=1.5, output_price_per_million=4.5,
        ))
        await db.commit()

    set_instance_overrides()          # on part d'un registre vide
    assert instance_max_output(model) is None

    await refresh_instance_overrides()

    assert get_context_window(model) == 123_456
    assert instance_max_output(model) == 7_777


@pytest.mark.asyncio
async def test_refreshing_drops_what_was_deleted():
    """Une instance supprimée ne doit pas laisser ses valeurs derrière elle."""
    import uuid

    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.llm_instance import LLMInstance
    from app.services.context_manager import instance_max_output
    from app.services.llm_provider import refresh_instance_overrides

    await init_db()
    model = f"modele-jetable-{uuid.uuid4().hex[:8]}"
    inst_id = str(uuid.uuid4())
    async with async_session() as db:
        db.add(LLMInstance(
            id=inst_id, label="jetable", provider="deepseek", model=model,
            max_output_tokens=999,
        ))
        await db.commit()

    await refresh_instance_overrides()
    assert instance_max_output(model) == 999

    async with async_session() as db:
        await db.execute(delete(LLMInstance).where(LLMInstance.id == inst_id))
        await db.commit()
    await refresh_instance_overrides()

    assert instance_max_output(model) is None


@pytest.mark.asyncio
async def test_refreshing_never_raises():
    """Un rafraîchissement est un effet de bord d'un enregistrement réussi :
    il ne doit jamais faire échouer la sauvegarde de l'utilisateur."""
    from app.services.llm_provider import refresh_instance_overrides

    await refresh_instance_overrides()
    await refresh_instance_overrides()

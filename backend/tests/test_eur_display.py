# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_eur_display.py
# @brief      Le tableau de bord affiche des euros — Franck paie en euros.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la conversion d'affichage USD → EUR.

**Le choix, arrêté avec Franck.** Les tarifs sont **stockés en dollars**, tels
que les fournisseurs les publient. Trois raisons :

1. un prix en dollars se vérifie d'un coup d'œil sur la page tarifaire ;
2. un taux unique se met à jour en un endroit, au lieu de N modèles ;
3. convertir À LA SAISIE produirait une valeur vraie le jour même, puis
   vieillissant en silence — la classe de défaut que tout ce chantier
   supprime.

La conversion est donc un **réglage d'affichage**, appliqué à la lecture.

⚠️ Le taux est **exposé avec le montant**, jamais appliqué en douce. Un
tableau de bord qui affiche « 44,68 € » sans dire à quel taux redevient une
boîte noire — et le coût réel dépend de toute façon du taux appliqué par la
banque le jour du prélèvement. Mieux vaut un chiffre dont on connaît
l'hypothèse qu'un chiffre qui a l'air exact.

Run with:  cd backend && python -m pytest tests/test_eur_display.py -v
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_the_summary_carries_the_rate_it_used():
    """LE test du lot : le montant ne voyage jamais sans son hypothèse."""
    import uuid

    from app.database import init_db
    from app.services.analytics_service import get_summary

    await init_db()
    summary = await get_summary(user_id=str(uuid.uuid4()), days=7)

    assert "usd_to_eur_rate" in summary
    assert summary["usd_to_eur_rate"] > 0


@pytest.mark.asyncio
async def test_the_rate_is_configurable():
    """Le taux bouge ; il doit se corriger sans toucher au code."""
    import uuid

    from app.database import init_db
    from app.services.analytics_service import get_summary
    from app.services.system_config import set_config

    await init_db()
    await set_config("usd_to_eur_rate", "0.85")
    try:
        summary = await get_summary(user_id=str(uuid.uuid4()), days=7)
        assert abs(summary["usd_to_eur_rate"] - 0.85) < 0.001
    finally:
        await set_config("usd_to_eur_rate", "")


@pytest.mark.asyncio
async def test_an_unset_rate_falls_back_to_a_documented_default():
    """Sans réglage, on affiche quand même des euros — avec un taux par défaut
    assumé et visible, pas un 1,0 déguisé qui ferait passer des dollars pour
    des euros."""
    import uuid

    from app.database import init_db
    from app.services.analytics_service import get_summary
    from app.services.system_config import set_config

    await init_db()
    await set_config("usd_to_eur_rate", "")

    summary = await get_summary(user_id=str(uuid.uuid4()), days=7)

    assert 0.5 < summary["usd_to_eur_rate"] < 1.5
    assert summary["usd_to_eur_rate"] != 1.0, (
        "un taux de 1,0 afficherait des dollars en les appelant des euros"
    )


@pytest.mark.asyncio
async def test_a_broken_rate_never_breaks_the_dashboard():
    """La valeur vient d'un formulaire : elle arrivera un jour en texte, vide
    ou négative. Le tableau de bord doit rester lisible."""
    import uuid

    from app.database import init_db
    from app.services.analytics_service import get_summary
    from app.services.system_config import set_config

    await init_db()
    for bad in ("abc", "-1", "0", "  "):
        await set_config("usd_to_eur_rate", bad)
        summary = await get_summary(user_id=str(uuid.uuid4()), days=7)
        assert summary["usd_to_eur_rate"] > 0, f"taux cassé accepté : {bad!r}"
    await set_config("usd_to_eur_rate", "")


@pytest.mark.asyncio
async def test_the_dollar_amount_is_still_there():
    """On ajoute une lecture, on n'en retire pas : le montant en dollars reste
    la donnée de référence, vérifiable sur les pages tarifaires."""
    import uuid

    from app.database import init_db
    from app.services.analytics_service import get_summary

    await init_db()
    summary = await get_summary(user_id=str(uuid.uuid4()), days=7)

    assert "total_cost_usd" in summary

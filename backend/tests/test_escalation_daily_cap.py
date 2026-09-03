# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_escalation_daily_cap.py
# @brief      Le panel d'escalade est le premier poste de coût du produit :
#             il lui manquait un plafond CUMULÉ, par jour et par utilisateur.
# @license    MIT
# =============================================================================
"""Le plafond quotidien du panel — audit du 02/09/2026.

⚠️ CE QUE ÇA CORRIGE (02/09/2026) : mesuré sur 30 jours de production,
``escalation:panel`` pèse 68 appels pour 1,29 $ — le PREMIER poste de coût,
devant tout le reste (la boucle de conformité coûte 0 $, elle tourne sur un
modèle au forfait ; l'extraction mémoire 0,23 $).

Ce qui existait déjà était bon, et reste :

  - le DÉCLENCHEUR : ``should_escalate`` ne convoque le panel que si la reprise
    n'a rien fait reculer (stagnation mesurée, pas un compteur fixe, #289) ;
  - le plafond PAR DEMANDE : ``METERED_BUDGET_USD`` écarte un modèle facturé
    dont l'estimation ferait déborder l'escalade en cours.

Ce qui manquait : le CUMUL. Rien n'empêchait soixante-huit escalades dans le
mois, ni dix dans la même journée — chacune sous le plafond par demande, toutes
ensemble hors de contrôle.

Le budget du jour se lit dans ce que le produit MESURE DÉJÀ (``usage_logs``,
colonne ``cost_usd``, lignes marquées ``escalation:*``). Pas de compteur
parallèle : un compteur en mémoire divergerait au premier redémarrage, et deux
vérités sur l'argent valent moins qu'une.

Deux asymétries à ne pas perdre :

  - un panel entièrement AU FORFAIT ne coûte rien ; le compter interdirait une
    escalade gratuite ;
  - le plafond ne compte QUE les escalades du jour, et la vérification a lieu
    AVANT de payer : la première escalade d'une journée passe donc toujours.

Run with:  cd backend && python -m pytest tests/test_escalation_daily_cap.py -v
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database import async_session, init_db
from app.models.usage_log import UsageLog


class _ModeleQuiCompte:
    """Un faux modèle qui note qu'on l'a interrogé, et remonte son usage."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, payload, **kwargs):
        self.prompts.append(
            payload[0].content if isinstance(payload, list) else str(payload)
        )

        class _R:
            content = self.reply
            usage_metadata = {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
            }

        return _R()


@pytest.fixture
def panel_facture(monkeypatch):
    """Deux modèles FACTURÉS (deepseek-v4-pro) — le cas que le plafond vise."""
    models = {
        "id-a": _ModeleQuiCompte("Réponse de A"),
        "id-b": _ModeleQuiCompte("1"),
    }
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": list(models), "fallback_enabled": True}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance",
        lambda iid, **kw: models.get(iid),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm",
        lambda llm: ("deepseek", "deepseek-v4-pro"),
    )

    async def _capture(**kwargs):
        return None

    monkeypatch.setattr("app.services.analytics_service.log_usage", _capture)
    return models


@pytest.fixture
def panel_au_forfait(panel_facture, monkeypatch):
    """Le même panel, mais servi par un modèle au forfait (gpt-5.6-terra)."""
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm",
        lambda llm: ("openai", "gpt-5.6-terra"),
    )
    return panel_facture


def _depense_du_jour(monkeypatch, montant: float) -> None:
    """Fixe ce que les escalades du jour ont déjà coûté."""
    from app.agent import escalation

    async def _lire(user_id: str) -> float:
        return montant

    monkeypatch.setattr(escalation, "get_today_escalation_spend_usd", _lire)


# ─────────────────────────────────────────────────────────────────────
# Le plafond mord — ou pas
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sous_le_plafond_l_escalade_a_bien_lieu(panel_facture, monkeypatch):
    """Le plafond borne un emballement, il ne supprime pas la fonction : une
    journée normale (une escalade ou deux) doit continuer de passer."""
    from app.agent.escalation import escalate_to_panel

    _depense_du_jour(monkeypatch, 0.01)

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-cap", conversation_id="c-1",
    )

    assert result is not None
    assert sum(1 for m in panel_facture.values() if m.prompts) >= 2


@pytest.mark.asyncio
async def test_au_dela_du_plafond_aucun_modele_n_est_appele(
    panel_facture, monkeypatch,
):
    """Refuser après avoir payé ne serait pas un plafond. Le refus doit
    intervenir AVANT le moindre appel — et rendre ``None``, pour que la
    conformité retombe sur son constat d'écarts (échouer OUVERT)."""
    from app.agent.escalation import escalate_to_panel

    _depense_du_jour(monkeypatch, 0.30)

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-cap", conversation_id="c-1",
    )

    assert result is None
    assert all(m.prompts == [] for m in panel_facture.values()), (
        "un modèle a été interrogé alors que le plafond était déjà atteint"
    )


@pytest.mark.asyncio
async def test_un_panel_entierement_au_forfait_ignore_le_plafond(
    panel_au_forfait, monkeypatch,
):
    """« Si le modèle est de type forfait, pas de plafond » (Franck, 28/07).

    Un plafond en dollars qui bloquerait des appels à zéro dollar interdirait
    une escalade GRATUITE — il retirerait de la qualité sans rien économiser.
    """
    from app.agent.escalation import escalate_to_panel

    _depense_du_jour(monkeypatch, 999.0)

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-cap", conversation_id="c-1",
    )

    assert result is not None
    assert sum(1 for m in panel_au_forfait.values() if m.prompts) >= 2


@pytest.mark.asyncio
async def test_une_lecture_de_budget_en_panne_laisse_passer(
    panel_facture, monkeypatch,
):
    """Même contrat que le reste du fichier : ÉCHOUER OUVERT. Une base
    indisponible ne doit pas priver l'utilisateur d'une amélioration — le
    plafond est un garde-fou de coût, pas une barrière de sécurité."""
    from app.agent import escalation

    async def _casse(user_id: str) -> float:
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(escalation, "get_today_escalation_spend_usd", _casse)

    result = await escalation.escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-cap", conversation_id="c-1",
    )

    assert result is not None


@pytest.mark.asyncio
async def test_le_plafond_qui_mord_se_voit_dans_les_journaux(
    panel_facture, monkeypatch, caplog,
):
    """Une garde silencieuse est une garde qu'on croit cassée : quand
    l'escalade disparaît, le journal doit dire pourquoi, et avec quel
    montant."""
    from app.agent.escalation import escalate_to_panel

    _depense_du_jour(monkeypatch, 0.30)

    with caplog.at_level(logging.INFO, logger="app.agent.escalation"):
        await escalate_to_panel(
            demande="x", produit="y", ecarts="- z",
            user_id="u-cap", conversation_id="c-1",
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any("plafond quotidien" in m and "0.30" in m for m in messages), messages


# ─────────────────────────────────────────────────────────────────────
# Ce que « le budget du jour » veut dire exactement
# ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def _base_propre():
    """Base initialisée, sans reste des tours précédents pour ces users."""
    await init_db()
    async with async_session() as db:
        await db.execute(
            delete(UsageLog).where(UsageLog.user_id.in_(["u-cap", "u-autre"]))
        )
        await db.commit()
    yield
    async with async_session() as db:
        await db.execute(
            delete(UsageLog).where(UsageLog.user_id.in_(["u-cap", "u-autre"]))
        )
        await db.commit()


@pytest.mark.asyncio
async def test_le_budget_est_compte_par_jour_et_par_utilisateur(_base_propre):
    """Trois découpes, et elles comptent toutes les trois.

    PAR JOUR : sans la borne de minuit, la dépense d'hier condamnerait
    aujourd'hui, et le plafond deviendrait un interrupteur définitif.
    PAR UTILISATEUR : c'est le contrat de ``budget_guard`` depuis la revue
    multi-utilisateurs — la consommation d'un autre ne coupe pas la mienne.
    PAR ESCALADE : le reste du tour n'est pas une escalade ; le compter ferait
    mordre le plafond sur un usage qui n'a rien à voir.
    """
    from app.agent.escalation import get_today_escalation_spend_usd

    hier = datetime.now(timezone.utc) - timedelta(days=1)
    async with async_session() as db:
        db.add(UsageLog(
            user_id="u-cap", model="deepseek-v4-pro", provider="deepseek",
            cost_usd=0.10, skill_used="escalation:panel",
        ))
        db.add(UsageLog(
            user_id="u-cap", model="deepseek-v4-pro", provider="deepseek",
            cost_usd=0.02, skill_used="escalation:juge",
        ))
        db.add(UsageLog(  # même jour, même user, mais PAS une escalade
            user_id="u-cap", model="deepseek-v4-pro", provider="deepseek",
            cost_usd=5.00, skill_used="agent.tool_call",
        ))
        db.add(UsageLog(  # même user, même skill, mais HIER
            user_id="u-cap", model="deepseek-v4-pro", provider="deepseek",
            cost_usd=9.00, skill_used="escalation:panel", timestamp=hier,
        ))
        db.add(UsageLog(  # aujourd'hui, même skill, mais UN AUTRE user
            user_id="u-autre", model="deepseek-v4-pro", provider="deepseek",
            cost_usd=7.00, skill_used="escalation:panel",
        ))
        await db.commit()

    depense = await get_today_escalation_spend_usd("u-cap")

    assert abs(depense - 0.12) < 1e-6, f"{depense} $ compté au lieu de 0,12 $"


def test_le_plafond_est_actif_sans_reglage_particulier():
    """Une garde qui n'existe que dans le .env d'une machine n'est pas une
    garde (même leçon que ``trust_substrate_enabled``, audit 02/09) : livré à
    0, le plafond serait absent partout où personne ne l'a configuré."""
    from app.config import get_settings

    assert get_settings().escalation_daily_budget_usd > 0


@pytest.mark.asyncio
async def test_une_journee_sans_escalade_coute_zero(_base_propre):
    """Le cas nominal : rien de dépensé, donc rien qui bloque. Un lecteur qui
    rendrait ``None`` ou lèverait sur une table vide ferait échouer la
    comparaison au plafond au lieu de laisser passer."""
    from app.agent.escalation import get_today_escalation_spend_usd

    assert await get_today_escalation_spend_usd("u-cap") == 0.0


# ─────────────────────────────────────────────────────────────────────
# Panel mixte : le plafond ne doit pas sacrifier ce qui est gratuit
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def panel_mixte(monkeypatch):
    """Deux modèles AU FORFAIT et un FACTURÉ dans la même chaîne."""
    gratuit_a = _ModeleQuiCompte("Réponse au forfait A")
    gratuit_b = _ModeleQuiCompte("Réponse au forfait B")
    facture = _ModeleQuiCompte("Réponse facturée")
    models = {
        "id-gratuit-a": gratuit_a,
        "id-gratuit-b": gratuit_b,
        "id-facture": facture,
    }
    tarifs = {
        id(gratuit_a): ("openai", "gpt-5.6-terra"),
        id(gratuit_b): ("openai", "gpt-5.6-terra"),
        id(facture): ("deepseek", "deepseek-v4-pro"),
    }
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": list(models), "fallback_enabled": True}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance",
        lambda iid, **kw: models.get(iid),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: tarifs[id(llm)],
    )

    async def _capture(**kwargs):
        return None

    monkeypatch.setattr("app.services.analytics_service.log_usage", _capture)
    return models


@pytest.mark.asyncio
async def test_le_plafond_du_jour_ecarte_les_factures_et_garde_les_gratuits(
    panel_mixte, monkeypatch,
):
    """La même asymétrie que plus haut, mais dans un panel MIXTE.

    Refuser le panel entier parce qu'un de ses trois membres se paie
    supprimerait aussi les deux qui ne coûtent rien — exactement ce que
    ``test_un_panel_entierement_au_forfait_ignore_le_plafond`` interdit, à un
    membre près. Le plafond PAR DEMANDE traite déjà ce cas ainsi : il ÉCARTE
    ce qui déborde et continue avec le reste.
    """
    from app.agent.escalation import escalate_to_panel

    _depense_du_jour(monkeypatch, 0.30)

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-cap", conversation_id="c-1",
    )

    assert result is not None, "le panel gratuit a été refusé avec le facturé"
    assert panel_mixte["id-facture"].prompts == [], (
        "le modèle facturé a été interrogé alors que le plafond était atteint"
    )
    assert panel_mixte["id-gratuit-a"].prompts, "le forfait A n'a pas été interrogé"
    assert panel_mixte["id-gratuit-b"].prompts, "le forfait B n'a pas été interrogé"
    assert "deepseek-v4-pro" in result.skipped_for_budget, result.skipped_for_budget

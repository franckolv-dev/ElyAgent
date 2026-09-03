# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_escalation_panel.py
# @brief      Quand ça n'avance plus, Ely demande à plusieurs modèles au lieu
#             d'abandonner — et te dit lequel a répondu, et ce que ça a coûté.
# @license    MIT
# =============================================================================
"""Lot 2 du plan de marche — la chaîne de repli devient un panel.

Ce que Franck a demandé, le 28/07/2026
---------------------------------------
    « On a utilisé les fallback au cas où un modèle n'est plus disponible, il
      faut modifier cette approche et les utiliser également si les résultats
      ne sont pas convenables […] demander à 2 ou 3 modèles simultanément,
      prendre le meilleur retour et me le proposer. »

Mesuré : les huit déclencheurs de repli existants sont **tous techniques**
(``rate_limit``, ``timeout``, ``billing``, ``unavailable``…). Aucun ne regarde
la QUALITÉ. Un modèle qui répond vite et mal ne déclenche rien.

Le déclencheur : le progrès, pas un compteur
---------------------------------------------
Franck avait proposé « après 3 tentatives ». On a mesuré en #289 que le
compteur fixe était mauvais et on l'a remplacé par le progrès. Le panel se
branche donc exactement là où #289 constate que ça n'avance plus : aujourd'hui
la boucle ABANDONNE et rédige un constat d'échec, demain elle ESCALADE. C'est
mieux qu'un compteur dans les deux sens — plus tôt quand c'est bloqué, jamais
quand ça progresse.

⚠️ Ce que le panel peut, et ce qu'il ne peut pas
-------------------------------------------------
Les modèles du panel répondent **sans outils**. Ils améliorent donc une
RÉPONSE, pas le RÉSULTAT d'un outil : sur « la conversion a aplati les pages »,
aucun d'eux ne peut reconvertir le PDF. C'est délibéré — trois agents outillés
en parallèle enverraient trois mails et écriraient trois fichiers. Le panel est
en lecture seule par construction, et c'est ce qui le rend sûr.

Budget — décision de Franck
----------------------------
    « Si le modèle est de type forfait (GPT 5.6), pas de plafond et si c'est
      via API, on établira un plafond par demande et qu'Ely me le dise. »

Le tarif ``(0.0, 0.0)`` d'``analytics_service._PRICING`` identifie déjà les
modèles au forfait et les locaux. Un modèle facturé n'entre au panel que si le
plafond de la demande le permet — et ce qui a été écarté est DIT.

Run with:  cd backend && python -m pytest tests/test_escalation_panel.py -v
"""
from __future__ import annotations

import pytest


class _Model:
    """Un faux modèle qui rend une réponse fixe et note ce qu'on lui envoie."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, payload, **kwargs):
        self.prompts.append(payload[0].content if isinstance(payload, list) else str(payload))

        class _R:
            content = self.reply

        return _R()


@pytest.fixture
def panel(monkeypatch):
    """Trois modèles distincts, chacun identifiable par sa réponse."""
    models = {
        "id-a": _Model("Réponse de A"),
        "id-b": _Model("Réponse de B"),
        "id-c": _Model("Réponse de C"),
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
        "app.services.llm_provider.describe_llm", lambda llm: "modèle-test",
    )
    return models


# ─────────────────────────────────────────────────────────────────────
# Le panel interroge plusieurs modèles, en parallèle
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_several_distinct_models_are_asked(panel):
    """Interroger deux fois le même modèle ne vaut pas un panel : c'est la
    DIVERSITÉ qui donne une chance d'obtenir mieux."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis ce texte en néerlandais.",
        produit="[résultat d'outil] traduction en anglais",
        ecarts="- la langue demandée était le néerlandais",
    )

    interroges = [m for m in panel.values() if m.prompts]
    assert len(interroges) >= 2, f"{len(interroges)} modèle(s) interrogé(s)"


@pytest.mark.asyncio
async def test_the_panel_receives_the_gaps_not_just_the_request(panel):
    """Sans les écarts, les modèles referaient la même erreur : c'est
    précisément ce que la reprise a déjà tenté sans succès."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis ce texte en néerlandais.",
        produit="traduction en anglais",
        ecarts="- la langue demandée était le néerlandais",
    )

    prompt = next(m.prompts[0] for m in panel.values() if m.prompts)
    assert "néerlandais" in prompt
    assert "la langue demandée" in prompt


@pytest.mark.asyncio
async def test_the_best_answer_is_returned_with_its_author(panel):
    """« Prendre le meilleur retour et me le proposer » — et savoir d'où il
    vient, sinon Franck ne peut ni arbitrer ni corriger."""
    from app.agent.escalation import escalate_to_panel

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
    )

    assert result is not None
    assert result.answer.startswith("Réponse de")
    assert result.model, "la réponse ne dit pas quel modèle l'a produite"


# ─────────────────────────────────────────────────────────────────────
# Échouer OUVERT — une escalade cassée ne retient rien
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_panel_that_fails_returns_nothing_rather_than_blocking(monkeypatch):
    """Même règle que la boucle de conformité : l'utilisateur reçoit la réponse
    d'origine plutôt qu'une erreur. Une amélioration qui tombe ne doit jamais
    coûter le résultat déjà obtenu."""
    class _Broken:
        async def ainvoke(self, payload, **kwargs):
            raise RuntimeError("quota épuisé")

    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": ["a", "b"]}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance", lambda iid, **kw: _Broken(),
    )
    from app.agent.escalation import escalate_to_panel

    assert await escalate_to_panel(demande="x", produit="y", ecarts="- z") is None


@pytest.mark.asyncio
async def test_a_single_available_model_is_not_a_panel(monkeypatch):
    """Un seul modèle disponible, c'est ce que la reprise vient déjà de faire.
    Le refaire coûterait un appel pour rien."""
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": ["seul"]}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance",
        lambda iid, **kw: _Model("Réponse unique"),
    )
    from app.agent.escalation import escalate_to_panel

    assert await escalate_to_panel(demande="x", produit="y", ecarts="- z") is None


# ─────────────────────────────────────────────────────────────────────
# Le budget — décision de Franck du 28/07
# ─────────────────────────────────────────────────────────────────────


def test_the_real_describe_llm_yields_a_usable_model_name():
    """⚠️ Le doublon anti-stub, et il a servi.

    Les pins ci-dessus stubbent ``describe_llm`` par ``lambda llm: "modèle"``.
    La VRAIE fonction rend un **tuple** ``(provider, model)`` : ``_model_name``
    rendait donc un tuple, ``is_flat_rate`` recevait un tuple, ``_PRICING.get``
    répondait ``None``, et **tous les modèles au forfait passaient pour
    facturés** — le plafond de budget les aurait écartés du panel, donc aucun
    panel n'aurait jamais eu lieu en production.

    Aucun test stubbé ne pouvait le voir. C'est la leçon de #288, à appliquer
    chaque fois qu'un test stubbe une fonction partagée : en doubler un qui
    appelle la vraie.
    """
    from app.agent.escalation import _model_name
    from app.services.llm_provider import describe_llm

    class _Fake:
        model = "gpt-5.6-terra"

    assert isinstance(describe_llm(_Fake()), tuple), "le contrat a changé"
    name = _model_name(_Fake(), "repli")
    assert isinstance(name, str), f"_model_name rend {type(name).__name__}"
    assert name == "gpt-5.6-terra"


def test_a_flat_rate_model_name_survives_the_real_pipeline():
    """Le bout de la chaîne : ce que ``_model_name`` produit doit être
    reconnaissable par ``is_flat_rate``, sinon le budget se trompe en silence."""
    from app.agent.escalation import _model_name, is_flat_rate

    class _Fake:
        model = "gpt-5.6-terra"

    assert is_flat_rate(_model_name(_Fake(), "repli")) is True


def test_a_flat_rate_model_has_no_ceiling():
    """« Si le modèle est de type forfait (GPT 5.6), pas de plafond. »
    Le tarif (0.0, 0.0) l'identifie déjà dans ``_PRICING``."""
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("gpt-5.6-terra") is True
    assert is_flat_rate("qwen/qwen3.5-9b") is True


def test_a_metered_model_is_not_flat_rate():
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("deepseek-v4-pro") is False


def test_an_unknown_model_is_treated_as_metered():
    """Prudence sur l'argent : un modèle dont on ignore le tarif est supposé
    facturé. Se tromper dans l'autre sens ferait payer sans plafond."""
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("modele-jamais-vu") is False


@pytest.mark.asyncio
async def test_what_the_escalation_cost_is_reported(panel):
    """« Qu'Ely me le dise. » Une escalade muette sur son coût empêche
    d'arbitrer si elle vaut ce qu'elle rapporte."""
    from app.agent.escalation import escalate_to_panel

    result = await escalate_to_panel(demande="x", produit="y", ecarts="- z")

    assert result is not None
    assert result.models_asked >= 2
    assert result.cost_usd >= 0.0


# ─────────────────────────────────────────────────────────────────────
# Le déclencheur — le progrès, jamais un compteur
# ─────────────────────────────────────────────────────────────────────


def test_the_panel_is_convened_only_when_progress_stops():
    """Le garde-fou de la facture. Un tour qui progresse (6 écarts → 2 → 1) se
    règle tout seul : convoquer le panel à chaque reprise multiplierait le coût
    de toutes les demandes qui allaient très bien."""
    from app.agent.escalation import should_escalate

    assert should_escalate(new_count=3, previous_count=3) is True   # bloqué
    assert should_escalate(new_count=5, previous_count=3) is True   # empiré
    assert should_escalate(new_count=1, previous_count=3) is False  # progresse
    assert should_escalate(new_count=2, previous_count=0) is False  # 1re vérification


# ---------------------------------------------------------------------------
# Le panel n'est pas témoin de l'outillage d'Ely
# ---------------------------------------------------------------------------

def test_the_panel_is_not_told_to_declare_tools_missing():
    """Le panel n'a pas d'outils ; **Ely en a 84**. Il ne parle que pour lui.

    ⛔ Incident du 01/08. Ely écrit `Audit_Pro_BAT.md` sur le Drive de Franck à
    18:46 — `drive_create_file` réussit, le lien est dans la trace. À 19:02,
    même conversation, elle lui répond :

        « Je n'ai aucun outil de fichier dans cette session : impossible de
          créer ou sauvegarder Audit_Pro_BAT.md sur le drive. Il faudrait me
          redonner cet accès, ou créer le document vous-même. »

    Le fichier existait depuis seize minutes. Cette réponse venait du panel,
    qui a obéi au mot près à ce que _PANEL_PROMPT lui demandait : « Tu n'as
    aucun outil : tu ne peux ni créer de fichier […] dis-le franchement ».

    Le prompt confondait deux « tu » : le MEMBRE DU PANEL, qui n'a
    effectivement pas d'outil, et ELY, que l'utilisateur lit. Vrai du premier,
    faux de la seconde — et l'utilisateur ne voit que la seconde.

    Ce que le panel doit continuer de garantir : ne rien inventer, ne rien
    promettre. Ce qu'il ne doit plus faire : déclarer un outil absent, réclamer
    un accès, ou renvoyer l'utilisateur au travail manuel. Il n'a pas la
    liste des outils sous les yeux — il n'est pas en position de témoigner.
    """
    from app.agent.escalation import _PANEL_PROMPT

    p = _PANEL_PROMPT.lower()

    # La garantie qui doit SURVIVRE : pas de résultat inventé, pas de promesse.
    assert "n'invente" in p
    assert "promets" in p or "promesse" in p

    # Ce qu'il ne doit plus affirmer.
    assert "tu n'as aucun outil" not in p, (
        "le panel écrit à l'utilisateur au nom d'Ely : lui faire dire qu'il "
        "n'a aucun outil devient « Ely n'a aucun outil »"
    )
    assert "ni créer de fichier" not in p, (
        "Ely a drive_create_file, desktop_write_file et neuf outils Drive — "
        "annoncer l'inverse est faux, et l'utilisateur agit dessus"
    )

    # L'interdiction doit être EXPLICITE, sinon le modèle la réinventera :
    # le prompt doit nommer ce qu'il ne faut pas dire.
    assert "outil" in p, "l'interdiction doit nommer le sujet qu'elle couvre"
    interdits = ("ne dis jamais", "n'affirme jamais", "ne déclare jamais")
    assert any(mot in p for mot in interdits), (
        "une interdiction implicite n'en est pas une : elle doit être écrite"
    )


def test_the_escalation_note_says_the_answer_came_without_tools():
    """La note affichée doit dire que le panel a répondu SANS OUTILS.

    Le panel est en lecture seule par construction — c'est ce qui le rend sûr.
    Mais tant que la note ne le dit pas, une réponse qui bute sur une action
    se lit comme un constat d'impuissance d'Ely, pas comme la limite connue
    d'un relais textuel. Nommer la limite, c'est ce qui la rend lisible.
    """
    from app.agent.conformity import _ESCALATION_NOTE

    note = _ESCALATION_NOTE.lower()
    assert "sans outil" in note, (
        "l'utilisateur doit pouvoir situer une réponse qui ne peut pas agir"
    )


# ─────────────────────────────────────────────────────────────────────
# Ce que le panel dépense doit se voir — diagnostic du 05/08/2026
# ─────────────────────────────────────────────────────────────────────
#
# L'incident. Le tableau de bord DeepSeek montrait 994 requêtes et 42 M
# tokens sur `deepseek-v4-pro` du 28/07 au 05/08, sans que rien côté Ely ne
# permette d'en rendre compte. Deux chemins y menaient, aucun tracé :
#
#   1. la cascade de CONSTRUCTION (`get_llm_for_tier`) — couverte par
#      `test_config_reality_check.py` ;
#   2. le panel d'escalade — couvert ici.
#
# `_ask` ne rendait que le texte. `response.usage_metadata` était jeté, et la
# coupure `config={"callbacks": []}` — nécessaire, sinon les tokens du panel
# s'affichent dans la réponse (bug du 19/07) — détache aussi l'appel de
# l'instrumentation du tour. Jusqu'à trois modèles facturés par escalade, plus
# un juge, dépensaient donc sans laisser AUCUNE ligne.


class _ModelWithUsage:
    """Un faux modèle qui remonte son usage, comme le font les fournisseurs.

    ⚠️ Garde la signature réelle (`ainvoke(payload, **kwargs)`) et la forme
    réelle de `usage_metadata` : c'est ce qui fait remarquer un changement de
    contrat côté LangChain.
    """

    def __init__(self, reply: str, tokens_in: int = 1000, tokens_out: int = 200):
        self.reply, self.tokens_in, self.tokens_out = reply, tokens_in, tokens_out

    async def ainvoke(self, payload, **kwargs):
        class _R:
            content = self.reply
            usage_metadata = {
                "input_tokens": self.tokens_in,
                "output_tokens": self.tokens_out,
                "total_tokens": self.tokens_in + self.tokens_out,
            }

        return _R()


@pytest.fixture
def panel_mesure(monkeypatch):
    """Deux modèles qui remontent leur usage + la capture des lignes écrites."""
    ecrit: list[dict] = []

    models = {
        "id-a": _ModelWithUsage("Réponse de A", 1000, 200),
        "id-b": _ModelWithUsage("1", 500, 10),
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
        ecrit.append(kwargs)

    monkeypatch.setattr("app.services.analytics_service.log_usage", _capture)
    return ecrit


@pytest.mark.asyncio
async def test_each_panel_call_is_written_to_usage_logs(panel_mesure):
    """Un appel facturé qui n'apparaît pas dans `usage_logs` est de l'argent
    dépensé qu'Ely ne sait pas compter — c'est le défaut qui a rendu 42 M
    tokens inexplicables pendant neuf jours."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-1", conversation_id="c-1",
    )

    panel = [e for e in panel_mesure if e.get("skill_used") == "escalation:panel"]
    assert len(panel) == 2, (
        f"les 2 modèles interrogés doivent produire 2 lignes, vu {len(panel)}"
    )
    assert all(e["input_tokens"] > 0 for e in panel), (
        "les tokens doivent venir de usage_metadata, pas d'un zéro par défaut"
    )
    assert all(e["user_id"] == "u-1" and e["conversation_id"] == "c-1" for e in panel), (
        "user_id et conversation_id étaient acceptés depuis #298 et jamais "
        "utilisés : la ligne doit être rattachable à son tour"
    )


@pytest.mark.asyncio
async def test_the_judge_is_billed_too(panel_mesure):
    """Le juge est un appel facturé de plus par escalade. L'oublier
    sous-estimerait la facture d'un tiers sur un panel de deux."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-1", conversation_id="c-1",
    )

    juge = [e for e in panel_mesure if e.get("skill_used") == "escalation:juge"]
    assert len(juge) == 1, "le verdict du juge coûte, et doit se compter"


@pytest.mark.asyncio
async def test_a_provider_that_reports_nothing_is_not_written_as_zero(panel, monkeypatch):
    """Écrire 0 token se lirait « gratuit ». Un fournisseur muet (fréquent en
    local) n'est PAS un fournisseur gratuit — mieux vaut aucune ligne qu'une
    ligne fausse, la même règle que `usage_from_result.has_metadata`."""
    from app.agent.escalation import escalate_to_panel

    ecrit: list[dict] = []

    async def _capture(**kwargs):
        ecrit.append(kwargs)

    monkeypatch.setattr("app.services.analytics_service.log_usage", _capture)

    # La fixture `panel` rend des réponses SANS usage_metadata.
    await escalate_to_panel(
        demande="x", produit="y", ecarts="- z",
        user_id="u-1", conversation_id="c-1",
    )
    assert ecrit == [], "un usage non remonté ne doit pas devenir un usage nul"


@pytest.mark.asyncio
async def test_the_reported_cost_is_measured_not_estimated(panel_mesure, monkeypatch):
    """`_estimate_call_usd` sert à décider AVANT de payer (4 caractères par
    token, sortie supposée au quart). L'annoncer ensuite ferait passer une
    approximation pour une facture."""
    from app.agent import escalation

    monkeypatch.setattr(
        "app.services.analytics_service.estimate_cost",
        lambda model, tin, tout: 0.25,
    )
    # Une estimation volontairement absurde : si elle ressort, c'est elle
    # qu'on affichait.
    monkeypatch.setattr(escalation, "_estimate_call_usd", lambda *a, **k: 0.0001)

    result = await escalation.escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
        user_id="u-1", conversation_id="c-1",
    )

    assert result is not None
    assert result.cost_usd > 0.0001, (
        f"coût rendu {result.cost_usd} — c'est l'estimation d'avant-appel, "
        f"pas ce qui a été mesuré"
    )

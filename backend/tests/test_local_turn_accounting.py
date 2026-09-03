# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_local_turn_accounting.py
# @brief      Un tour local doit se compter, et se compter sous le bon nom.
# @license    MIT
# =============================================================================
"""Deux compteurs qui mentaient, découverts le 21/08 en regardant l'écran.

La voie locale venait d'être réparée (#329, #330). Nemotron répond, l'étiquette
est juste — et le panneau SESSION affiche ``TOKENS —`` pendant que le tableau
de bord attribue le tour à un fournisseur nommé « nvidia ».

1. UN COMPTEUR QUE PERSONNE N'ALIMENTAIT
-----------------------------------------
``AvatarPanel`` lit ``input_tokens`` / ``output_tokens`` sur le websocket.
Le backend ne les a **jamais** émis : la charge utile du message final portait
``content``, ``model_used``, ``routing_score``, ``attachments`` — pas les
compteurs. « TOKENS » valait donc « — » sur TOUS les tours, locaux comme
distants, depuis l'origine.

Ce n'était pas un trou de la voie locale, contrairement à ce que j'ai annoncé
d'abord : c'était un trou pour tout le monde, que la voie locale a rendu
visible parce qu'on regardait enfin ce panneau.

⚠️ Le frontend lisait ces champs via ``as unknown as {…}``. Le cast est
exactement ce qui a permis au défaut de durer : TypeScript aurait signalé des
champs absents de ``WSMessage``, le cast lui a dit de se taire.

2. UN FOURNISSEUR NOMMÉ AU HASARD
----------------------------------
LM Studio nomme ses modèles ``nvidia/nemotron-3-nano-4b``. Le chemin SLM
émettait ``slm:<modèle>`` nu, et ``split_model_used`` découpe sur le premier
``/`` — d'où un « fournisseur » nvidia qui n'existe dans aucune configuration.

Le repli valait ``"ollama"`` en dur, reste du temps où le SLM ne pouvait être
que ça. Deux façons différentes d'inventer un fournisseur, toutes deux
plausibles à l'œil : la pire signature pour un chiffre.

Run with:  cd backend && python -m pytest tests/test_local_turn_accounting.py -v
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace


# ─────────────────────────────────────────────────────────────────────
# 1 — Le découpage de l'étiquette
# ─────────────────────────────────────────────────────────────────────

def test_a_local_model_name_containing_a_slash_keeps_its_provider():
    """Le CONTRAT de format, pas le défaut.

    ⚠️ Ce test passe déjà sur le code d'avant : le découpage était correct,
    c'est l'étiquette qui n'apportait pas de fournisseur à découper. Le pin
    qui rougit sur le vrai défaut est
    `test_the_local_label_carries_its_provider`, plus bas. Celui-ci fixe la
    convention que l'autre suppose — les deux se tiennent, aucun ne suffit.
    """
    from app.services.usage_instrumentation import split_model_used

    provider, model = split_model_used("slm:lm_studio/nvidia/nemotron-3-nano-4b")

    assert provider == "lm_studio", (
        f"fournisseur lu « {provider} » — le tableau de bord attribuait les "
        f"tours locaux à nvidia, qui n'est pas un fournisseur configurable"
    )
    assert model == "nvidia/nemotron-3-nano-4b", (
        "le nom du modèle doit rester entier : c'est lui qui sert de clé à la "
        "table des fenêtres de contexte"
    )


def test_an_unqualified_local_label_does_not_invent_ollama():
    """« ollama » en dur datait du temps où le SLM ne pouvait être que ça.

    Le tier A est configurable depuis longtemps — LM Studio chez Franck. Un
    défaut qui nomme un fournisseur précis se lit comme une information ;
    « local » admet le trou, ce qui est la seule chose vraie ici.
    """
    from app.services.usage_instrumentation import split_model_used

    provider, model = split_model_used("slm:qwen2.5")

    assert provider != "ollama", (
        "un fournisseur deviné au hasard est pire qu'un fournisseur inconnu"
    )
    assert model == "qwen2.5"


def test_the_tools_suffix_never_reaches_the_model_name():
    """Le comportement dont la copie de `voice.py` avait dérivé.

    ⚠️ Comme le précédent, il passait déjà : la fonction partagée retirait bien
    le suffixe. C'est la TROISIÈME copie, dans `voice.py`, qui ne le faisait
    pas — le nom de modèle portait « +tools » dans les lignes d'usage de la
    voix. Ce que `test_voice_uses_the_shared_split_and_not_its_own` épingle.
    """
    from app.services.usage_instrumentation import split_model_used

    _p, model = split_model_used("llm:lm_studio/gemma-4-12b+tools")
    assert model == "gemma-4-12b", f"suffixe non retiré : « {model} »"


def test_voice_uses_the_shared_split_and_not_its_own():
    """Trois copies du même découpage : c'est celle-ci qui avait dérivé."""
    from app.routers import voice

    src = inspect.getsource(voice)
    assert "split_model_used" in src, (
        "la voix doit réutiliser le découpage partagé"
    )
    assert '"ollama" if _type == "slm"' not in src, (
        "le fournisseur deviné en dur subsiste dans le chemin voix"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — L'étiquette produite par le nœud agent
# ─────────────────────────────────────────────────────────────────────

class _Settings:
    slm_model = "réglage-périmé"


def test_the_local_label_carries_its_provider(monkeypatch):
    """`slm:<fournisseur>/<modèle>` — sans le fournisseur en tête, le
    découpage n'a aucun moyen de savoir où couper."""
    from app.agent import nodes

    monkeypatch.setattr(
        "app.services.llm_provider.declared_provider_for_tier",
        lambda tier: "lm_studio",
    )
    etiquette = nodes._slm_label(SimpleNamespace(), _Settings())

    assert etiquette.startswith("slm:lm_studio/"), etiquette


def test_the_declared_provider_beats_the_deduced_one(monkeypatch):
    """Remarque de Franck : « quand j'ajoute un modèle, je définis si c'est du
    Ollama ou du LM Studio, il faut utiliser cette info sinon pourquoi la
    définir ? ». `describe_llm` DÉDUIT depuis le `base_url` ; l'instance porte
    le choix explicite de l'utilisateur. Le déclaré gagne."""
    from app.agent import nodes

    monkeypatch.setattr(
        "app.services.llm_provider.declared_provider_for_tier",
        lambda tier: "lm_studio",
    )
    # La déduction se trompe — un LM Studio derrière ChatOpenAI se lit
    # volontiers « openai » quand le base_url n'est pas reconnu.
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm",
        lambda llm: ("openai", "nemotron-3-nano-4b"),
    )

    assert nodes._slm_provider(SimpleNamespace()) == "lm_studio"


def test_the_deduction_still_serves_when_nothing_is_declared(monkeypatch):
    """Le repli reste : une chaîne illisible ne doit pas effacer ce qu'on sait."""
    from app.agent import nodes

    monkeypatch.setattr(
        "app.services.llm_provider.declared_provider_for_tier", lambda tier: "",
    )
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: ("ollama", "qwen"),
    )

    assert nodes._slm_provider(SimpleNamespace()) == "ollama"


def test_an_unreadable_provider_never_breaks_the_turn(monkeypatch):
    """Une étiquette est un confort. Elle ne coûte pas une réponse."""
    from app.agent import nodes

    def _explose(_tier):
        raise RuntimeError("configuration illisible")

    monkeypatch.setattr(
        "app.services.llm_provider.declared_provider_for_tier", _explose,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: ("x", "y"),
    )

    assert nodes._slm_provider(SimpleNamespace()) == "local"


# ─────────────────────────────────────────────────────────────────────
# 3 — Les compteurs de jetons
# ─────────────────────────────────────────────────────────────────────

def test_an_estimate_says_that_it_is_one():
    """L'invariant « un repli doit se voir », appliqué à un chiffre.

    Une estimation muette se lit comme une mesure, et on raisonne dessus.
    """
    from app.services.usage_instrumentation import estimate_tokens_if_missing

    entree, sortie, estime = estimate_tokens_if_missing(
        input_tokens=0, output_tokens=0,
        user_content="bonjour Ely", ai_content="Bonjour Franck !",
    )

    assert entree > 0 and sortie > 0, "un tour qui a eu lieu ne compte pas zéro"
    assert estime is True, "sans ce drapeau, l'interface ne peut pas le dire"


def test_a_real_measurement_is_not_flagged_as_an_estimate():
    """Le drapeau ne doit pas devenir décoratif : s'il est toujours vrai, le
    « ~ » de l'interface ne veut plus rien dire."""
    from app.services.usage_instrumentation import estimate_tokens_if_missing

    entree, sortie, estime = estimate_tokens_if_missing(
        input_tokens=1200, output_tokens=340,
        user_content="bonjour", ai_content="salut",
    )

    assert (entree, sortie) == (1200, 340), "une mesure ne se réécrit pas"
    assert estime is False


def test_a_half_measured_turn_is_still_flagged():
    """Certains serveurs rendent l'entrée et pas la sortie. Le total affiché
    est alors partiellement estimé — donc estimé."""
    from app.services.usage_instrumentation import estimate_tokens_if_missing

    _e, sortie, estime = estimate_tokens_if_missing(
        input_tokens=900, output_tokens=0,
        user_content="x", ai_content="une réponse un peu longue",
    )
    assert sortie > 0 and estime is True


def test_the_websocket_actually_ships_the_counters():
    """LE pin du premier défaut, et il est structurel à dessein.

    Le frontend lisait ces deux champs depuis toujours ; rien ne les envoyait.
    Aucun test de bout en bout n'existait pour le dire, et le `as unknown as`
    côté TypeScript empêchait le compilateur de le dire non plus.
    """
    from app.routers import chat

    src = inspect.getsource(chat)
    for champ in ("input_tokens", "output_tokens", "tokens_estimated"):
        assert f'payload["{champ}"]' in src, (
            f"le message final n'emporte pas « {champ} » — le panneau SESSION "
            f"le lit et affichera « — » quoi qu'il arrive"
        )


def test_the_counters_are_completed_before_the_message_is_sent():
    """L'ordre EST le défaut.

    L'estimation existait déjà — mais dans le bloc d'analytique, APRÈS
    `_ws_send`. Elle alimentait la base et jamais l'écran. Déplacer le calcul
    est tout le correctif ; un pin sur la seule présence des champs ne
    remarquerait pas qu'ils repartent en arrière.
    """
    from app.routers import chat

    src = inspect.getsource(chat)
    calcul = src.find("estimate_tokens_if_missing(")
    envoi = src.find('payload["input_tokens"]')

    assert calcul != -1 and envoi != -1, "structure inattendue"
    assert calcul < envoi, (
        "les compteurs sont estimés APRÈS avoir été mis dans la charge utile — "
        "l'écran recevra les zéros"
    )

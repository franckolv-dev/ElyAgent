# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_or_skill.py
# @brief      On ne fabrique un outil que si la demande exige une ACTION —
#             sinon c'est une compétence, et un modèle suffit.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La règle posée par Franck le 29/07/2026.

    « Soit la demande peut être réglée par un modèle local ou cloud, et dans
      ce cas ce n'est pas un outil qu'il faut développer mais plutôt une
      skill ; soit la demande ne peut pas être réglée par un modèle (car cela
      nécessite une ou plusieurs actions) et là il faut créer un outil. »

Ce qui déclenchait la génération avant ce lot
-----------------------------------------------
``find_tool`` ne trouve rien → un gap est consigné → **on génère un outil**.
Les seules gardes portaient sur « existe-t-il DÉJÀ un outil ? » (flag, gap déjà
tenté, pré-check sémantique). Aucune ne posait la question de Franck : **faut-il
un outil du tout ?**

D'où des outils fabriqués pour des besoins qu'un modèle règle en une phrase —
« résume ce texte », « traduis ça » — puis jamais utilisés.

Le critère, opérationnel
-------------------------
**La capacité touche-t-elle quelque chose HORS du modèle ?** Un fichier, une
API, un service, la machine. C'est le même axe que l'EFFET de
``tool_nature`` : produire du texte n'est pas agir.

⚠️ On échoue en NE générant PAS
---------------------------------
Contrairement à la boucle de conformité qui laisse passer en cas de doute, ici
le doute ne fabrique rien. Rien n'est perdu : le gap reste consigné dans
« Capacités manquantes » avec son bouton manuel. Générer à tort coûte un outil
mort de plus — c'est exactement ce que ce lot supprime.

Run with:  cd backend && python -m pytest tests/test_tool_or_skill.py -v
"""
from __future__ import annotations

import pytest


class _Judge:
    """Un faux modèle de jugement, qui note ce qu'on lui demande."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, payload, **kwargs):
        self.prompts.append(payload[0].content if isinstance(payload, list) else str(payload))

        class _R:
            content = self.reply

        return _R()


@pytest.fixture
def judge(monkeypatch):
    def _install(reply: str):
        j = _Judge(reply)

        async def _get(**kwargs):
            return j, "qwen/qwen2.5-coder-14b"

        monkeypatch.setattr(
            "app.services.learning.tier_s.get_tier_s_llm", _get,
        )
        return j
    return _install


# ─────────────────────────────────────────────────────────────────────
# La règle
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_capability_that_only_needs_words_is_a_skill(judge):
    """« Résume ce texte » : aucun modèle n'a besoin d'un outil pour ça."""
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("COMPETENCE")
    assert await needs_a_tool("résumer un texte en trois points") is False


@pytest.mark.asyncio
async def test_a_capability_that_touches_the_world_is_a_tool(judge):
    """« Envoyer un mail » : aucun modèle ne peut le faire en parlant."""
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("OUTIL")
    assert await needs_a_tool("envoyer un SMS via un opérateur") is True


@pytest.mark.asyncio
async def test_the_judge_is_asked_the_right_question(judge):
    """Le critère doit être l'ACTION, pas la difficulté : une traduction
    juridique est difficile et reste une compétence."""
    from app.services.learning.tool_or_skill import needs_a_tool

    j = judge("COMPETENCE")
    await needs_a_tool("traduire un contrat en néerlandais")

    prompt = j.prompts[0].lower()
    assert "action" in prompt
    assert "traduire un contrat" in prompt


# ─────────────────────────────────────────────────────────────────────
# Échouer en NE générant PAS
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_verdict_qui_hesite_penche_vers_la_procedure(judge):
    """⚠️ L'ARBITRAGE PENCHE VERS LE DOCUMENT (02/09/2026).

    Avant ce lot, la lecture du verdict était « OUTIL est-il quelque part dans
    la réponse ? ». Un juge hésitant — « OUTIL ou COMPETENCE, difficile à
    dire » — fabriquait donc un outil : le mot OUTIL apparaissait, et il
    passait en premier dans la lecture.

    98 compétences apprises et 43 périmées plus tard, le doute doit produire
    une procédure : elle coûte des caractères plafonnés, l'outil coûte un
    schéma JSON à chaque tour, pour toujours.
    """
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("OUTIL ou COMPETENCE, difficile à dire ici")
    assert await needs_a_tool("archiver une note quelque part") is False


@pytest.mark.asyncio
async def test_un_verdict_delaye_ne_fabrique_pas_non_plus(judge):
    """« Je dirais qu'il faut un OUTIL » n'est pas le mot unique demandé.

    Le contrat du prompt est UN mot. Une phrase autour du mot est un juge qui
    raisonne à voix haute, donc qui hésite — et l'hésitation ne fabrique plus.
    """
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("Je dirais qu'il faut plutôt un OUTIL pour ça")
    assert await needs_a_tool("classer des fichiers") is False


@pytest.mark.asyncio
async def test_une_action_franche_reste_un_outil(judge):
    """Le pendant, sinon le lot ne fait que tout éteindre : un verdict net sur
    une capacité qui exige une action rend toujours « outil »."""
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("OUTIL")
    assert await needs_a_tool("téléverser un fichier sur un serveur SFTP") is True


@pytest.mark.asyncio
async def test_le_juge_est_prevenu_quune_procedure_peut_decrire_laction(judge):
    """Le critère écrit dans le prompt : un outil ne se justifie que si AUCUNE
    procédure ne peut décrire la marche à suivre avec les outils existants."""
    from app.services.learning.tool_or_skill import needs_a_tool

    j = judge("COMPETENCE")
    await needs_a_tool("préparer un devis à partir d'un tableau")

    prompt = j.prompts[0].lower()
    assert "procédure" in prompt, (
        "le juge n'est pas prévenu qu'une procédure peut couvrir le besoin — "
        "il tranchera comme avant"
    )


@pytest.mark.asyncio
async def test_an_unreadable_verdict_does_not_build_a_tool(judge):
    """Le doute ne fabrique rien. Rien n'est perdu — le gap reste consigné
    avec son bouton manuel."""
    from app.services.learning.tool_or_skill import needs_a_tool

    judge("Je ne suis pas certain de comprendre la question.")
    assert await needs_a_tool("quelque chose d'ambigu") is False


@pytest.mark.asyncio
async def test_no_judge_available_does_not_build_a_tool(monkeypatch):
    """Même règle quand le niveau S n'a aucun modèle : on ne fabrique pas à
    l'aveugle."""
    async def _none(**kwargs):
        return None, "none"

    monkeypatch.setattr("app.services.learning.tier_s.get_tier_s_llm", _none)
    from app.services.learning.tool_or_skill import needs_a_tool

    assert await needs_a_tool("envoyer un SMS") is False


@pytest.mark.asyncio
async def test_a_broken_judge_does_not_build_a_tool(monkeypatch):
    from app.services.learning.tool_or_skill import needs_a_tool

    class _Broken:
        async def ainvoke(self, payload, **kwargs):
            raise RuntimeError("modèle local éteint")

    async def _get(**kwargs):
        return _Broken(), "local"

    monkeypatch.setattr("app.services.learning.tier_s.get_tier_s_llm", _get)
    assert await needs_a_tool("envoyer un SMS") is False


@pytest.mark.asyncio
async def test_an_empty_capability_is_never_a_tool(judge):
    from app.services.learning.tool_or_skill import needs_a_tool

    assert await needs_a_tool("") is False
    assert await needs_a_tool("   ") is False


# ─────────────────────────────────────────────────────────────────────
# La garde est branchée sur le vrai déclencheur
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_skill_shaped_gap_never_reaches_the_generator(monkeypatch):
    """Le bout du lot : la génération ne part plus pour une capacité qu'un
    modèle règle en parlant."""
    from app.services.learning import auto_tool_generation as atg

    async def _no_tool_needed(capability, **kwargs):
        return False

    genere = {"n": 0}

    async def _generate(**kwargs):
        genere["n"] += 1
        return {"status": "created", "tool_name": "x"}

    monkeypatch.setattr(
        "app.services.learning.tool_or_skill.needs_a_tool", _no_tool_needed,
    )
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", _generate,
    )
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _none_existing,
    )
    monkeypatch.setattr(
        "app.services.learning.skill_creator.draft_playbook_for_gap",
        _drafted,
    )
    _fabrique_ouverte(monkeypatch)
    atg.reset_attempts()

    out = await atg.maybe_generate_for_gap(101, "résumer un texte", "u1")

    assert genere["n"] == 0, "un outil a été fabriqué pour une compétence"
    assert out is None or out.get("status") != "created"


@pytest.mark.asyncio
async def test_an_action_shaped_gap_still_reaches_the_generator(monkeypatch):
    """Le pendant : la garde ne doit pas tout bloquer. Ely gère les mails et
    l'agenda — ces actions-là ont besoin d'outils."""
    from app.services.learning import auto_tool_generation as atg

    async def _tool_needed(capability, **kwargs):
        return True

    genere = {"n": 0}

    async def _generate(**kwargs):
        genere["n"] += 1
        return {"status": "created", "tool_name": "sms_send"}

    monkeypatch.setattr(
        "app.services.learning.tool_or_skill.needs_a_tool", _tool_needed,
    )
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", _generate,
    )
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _none_existing,
    )
    monkeypatch.setattr(
        "app.services.learning.candidate_notify.notify_candidate", _noop_notify,
    )
    _fabrique_ouverte(monkeypatch)
    atg.reset_attempts()

    await atg.maybe_generate_for_gap(102, "envoyer un SMS", "u1")

    assert genere["n"] == 1


def _fabrique_ouverte(monkeypatch):
    """⚠️ Ces deux pins mesurent l'ARBITRAGE, pas le drapeau (02/09/2026).

    Depuis le gel de la fabrique, ``auto_tool_generation_enabled`` est destiné
    à valoir False par défaut : sans cette ouverture explicite, les deux tests
    passeraient au vert par le gel, sans jamais atteindre le juge qu'ils
    prétendent mesurer.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "auto_tool_generation_enabled", True)


async def _none_existing(capability, user_id=None):
    return None


async def _noop_notify(*a, **k):
    return None


async def _drafted(*a, **k):
    return {"status": "drafted", "skill_name": "resumer-un-texte"}

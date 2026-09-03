# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_todo_de_session.py
# @brief      Sur une demande à plusieurs étapes, Ely tient sa propre liste.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le carnet d'étapes de la conversation — 02/09/2026.

LE DÉFAUT : sur « télécharge les trois factures, renomme-les et range-les dans
Drive », Ely n'avait aucun endroit où écrire où elle en était. L'état du plan
ne vivait que dans le fil de messages, c'est-à-dire dans ce que la troncature
supprime en premier. D'où des étapes refaites, et des étapes oubliées.

CE QUE L'OUTIL DOIT GARANTIR, et que ces tests épinglent :
  - écrire puis relire rend la liste ;
  - l'appel sans argument LIT, il ne détruit rien (sinon le modèle perdrait son
    plan en voulant le consulter) ;
  - deux conversations ne partagent rien ;
  - les bornes tiennent, et elles ne se comportent pas pareil : une liste trop
    LONGUE est REFUSÉE (des étapes silencieusement absentes feraient croire au
    modèle qu'il suit un travail qu'il a perdu), une entrée trop longue est
    COUPÉE (une étiquette bavarde ne justifie pas de jeter un plan valide) ;
  - une seule entrée en cours à la fois ;
  - cocher ENRICHIT l'avancement : un modèle qui ne rapporte que l'étape qu'il
    vient de finir ne décoche pas les précédentes (relecture du 02/09/2026) ;
  - le registre évince par RÉCENCE et non par ordre d'apparition, et relire un
    plan compte comme le toucher.

Run with:  cd backend && python -m pytest tests/test_todo_de_session.py -v
"""
from __future__ import annotations

import pytest


def _poser_conversation(cid: str) -> None:
    """Ce que ``tool_node`` fait au début de chaque tour."""
    from app.agent.tool_context import CURRENT_CONVERSATION_ID

    CURRENT_CONVERSATION_ID.set(cid)


async def _appeler(**kwargs) -> str:
    from app.agent.tools.todo_tool import session_todo

    return await session_todo.ainvoke(kwargs)


# ─────────────────────────────────────────────────────────────────────
# Écrire, relire
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ecrire_puis_relire_rend_la_liste():
    _poser_conversation("conv-ecrire-relire")
    await _appeler(taches=["lire le devis", "extraire le total", "répondre"])

    rendu = await _appeler()
    for etape in ("lire le devis", "extraire le total", "répondre"):
        assert etape in rendu


@pytest.mark.asyncio
async def test_l_ecriture_rend_deja_la_liste_complete():
    """L'état revient dans le contexte SANS second appel : c'est ce qui permet
    de ne toucher à aucun prompt système."""
    _poser_conversation("conv-retour-immediat")
    rendu = await _appeler(taches=["étape A", "étape B"], en_cours=1)

    assert "étape A" in rendu and "étape B" in rendu


@pytest.mark.asyncio
async def test_un_appel_sans_argument_ne_detruit_pas_la_liste():
    _poser_conversation("conv-lecture-seule")
    await _appeler(taches=["une seule étape"])

    await _appeler()
    assert "une seule étape" in await _appeler()


@pytest.mark.asyncio
async def test_une_liste_vide_efface_explicitement():
    """Effacer doit rester POSSIBLE, mais seulement sur un geste explicite."""
    _poser_conversation("conv-effacer")
    await _appeler(taches=["à jeter"])

    await _appeler(taches=[])
    assert "à jeter" not in await _appeler()


# ─────────────────────────────────────────────────────────────────────
# L'état est par conversation
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deux_conversations_ne_partagent_pas_leur_liste():
    _poser_conversation("conv-alpha")
    await _appeler(taches=["tâche d'alpha"])

    _poser_conversation("conv-beta")
    await _appeler(taches=["tâche de beta"])
    rendu_beta = await _appeler()
    assert "tâche de beta" in rendu_beta
    assert "tâche d'alpha" not in rendu_beta

    _poser_conversation("conv-alpha")
    assert "tâche d'alpha" in await _appeler()


@pytest.mark.asyncio
async def test_le_registre_evince_par_recence_et_non_par_ordre_d_apparition():
    """Borné comme ``discovered_tools``, mais évincé autrement.

    La plus ANCIENNEMENT OUVERTE est retouchée entre-temps : elle survit, et
    c'est celle du milieu qui tombe. Sans réinsertion, c'est l'inverse — et
    perdre le plan d'une conversation vivante parce que 500 autres se sont
    ouvertes serait le pire moment pour l'oublier.
    """
    from app.agent.tools import todo_tool

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(todo_tool, "_MAX_CONVERSATIONS", 2)
        _poser_conversation("conv-vieille-mais-vivante")
        await _appeler(taches=["plan ancien"])
        _poser_conversation("conv-milieu")
        await _appeler(taches=["plan du milieu"])

        _poser_conversation("conv-vieille-mais-vivante")
        await _appeler(taches=["plan ancien, revu"])

        _poser_conversation("conv-neuve")
        await _appeler(taches=["plan récent"])

        _poser_conversation("conv-vieille-mais-vivante")
        assert "plan ancien, revu" in await _appeler(), "la retouche protège"
        _poser_conversation("conv-milieu")
        assert "plan du milieu" not in await _appeler(), "la plus vieille TOUCHE"


@pytest.mark.asyncio
async def test_relire_un_plan_le_protege_de_l_eviction():
    """Relire son plan est un signe de vie : la lecture rafraîchit la récence.

    Défaut relevé le 02/09/2026 : seule l'écriture réinsérait, donc une
    conversation qui consultait son plan sans le changer restait la première
    évincée — exactement le cas que la récence prétend couvrir.
    """
    from app.agent.tools import todo_tool

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(todo_tool, "_MAX_CONVERSATIONS", 2)
        _poser_conversation("conv-relue")
        await _appeler(taches=["plan relu"])
        _poser_conversation("conv-jamais-relue")
        await _appeler(taches=["plan jamais relu"])

        _poser_conversation("conv-relue")
        await _appeler()  # lecture seule, aucun changement d'état

        _poser_conversation("conv-neuve")
        await _appeler(taches=["plan récent"])

        _poser_conversation("conv-relue")
        assert "plan relu" in await _appeler(), "la lecture devait la rafraîchir"
        _poser_conversation("conv-jamais-relue")
        assert "plan jamais relu" not in await _appeler()


@pytest.mark.asyncio
async def test_relire_une_conversation_inconnue_n_evince_personne():
    """Sinon une simple question ferait tomber le plan de quelqu'un d'autre :
    une lecture qui ne trouve rien n'a aucune place à prendre dans le registre.
    """
    from app.agent.tools import todo_tool

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(todo_tool, "_MAX_CONVERSATIONS", 2)
        _poser_conversation("conv-occupante-1")
        await _appeler(taches=["premier plan"])
        _poser_conversation("conv-occupante-2")
        await _appeler(taches=["second plan"])

        _poser_conversation("conv-sans-plan")
        await _appeler()

        _poser_conversation("conv-occupante-1")
        assert "premier plan" in await _appeler()
        _poser_conversation("conv-occupante-2")
        assert "second plan" in await _appeler()


# ─────────────────────────────────────────────────────────────────────
# Les bornes
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_liste_trop_longue_est_refusee_et_l_ancienne_survit():
    """REFUSÉE, pas coupée : une liste tronquée ferait croire au modèle qu'il
    suit un travail dont les dernières étapes ont disparu."""
    from app.agent.tools.todo_tool import _MAX_TACHES

    _poser_conversation("conv-trop-longue")
    await _appeler(taches=["plan valide"])

    rendu = await _appeler(taches=[f"étape {i}" for i in range(_MAX_TACHES + 1)])
    assert "étape 0" not in rendu
    assert "plan valide" in rendu, "la liste précédente doit survivre au refus"


@pytest.mark.asyncio
async def test_une_entree_trop_longue_est_coupee_pas_refusee():
    from app.agent.tools.todo_tool import _MAX_LONGUEUR

    _poser_conversation("conv-entree-longue")
    rendu = await _appeler(taches=["z" * (_MAX_LONGUEUR + 50)])

    assert "z" * (_MAX_LONGUEUR + 1) not in rendu, "l'entrée devait être coupée"
    assert "z" * 40 in rendu, "l'entrée coupée reste dans la liste"


@pytest.mark.asyncio
async def test_une_entree_vide_n_encombre_pas_la_liste():
    from app.agent.tools.todo_tool import MARQUEUR_A_FAIRE

    _poser_conversation("conv-entree-vide")
    rendu = await _appeler(taches=["vraie étape", "   ", ""])

    assert rendu.count(MARQUEUR_A_FAIRE) == 1, f"une seule étape attendue :\n{rendu}"


# ─────────────────────────────────────────────────────────────────────
# Une seule entrée en cours
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_seule_entree_peut_etre_en_cours():
    from app.agent.tools.todo_tool import MARQUEUR_EN_COURS

    _poser_conversation("conv-un-seul-en-cours")
    await _appeler(taches=["a", "b", "c"], en_cours=1)
    rendu = await _appeler(en_cours=3)

    assert rendu.count(MARQUEUR_EN_COURS) == 1


@pytest.mark.asyncio
async def test_l_avancement_se_deplace_sans_retaper_la_liste():
    """Sinon le modèle réécrit trois étapes pour en cocher une — des tokens à
    chaque changement d'état, et une occasion de les réécrire de travers."""
    from app.agent.tools.todo_tool import MARQUEUR_FAITE

    _poser_conversation("conv-avancement")
    await _appeler(taches=["première", "seconde"], en_cours=1)

    rendu = await _appeler(faites=[1], en_cours=2)
    assert "première" in rendu and "seconde" in rendu
    assert f"{MARQUEUR_FAITE} première" in rendu


@pytest.mark.asyncio
async def test_cocher_une_etape_ne_decoche_pas_les_precedentes():
    """LE défaut du 02/09/2026 : ``faites`` remplaçait l'ensemble coché.

    Un modèle qui rapporte son avancement pas à pas — « je viens de finir la
    2 » — décochait la 1 et la refaisait : le défaut même que cet outil existe
    pour supprimer. ``faites`` ENRICHIT donc ; un rapport incomplet ne détruit
    plus rien.
    """
    from app.agent.tools.todo_tool import MARQUEUR_FAITE

    _poser_conversation("conv-cocher-cumulatif")
    await _appeler(taches=["première", "seconde", "troisième"])

    await _appeler(faites=[1], en_cours=2)
    rendu = await _appeler(faites=[2], en_cours=3)

    assert f"{MARQUEUR_FAITE} première" in rendu, "la 1 s'est décochée toute seule"
    assert f"{MARQUEUR_FAITE} seconde" in rendu
    assert rendu.count(MARQUEUR_FAITE) == 2


@pytest.mark.asyncio
async def test_decocher_demande_un_geste_explicite():
    """Une étape cochée par erreur reste corrigeable SANS retaper la liste."""
    from app.agent.tools.todo_tool import MARQUEUR_FAITE

    _poser_conversation("conv-decocher")
    await _appeler(taches=["première", "seconde"], faites=[1, 2])

    rendu = await _appeler(a_refaire=[1], en_cours=1)
    assert f"{MARQUEUR_FAITE} première" not in rendu
    assert f"{MARQUEUR_FAITE} seconde" in rendu, "seule la 1 était visée"


@pytest.mark.asyncio
async def test_decocher_une_etape_hors_liste_est_refuse_sans_rien_changer():
    """Un no-op silencieux laisserait le modèle croire qu'il a corrigé son
    plan, alors qu'il se trompe de plan."""
    from app.agent.tools.todo_tool import MARQUEUR_FAITE

    _poser_conversation("conv-decocher-hors-bornes")
    await _appeler(taches=["seule étape"], faites=[1])

    rendu = await _appeler(a_refaire=[7])
    assert "Refusé" in rendu
    assert f"{MARQUEUR_FAITE} seule étape" in rendu


@pytest.mark.asyncio
async def test_remplacer_la_liste_remet_l_avancement_a_zero():
    """Un numéro d'étape ne veut plus rien dire quand la liste change : garder
    l'ancien curseur cocherait une tâche au hasard."""
    from app.agent.tools.todo_tool import MARQUEUR_EN_COURS, MARQUEUR_FAITE

    _poser_conversation("conv-remplacement")
    await _appeler(taches=["ancienne 1", "ancienne 2"], en_cours=2, faites=[1])

    rendu = await _appeler(taches=["nouvelle 1", "nouvelle 2"])
    assert MARQUEUR_EN_COURS not in rendu
    assert MARQUEUR_FAITE not in rendu, "les coches ne survivent pas à la liste"


@pytest.mark.asyncio
async def test_un_numero_hors_liste_est_refuse_sans_rien_changer():
    from app.agent.tools.todo_tool import MARQUEUR_EN_COURS

    _poser_conversation("conv-hors-bornes")
    await _appeler(taches=["seule étape"], en_cours=1)

    rendu = await _appeler(en_cours=7)
    assert "seule étape" in rendu
    assert rendu.count(MARQUEUR_EN_COURS) == 1, "l'avancement précédent tient"


# ─────────────────────────────────────────────────────────────────────
# L'outil dans le dépôt : classé, joignable, et pas cher
# ─────────────────────────────────────────────────────────────────────


def test_l_outil_est_classe_et_ne_demande_pas_d_autorisation():
    """Il n'atteint rien d'extérieur : ni fichier, ni API, ni tiers. Le faire
    confirmer apprendrait à valider sans lire."""
    from app.agent.tool_nature import effect_of, requires_approval

    assert effect_of("session_todo") == "ECRITURE"
    assert requires_approval("session_todo") is False


def test_l_outil_est_joignable_depuis_les_deux_profils():
    from app.agent.toolset_profiles import resolve_profile_tools
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    catalogue = get_skill_registry().all_tools
    for profil in ("default", "compact"):
        noms = {t.name for t in resolve_profile_tools(profil, catalogue)}
        assert "session_todo" in noms, f"injoignable depuis le profil {profil}"


def test_la_description_envoyee_au_modele_reste_courte():
    """Elle repart au modèle à CHAQUE tour, dans le catalogue mis en cache.

    Mesuré le 02/09/2026 : 609 caractères, 195 tokens (cl100k), quand les 85
    outils du profil `compact` pèsent 7 786 tokens de descriptions, soit 92 en
    moyenne. C'est au-dessus de la moyenne parce que la consigne d'usage vit
    ICI et non dans le prompt système — donc payée une fois dans un schéma mis
    en cache, au lieu d'un préambule renvoyé à chaque tour. Ce plafond dit
    jusqu'où cet arbitrage va : 630 caractères, pas la moitié du fichier.

    Le plafond a monté de 520 à 630 le 02/09/2026, à la relecture du lot : il
    fallait 118 caractères (40 tokens, 0,5 % du catalogue `compact`) pour dire
    au modèle que `faites` ENRICHIT la liste des étapes terminées au lieu de
    la remplacer. Sans cette phrase, un modèle qui rapporte son avancement pas
    à pas décochait ses étapes et refaisait le travail : le contrat se lit là
    où le modèle le lit, pas dans le corps de l'outil.

    ⚠️ Le nombre de tokens n'est pas épinglé : il dépend du tokeniseur, et
    `tiktoken` n'est pas une dépendance déclarée du dépôt.
    """
    from app.agent.tools.todo_tool import session_todo

    assert len(session_todo.description) <= 630, (
        f"description de {len(session_todo.description)} caractères "
        "— environ 3,2 caractères par token en français, ça sort du budget"
    )

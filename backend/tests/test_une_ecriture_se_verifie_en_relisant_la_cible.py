# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_ecriture_se_verifie_en_relisant_la_cible.py
# @brief      Un appel d'outil réussi n'est pas une tâche réussie.
# @license    MIT
# =============================================================================
"""Le tableur créé, exporté vide (02/09/2026).

Ely a créé un tableur, écrit dedans, puis annoncé le travail fait. L'écriture
avait échoué en HTTP 400. Personne n'a relu la cible, et l'utilisateur a
découvert le fichier vide en l'ouvrant.

CE QUE LE DÉPÔT AVAIT DÉJÀ, ET POURQUOI ÇA N'A PAS SUFFI
---------------------------------------------------------
- ``completion_guard`` attrape l'affirmation NON ÉTAYÉE par un appel d'outil
  (« j'ai envoyé le mail » sans ``gmail_send_email``). Ici l'outil a bien été
  appelé : l'affirmation est étayée, et fausse quand même.
- La boucle de conformité (``agent/conformity.py``) confronte le résultat à la
  demande, au prix d'un second appel de modèle, et elle **échoue OUVERT** par
  contrat : juge indisponible, le tour passe.
- Le prompt disait « Retour d'outil = vérité absolue », mais seulement pour les
  retours qui COMMENCENT par « Erreur ». Un 200 qui n'a rien écrit ne dit rien.

Aucun des trois ne regarde la CIBLE. C'est la consigne d'Hermes
(``<external_state_verification>``) qui manquait : après une écriture, relire
l'objet exact avant de conclure.

Ce qu'elle coûte, sans arrondir : un appel d'OUTIL de plus par écriture, plus
l'itération d'inférence qui réinjecte son retour. Ce qu'elle ÉVITE, c'est un
appel de MODÈLE-JUGE — le second appel de ``conformity.py``. Seul le coût en
caractères du prompt a été mesuré (+281, ~70 tokens par tour) ; l'autre, non.

CE QUE CES PINS TIENNENT
-------------------------
1. La consigne est dans le prompt que le nœud envoie, et elle dit quoi relire
   et quoi en conclure. Le segment CACHEABLE, lui, n'est pas pinné : le pin qui
   prétendait le vérifier relisait le même objet que celui d'à côté, sans rien
   savoir de l'ordre de concaténation — retiré le 02/09 plutôt que gardé pour
   la forme.
2. Elle nomme les outils par leur NATURE (``tool_nature.EFFECTS``) et pas par
   une liste figée. Une liste écrite dans un prompt périme au premier ajout, et
   un prompt faux est pire qu'un prompt vague — c'est aussi pourquoi aucun
   COMPTE d'outils n'est cité ici : ce chiffre-là bouge, et le seul qui fasse
   foi est celui que ``test_docs_match_the_code.py`` relit dans le registre.
3. Elle n'apparaît qu'une fois, et elle est BORNÉE. Chaque caractère du prompt
   système est payé à chaque tour, sur chaque surface ; le dépôt vient de
   passer les descriptions d'outils de 15 486 à 8 676 tokens, on ne défait pas
   cet effort une ligne à la fois.

Run with:  cd backend && python -m pytest \
    tests/test_une_ecriture_se_verifie_en_relisant_la_cible.py -v
"""
from __future__ import annotations

import re
import unicodedata


# La phrase-pivot de la consigne. Sert d'ancre pour retrouver la ligne dans le
# prompt sans dépendre de sa position.
_ANCRE = "un appel d'outil réussi n'est pas une tâche réussie"


def _prompt() -> str:
    """Le prompt tel que le nœud agent le concatène.

    On le prend à ``app.agent.nodes``, le site d'import réel, et pas au module
    qui le déclare : c'est cette valeur-là qui part au modèle.
    """
    from app.agent.nodes import _SYSTEM_PROMPT_BASE

    return _SYSTEM_PROMPT_BASE


def _consigne(prompt: str) -> str:
    """La ligne qui porte la consigne, ou une chaîne vide."""
    for ligne in prompt.splitlines():
        if _ANCRE in ligne.lower():
            return ligne
    return ""


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )


# ─────────────────────────────────────────────────────────────────────
# 1 — La consigne existe, là où elle sera lue
# ─────────────────────────────────────────────────────────────────────

def test_le_prompt_demande_de_relire_la_cible_avant_de_conclure():
    """LE pin de l'incident.

    Sans cette phrase, le modèle n'a aucune raison de relire : son outil a
    rendu un succès, et c'est tout ce qu'il voit.
    """
    bas = _prompt().lower()

    assert _ANCRE in bas, (
        "le prompt ne dit nulle part qu'un appel réussi ne vaut pas une tâche "
        "réussie : le tableur vide du 02/09 repasserait à l'identique"
    )
    assert "relis" in bas, (
        "la consigne ne dit pas quoi FAIRE. Constater qu'un succès d'outil "
        "n'est pas un succès de tâche sans dire de relire ne change rien"
    )


def test_la_consigne_dit_quoi_relire_et_quoi_conclure():
    """Une consigne qui s'arrête à « vérifie » se satisfait d'un coup d'œil au
    retour de l'outil, celui-là même qui a menti. Elle doit nommer la CIBLE, et
    dire ce qu'on conclut quand la relecture ne montre rien."""
    ligne = _consigne(_prompt()).lower()

    assert "cible" in ligne, (
        "la consigne ne nomme pas ce qu'il faut relire. « Vérifie » tout court "
        "renvoie le modèle vers le retour d'outil qu'il a déjà"
    )
    assert "lecture" in ligne, (
        "rien n'indique de repasser par un outil de LECTURE : le modèle peut "
        "croire qu'un raisonnement suffit"
    )
    sans_accents = _sans_accents(ligne)
    assert "echec" in sans_accents or "echou" in sans_accents, (
        "la consigne ne dit pas quoi conclure quand la relecture ne montre "
        "pas l'effet. Sans verdict nommé, le modèle annonce quand même"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Par nature, pas par liste
# ─────────────────────────────────────────────────────────────────────

def test_la_consigne_designe_les_outils_par_leur_nature():
    """Le dépôt classe déjà ses outils sur l'axe EFFET
    (``tool_nature.EFFECTS``). La consigne doit emprunter ce vocabulaire :
    renommer une nature d'un côté sans l'autre rendrait le prompt muet sur la
    moitié des outils qu'il vise, sans que rien ne rougisse."""
    from app.agent.tool_nature import EFFECTS

    ligne = _sans_accents(_consigne(_prompt()).lower())

    for nature in ("ECRITURE", "ENGAGEANT"):
        assert nature in EFFECTS, f"{nature} n'est plus une nature du dépôt"
        assert nature.lower() in ligne, (
            f"la consigne ne nomme pas les outils « {nature.lower()} ». Elle "
            f"laisse alors le modèle décider seul de ce qui mérite relecture"
        )


def test_la_consigne_ne_fige_aucune_liste_d_outils():
    """Une liste d'outils nommée dans le prompt périme au premier ajout, et un
    prompt faux est pire qu'un prompt vague : c'est déjà la raison pour
    laquelle aucun COMPTE d'outils n'y figure — le registre en compte plusieurs
    centaines et le nombre bouge à chaque compétence ajoutée."""
    ligne = _consigne(_prompt())
    assert ligne, "consigne introuvable"
    noms = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", ligne)

    assert not noms, (
        f"la consigne nomme {noms} : cette liste ne couvrira jamais le "
        f"catalogue et mentira dès le prochain ajout. Décris la nature."
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — Ce que la consigne coûte
# ─────────────────────────────────────────────────────────────────────

def test_la_consigne_n_apparait_qu_une_fois():
    """Le prompt a déjà une section « Intégrité des actions » et une RÈGLE 0.
    Une deuxième copie de la même règle se paierait à chaque tour sans rien
    ajouter, et le pin anti-duplication existant ne voit que les paragraphes
    de 200 caractères et plus."""
    bas = _prompt().lower()

    assert bas.count(_ANCRE) == 1, (
        f"la consigne apparaît {bas.count(_ANCRE)} fois"
    )
    assert bas.count("relis la cible") <= 1, (
        "la consigne de relecture est dupliquée dans le prompt"
    )


def test_la_consigne_tient_en_une_ligne_bornee():
    """⚠️ LE GARDE-FOU DE COÛT, et il n'est pas décoratif.

    Le prompt de base occupait 14 901 caractères sur les 15 000 de sa garde
    avant cet ajout. Chaque caractère part à chaque tour, sur chaque surface,
    et le dépôt vient de passer les descriptions d'outils de 15 486 à 8 676
    tokens. Une consigne qui redevient un paragraphe de vingt lignes défait cet
    effort sans que personne ne le voie.
    """
    ligne = _consigne(_prompt())

    assert ligne, "consigne introuvable"
    assert len(ligne) <= 400, (
        f"la consigne pèse {len(ligne)} caractères (~{len(ligne) // 4} tokens) "
        f"payés à chaque tour. Au-delà de 400, compacte-la."
    )

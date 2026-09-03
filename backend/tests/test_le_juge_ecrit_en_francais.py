# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_juge_ecrit_en_francais.py
# @brief      Une espace avant les deux-points annulait toute la boucle de
#             reprise.
# @license    MIT
# =============================================================================
"""Le juge écrit en français, le lecteur lisait de l'anglais — 02/09/2026.

``parse_conformity_verdict`` cherchait ``ÉCARTS:`` collé aux deux-points. La
typographie française met une espace avant « : », et le juge répond en
français : un verdict « ÉCARTS : … » ne portait donc AUCUN marqueur reconnu.

Conséquence en chaîne, et elle est silencieuse :

  - le verdict est classé CONFORME, la reprise ne part pas ;
  - l'utilisateur reçoit un résultat incomplet sans le savoir — exactement ce
    que cette boucle existe pour supprimer ;
  - le journal dit « verdict hors contrat » alors que le juge a suivi le
    contrat à une espace près ;
  - ``conformity_retries`` reste à zéro, donc ``skill_from_success`` ne
    propose JAMAIS de procédure (il exige un succès APRÈS reprise).

⚠️ La fonction échoue OUVERT à dessein : un verdict illisible doit continuer
de passer. Les tests ci-dessous tiennent les deux bouts.
"""
from __future__ import annotations

import pytest

from app.agent.conformity import parse_conformity_verdict


ESPACES_FRANCAISES = (
    " ",         # espace ordinaire
    " ",    # insécable
    " ",    # insécable étroite (celle que met un traitement de texte)
)


@pytest.mark.parametrize("espace", ESPACES_FRANCAISES)
def test_un_verdict_a_la_francaise_est_un_ecart(espace):
    """« ÉCARTS : … » — la forme que produit un modèle qui écrit en français."""
    ok, ecarts = parse_conformity_verdict(
        f"ÉCARTS{espace}:\n- les marges du document source ne sont pas reprises"
    )
    assert ok is False, "le verdict a été classé conforme"
    assert "marges" in ecarts


def test_un_verdict_sans_accent_reste_lu():
    ok, ecarts = parse_conformity_verdict("ECARTS : - la police est remplacée")
    assert ok is False
    assert "police" in ecarts


def test_le_mot_conforme_dans_un_ecart_ne_fait_pas_passer_le_tour():
    """« … n'est pas conforme au format demandé » est du français ordinaire.

    Le mot cherché n'importe où dans le texte faisait passer pour satisfait un
    verdict qui nommait des écarts.
    """
    ok, ecarts = parse_conformity_verdict(
        "ÉCARTS :\n- le fichier rendu n'est pas conforme au format .docx demandé"
    )
    assert ok is False
    assert ".docx" in ecarts


def test_un_verdict_illisible_passe_toujours():
    """Échouer OUVERT : une panne du juge ne se transforme pas en boucle de
    relances payantes."""
    for bruit in ("", "   ", "je ne sais pas quoi répondre", "{json cassé"):
        ok, _ = parse_conformity_verdict(bruit)
        assert ok is True, f"{bruit!r} a déclenché une relance"


def test_un_verdict_conforme_reste_conforme():
    for texte in ("CONFORME", "Après vérification : CONFORME.", "CONFORME."):
        ok, ecarts = parse_conformity_verdict(texte)
        assert ok is True, f"{texte!r} a déclenché une relance"
        assert ecarts == ""

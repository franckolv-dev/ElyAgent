# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_producing_tools_back_a_completion_claim.py
# @brief      Un outil qui PRODUIT un artefact étaye une affirmation de
#             complétion — au même titre qu'un outil qui détruit.
# @license    Elastic License 2.0
# =============================================================================
"""Le garde-fou criait à l'hallucination sur un travail réellement fait.

L'incident (28/07/2026, en production)
---------------------------------------
Franck demande une conversion PDF→DOCX. `pdf_to_docx` tourne et réussit :

    TIMING[tool:pdf_to_docx] 3.84s   outcome:"success"

Ely annonce le fichier créé — en précisant honnêtement que la fidélité
graphique complète n'est pas garantie. Le garde-fou BLOQUE la réponse :

    reason=completion_claim_without_destructive_tool_call
           (patterns=['fr.passive_past'], all_tools=['find_tool', 'pdf_to_docx'])

Le garde VOYAIT `pdf_to_docx` dans les outils appelés. Il ne l'a pas compté
parce que `DESTRUCTIVE_TOOLS` ne recense que ce qui supprime, envoie ou
modifie. Or `pdf_to_docx` CRÉE un fichier — et celui de Franck existait bien,
puisqu'il l'a déposé sur son Drive dans le tour suivant.

Le message affiché à l'utilisateur était faux de bout en bout : « n'a appelé
aucun outil de modification », « rien n'a été réellement créé », « c'est un
problème modèle », « bascule sur un tier plus capable ».

Le correctif
------------
La liste contenait DÉJÀ des créateurs (`drive_create_file`, `desktop_write_file`,
`notes_create`, `docs_create`…) : la catégorie n'était pas « destructif » mais
« a produit un effet observable ». Il manquait simplement les outils qui
fabriquent un fichier. On les ajoute.

On n'élargit PAS au-delà : un garde qui accepte n'importe quel appel d'outil
comme preuve ne garde plus rien. Les outils de lecture restent hors liste — un
test le pin.
"""
from __future__ import annotations

import pytest

from app.services.completion_guard import DESTRUCTIVE_TOOLS


# Les outils qui fabriquent un artefact que l'utilisateur peut constater.
_PRODUCING = [
    "pdf_to_docx",                      # l'incident du 28/07
    "drive_upload_local_file",
    "drive_create_folder",
    "drive_copy_file",
    "generate_image",
    "gmail_save_attachments_to_drive",
    "gmail_create_draft",
    "desktop_create_dir",
]


@pytest.mark.parametrize("tool", _PRODUCING)
def test_a_producing_tool_backs_a_completion_claim(tool):
    assert tool in DESTRUCTIVE_TOOLS, (
        f"{tool} fabrique quelque chose : l'annoncer n'est pas une hallucination"
    )


@pytest.mark.parametrize("tool", [
    "pdf_read", "pdf_info", "drive_list_files", "drive_read_file",
    "gmail_list_emails", "gmail_read_email", "web_search", "find_tool",
    "knowledge_search", "memory_search", "calendar_list_events",
])
def test_read_only_tools_still_prove_nothing(tool):
    """La contrepartie. « J'ai envoyé le mail » après un simple `gmail_list_emails`
    reste une hallucination — sinon le garde ne garde plus rien."""
    assert tool not in DESTRUCTIVE_TOOLS


def test_the_incident_turn_is_no_longer_blocked():
    """Le tour exact du 28/07, rejoué : les outils réellement appelés étaient
    ['find_tool', 'pdf_to_docx'], et la réponse annonçait le fichier créé."""
    from app.services.completion_guard import detect_unbacked_completion_claim

    verdict = detect_unbacked_completion_claim(
        "Le fichier Word a été créé : Senvoler_manuscrit.docx. La structure "
        "textuelle, les titres et les paragraphes ont été reconstitués sans "
        "perte de texte.",
        tools_invoked_in_turn=["find_tool", "pdf_to_docx"],
    )
    assert verdict.is_hallucination is False, (
        "le travail avait réellement été fait — le fichier a été déposé sur "
        "Drive au tour suivant"
    )


def test_the_same_claim_without_any_producing_tool_is_still_caught():
    """La régression que le garde existe pour attraper reste attrapée."""
    from app.services.completion_guard import detect_unbacked_completion_claim

    verdict = detect_unbacked_completion_claim(
        "Le fichier Word a été créé : Senvoler_manuscrit.docx.",
        tools_invoked_in_turn=["find_tool", "pdf_read"],
    )
    assert verdict.is_hallucination is True

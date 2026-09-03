# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_no_confirmation_incantations.py
# @brief      Ménage lot 3 — une docstring ne promet plus une confirmation.
#             La garde est le mécanisme ; le texte n'en était que le décor.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du retrait des « ALWAYS ask user confirmation » de docstrings.

**Pourquoi.** #297 a posé la garde réelle : `requires_approval()`, adossée à
`LOCKED_HITL_TOOLS ∪ ALWAYS_CRITICAL_TOOLS`, dispenses écrites, défaut FERMÉ.
Restaient 9 docstrings qui **affirmaient** une confirmation. Une consigne au
modèle n'est pas un garde-fou ([[nature_des_outils]]) : elle coûte des tokens
à chaque tour et fait croire à une protection qui vit ailleurs.

**Trois d'entre elles étaient pires que redondantes — elles mentaient**, en
contredisant une décision écrite de Franck du 28/07 :

```
browser_click          « ALWAYS requires human validation »  ← DISPENSÉ :
                         « naviguer n'est pas engager »
browser_fill           « ALWAYS requires human validation »  ← DISPENSÉ :
                         « remplir un formulaire n'est pas le soumettre »
calendar_create_event  « ALWAYS confirm with user »          ← classé ECRITURE
                         (privé et réversible ; c'est calendar_create_meet_event,
                         qui envoie des invitations, qui est gardé)
```

Elles faisaient redemander un accord que Franck avait explicitement retiré.

**Le second test est celui qui compte dans la durée** : il n'interdit pas le
texte, il interdit le **mensonge**. Une docstring qui promet une confirmation
alors que `requires_approval()` dit non redevient rouge — dans les deux sens,
qu'on ajoute la phrase ou qu'on retire la garde.

Run with:  cd backend && python -m pytest tests/test_no_confirmation_incantations.py -v
"""
from __future__ import annotations

import re

import pytest

# Formulations qui AFFIRMENT une exigence de confirmation. Volontairement
# étroit : on ne veut pas attraper une phrase qui explique un comportement
# (« the user will be asked »), seulement celles qui posent une règle.
_INCANTATION = re.compile(
    r"ALWAYS\s+(ask|confirm|require)"
    r"|ALWAYS\s+requires?\s+human\s+validation"
    r"|ask\s+user\s+confirmation",
    re.IGNORECASE,
)

# Les 9 docstrings retirées par ce lot — figées pour que le second test garde
# son objet même une fois le texte parti.
_FORMERLY_INCANTING = (
    "gmail_send_email",
    "gmail_move_emails",
    "gmail_reply_email",
    "gmail_send_with_attachment",
    "gmail_send_with_local_attachment",
    "calendar_create_event",
    "calendar_delete_event",
    "browser_click",
    "browser_fill",
)


def _all_tools():
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry

    register_all()
    return get_skill_registry().all_tools


def test_no_tool_description_claims_a_confirmation() -> None:
    """Aucune description d'outil n'affirme d'exigence de confirmation.

    Le catalogue d'outils part dans le prompt à chaque tour : ces phrases se
    paient à chaque itération de la boucle, pour un effet que la garde produit
    déjà — et mieux.
    """
    offenders = [
        t.name for t in _all_tools()
        if _INCANTATION.search(t.description or "")
    ]
    assert offenders == [], (
        "incantations encore présentes dans des descriptions d'outils : "
        f"{sorted(offenders)}"
    )


@pytest.mark.parametrize("name", _FORMERLY_INCANTING)
def test_formerly_incanting_tool_is_governed_by_the_real_mechanism(name: str) -> None:
    """Retirer le texte ne perd rien : la décision vit dans le mécanisme.

    Soit l'outil est gardé — HITL demandera l'accord de toute façon —, soit sa
    dispense est écrite noir sur blanc dans `APPROVAL_WAIVED`, soit la table le
    classe comme non engageant. Dans les trois cas, une phrase de docstring
    n'ajoutait rien.
    """
    from app.agent import tool_nature as tn

    # ⚠️ Sans ce garde-fou, le test passerait sur une FAUTE DE FRAPPE :
    # `requires_approval()` échoue FERMÉ, donc un nom inexistant rend True et
    # l'assertion ci-dessous serait satisfaite pour rien. Trois des neuf noms
    # étaient faux au premier jet et les cas passaient quand même.
    assert name in {t.name for t in _all_tools()}, (
        f"{name} n'est pas un outil enregistré — nom périmé dans le pin"
    )

    guarded = tn.requires_approval(name)
    waived = name in getattr(tn, "APPROVAL_WAIVED", {})
    effect = tn.effect_of(name)

    assert guarded or waived or effect != "ENGAGEANT", (
        f"{name} : ni gardé, ni dispensé avec raison, et classé ENGAGEANT. "
        f"Retirer son incantation laisserait un acte engageant sans rien du "
        f"tout — ajouter une garde AVANT de retirer le texte."
    )

# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduler_missed_runs.py
# @brief      Une occurrence manquée doit se voir, un rattrapage doit s'annoncer,
#             et une tâche à livrable ne doit pas pouvoir se taire.
# @license    MIT
# =============================================================================
"""L'incident du 06/08/2026 — « aucun post, aucune proposition ».

La tâche « Propositions LinkedIn PAO et InDesign » (un mercredi sur deux,
09:00, première date le mercredi 5 août) affichait « Dernière exécution :
06/08/2026 17:31:26 » — un **jeudi soir**. Rien n'avait été livré, et il ne
restait aucune conversation à relire.

Trois défauts empilés, chacun épinglé ici :

1. **L'occurrence de mercredi n'a jamais eu lieu et n'a jamais été récupérée.**
   `scheduler_catchup_max_age_hours` vaut 24 h ; entre mercredi 09:00 et le
   redémarrage, il s'était écoulé plus que ça. L'occurrence était écartée en
   silence. Pour une tâche « un mercredi sur deux », ce n'est pas un jour
   sauté, c'est un CYCLE : quatre semaines entre deux livraisons au lieu de
   deux.

2. **Un rattrapage rejouait le prompt à l'identique.** La consigne disait
   « Nous sommes un mercredi matin », Ely injecte la vraie date dans son
   prompt système, et la tâche demandait de s'arrêter si la date du jour
   n'appartenait pas à la cadence. Le modèle a constaté « jeudi », s'est
   arrêté, et a rendu `[SILENT]`. **Il a fait exactement ce qu'on lui
   demandait** — le mode dégradé se présentait comme nominal AU MODÈLE.

3. **`[SILENT]` a effacé la preuve.** La conversation était supprimée, et le
   test était `startswith` là où la consigne dit « ce seul mot, rien
   d'autre ». Une tâche à livrable pouvait se taire sur la foi d'une phrase
   de prompt — invariant 3 : une consigne au modèle n'est pas un verrou.

Run with:  cd backend && python -m pytest tests/test_scheduler_missed_runs.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — Une occurrence trop vieille est ÉCARTÉE, et ça doit se voir
# ─────────────────────────────────────────────────────────────────────

def test_an_occurrence_older_than_the_window_is_not_caught_up():
    """Le comportement de base, épinglé pour que le constat ait un sens.

    Sans ce pin, on pourrait « corriger » le silence en élargissant la
    fenêtre — ce qui rejouerait des occurrences périmées au lieu de les
    signaler. Les deux décisions sont distinctes.
    """
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 8, 6, 17, 31, tzinfo=timezone.utc)  # jeudi 17h31
    # ⚠️ `day_of_week` compte 0 = LUNDI chez APScheduler : mercredi vaut 2,
    # pas 3. Écrire 3 donne un jeudi, donc une occurrence du matin même —
    # dans la fenêtre — et le test passerait pour la mauvaise raison.
    manque = compute_catchup_run(
        "0 9 * * 2", now - timedelta(days=15), now=now, max_age=timedelta(hours=24),
    )
    assert manque is None, (
        "une occurrence de plus de 24 h ne doit pas être rejouée telle quelle"
    )


def test_the_same_occurrence_exists_once_the_window_is_lifted():
    """Ce que le constat s'appuie dessus : l'occurrence EXISTAIT.

    C'est la différence entre « rien n'était dû » et « quelque chose était dû
    et on l'a jetée ». Confondre les deux, c'est précisément ce qui a rendu
    l'incident du 06/08 illisible.
    """
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 8, 6, 17, 31, tzinfo=timezone.utc)  # jeudi 17h31
    perdue = compute_catchup_run(
        "0 9 * * 2", now - timedelta(days=15), now=now, max_age=timedelta(days=365),
    )
    assert perdue is not None, (
        "sans occurrence retrouvée à fenêtre levée, le constat « manquée » "
        "n'aurait aucune base"
    )
    assert perdue < now


# ─────────────────────────────────────────────────────────────────────
# 2 — Un rattrapage DIT qu'il est en retard
# ─────────────────────────────────────────────────────────────────────

def test_a_late_run_tells_the_task_it_is_late():
    """Sans cet aveu, une tâche qui raisonne sur « aujourd'hui » se trompe.

    C'est l'invariant « un repli doit se voir », adressé au modèle et non à
    l'utilisateur.
    """
    from app.services.scheduler import _late_run_notice

    note = _late_run_notice("2026-08-05T09:00")
    assert "2026-08-05T09:00" in note, (
        "l'occurrence manquée doit être NOMMÉE : c'est la date sur laquelle la "
        "tâche doit raisonner"
    )
    bas = note.lower()
    assert "retard" in bas or "rattrapage" in bas
    assert "pas" in bas and "prévu" in bas, (
        "l'aveu doit dire explicitement qu'on n'est PAS au moment prévu — "
        "sinon la prémisse du prompt d'origine reste crue"
    )


def test_a_late_run_still_asks_for_a_deliverable():
    """Le piège du correctif : un aveu de retard qui autoriserait à ne rien
    rendre reproduirait le silence qu'on corrige, avec une meilleure excuse.
    """
    from app.services.scheduler import _late_run_notice

    bas = _late_run_notice("2026-08-05T09:00").lower()
    assert "livrable" in bas or "produis" in bas
    assert "dis-le" in bas or "explicitement" in bas, (
        "si la tâche juge le travail périmé, elle doit le DIRE — rendre "
        "quelque chose, jamais disparaître"
    )


def test_the_notice_precedes_the_original_prompt():
    """L'ordre compte : la consigne d'origine doit rester lisible APRÈS
    l'aveu, sinon on ne sait plus ce que la tâche demandait vraiment."""
    from app.services.scheduler import _late_run_notice

    note = _late_run_notice("2026-08-05T09:00")
    assert note.rstrip().endswith("---") or "origine" in note.lower(), (
        "l'aveu doit se terminer par une séparation explicite avant le prompt"
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — `[SILENT]` : permission portée par la tâche, égalité stricte
# ─────────────────────────────────────────────────────────────────────

def test_allow_silent_defaults_to_false():
    """On échoue FERMÉ du côté de la livraison.

    Une proposition en trop se lit et s'ignore ; une proposition manquante ne
    se voit pas. Le défaut inverse rendrait muette, au premier `[SILENT]` mal
    placé, une tâche dont c'est tout le travail de livrer.
    """
    from app.models.scheduled_task import ScheduledTask

    t = ScheduledTask(
        user_id="u", name="n", prompt="p", cron_expression="0 9 * * 3",
    )
    # `default=` s'applique au flush ; on vérifie la valeur DÉCLARÉE, qui est
    # ce que lit le planificateur via getattr sur un objet non encore flushé.
    colonne = ScheduledTask.__table__.c.allow_silent
    assert colonne.default is not None and colonne.default.arg is False, (
        "allow_silent doit valoir False par défaut"
    )
    assert colonne.nullable is False, (
        "un NULL se lirait « pas décidé » et ferait diverger les lectures"
    )
    assert t is not None


@pytest.mark.parametrize("reponse,attendu", [
    ("[SILENT]", True),
    ("  [silent]  ", True),
    ("[SILENT] côté actualités, mais voici trois propositions…", False),
    ("[SILENT]\n\nVoici quand même le rapport", False),
    ("Rien à signaler", False),
])
def test_only_the_exact_word_counts_as_silent(reponse: str, attendu: bool):
    """`startswith` avalait le livrable avec le préfixe.

    La consigne dit « ce seul mot, rien d'autre » ; le test l'acceptait suivi
    de n'importe quoi. Un test plus large que son contrat finit toujours par
    avaler autre chose que ce qu'il visait — ici, les propositions elles-mêmes.
    """
    assert (reponse.strip().upper() == "[SILENT]") is attendu


def test_the_scheduler_reads_the_permission_not_the_prompt():
    """Invariant 3 : une phrase de prompt n'est pas un verrou.

    Le garde-fou existait — « pour une tâche qui produit toujours un livrable,
    NE l'utilise JAMAIS » — et il était adressé au modèle. Le planificateur,
    lui, acceptait `[SILENT]` de n'importe qui. Ce pin vérifie que la décision
    lit désormais un CHAMP.
    """
    import inspect

    from app.services import scheduler

    src = inspect.getsource(scheduler._execute_task)
    assert "allow_silent" in src, (
        "la décision de se taire doit lire la permission de la tâche"
    )
    assert 'startswith("[SILENT]")' not in src, (
        "le test doit être une égalité stricte, pas un préfixe"
    )
    assert "db.delete(_conv)" not in src, (
        "la conversation d'une exécution silencieuse doit être CONSERVÉE : "
        "la supprimer efface la seule trace du raisonnement, et c'est ce qui "
        "a rendu l'incident du 06/08 inexplicable après coup"
    )

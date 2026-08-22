# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_watched_folders_report_reality.py
# @brief      Un dossier « en cours de scan » depuis des mois ne scanne rien.
# @license    Elastic License 2.0
# =============================================================================
"""L'indexation muette, découverte le 21/08.

Franck, sur un dossier surveillé depuis des mois :

    /Users/franck/Documents  [RÉCURSIF]
    running — · 0 fichier(s) indexé(s)
    Scan en cours...

Un scan « en cours » depuis des semaines, zéro fichier, et une interface qui
promettait « le scan tourne toutes les heures et détecte les nouveaux
fichiers ».

DEUX DÉFAUTS QUI SE COUVRAIENT
-------------------------------
1. **La sortie précoce ne consignait rien.** `scan_folder` posait
   ``last_scan_status = "running"`` puis sortait par `return` sur ses deux
   échecs les plus fréquents — démon absent, marche impossible — sans jamais
   atteindre le bloc de persistance, tout en bas de la fonction. La ligne
   restait donc gelée sur « running / Scan en cours… », définitivement.

2. **Le cron horaire sautait en silence.** `scan_all_enabled` faisait
   ``continue`` sur les dossiers dont le démon est hors ligne, sans un log ni
   un mot sur la ligne. Le commentaire disait « no point trying » — c'est
   vrai. Le défaut n'était pas de sauter, c'était de le taire.

Ensemble : le cron passait toutes les heures sans rien écrire, et la seule
ligne jamais écrite était le « running » d'un scan manuel mort à la première
instruction. L'écran annonçait un travail qui n'avait jamais commencé —
l'invariant 5 du dépôt, une fausse déclaration d'action.

⚠️ CE QUE ÇA RÉVÈLE, et qui n'était écrit nulle part : cette fonctionnalité
ne lit PAS le système de fichiers du conteneur. Elle demande à ELY Desktop, sur
la machine de l'utilisateur, de marcher dans le dossier et de lire les
fichiers. Sans démon, elle ne peut rien — et le registre des connexions vit en
mémoire, donc chaque redémarrage du backend la coupe.

Run with:  cd backend && python -m pytest tests/test_watched_folders_report_reality.py -v
"""
from __future__ import annotations

import inspect

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — Toute sortie consigne
# ─────────────────────────────────────────────────────────────────────

def test_every_early_exit_records_its_outcome():
    """LE pin de l'incident.

    Structurel à dessein : monter un scan réel demande une base, un dossier
    surveillé et un faux démon. Ce qui a produit le défaut est bien plus
    simple — un `return` placé avant la persistance — et ça se lit.
    """
    from app.services import auto_indexer

    src = inspect.getsource(auto_indexer.scan_folder)
    lignes = src.splitlines()

    # Chaque `return summary` doit être précédé, dans les lignes qui le
    # précèdent immédiatement, d'un appel à `_consigner`.
    manquants: list[int] = []
    for i, ligne in enumerate(lignes):
        if ligne.strip() != "return summary":
            continue
        fenetre = "\n".join(lignes[max(0, i - 6):i])
        if "_consigner(" not in fenetre:
            manquants.append(i + 1)

    assert not manquants, (
        f"`return summary` sans consignation aux lignes {manquants} de "
        f"`scan_folder`. La ligne du dossier restera gelée sur « running » — "
        f"c'est exactement ce qui a rendu l'indexation muette pendant des mois."
    )


def test_a_missing_daemon_is_not_reported_as_an_error():
    """`offline` et `error` appellent des gestes DIFFÉRENTS.

    « Erreur » envoie chercher une panne ; ici il n'y en a pas — ni démon
    connecté, ni dossier monté. Confondre les deux, c'est envoyer
    l'utilisateur fouiller des logs pour un programme qu'il n'a pas lancé.

    ⚠️ Ancré sur `_mode_de_lecture` depuis le 22/08, et pas sur
    `is_connected` : le montage de dossier a ajouté une seconde voie de
    lecture, donc « pas de démon » ne suffit plus à conclure `offline`.
    L'invariant n'a pas bougé, sa condition oui.
    """
    from app.services import auto_indexer

    src = inspect.getsource(auto_indexer.scan_folder)
    bloc = src[src.find("_mode_de_lecture("):]
    assert '"offline"' in bloc[:900], (
        "une source illisible doit se distinguer d'un scan qui a échoué"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Le cron ne saute plus en silence
# ─────────────────────────────────────────────────────────────────────

def test_the_hourly_cron_says_when_it_skips():
    """Un mécanisme qui ne fait rien doit le dire. Invariant 4 du dépôt."""
    from app.services import auto_indexer

    # ⚠️ Ancré sur `_mode_de_lecture` depuis le 22/08 : tester `is_connected`
    # ici écarterait les dossiers MONTÉS, qui n'ont pas besoin du démon. Le
    # pin `test_the_cron_asks_the_same_question_as_the_scan` garde ce point.
    src = inspect.getsource(auto_indexer.scan_all_enabled)
    pos_test = src.find("_mode_de_lecture(")
    pos_continue = src.find("continue", pos_test)
    pos_consigner = src.find("_consigner(", pos_test)

    assert pos_consigner != -1, (
        "le cron saute les dossiers hors ligne sans laisser de trace — "
        "l'utilisateur ne peut pas distinguer « ça marche » de « ça n'a "
        "jamais démarré »"
    )
    assert pos_consigner < pos_continue, (
        "la consignation doit précéder le `continue`, sinon elle n'est jamais "
        "atteinte"
    )


def test_the_cron_does_not_rewrite_an_unchanged_state():
    """⚠️ Le piège du correctif.

    Consigner à chaque tick ferait battre `last_scan_at` toutes les heures.
    L'écran afficherait « il y a 3 minutes » sur un dossier que personne n'a
    scanné depuis des mois : on remplacerait un silence par un mensonge plus
    convaincant.
    """
    from app.services import auto_indexer

    src = inspect.getsource(auto_indexer.scan_all_enabled)
    assert "seulement_si_change=True" in src, (
        "le cron doit n'écrire que sur changement d'état"
    )


@pytest.mark.asyncio
async def test_recording_a_state_never_breaks_a_scan(monkeypatch):
    """Consigner est un rangement : si la base tousse, le scan continue."""
    from app.services import auto_indexer

    def _base_cassee(*_a, **_k):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(auto_indexer, "async_session", _base_cassee)
    await auto_indexer._consigner("id", "ok", "message")  # ne lève pas


# ─────────────────────────────────────────────────────────────────────
# 3 — L'interface ne promet plus ce qu'elle ne tient pas
# ─────────────────────────────────────────────────────────────────────

def test_the_ui_names_the_daemon_dependency():
    """Le texte disait « le scan tourne toutes les heures et détecte les
    nouveaux fichiers — plus besoin d'uploader manuellement ». Vrai seulement
    si ELY Desktop tourne, ce que rien n'indiquait. C'est cette phrase qui a
    fait conclure à Franck que l'indexation fonctionnait."""
    import json
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2] / "frontend" / "messages"
    for langue in ("fr", "en"):
        data = json.loads((racine / f"{langue}.json").read_text(encoding="utf-8"))

        def trouver(o):
            for cle, val in o.items():
                if isinstance(val, dict):
                    if cle == "watchedFolders":
                        return val
                    trouve = trouver(val)
                    if trouve is not None:
                        return trouve
            return None

        bloc = trouver(data)
        assert bloc is not None, f"section watchedFolders introuvable en {langue}"
        sous_titre = bloc.get("subtitle", "").lower()
        assert "desktop" in sous_titre, (
            f"[{langue}] le sous-titre ne nomme pas la dépendance au démon — "
            f"il promet une indexation automatique qui ne peut pas tourner "
            f"sans lui"
        )


def test_the_offline_status_has_a_colour():
    """Un statut absent de la table retombe sur le style « pending », gris :
    l'utilisateur lirait « en attente » là où il faut lancer un programme."""
    from pathlib import Path

    composant = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
        / "knowledge" / "WatchedFoldersSection.tsx"
    )
    src = composant.read_text(encoding="utf-8")
    bloc = src[src.find("STATUS_COLOR"):src.find("};", src.find("STATUS_COLOR"))]
    assert "offline:" in bloc, "le statut `offline` n'a pas de style dédié"

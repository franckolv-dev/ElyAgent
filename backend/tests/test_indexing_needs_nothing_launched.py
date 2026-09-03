# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_indexing_needs_nothing_launched.py
# @brief      L'indexation ne doit dépendre d'aucun programme à lancer.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La suite de l'enquête du 21/08 — cette fois on traite la CAUSE.

#334 a rendu l'indexation honnête : un dossier illisible le dit au lieu
d'afficher « Scan en cours… » pendant des mois. Restait la question de
Franck : « est-il obligatoire de lancer ELY Desktop ? »

Non. Deux voies, et elles se complètent :

1. LE DOSSIER MONTÉ. `ELY_INDEX_PATH` monte un dossier dans le conteneur, en
   lecture seule, AU MÊME CHEMIN ABSOLU des deux côtés. `/Users/x/Documents`
   existe alors tel quel côté backend — aucune traduction, et les citations
   RAG restent vraies. Rien à lancer, et ça survit aux redémarrages.

2. LE DÉMON. Toujours là pour les dossiers non montés : en ajouter un ne
   demande alors ni édition de compose ni redémarrage.

⚠️ ET LA CAUSE RÉELLE, TROUVÉE DANS L'INSTALLATEUR. Le bloc de démarrage
automatique de `install.sh` était sous `if [[ "$OS" == "Linux" ]]`. Windows
avait sa clé de registre dans `install.bat`, Linux son entrée XDG — **macOS
n'avait rien**. Le script finissait par `exec "$BINARY_PATH"` au premier
plan : on ferme le terminal, le démon meurt. C'est pour ça que le dossier de
Franck affichait 0 fichier depuis des mois.

Run with:  cd backend && python -m pytest tests/test_indexing_needs_nothing_launched.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────
# 1 — Le choix de la voie de lecture
# ─────────────────────────────────────────────────────────────────────

def test_a_mounted_folder_needs_no_daemon(monkeypatch, tmp_path):
    """LE pin de la demande. Un dossier lisible ici ne réclame personne."""
    from app.services import auto_indexer

    monkeypatch.setattr(
        "app.services.desktop_registry.is_connected", lambda _uid: False,
    )
    assert auto_indexer._mode_de_lecture("u", str(tmp_path)) == "local", (
        "un dossier monté doit s'indexer sans ELY Desktop — c'est tout "
        "l'intérêt du montage"
    )


def test_the_daemon_still_serves_unmounted_folders(monkeypatch):
    """Le montage ne REMPLACE pas le démon, il s'ajoute. Ajouter un dossier
    non monté ne doit demander ni édition de compose ni redémarrage."""
    from app.services import auto_indexer

    monkeypatch.setattr(
        "app.services.desktop_registry.is_connected", lambda _uid: True,
    )
    assert auto_indexer._mode_de_lecture("u", "/chemin/absent/du/conteneur") == "daemon"


def test_neither_route_available_is_offline(monkeypatch):
    """Ni monté ni servi : `offline`, et surtout pas `error`. Rien n'a
    échoué — il n'y a personne, et le geste attendu diffère."""
    from app.services import auto_indexer

    monkeypatch.setattr(
        "app.services.desktop_registry.is_connected", lambda _uid: False,
    )
    assert auto_indexer._mode_de_lecture("u", "/chemin/absent") == "offline"


def test_a_file_is_not_a_folder(tmp_path):
    """⚠️ Le défaut du montage no-op. Quand `ELY_INDEX_PATH` est vide, le
    compose monte quand même quelque chose. Si `_lisible_localement` acceptait
    n'importe quel chemin existant, un fichier passerait pour un dossier
    indexable et la marche exploserait."""
    from app.services import auto_indexer

    fichier = tmp_path / "pas_un_dossier.txt"
    fichier.write_text("x", encoding="utf-8")
    assert auto_indexer._lisible_localement(str(fichier)) is False


# ─────────────────────────────────────────────────────────────────────
# 2 — Le cron suit la même règle
# ─────────────────────────────────────────────────────────────────────

def test_the_cron_asks_the_same_question_as_the_scan():
    """⚠️ LE PIÈGE DE CE CORRECTIF, et je suis tombé dedans en l'écrivant.

    `scan_all_enabled` testait `is_connected` pour sauter les dossiers hors
    ligne. Laisser ce test aurait écarté les dossiers MONTÉS — qui n'ont
    justement pas besoin du démon — et le scan horaire n'aurait jamais rien
    indexé pour eux. On aurait remplacé une dépendance muette par une autre.
    """
    from app.services import auto_indexer

    src = inspect.getsource(auto_indexer.scan_all_enabled)
    assert "_mode_de_lecture(" in src, (
        "le cron doit interroger le mode de lecture, pas le seul démon"
    )
    assert "is_connected(" not in src, (
        "un test direct du démon dans le cron écarte les dossiers montés"
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — Le démarrage automatique, sur les trois systèmes
# ─────────────────────────────────────────────────────────────────────

def test_macos_finally_has_an_autostart():
    """LA cause du « 0 fichier indexé » de Franck.

    Le bloc était sous `if [[ "$OS" == "Linux" ]]` ; macOS n'avait rien et le
    script se terminait par un `exec` au premier plan.
    """
    src = (RACINE / "desktop" / "install.sh").read_text(encoding="utf-8")
    assert "LaunchAgents" in src and "launchctl" in src, (
        "macOS n'a toujours aucun démarrage automatique — le démon mourra "
        "avec le terminal, comme il l'a fait pendant des mois"
    )
    assert "KeepAlive" in src, (
        "sans KeepAlive le démon ne se relève pas après un plantage"
    )


def test_the_three_platforms_are_covered():
    """Windows était déjà couvert (`HKCU\\...\\Run`), Linux aussi (XDG). Ce pin
    empêche qu'un des trois reparte en silence."""
    sh = (RACINE / "desktop" / "install.sh").read_text(encoding="utf-8")
    bat = (RACINE / "desktop" / "install.bat").read_text(encoding="utf-8")

    assert "autostart" in sh, "l'entrée XDG de Linux a disparu"
    assert "LaunchAgents" in sh, "le LaunchAgent de macOS a disparu"
    assert "CurrentVersion\\Run" in bat, "la clé de registre Windows a disparu"


def test_the_installer_does_not_start_a_second_instance():
    """⚠️ Sans ce garde-fou, activer le démarrage automatique lancerait DEUX
    démons : celui de launchd et celui du `exec` final. Ils se battraient pour
    le même WebSocket, et l'utilisateur verrait des déconnexions juste après
    avoir activé l'automatisme censé les supprimer."""
    src = (RACINE / "desktop" / "install.sh").read_text(encoding="utf-8")
    assert "_autostart_installe" in src, (
        "rien n'empêche le lancement d'une seconde instance après l'installation "
        "du LaunchAgent"
    )
    pos_garde = src.find('if [[ "$_autostart_installe" == "1" ]]')
    pos_exec = src.rfind('exec "$BINARY_PATH"')
    assert pos_garde != -1 and pos_garde < pos_exec, (
        "le garde-fou doit précéder le lancement au premier plan"
    )


# ─────────────────────────────────────────────────────────────────────
# 4 — Le montage, et ce que l'interface en dit
# ─────────────────────────────────────────────────────────────────────

def test_the_mount_uses_the_same_path_on_both_sides():
    """C'est le détail qui rend le montage utilisable.

    Monter `/Users/x/Documents` sur `/host-docs` obligerait à traduire les
    chemins partout — dans la saisie, en base, et dans les citations RAG, qui
    mentiraient alors sur l'emplacement réel du fichier.
    """
    compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${ELY_INDEX_PATH:-" in compose, "le montage d'indexation a disparu"
    ligne = next(
        l for l in compose.splitlines() if l.strip().startswith("- ${ELY_INDEX_PATH")
    )
    source, cible = ligne.split(":-")[1].split("}")[0], ligne.split(":-")[2].split("}")[0]
    assert "ELY_INDEX_PATH" in ligne and ligne.count("ELY_INDEX_PATH") == 2, (
        "la variable doit servir des DEUX côtés du montage"
    )
    assert ":ro" in ligne, (
        "le montage doit être en lecture seule — Ely n'a aucune raison "
        "d'écrire dans les documents de l'utilisateur"
    )
    assert source != cible, (
        "les deux valeurs par défaut doivent différer : le no-op monte un "
        "dossier du dépôt sur une cible inutilisée"
    )


def test_the_setting_is_documented():
    """Un réglage absent de `.env.example` n'existe pas pour l'utilisateur.

    C'est exactement ce qui s'est passé avec les réglages SLM, cherchés une
    journée entière sans qu'ils soient écrits nulle part.
    """
    env = (RACINE / ".env.example").read_text(encoding="utf-8")
    debut = env.find("Indexation automatique")
    assert debut != -1, "la section d'indexation a disparu de .env.example"
    bloc = env[debut:debut + 2000]
    assert "ELY_INDEX_PATH" in bloc, "le réglage n'est pas dans sa section"
    assert "lecture seule" in bloc.lower(), (
        "la documentation doit dire que le montage est en LECTURE SEULE — "
        "c'est la propriété qui le rend plus sûr que le démon"
    )
    assert "make down" in bloc, (
        "elle doit aussi dire qu'un changement demande un redémarrage : c'est "
        "le vrai coût du montage face au démon, et le taire serait vendre "
        "l'option pour mieux qu'elle n'est"
    )


def test_the_settings_panel_offers_no_button_it_cannot_honour():
    """⚠️ La demande initiale était un bouton « Connecter ELY Desktop ».

    Une page web NE PEUT PAS lancer un programme sur la machine — c'est une
    frontière de sécurité du navigateur — et le backend est dans un conteneur,
    il ne le peut pas davantage. Un tel bouton ne saurait qu'attendre : une
    action annoncée qui n'a pas lieu, ce que l'invariant 5 interdit.

    Le panneau donne les deux vrais leviers à la place. Ce pin empêche qu'on
    « améliore » l'ergonomie en ajoutant le bouton impossible.
    """
    page = (RACINE / "frontend" / "src" / "app" / "settings" / "page.tsx")
    src = page.read_text(encoding="utf-8")
    assert "desktopOfflineAutostart" in src and "desktopOfflineMount" in src, (
        "le panneau ne propose pas les deux voies quand le démon est absent"
    )
    for langue in ("fr", "en"):
        import json
        data = json.loads(
            (RACINE / "frontend" / "messages" / f"{langue}.json").read_text(encoding="utf-8")
        )
        assert "desktopOfflineTitle" in json.dumps(data), (
            f"[{langue}] les textes du bloc « démon absent » manquent"
        )


@pytest.mark.asyncio
async def test_a_local_walk_lists_only_files(tmp_path):
    """La marche locale doit rendre des FICHIERS, chemins absolus — même
    contrat que celle du démon, sinon le filtrage d'extensions casserait."""
    from app.services import auto_indexer

    (tmp_path / "sous").mkdir()
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sous" / "b.pdf").write_text("y", encoding="utf-8")

    trouve = await auto_indexer._local_walk(str(tmp_path), recursive=True)
    assert sorted(Path(p).name for p in trouve) == ["a.txt", "b.pdf"]
    assert all(Path(p).is_absolute() for p in trouve)

    plat = await auto_indexer._local_walk(str(tmp_path), recursive=False)
    assert [Path(p).name for p in plat] == ["a.txt"], (
        "sans récursif, on ne descend pas dans les sous-dossiers"
    )

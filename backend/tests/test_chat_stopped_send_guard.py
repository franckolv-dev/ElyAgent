# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_chat_stopped_send_guard.py
# @brief      Incident prod 2026-07-18 — send "stopped" sur socket déjà fermée
#             loggé en ERROR + traceback. Pin le try/except ciblé autour de la
#             paire stopped/done du chemin d'interruption.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Régression — bruit ERROR quand le client coupe pendant un tour.

Symptôme (prod, 2026-07-18 13:38:53 UTC) :
  le client perd le réseau pendant qu'un tour est en cours. Le watcher
  ``_watch_for_stop()`` prend une exception sur ``receive_text()`` et set
  ``stop_event``. La branche ``was_stopped`` tente alors d'envoyer
  ``{"type": "stopped"}`` sur la socket fermée →
  ``RuntimeError: Unexpected ASGI message 'websocket.send', after sending
  'websocket.close'`` → remonte au ``except Exception`` générique du
  handler → loggé ERROR avec traceback. Bruit purement cosmétique : la
  socket est morte, il n'y a personne à prévenir.

Fix :
  la paire stopped/done du chemin d'interruption est entourée d'un
  try/except ciblé ``(RuntimeError, WebSocketDisconnect)`` → ``logger.debug``.

Même approche que test_chat_done_event.py : on pin le contrat en grepant
la source — un round-trip WS complet exigerait un faux graphe agent,
hors scope (cf. docstring de test_chat_done_event.py).
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _stopped_branch_window() -> str:
    """Le corps de la branche `was_stopped` (+ un peu de suite), où vivent
    les deux sends du chemin de cleanup."""
    src = (_REPO / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    marker = "if was_stopped:"
    assert marker in src, "la branche d'interruption `was_stopped` a disparu de chat.py"
    idx = src.index(marker)
    return src[idx:idx + 1000]


def test_stopped_and_done_sends_are_guarded() -> None:
    """Les DEUX sends du chemin de cleanup (stopped puis done) doivent être
    dans un try dont le except cible (RuntimeError, WebSocketDisconnect) —
    pas un except large — et logge en debug, pas en error."""
    window = _stopped_branch_window()
    stopped_send = '_dumps({"type": "stopped"})'
    done_send = '_dumps({"type": "done"})'
    guard = "except (RuntimeError, WebSocketDisconnect)"

    assert stopped_send in window, "le send `stopped` doit rester dans la branche"
    assert done_send in window, "le send `done` doit rester apparié au `stopped`"
    assert "try:" in window, "les sends stopped/done doivent être sous un try"
    assert guard in window, (
        "le except doit rester ciblé (RuntimeError, WebSocketDisconnect) — "
        "pas un except Exception qui masquerait de vrais bugs d'envoi"
    )

    # Ordre attendu : try < stopped < done < except — c.-à-d. la paire
    # ENTIÈRE dans le bloc gardé (si `stopped` passe mais que la socket
    # meurt avant `done`, on ne veut pas non plus d'ERROR).
    i_try = window.index("try:")
    i_stopped = window.index(stopped_send)
    i_done = window.index(done_send)
    i_except = window.index(guard)
    assert i_try < i_stopped < i_done < i_except, (
        "la paire stopped/done doit être entièrement dans le bloc try gardé"
    )
    assert "logger.debug" in window[i_except:i_except + 400], (
        "socket déjà fermée = bruit cosmétique → logger.debug, pas ERROR"
    )

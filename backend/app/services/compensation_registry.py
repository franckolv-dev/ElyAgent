# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/compensation_registry.py
# @brief      Registre des compensations — l'exécuteur derrière le champ
#             `CapabilityManifest.compensation` (jusqu'ici une simple string).
# @license    MIT
# =============================================================================
"""Registre de compensations du Reversible Action Journal (substrat / J1).

Le manifeste d'une capacité déclare une *référence* de compensation (ex.
``"restore_from_trash"``). Ce module résout cette référence vers du code réel :

* ``capture(args, result)`` — extrait le MINIMUM nécessaire à l'annulation
  (des identifiants, jamais un secret ni un corps de message) au moment où
  l'action réussit ;
* ``revert(compensation_args, user_id)`` — exécute l'opération inverse à la
  demande d'annulation, en re-résolvant les droits de l'utilisateur (les creds
  ne transitent jamais par le journal).

V1 : une seule famille, l'**opération inverse** (sans snapshot préalable) — la
corbeille Drive EST le snapshot. La compensation par snapshot (update/rename)
viendra en J3.

« Annuler partout » (audit du 02/09/2026)
-----------------------------------------
L'audit a mesuré la promesse du README : TROIS compensations, toutes sur Drive,
sur deux cents outils. Ce module couvre désormais les écritures dont l'inverse
est FIDÈLE — pas une de plus. Trois règles ont décidé de chaque ajout :

1. **Fidélité ou rien.** Une annulation qui ne restaure pas exactement est PIRE
   que pas d'annulation : elle fait croire que c'est défait. Elle exclut
   ``gmail_trash_by_query`` et ``gmail_trash_by_category`` (ils retirent
   ``INBOX`` sans dire quels messages l'avaient), ``sheets_append_rows`` (son
   retour ne dit pas QUELLES lignes ont été écrites), et ``gmail_mark_read`` /
   ``gmail_mark_unread`` (remettre ``UNREAD`` sur tout le lot inventerait un
   état pour les messages déjà lus ; la version fidèle demanderait une lecture
   d'API par message AVANT l'action, sur le chemin chaud).
   C'est aussi elle qui borne les captures : un lot Gmail partiellement trashé
   n'est PAS journalisé, et un ``drive_create_folder`` qui a RÉUTILISÉ un
   dossier existant non plus.
2. **Minimisation.** Le journal ne retient que des IDENTIFIANTS. C'est ce qui
   exclut ``calendar_delete_event``, ``calendar_update_event``,
   ``notes_update``, ``tasks_update``, ``contacts_update`` et
   ``drive_update_file`` : les restaurer fidèlement demanderait de stocker le
   titre, le corps, les invités — du contenu et de la PII, dans une table qui
   vit sept jours.
3. **Frontière du tiers.** Ce qu'un tiers a vu ne se défait pas
   (``gmail_send_email``, cf. son manifeste ; ``calendar_create_meet_event``,
   dont la suppression enverrait une annulation aux invités ;
   ``drive_share_file``).
4. **L'annulation elle-même doit être rattrapable.** Défaire une création,
   c'est supprimer — donc mieux vaut que la suppression atterrisse quelque part
   de récupérable. La corbeille Drive, le statut ``cancelled`` de l'Agenda, le
   ``deleted`` de Tasks et la corbeille Contacts le sont. ``drafts.delete``
   (Gmail) et la suppression d'un onglet ou d'une liste de tâches ne le sont
   pas : ``gmail_create_draft``, ``sheets_add_sheet`` et
   ``tasks_create_tasklist`` restent donc sans compensation, car une annulation
   tardive détruirait sans recours ce que l'utilisateur y aurait mis depuis.

⚠️ Les outils d'Ely rendent du TEXTE FRANÇAIS formaté pour le modèle, pas du
JSON. Quand l'identifiant n'existe que dans ce texte, la capture est ancrée sur
le marqueur exact émis par la branche de SUCCÈS de l'outil (préfixe + ligne
``ID``), et sur la DERNIÈRE occurrence quand un nom choisi par le modèle
précède le marqueur — sinon un nom de fichier contenant « \\nID : autre » ferait
désigner la ressource de quelqu'un d'autre. Si rien ne matche, la capture rend
``{}`` : pas d'entrée au journal plutôt qu'une annulation qui vise à côté.

La règle des SEPT JOURS (relecture sceptique du 02/09/2026)
-----------------------------------------------------------
La fenêtre d'annulation dure une semaine : entre l'action et le clic, tout a pu
changer. La règle 4 ci-dessus (« une annulation tardive ne doit pas détruire
sans recours ce que l'utilisateur y aurait mis depuis ») ne suffit donc pas à
choisir QUOI couvrir — elle doit aussi s'appliquer à l'intérieur de chaque
compensation. Tout revert qui SUPPRIME relit sa cible et **refuse** si elle
n'est plus celle qu'Ely a créée : une note écrite depuis, un libellé qui classe
des messages, un événement qui a gagné des invités. Le refus lève
``CompensationRefused``, que ``journal_service.undo`` traduit en état
``revert_failed`` — un échec nommé, pas une erreur opaque, et surtout pas une
destruction.

⚠️ TROUS CONNUS, à écrire plutôt qu'à taire
--------------------------------------------
1. **Un outil qui bascule en tâche de fond n'entre PAS au journal.** Au-delà du
   délai souple, la passerelle rend la main AVANT d'atteindre l'enregistrement,
   et le chemin de livraison ne le rattrape pas : la ressource est bien créée,
   mais rien n'est annulable et rien ne le dit. Ça vise en premier les gros
   fichiers — ``drive_upload_local_file`` et ``drive_copy_file``. Le correctif
   est dans la passerelle, pas ici.
2. **Le mode snapshot journalise sans avoir vu le résultat de l'outil.** Les
   outils d'Ely ne lèvent pas : ils rendent « Erreur … » en texte, et la
   passerelle prend quand même la branche de succès. Une action ÉCHOUÉE peut
   donc apparaître dans la liste « Annuler ». Le filtre manquant est à
   l'enregistrement (``journal_service.record_reversible``) ; en attendant,
   ``restore_task_status`` refuse au revert si la tâche n'est pas dans l'état
   que l'action prétend avoir produit. ``restore_name`` et ``restore_parents``
   (J3) n'ont pas ce garde-fou : une entrée fantôme y rejouerait un ancien nom
   ou un ancien dossier.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class CompensationRefused(RuntimeError):
    """L'annulation est REFUSÉE : l'exécuter détruirait autre chose que l'action
    journalisée (relecture du 02/09/2026).

    Ce n'est pas une panne. ``journal_service.undo`` la traite comme n'importe
    quel échec de revert — l'entrée passe en ``revert_failed`` et la surface
    d'annulation reçoit ``{"ok": False, "reason": "revert_failed",
    "error": "CompensationRefused"}``. La cible, elle, n'a pas bougé."""


@dataclass(frozen=True)
class Compensation:
    name: str
    revert: Callable[[dict, str], Awaitable[None]]    # (comp_args, user_id) -> exécute l'inverse
    # Mode « opération inverse » (J1) : capture l'état utile APRÈS succès (ids only).
    capture: Optional[Callable[[dict, str], dict]] = None        # (args, result) -> comp_args
    # (J4) Confirme que l'annulation a RÉELLEMENT pris (ex. fichier hors corbeille).
    # Optionnel, best-effort : (comp_args, user_id) -> True si vérifié.
    verify: Optional[Callable[[dict, str], Awaitable[bool]]] = None
    # (J3) Mode « snapshot » : capture l'état AVANT exécution (rename/move…, où
    # l'état d'avant est perdu après l'action). (args, user_id) -> snapshot dict.
    # Exclusif de `capture` : si `snapshot` est présent, c'est lui qui alimente
    # compensation_args (pré-exécution), via le hook de tool_node.
    snapshot: Optional[Callable[[dict, str], Awaitable[dict]]] = None


async def _creds_for_user(user_id: str) -> str:
    """Creds Google de l'utilisateur, par user_id (même chemin que tool_node).

    Le journal ne stocke jamais de creds : on les re-résout à l'annulation.
    """
    from app.services.credential_store import get_credential_store

    store = get_credential_store()
    creds = store.get(user_id) or ""
    if not creds and user_id:
        try:
            from app.database import async_session
            from app.models.user import User
            async with async_session() as db:
                u = await db.get(User, user_id)
                if u and getattr(u, "google_credentials", None):
                    creds = u.google_credentials
                    store.set(user_id, creds)
        except Exception as exc:  # pragma: no cover — défensif
            logger.debug("creds DB fallback failed for %s: %s", (user_id or "")[:8], exc)
    return creds


async def _drive_untrash(comp_args: dict, user_id: str) -> None:
    """Opération inverse de ``drive_delete_file`` : sortir le fichier de la
    corbeille (``trashed=False``). ``drive_delete_file`` ne fait que trasher
    (``trashed=True``), donc le fichier est récupérable tant que la corbeille
    n'a pas été purgée."""
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        raise ValueError("compensation_args sans file_id")
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service

    service = await _get_drive_service(creds)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    # .execute() est bloquant (client Google sync) — on suit le pattern des
    # autres outils Drive (drive_tool.py appelle .execute() de la même façon).
    service.files().update(fileId=file_id, body={"trashed": False}).execute()


async def _drive_is_untrashed(comp_args: dict, user_id: str) -> bool:
    """(J4) Vérifie que le fichier est bien ressorti de la corbeille (trashed=False).

    Best-effort : si on ne peut pas lire l'état, on renvoie False (= non confirmé,
    pas une erreur) plutôt que de prétendre que tout va bien."""
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        return False
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service

    service = await _get_drive_service(creds)
    if not service:
        return False
    meta = service.files().get(fileId=file_id, fields="trashed").execute()
    return meta.get("trashed") is False


# ── Compensations par SNAPSHOT (J3) : capturer l'état AVANT, restaurer après ──
# Pour rename/move, l'état d'avant (nom / dossier parent) est PERDU après
# l'action → on le lit juste avant l'exécution (hook tool_node) et on le rejoue.


async def _drive_service(user_id: str):
    """Service Drive de l'utilisateur (creds re-résolus par user_id), ou None."""
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service
    return await _get_drive_service(creds)


# --- drive_rename_file : snapshot = ancien nom ---
async def _drive_snapshot_name(args: dict, user_id: str) -> dict:
    file_id = (args or {}).get("file_id")
    if not file_id:
        return {}
    service = await _drive_service(user_id)
    if not service:
        return {}
    meta = service.files().get(fileId=file_id, fields="name").execute()
    return {"file_id": file_id, "name": meta.get("name")}


async def _drive_restore_name(snap: dict, user_id: str) -> None:
    file_id = (snap or {}).get("file_id")
    name = (snap or {}).get("name")
    if not file_id or name is None:
        raise ValueError("snapshot incomplet (file_id/name)")
    service = await _drive_service(user_id)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    service.files().update(fileId=file_id, body={"name": name}).execute()


async def _drive_verify_name(snap: dict, user_id: str) -> bool:
    file_id = (snap or {}).get("file_id")
    if not file_id:
        return False
    service = await _drive_service(user_id)
    if not service:
        return False
    meta = service.files().get(fileId=file_id, fields="name").execute()
    return meta.get("name") == (snap or {}).get("name")


# --- drive_move_file : snapshot = anciens parents ---
async def _drive_snapshot_parents(args: dict, user_id: str) -> dict:
    file_id = (args or {}).get("file_id")
    if not file_id:
        return {}
    service = await _drive_service(user_id)
    if not service:
        return {}
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    return {"file_id": file_id, "parents": meta.get("parents", [])}


async def _drive_restore_parents(snap: dict, user_id: str) -> None:
    file_id = (snap or {}).get("file_id")
    old = (snap or {}).get("parents") or []
    if not file_id or not old:
        raise ValueError("snapshot incomplet (file_id/parents)")
    service = await _drive_service(user_id)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    cur = service.files().get(fileId=file_id, fields="parents").execute().get("parents", [])
    service.files().update(
        fileId=file_id,
        addParents=",".join(old),
        removeParents=",".join(cur),
        fields="id,parents",
    ).execute()


async def _drive_verify_parents(snap: dict, user_id: str) -> bool:
    file_id = (snap or {}).get("file_id")
    if not file_id:
        return False
    service = await _drive_service(user_id)
    if not service:
        return False
    cur = set(service.files().get(fileId=file_id, fields="parents").execute().get("parents", []))
    return cur == set((snap or {}).get("parents") or [])


# ── Lire un identifiant dans le retour TEXTE d'un outil (02/09/2026) ─────────
# Les outils de création d'Ely finissent par une ligne « ID : <id> » (Drive,
# Sheets, Docs, Agenda) ou par « (ID: <id>) » en fin de chaîne (Tasks, libellé
# Gmail). La classe de caractères borne ce qu'un identifiant Google peut être :
# une valeur exotique ne matche pas, donc rien n'est journalisé.
_ID_LINE = re.compile(r"^[ \t]*ID\s*:\s*([A-Za-z0-9_@.\-]{3,256})\s*$", re.MULTILINE)
_TRAILING_ID = re.compile(r"\(ID:\s*([A-Za-z0-9_@.\-]{3,256})\)\s*$")
_TRAILING_LABEL_ID = re.compile(r"\(id:\s*([A-Za-z0-9_@.\-]{3,256})\)\s*$")
_RESOURCE_LINE = re.compile(r"^resourceName:\s*(people/[A-Za-z0-9_\-]{2,128})\s*$", re.MULTILINE)

# Les cinq outils qui font NAÎTRE un fichier Drive. Créer, téléverser et copier
# produisent le même objet, donc le même inverse : la mise à la corbeille — d'où
# le fichier reste récupérable, y compris par `restore_from_trash`. Chacun
# annonce son succès par un préfixe qui lui est propre, et c'est ce préfixe qui
# distingue le succès de l'erreur, jamais la présence d'un identifiant.
_DRIVE_CREATED_PREFIXES = (
    "Fichier créé",                  # drive_create_file
    "Fichier téléversé sur Drive",   # drive_upload_local_file
    "✓ Copie créée",                 # drive_copy_file
    "Feuille de calcul créée",       # sheets_create_spreadsheet
    "Document créé",                 # docs_create_document
)


def _last_id_line(result: str) -> str | None:
    """DERNIÈRE ligne ``ID : …``. Le nom de la ressource, choisi par le modèle,
    est imprimé AVANT ; prendre la dernière neutralise un nom qui imiterait le
    marqueur pour faire désigner un autre fichier."""
    found = _ID_LINE.findall(result or "")
    return found[-1] if found else None


def _is_gone(exc: Exception) -> bool:
    """La ressource n'existe plus. À distinguer d'une panne (5xx), qui ne doit
    JAMAIS être lue comme « c'est bien supprimé ».

    404 ET 410 : les API Google répondent aussi *Gone* sur une ressource déjà
    supprimée (un événement d'agenda effacé par l'utilisateur lui-même, par
    exemple). Ne reconnaître que le 404 rendait un échec alors que l'état visé
    était atteint (relecture du 02/09/2026)."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    return status in (404, 410)


async def _google_service(user_id: str, module: str, getter: str):
    """Service Google de l'utilisateur (creds re-résolus par user_id), ou None."""
    creds = await _creds_for_user(user_id)
    mod = __import__(f"app.agent.tools.{module}", fromlist=[getter])
    return await getattr(mod, getter)(creds)


def _require(service, quoi: str):
    if not service:
        raise RuntimeError(f"Google non connecté — {quoi} impossible")
    return service


# --- gmail_trash_emails : corbeille → hors corbeille -------------------------
# La corbeille Gmail EST le snapshot : ``messages.trash`` pose le libellé TRASH
# et ``messages.untrash`` le retire, les autres libellés (INBOX compris) sont
# conservés de bout en bout. C'est le seul outil de mise à la corbeille d'Ely
# dont on connaisse les identifiants : les deux variantes en masse
# (``gmail_trash_by_query`` / ``_by_category``) les calculent en interne, ne les
# rendent pas, ET retirent INBOX explicitement — leur inverse ne serait pas
# fidèle pour un message archivé ou en spam. Elles restent non annulables.
#
# Le journal borne compensation_args à 4 Ko : au-delà, le JSON serait TRONQUÉ
# et illisible à l'annulation. On refuse donc de promettre un gros lot plutôt
# que d'en annuler la moitié.
_MAX_TRASHED_IDS = 120


# `gmail_trash_emails` trashe message par message et résume « k/n ». Un lot
# PARTIEL ne dit pas LESQUELS sont partis (la liste d'erreurs est tronquée à
# trois) : sortir les n de la corbeille en ferait ressortir ceux que
# l'utilisateur y avait mis LUI-MÊME, c'est-à-dire défaire autre chose que
# l'action journalisée. On n'annule donc que le lot parti en entier.
_TRASH_DONE = re.compile(r"^🗑️\s*(\d+)\s*/\s*(\d+)\s+email\(s\) envoyés à la corbeille\.")


def _capture_message_ids(args: dict, result: str) -> dict:
    ids = [str(i) for i in ((args or {}).get("email_ids") or []) if i]
    if not ids or len(ids) > _MAX_TRASHED_IDS:
        return {}
    m = _TRASH_DONE.match(result or "")
    if not m or m.group(1) != m.group(2) or int(m.group(2)) != len(ids):
        return {}
    return {"message_ids": ids}


async def _gmail_untrash(comp_args: dict, user_id: str) -> None:
    ids = (comp_args or {}).get("message_ids") or []
    if not ids:
        raise ValueError("compensation_args sans message_ids")
    service = _require(await _google_service(user_id, "gmail_tool", "_get_gmail_service"), "restauration")
    echecs = 0
    for mid in ids:
        try:
            service.users().messages().untrash(userId="me", id=mid).execute()
        except Exception as exc:
            echecs += 1
            logger.debug("untrash a échoué pour %s: %s", mid, exc)
    # Un message qui n'avait pas pu être trashé fait échouer son untrash sans
    # que rien ne soit cassé ; c'est l'échec TOTAL qui signale une vraie panne.
    if echecs == len(ids):
        raise RuntimeError(f"aucun message n'a pu sortir de la corbeille ({echecs})")


async def _gmail_is_untrashed(comp_args: dict, user_id: str) -> bool:
    ids = (comp_args or {}).get("message_ids") or []
    if not ids:
        return False
    service = await _google_service(user_id, "gmail_tool", "_get_gmail_service")
    if not service:
        return False
    for mid in ids:
        meta = service.users().messages().get(
            userId="me", id=mid, format="minimal", fields="labelIds",
        ).execute()
        if "TRASH" in (meta.get("labelIds") or []):
            return False
    return True


# --- gmail_create_label : libellé créé → libellé supprimé --------------------
# La branche « existe déjà » ne matche pas le marqueur : on ne supprime jamais
# un libellé qu'Ely n'a pas créé, ce serait détruire le classement de
# l'utilisateur.
def _capture_created_label(args: dict, result: str) -> dict:
    if not (result or "").startswith("Label '"):
        return {}
    m = _TRAILING_LABEL_ID.search(result)
    return {"label_id": m.group(1)} if m else {}


async def _gmail_delete_label(comp_args: dict, user_id: str) -> None:
    """Supprime le libellé — SEULEMENT s'il est resté vide.

    ⚠️ ``labels.delete`` est immédiat, définitif, et retire le libellé de TOUS
    les messages qui le portent : il n'y a pas de corbeille pour un libellé. La
    capture garantit qu'Ely l'a créé, pas qu'il soit encore vide sept jours plus
    tard. Si l'utilisateur a classé 800 messages dedans, « Annuler » effacerait
    ce classement sans recours — même cas que l'onglet de tableur, que ce lot
    exclut pour cette raison (relecture du 02/09/2026)."""
    label_id = (comp_args or {}).get("label_id")
    if not label_id:
        raise ValueError("compensation_args sans label_id")
    service = _require(await _google_service(user_id, "gmail_tool", "_get_gmail_service"), "suppression")
    try:
        label = service.users().labels().get(userId="me", id=label_id).execute() or {}
    except Exception as exc:
        if _is_gone(exc):
            return  # déjà supprimé : l'état visé est atteint
        raise
    classes = int(label.get("messagesTotal") or 0) + int(label.get("threadsTotal") or 0)
    if classes:
        raise CompensationRefused(
            f"le libellé classe {classes} élément(s) depuis sa création — suppression refusée"
        )
    try:
        service.users().labels().delete(userId="me", id=label_id).execute()
    except Exception as exc:
        if not _is_gone(exc):
            raise


async def _gmail_label_is_gone(comp_args: dict, user_id: str) -> bool:
    label_id = (comp_args or {}).get("label_id")
    if not label_id:
        return False
    service = await _google_service(user_id, "gmail_tool", "_get_gmail_service")
    if not service:
        return False
    try:
        service.users().labels().get(userId="me", id=label_id).execute()
    except Exception as exc:
        if _is_gone(exc):
            return True
        raise
    return False


# --- calendar_create_event : événement créé → événement supprimé -------------
# L'inverse d'une création est exact et ne demande RIEN à retenir d'autre que
# l'id — c'est pour ça que la création est couverte et pas la suppression :
# recréer un événement supprimé exigerait d'avoir stocké son titre, sa
# description et ses invités, donc du contenu et de la PII.
# ⚠️ Seul ``calendar_create_event`` est couvert. ``calendar_create_meet_event``
# invite des tiers : sa suppression leur enverrait une annulation, ce qui
# retombe du côté « vu par un tiers » de la frontière.
def _capture_created_event(args: dict, result: str) -> dict:
    if not (result or "").startswith("Événement créé"):
        return {}
    event_id = _last_id_line(result)
    return {"event_id": event_id} if event_id else {}


async def _calendar_delete_event(comp_args: dict, user_id: str) -> None:
    """Supprime l'événement — sans notifier personne, et seulement s'il est resté
    solitaire.

    ``calendar_create_event`` ne pose JAMAIS d'invités, mais sept jours passent :
    l'utilisateur (ou ``calendar_update_event``) a pu en ajouter. L'événement
    retombe alors du côté « vu par un tiers » de la frontière, et le supprimer
    enverrait une annulation à des gens qu'Ely n'a pas invités. On refuse.
    ``sendUpdates="none"`` est explicite parce que le défaut de l'API n'est pas
    un contrat : on ne veut aucun courriel émis par une annulation, jamais
    (relecture du 02/09/2026)."""
    event_id = (comp_args or {}).get("event_id")
    if not event_id:
        raise ValueError("compensation_args sans event_id")
    service = _require(
        await _google_service(user_id, "calendar_tool", "_get_calendar_service"), "suppression",
    )
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute() or {}
    except Exception as exc:
        # L'état visé EST « l'événement n'existe plus » : un 404/410 l'atteint déjà.
        if _is_gone(exc):
            return
        raise
    if event.get("status") == "cancelled":
        return  # déjà supprimé
    # `self: True` = le propriétaire de l'agenda, que Google ajoute à la liste
    # dès qu'il y a un invité. Ce sont les AUTRES qui posent la frontière.
    tiers = [a for a in (event.get("attendees") or []) if not a.get("self")]
    if tiers:
        raise CompensationRefused(
            f"l'événement compte {len(tiers)} invité(s) depuis sa création — suppression refusée"
        )
    try:
        service.events().delete(
            calendarId="primary", eventId=event_id, sendUpdates="none",
        ).execute()
    except Exception as exc:
        if not _is_gone(exc):
            raise


async def _calendar_event_is_gone(comp_args: dict, user_id: str) -> bool:
    event_id = (comp_args or {}).get("event_id")
    if not event_id:
        return False
    service = await _google_service(user_id, "calendar_tool", "_get_calendar_service")
    if not service:
        return False
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
    except Exception as exc:
        if _is_gone(exc):
            return True
        raise
    # L'Agenda conserve les événements supprimés en statut « cancelled ».
    return event.get("status") == "cancelled"


# --- créations de fichiers Drive (Drive / Sheets / Docs) → corbeille ---------
def _capture_created_drive_file(args: dict, result: str) -> dict:
    if not (result or "").startswith(_DRIVE_CREATED_PREFIXES):
        return {}
    file_id = _last_id_line(result)
    return {"file_id": file_id} if file_id else {}


def _capture_created_drive_folder(args: dict, result: str) -> dict:
    """⚠️ ``drive_create_folder`` est IDEMPOTENT depuis le 04/06/2026 : il
    RÉUTILISE un dossier de même nom au lieu d'en créer un doublon, et rend
    alors l'id d'un dossier PRÉEXISTANT. Le mettre à la corbeille détruirait ce
    qu'Ely n'a pas créé — seule la branche « Dossier créé » est annulable."""
    if not (result or "").startswith("Dossier créé"):
        return {}
    file_id = _last_id_line(result)
    return {"file_id": file_id} if file_id else {}


async def _drive_trash(comp_args: dict, user_id: str) -> None:
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        raise ValueError("compensation_args sans file_id")
    service = _require(await _drive_service(user_id), "mise à la corbeille")
    service.files().update(fileId=file_id, body={"trashed": True}).execute()


async def _drive_is_trashed(comp_args: dict, user_id: str) -> bool:
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        return False
    service = await _drive_service(user_id)
    if not service:
        return False
    meta = service.files().get(fileId=file_id, fields="trashed").execute()
    return meta.get("trashed") is True


# --- tasks_create : tâche créée → tâche supprimée ---------------------------
# ``tasks_create`` écrit toujours dans « @default » (pas de paramètre de liste)
# — le revert vise donc la même liste.
def _capture_created_task(args: dict, result: str) -> dict:
    if not (result or "").startswith("Tâche créée"):
        return {}
    m = _TRAILING_ID.search(result)
    return {"task_id": m.group(1)} if m else {}


async def _tasks_delete(comp_args: dict, user_id: str) -> None:
    task_id = (comp_args or {}).get("task_id")
    if not task_id:
        raise ValueError("compensation_args sans task_id")
    service = _require(await _google_service(user_id, "tasks_tool", "_get_tasks_service"), "suppression")
    try:
        service.tasks().delete(tasklist="@default", task=task_id).execute()
    except Exception as exc:
        if not _is_gone(exc):
            raise


async def _tasks_is_gone(comp_args: dict, user_id: str) -> bool:
    task_id = (comp_args or {}).get("task_id")
    if not task_id:
        return False
    service = await _google_service(user_id, "tasks_tool", "_get_tasks_service")
    if not service:
        return False
    try:
        task = service.tasks().get(tasklist="@default", task=task_id).execute()
    except Exception as exc:
        if _is_gone(exc):
            return True
        raise
    return bool(task.get("deleted"))


# --- tasks_complete : terminée → à faire (mode instantané) ------------------
# Le statut d'avant est perdu par l'action, d'où le snapshot. Une tâche DÉJÀ
# terminée rend un instantané vide : la rouvrir inventerait un état qui n'a
# jamais existé. On ne retient qu'un id et deux valeurs d'énumération.
_TASK_DONE = "completed"


async def _tasks_snapshot_status(args: dict, user_id: str) -> dict:
    task_id = (args or {}).get("task_id")
    if not task_id:
        return {}
    service = await _google_service(user_id, "tasks_tool", "_get_tasks_service")
    if not service:
        return {}
    status = (service.tasks().get(tasklist="@default", task=task_id).execute() or {}).get("status")
    if status != "needsAction":
        return {}
    # `expected_status` = ce que l'action PRÉTEND avoir produit. Le mode
    # instantané journalise avant de connaître le résultat de l'outil (cf. trou
    # connu n°2) ; c'est ce témoin qui permet au revert de s'en apercevoir.
    return {"task_id": task_id, "status": status, "expected_status": _TASK_DONE}


async def _tasks_restore_status(snap: dict, user_id: str) -> None:
    """Rouvre la tâche — seulement si elle est bien terminée aujourd'hui.

    Deux cas font diverger l'état : l'action a ÉCHOUÉ (les outils d'Ely rendent
    « Erreur … » en texte, la journalisation ne le voit pas), ou l'utilisateur a
    rouvert puis terminé la tâche lui-même pendant la semaine. Dans les deux
    cas, patcher détruirait son geste au lieu de défaire celui d'Ely
    (relecture du 02/09/2026)."""
    task_id = (snap or {}).get("task_id")
    status = (snap or {}).get("status")
    if not task_id or not status:
        raise ValueError("snapshot incomplet (task_id/status)")
    service = _require(await _google_service(user_id, "tasks_tool", "_get_tasks_service"), "restauration")
    attendu = (snap or {}).get("expected_status")
    # Instantané sans témoin = version antérieure au garde-fou : on refuse
    # plutôt que de rouvrir à l'aveugle.
    actuel = (service.tasks().get(tasklist="@default", task=task_id).execute() or {}).get("status")
    if actuel != attendu:
        raise CompensationRefused(
            f"la tâche n'est pas dans l'état attendu ({actuel!r} ≠ {attendu!r}) — réouverture refusée"
        )
    service.tasks().patch(tasklist="@default", task=task_id, body={"status": status}).execute()


async def _tasks_status_restored(snap: dict, user_id: str) -> bool:
    task_id = (snap or {}).get("task_id")
    if not task_id:
        return False
    service = await _google_service(user_id, "tasks_tool", "_get_tasks_service")
    if not service:
        return False
    task = service.tasks().get(tasklist="@default", task=task_id).execute() or {}
    return task.get("status") == (snap or {}).get("status")


# --- contacts_create : contact créé → contact supprimé ----------------------
# On ne retient que le ``resourceName`` (people/cNNN) : ni le nom, ni le
# courriel, ni le téléphone n'entrent au journal.
def _capture_created_contact(args: dict, result: str) -> dict:
    if not (result or "").startswith("Contact créé"):
        return {}
    found = _RESOURCE_LINE.findall(result)
    return {"resource_name": found[-1]} if found else {}


async def _contacts_delete(comp_args: dict, user_id: str) -> None:
    resource = (comp_args or {}).get("resource_name")
    if not resource:
        raise ValueError("compensation_args sans resource_name")
    service = _require(
        await _google_service(user_id, "contacts_tool", "_get_people_service"), "suppression",
    )
    try:
        service.people().deleteContact(resourceName=resource).execute()
    except Exception as exc:
        if not _is_gone(exc):
            raise


async def _contacts_is_gone(comp_args: dict, user_id: str) -> bool:
    resource = (comp_args or {}).get("resource_name")
    if not resource:
        return False
    service = await _google_service(user_id, "contacts_tool", "_get_people_service")
    if not service:
        return False
    try:
        service.people().get(resourceName=resource, personFields="names").execute()
    except Exception as exc:
        if _is_gone(exc):
            return True
        raise
    return False


# --- notes_create : note créée → note supprimée (base d'Ely) ----------------
# Ici l'id est en TÊTE du retour et le contenu de la note suit : c'est donc la
# PREMIÈRE ligne « ID: » qui fait foi (un contenu qui imiterait le marqueur
# arrive forcément après).
def _capture_created_note(args: dict, result: str) -> dict:
    if not (result or "").startswith("Note créée"):
        return {}
    m = _ID_LINE.search(result)
    return {"note_id": m.group(1)} if m else {}


# `created_at` et `updated_at` sont deux appels SÉPARÉS à l'horloge au moment de
# l'insertion : ils diffèrent de quelques microsecondes sur une note jamais
# touchée. La tolérance absorbe cet écart, rien d'autre — une édition humaine en
# moins de deux secondes après la création n'existe pas.
_NOTE_INSERT_SKEW = timedelta(seconds=2)


def _as_utc(dt: datetime) -> datetime:
    """SQLite rend souvent du naïf — on normalise avant toute soustraction."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _note_a_ete_etoffee(note) -> bool:
    """La note a-t-elle changé depuis qu'Ely l'a écrite ?

    Sans horodatage lisible, on répond OUI : le doute doit protéger le contenu,
    pas autoriser la suppression."""
    cree = getattr(note, "created_at", None)
    modifie = getattr(note, "updated_at", None)
    if cree is None or modifie is None:
        return True
    return (_as_utc(modifie) - _as_utc(cree)) > _NOTE_INSERT_SKEW


async def _notes_delete(comp_args: dict, user_id: str) -> None:
    """Supprime la note — seulement si personne n'a écrit dedans depuis.

    ⚠️ Le modèle ``Note`` n'a NI corbeille NI suppression douce : c'est un
    ``DELETE`` sans recours. Un outil de mise à jour existe, et la fenêtre
    d'annulation dure SEPT JOURS. Une note créée par Ely puis étoffée par
    l'utilisateur pendant six jours ne doit pas disparaître d'un clic sur la
    ligne de création — c'est exactement le cas qui a fait exclure
    ``gmail_create_draft``, ``sheets_add_sheet`` et ``tasks_create_tasklist``
    (relecture du 02/09/2026).

    On garde quand même la compensation : une note INTACTE ne contient que ce
    qu'Ely vient d'y écrire, et c'est la seule capacité purement locale du lot."""
    note_id = (comp_args or {}).get("note_id")
    if not note_id:
        raise ValueError("compensation_args sans note_id")
    from app.database import async_session
    from app.models.note import Note

    async with async_session() as db:
        note = await db.get(Note, note_id)
        if note is None:
            return  # déjà absente : l'état visé est atteint
        if note.user_id != user_id:
            raise PermissionError("note appartenant à un autre utilisateur")
        if _note_a_ete_etoffee(note):
            raise CompensationRefused(
                "la note a été modifiée depuis sa création — suppression refusée"
            )
        await db.delete(note)
        await db.commit()


async def _notes_is_gone(comp_args: dict, user_id: str) -> bool:
    note_id = (comp_args or {}).get("note_id")
    if not note_id:
        return False
    from app.database import async_session
    from app.models.note import Note

    async with async_session() as db:
        return await db.get(Note, note_id) is None


_REGISTRY: dict[str, Compensation] = {
    "restore_from_trash": Compensation(
        name="restore_from_trash",
        # On ne retient QUE l'id du fichier (minimisation — pas de PII/secret).
        capture=lambda args, result: {"file_id": (args or {}).get("file_id")},
        revert=_drive_untrash,
        verify=_drive_is_untrashed,
    ),
    "restore_name": Compensation(
        name="restore_name",
        snapshot=_drive_snapshot_name,     # capture l'ancien nom AVANT le rename
        revert=_drive_restore_name,
        verify=_drive_verify_name,
    ),
    "restore_parents": Compensation(
        name="restore_parents",
        snapshot=_drive_snapshot_parents,  # capture les anciens parents AVANT le move
        revert=_drive_restore_parents,
        verify=_drive_verify_parents,
    ),
    # ── « Annuler partout » (02/09/2026) ─────────────────────────────────────
    "untrash_messages": Compensation(
        name="untrash_messages",
        capture=_capture_message_ids,      # les ids sont dans les ARGS, rien à parser
        revert=_gmail_untrash,
        verify=_gmail_is_untrashed,
    ),
    "delete_created_label": Compensation(
        name="delete_created_label",
        capture=_capture_created_label,
        revert=_gmail_delete_label,
        verify=_gmail_label_is_gone,
    ),
    "delete_created_event": Compensation(
        name="delete_created_event",
        capture=_capture_created_event,
        revert=_calendar_delete_event,
        verify=_calendar_event_is_gone,
    ),
    "trash_created_file": Compensation(
        name="trash_created_file",
        capture=_capture_created_drive_file,
        revert=_drive_trash,
        verify=_drive_is_trashed,
    ),
    "trash_created_folder": Compensation(
        name="trash_created_folder",
        capture=_capture_created_drive_folder,   # refuse un dossier RÉUTILISÉ
        revert=_drive_trash,
        verify=_drive_is_trashed,
    ),
    "delete_created_task": Compensation(
        name="delete_created_task",
        capture=_capture_created_task,
        revert=_tasks_delete,
        verify=_tasks_is_gone,
    ),
    "restore_task_status": Compensation(
        name="restore_task_status",
        snapshot=_tasks_snapshot_status,   # le statut d'avant, perdu par l'action
        revert=_tasks_restore_status,
        verify=_tasks_status_restored,
    ),
    "delete_created_contact": Compensation(
        name="delete_created_contact",
        capture=_capture_created_contact,
        revert=_contacts_delete,
        verify=_contacts_is_gone,
    ),
    "delete_created_note": Compensation(
        name="delete_created_note",
        capture=_capture_created_note,
        revert=_notes_delete,
        verify=_notes_is_gone,
    ),
}


def get_compensation(name: str | None) -> Optional[Compensation]:
    """Compensation enregistrée pour ``name`` (None si inconnue/absente)."""
    if not name:
        return None
    return _REGISTRY.get(name)

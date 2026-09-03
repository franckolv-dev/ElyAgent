# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reversible_coverage.py
# @brief      « Annuler partout » — la couverture du journal réversible au-delà
#             des trois compensations Drive de J1/J3 (audit du 02/09/2026).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Ce que ces tests protègent.

L'audit du 02/09/2026 a mesuré la promesse « un agent qui sait défaire ce qu'il
a fait » : TROIS compensations, toutes sur Drive, sur deux cents outils. Ce
fichier couvre l'extension aux écritures réellement réversibles.

Trois exigences par compensation, plus une transversale :

1. la CAPTURE retient ce qu'il faut — et RIEN quand elle n'est pas sûre (une
   annulation approximative est pire que pas d'annulation : elle fait croire
   que c'est défait) ;
2. le REVERT appelle bien l'opération inverse (services Google simulés) ;
3. le VERIFY détecte le cas NON restauré — la page d'annulation avoue quand
   elle n'a pas pu vérifier, et c'est cette qualité qu'on nourrit ici ;
4. transversale : toute compensation DÉCLARÉE au manifeste est ENREGISTRÉE au
   registre (une déclaration qui pointe vers rien est journalisée en debug et
   n'enregistre rien — un piège silencieux).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

import app.services.compensation_registry as creg
from app.services.capability_manifest import _OVERRIDES, Approval, get_manifest


# ── Outillage : une API Google simulée, chaînable comme la vraie ─────────


class _Leaf:
    """Le maillon final : ``.execute()`` rend (ou lève) ce que le test veut."""

    def __init__(self, handler, kwargs):
        self._handler, self._kwargs = handler, kwargs

    def execute(self):
        return self._handler(self._kwargs) if callable(self._handler) else self._handler


class _Node:
    """``service.users().messages().untrash(id=...).execute()`` en dix lignes.

    Un nom présent dans ``handlers`` est une FEUILLE (on journalise l'appel et
    on rend la réponse voulue) ; tout autre nom est un nœud intermédiaire."""

    def __init__(self, log, handlers):
        self._log, self._handlers = log, handlers

    def __getattr__(self, name):
        def _call(**kwargs):
            if name not in self._handlers:
                return _Node(self._log, self._handlers)
            self._log.append((name, kwargs))
            return _Leaf(self._handlers[name], kwargs)
        return _call


class _Resp:
    def __init__(self, status):
        self.status = status


class _ApiError(Exception):
    """Simule ``googleapiclient.errors.HttpError`` (attribut ``.resp.status``)."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.resp = _Resp(status)


def _gone(_kwargs):
    raise _ApiError(404)


def _gone_410(_kwargs):
    # Les API Google répondent aussi 410 (Gone) sur une ressource déjà
    # supprimée — un utilisateur qui a fait le ménage avant de cliquer
    # « Annuler » a atteint l'état visé, ce n'est pas un échec (02/09/2026).
    raise _ApiError(410)


def _boom(_kwargs):
    raise _ApiError(500)


def _install(monkeypatch, target: str, handlers: dict) -> list:
    """Branche un service Google simulé et rend le journal des appels."""
    log: list = []

    async def fake_creds(user_id):
        return "{creds}"

    async def fake_service(creds):
        return _Node(log, handlers)

    monkeypatch.setattr(creg, "_creds_for_user", fake_creds)
    monkeypatch.setattr(target, fake_service)
    return log


_GMAIL = "app.agent.tools.gmail_tool._get_gmail_service"
_CALENDAR = "app.agent.tools.calendar_tool._get_calendar_service"
_DRIVE = "app.agent.tools.drive_tool._get_drive_service"
_TASKS = "app.agent.tools.tasks_tool._get_tasks_service"
_PEOPLE = "app.agent.tools.contacts_tool._get_people_service"


def _comp(name: str) -> creg.Compensation:
    comp = creg.get_compensation(name)
    assert comp is not None, f"compensation '{name}' absente du registre"
    return comp


# ── Transversal : déclaré au manifeste ⇒ enregistré au registre ──────────


def test_toute_compensation_declaree_est_enregistree():
    orphelines = [
        (tool, m.compensation)
        for tool, m in _OVERRIDES.items()
        if m.compensation and creg.get_compensation(m.compensation) is None
    ]
    assert orphelines == []


def test_toute_compensation_enregistree_est_declaree_quelque_part():
    # Le piège symétrique : une compensation qu'aucun manifeste ne nomme est
    # du code mort qui donne l'illusion d'une couverture.
    declarees = {m.compensation for m in _OVERRIDES.values() if m.compensation}
    assert set(creg._REGISTRY) - declarees == set()


def test_aucune_surcharge_nassouplit_la_garde_hitl():
    # INVARIANT durable, qui tient aussi pour les surcharges à venir : ajouter
    # une compensation ne retire JAMAIS une confirmation. Un outil de la garde
    # surchargé en risk_based serait une régression de sécurité déguisée en
    # fonctionnalité d'annulation.
    #
    # La garde réelle est l'UNION de DEUX listes (cf. #296/#297) : n'en
    # parcourir qu'une laissait 14 outils — `notes_delete`,
    # `calendar_create_meet_event`, `vault_set_secret`… — hors de l'invariant
    # alors qu'il se disait durable (relecture du 02/09/2026).
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS

    garde = ALWAYS_CRITICAL_TOOLS | LOCKED_HITL_TOOLS
    for tool, manifeste in _OVERRIDES.items():
        if tool in garde:
            assert manifeste.approval is Approval.ALWAYS, tool


def test_une_compensation_alimente_par_capture_ou_par_snapshot_jamais_les_deux():
    # Les deux modes sont EXCLUSIFS (cf. record_reversible) : avoir les deux
    # ferait taire silencieusement la capture post-succès.
    for name, comp in creg._REGISTRY.items():
        assert (comp.capture is None) != (comp.snapshot is None), name


def test_chaque_compensation_sait_verifier_son_annulation():
    # La page d'annulation AVOUE « non vérifié » ; on ne veut pas que ce soit
    # la règle. Toute compensation enregistrée porte un verify.
    sans_verify = [name for name, comp in creg._REGISTRY.items() if comp.verify is None]
    assert sans_verify == []


# ── Manifestes : ce que chaque outil déclare désormais ───────────────────


@pytest.mark.parametrize(
    ("tool", "compensation"),
    [
        ("gmail_trash_emails", "untrash_messages"),
        ("gmail_create_label", "delete_created_label"),
        ("calendar_create_event", "delete_created_event"),
        ("drive_create_file", "trash_created_file"),
        ("drive_create_folder", "trash_created_folder"),
        ("sheets_create_spreadsheet", "trash_created_file"),
        ("docs_create_document", "trash_created_file"),
        ("drive_upload_local_file", "trash_created_file"),
        ("drive_copy_file", "trash_created_file"),
        ("tasks_create", "delete_created_task"),
        ("tasks_complete", "restore_task_status"),
        ("notes_create", "delete_created_note"),
        ("contacts_create", "delete_created_contact"),
    ],
)
def test_manifeste_declare_la_compensation(tool, compensation):
    assert get_manifest(tool).compensation == compensation


def test_les_nouvelles_capacites_ne_changent_pas_la_garde_hitl():
    # INVARIANT du manifeste : ajouter une compensation n'ajoute ni ne retire
    # aucune confirmation. gmail_trash_emails est déjà ALWAYS_CRITICAL ; les
    # autres restent sur la dérivation (risk_based).
    assert get_manifest("gmail_trash_emails").approval is Approval.ALWAYS
    for tool in (
        "gmail_create_label", "calendar_create_event", "drive_create_file",
        "drive_create_folder", "sheets_create_spreadsheet", "docs_create_document",
        "drive_upload_local_file", "drive_copy_file",
        "tasks_create", "tasks_complete", "notes_create", "contacts_create",
    ):
        assert get_manifest(tool).approval is Approval.RISK_BASED, tool


def test_un_mail_envoye_reste_sans_compensation():
    # La frontière : ce qu'un tiers a vu ne se défait pas.
    assert get_manifest("gmail_send_email").compensation is None


# ── Gmail : corbeille → hors corbeille ──────────────────────────────────


def test_capture_gmail_retient_les_ids_de_message():
    capture = _comp("untrash_messages").capture
    args = {"email_ids": ["m1", "m2"], "user_google_credentials_json": "SECRET"}
    assert capture(args, "🗑️ 2/2 email(s) envoyés à la corbeille.") == {"message_ids": ["m1", "m2"]}


def test_capture_gmail_refuse_une_mise_a_la_corbeille_incomplete():
    # `gmail_trash_emails` trashe message par message et rend « k/n ». Retenir
    # les n identifiants quand seuls k sont partis ferait sortir de la
    # corbeille des messages que l'UTILISATEUR y avait mis lui-même : une
    # « annulation » qui défait autre chose que l'action journalisée.
    capture = _comp("untrash_messages").capture
    args = {"email_ids": ["m1", "m2", "m3"]}
    assert capture(args, "🗑️ 2/3 email(s) envoyés à la corbeille.\nErreurs (1): m3: 404") == {}
    assert capture(args, "Google non connecté.") == {}
    assert capture(args, "Erreur suppression emails: 500") == {}


def test_capture_gmail_ne_retient_aucun_secret():
    capture = _comp("untrash_messages").capture
    ok = "🗑️ 1/1 email(s) envoyés à la corbeille."
    captured = capture({"email_ids": ["m1"], "user_google_credentials_json": "SECRET"}, ok)
    assert "SECRET" not in str(captured)


def test_capture_gmail_renonce_au_dela_du_lot_journalisable():
    # Le journal borne compensation_args à 4 Ko : un lot énorme serait TRONQUÉ
    # donc illisible à l'annulation. Mieux vaut ne rien promettre.
    capture = _comp("untrash_messages").capture
    ok = "🗑️ 500/500 email(s) envoyés à la corbeille."
    assert capture({"email_ids": [f"m{i}" for i in range(500)]}, ok) == {}


def test_capture_gmail_vide_sans_ids():
    assert _comp("untrash_messages").capture({}, "Aucun email fourni.") == {}


@pytest.mark.asyncio
async def test_revert_gmail_sort_chaque_message_de_la_corbeille(monkeypatch):
    log = _install(monkeypatch, _GMAIL, {"untrash": {}})
    await _comp("untrash_messages").revert({"message_ids": ["m1", "m2"]}, "u1")
    assert [kw["id"] for _, kw in log] == ["m1", "m2"]
    assert {name for name, _ in log} == {"untrash"}


@pytest.mark.asyncio
async def test_revert_gmail_echoue_si_aucun_message_ne_sort(monkeypatch):
    _install(monkeypatch, _GMAIL, {"untrash": _boom})
    with pytest.raises(RuntimeError):
        await _comp("untrash_messages").revert({"message_ids": ["m1"]}, "u1")


@pytest.mark.asyncio
async def test_verify_gmail_faux_si_un_message_reste_a_la_corbeille(monkeypatch):
    etats = {"m1": ["INBOX"], "m2": ["TRASH", "INBOX"]}
    _install(monkeypatch, _GMAIL, {"get": lambda kw: {"labelIds": etats[kw["id"]]}})
    verify = _comp("untrash_messages").verify
    assert await verify({"message_ids": ["m1", "m2"]}, "u1") is False
    assert await verify({"message_ids": ["m1"]}, "u1") is True


# ── Gmail : libellé créé → libellé supprimé ─────────────────────────────


def test_capture_libelle_lit_lid_en_fin_de_ligne():
    capture = _comp("delete_created_label").capture
    out = capture({"name": "Newsletters"}, "Label 'Newsletters' créé avec succès (id: Label_42)")
    assert out == {"label_id": "Label_42"}


def test_capture_libelle_ignore_le_libelle_preexistant():
    # Branche « existe déjà » : le libellé n'a pas été créé par Ely, le
    # supprimer détruirait le classement de l'utilisateur.
    capture = _comp("delete_created_label").capture
    assert capture({"name": "Newsletters"}, "Le label 'Newsletters' existe déjà.") == {}


def test_capture_libelle_resiste_a_un_nom_qui_imite_le_marqueur():
    # Le nom est choisi par le modèle : il ne doit pas pouvoir désigner un
    # AUTRE libellé que celui qui vient d'être créé.
    capture = _comp("delete_created_label").capture
    piege = "Label 'faux (id: Label_VICTIME)' créé avec succès (id: Label_VRAI)"
    assert capture({"name": "x"}, piege) == {"label_id": "Label_VRAI"}


@pytest.mark.asyncio
async def test_revert_libelle_supprime_un_libelle_reste_vide(monkeypatch):
    log = _install(monkeypatch, _GMAIL, {"get": {"messagesTotal": 0, "threadsTotal": 0}, "delete": {}})
    await _comp("delete_created_label").revert({"label_id": "Label_42"}, "u1")
    assert ("delete", {"userId": "me", "id": "Label_42"}) in log


@pytest.mark.asyncio
async def test_revert_libelle_refuse_un_libelle_qui_sert_a_classer(monkeypatch):
    # Supprimer un libellé Gmail le retire de TOUS les messages qui le portent,
    # immédiatement et sans corbeille. Sept jours après sa création, il peut
    # classer 800 messages : l'annulation effacerait ce classement sans recours.
    log = _install(monkeypatch, _GMAIL, {
        "get": {"id": "Label_42", "messagesTotal": 800, "threadsTotal": 210},
        "delete": {},
    })
    with pytest.raises(creg.CompensationRefused):
        await _comp("delete_created_label").revert({"label_id": "Label_42"}, "u1")
    assert "delete" not in {nom for nom, _ in log}


@pytest.mark.asyncio
async def test_revert_libelle_tolere_un_libelle_deja_disparu(monkeypatch):
    _install(monkeypatch, _GMAIL, {"get": _gone})
    await _comp("delete_created_label").revert({"label_id": "Label_42"}, "u1")
    _install(monkeypatch, _GMAIL, {"get": _gone_410})
    await _comp("delete_created_label").revert({"label_id": "Label_42"}, "u1")


@pytest.mark.asyncio
async def test_verify_libelle_faux_si_toujours_present(monkeypatch):
    _install(monkeypatch, _GMAIL, {"get": {"id": "Label_42"}})
    assert await _comp("delete_created_label").verify({"label_id": "Label_42"}, "u1") is False


@pytest.mark.asyncio
async def test_verify_libelle_vrai_si_disparu(monkeypatch):
    _install(monkeypatch, _GMAIL, {"get": _gone})
    assert await _comp("delete_created_label").verify({"label_id": "Label_42"}, "u1") is True


# ── Agenda : événement créé → événement supprimé ────────────────────────


_EVENT_OK = (
    "Événement créé avec succès : 'Point équipe'\n"
    "Date : 2026-09-03T14:00:00+02:00\n"
    "Lien : https://www.google.com/calendar/event?eid=abc\n"
    "ID : evt123abc"
)


def test_capture_evenement_retient_lid_et_rien_du_contenu():
    out = _comp("delete_created_event").capture({"title": "Point équipe"}, _EVENT_OK)
    assert out == {"event_id": "evt123abc"}


def test_capture_evenement_vide_sur_erreur():
    capture = _comp("delete_created_event").capture
    assert capture({"title": "x"}, "Erreur création événement: quota exceeded") == {}


def test_capture_evenement_resiste_a_un_titre_qui_imite_le_marqueur():
    piege = "Événement créé avec succès : 'faux\nID : evtVICTIME'\nLien : x\nID : evtVRAI"
    assert _comp("delete_created_event").capture({}, piege) == {"event_id": "evtVRAI"}


@pytest.mark.asyncio
async def test_revert_evenement_supprime_sans_notifier_personne(monkeypatch):
    # `sendUpdates` par défaut n'est pas écrit dans le contrat de l'API : on
    # l'explicite, sinon une annulation pourrait envoyer un « rendez-vous
    # annulé » à des adresses qu'Ely n'a jamais invitées (02/09/2026).
    log = _install(monkeypatch, _CALENDAR, {"get": {"status": "confirmed"}, "delete": {}})
    await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")
    assert ("delete", {"calendarId": "primary", "eventId": "evt1", "sendUpdates": "none"}) in log


@pytest.mark.asyncio
async def test_revert_evenement_refuse_un_evenement_qui_a_gagne_des_invites(monkeypatch):
    # `calendar_create_event` ne pose jamais d'invités, mais sept jours passent :
    # l'utilisateur a pu en ajouter. Supprimer retombe alors du côté « vu par un
    # tiers » de la frontière que ce lot pose.
    log = _install(monkeypatch, _CALENDAR, {
        "get": {
            "status": "confirmed",
            "attendees": [{"email": "moi@x", "self": True}, {"email": "tiers@y"}],
        },
        "delete": {},
    })
    with pytest.raises(creg.CompensationRefused):
        await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")
    assert "delete" not in {nom for nom, _ in log}


@pytest.mark.asyncio
async def test_revert_evenement_tolere_un_evenement_deja_disparu(monkeypatch):
    # L'état visé EST « l'événement n'existe plus » : ni un 404 ni un 410 (Gone,
    # que Google rend aussi) n'est un échec.
    _install(monkeypatch, _CALENDAR, {"get": _gone})
    await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")
    _install(monkeypatch, _CALENDAR, {"get": _gone_410})
    await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")
    _install(monkeypatch, _CALENDAR, {"get": {"status": "cancelled"}})
    await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")


@pytest.mark.asyncio
async def test_revert_evenement_remonte_une_vraie_panne(monkeypatch):
    _install(monkeypatch, _CALENDAR, {"get": _boom})
    with pytest.raises(_ApiError):
        await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")
    _install(monkeypatch, _CALENDAR, {"get": {"status": "confirmed"}, "delete": _boom})
    with pytest.raises(_ApiError):
        await _comp("delete_created_event").revert({"event_id": "evt1"}, "u1")


@pytest.mark.asyncio
async def test_verify_evenement_faux_si_toujours_confirme(monkeypatch):
    _install(monkeypatch, _CALENDAR, {"get": {"status": "confirmed"}})
    assert await _comp("delete_created_event").verify({"event_id": "evt1"}, "u1") is False


@pytest.mark.asyncio
async def test_verify_evenement_vrai_si_annule_ou_absent(monkeypatch):
    _install(monkeypatch, _CALENDAR, {"get": {"status": "cancelled"}})
    assert await _comp("delete_created_event").verify({"event_id": "evt1"}, "u1") is True
    _install(monkeypatch, _CALENDAR, {"get": _gone})
    assert await _comp("delete_created_event").verify({"event_id": "evt1"}, "u1") is True
    _install(monkeypatch, _CALENDAR, {"get": _gone_410})
    assert await _comp("delete_created_event").verify({"event_id": "evt1"}, "u1") is True


# ── Drive / Sheets / Docs : ressource créée → à la corbeille ─────────────


@pytest.mark.parametrize(
    "result",
    [
        "Fichier créé : 'rapport.txt'\nID : f123\nLien : https://drive/x",
        "Feuille de calcul créée : 'Budget'\nURL : https://s/x\nID : f123\nLignes insérées : 3",
        "Document créé : 'Note'\nURL : https://d/x\nID : f123",
    ],
)
def test_capture_fichier_cree_retient_lid(result):
    assert _comp("trash_created_file").capture({"name": "x"}, result) == {"file_id": "f123"}


@pytest.mark.parametrize(
    "result",
    [
        # Un téléversement et une copie créent un fichier Drive exactement
        # comme une création : même inverse, même corbeille récupérable.
        "Fichier téléversé sur Drive : 'capture.png'\nID : f123\nLien : https://drive/x",
        "✓ Copie créée : 'Budget (copie)'\n  ID : f123\n  Lien : https://drive/x",
        "✓ Copie créée : 'x' (converti : application/vnd.google-apps.document)\n"
        "  ID : f123\n  Lien : https://drive/x",
    ],
)
def test_capture_fichier_ne_dort_pas_sur_les_autres_naissances(result):
    assert _comp("trash_created_file").capture({"name": "x"}, result) == {"file_id": "f123"}


def test_capture_fichier_vide_sur_erreur():
    capture = _comp("trash_created_file").capture
    assert capture({"name": "x"}, "Erreur création fichier: 403") == {}


def test_capture_dossier_ignore_un_dossier_reutilise():
    # drive_create_folder est IDEMPOTENT : il réutilise un dossier existant.
    # Mettre CE dossier à la corbeille détruirait ce qu'Ely n'a pas créé.
    capture = _comp("trash_created_folder").capture
    reutilise = (
        "Dossier déjà existant (réutilisé, pas de doublon créé) : '09_2026'\n"
        "ID : dossierPREEXISTANT\nLien : https://drive/x"
    )
    assert capture({"name": "09_2026"}, reutilise) == {}
    cree = "Dossier créé : '09_2026'\nID : dossierNEUF\nLien : https://drive/x"
    assert capture({"name": "09_2026"}, cree) == {"file_id": "dossierNEUF"}


@pytest.mark.asyncio
async def test_revert_fichier_met_a_la_corbeille(monkeypatch):
    log = _install(monkeypatch, _DRIVE, {"update": {}})
    await _comp("trash_created_file").revert({"file_id": "f123"}, "u1")
    assert log == [("update", {"fileId": "f123", "body": {"trashed": True}})]


@pytest.mark.asyncio
async def test_verify_fichier_faux_si_toujours_vivant(monkeypatch):
    _install(monkeypatch, _DRIVE, {"get": {"trashed": False}})
    assert await _comp("trash_created_file").verify({"file_id": "f123"}, "u1") is False
    _install(monkeypatch, _DRIVE, {"get": {"trashed": True}})
    assert await _comp("trash_created_file").verify({"file_id": "f123"}, "u1") is True


# ── Google Tasks : tâche créée → tâche supprimée ────────────────────────


def test_capture_tache_lit_lid_en_fin_de_ligne():
    capture = _comp("delete_created_task").capture
    assert capture({"title": "Rappeler"}, "Tâche créée : 'Rappeler' (ID: t42)") == {"task_id": "t42"}


def test_capture_tache_resiste_a_un_titre_qui_imite_le_marqueur():
    capture = _comp("delete_created_task").capture
    piege = "Tâche créée : 'faux (ID: tVICTIME)' (ID: tVRAI)"
    assert capture({"title": "x"}, piege) == {"task_id": "tVRAI"}


def test_capture_tache_vide_sur_erreur():
    assert _comp("delete_created_task").capture({"title": "x"}, "Erreur création tâche : 500") == {}


@pytest.mark.asyncio
async def test_revert_tache_supprime_la_tache(monkeypatch):
    log = _install(monkeypatch, _TASKS, {"delete": {}})
    await _comp("delete_created_task").revert({"task_id": "t42"}, "u1")
    assert log == [("delete", {"tasklist": "@default", "task": "t42"})]


@pytest.mark.asyncio
async def test_verify_tache_faux_si_toujours_la(monkeypatch):
    _install(monkeypatch, _TASKS, {"get": {"id": "t42", "status": "needsAction"}})
    assert await _comp("delete_created_task").verify({"task_id": "t42"}, "u1") is False
    _install(monkeypatch, _TASKS, {"get": _gone})
    assert await _comp("delete_created_task").verify({"task_id": "t42"}, "u1") is True


@pytest.mark.asyncio
async def test_une_ressource_deja_supprimee_par_lutilisateur_nest_pas_un_echec(monkeypatch):
    # 410 (Gone) autant que 404 : l'utilisateur qui a fait le ménage avant de
    # cliquer « Annuler » a déjà atteint l'état visé. Ne reconnaître que le 404
    # lui rendait un échec (relecture du 02/09/2026).
    _install(monkeypatch, _TASKS, {"delete": _gone_410})
    await _comp("delete_created_task").revert({"task_id": "t42"}, "u1")
    _install(monkeypatch, _TASKS, {"get": _gone_410})
    assert await _comp("delete_created_task").verify({"task_id": "t42"}, "u1") is True

    _install(monkeypatch, _PEOPLE, {"deleteContact": _gone_410})
    await _comp("delete_created_contact").revert({"resource_name": "people/c99"}, "u1")
    _install(monkeypatch, _PEOPLE, {"get": _gone_410})
    assert await _comp("delete_created_contact").verify({"resource_name": "people/c99"}, "u1") is True


# ── Google Tasks : tâche terminée → tâche à faire (instantané) ──────────


@pytest.mark.asyncio
async def test_snapshot_tache_retient_le_statut_davant_et_celui_quon_attend(monkeypatch):
    _install(monkeypatch, _TASKS, {"get": {"status": "needsAction"}})
    snap = await _comp("restore_task_status").snapshot({"task_id": "t42"}, "u1")
    assert snap == {"task_id": "t42", "status": "needsAction", "expected_status": "completed"}


@pytest.mark.asyncio
async def test_snapshot_tache_vide_si_deja_terminee(monkeypatch):
    # Rien à défaire : la rouvrir serait inventer un état qui n'a jamais existé.
    _install(monkeypatch, _TASKS, {"get": {"status": "completed"}})
    assert await _comp("restore_task_status").snapshot({"task_id": "t42"}, "u1") == {}


@pytest.mark.asyncio
async def test_revert_tache_rouvre_la_tache(monkeypatch):
    log = _install(monkeypatch, _TASKS, {"get": {"status": "completed"}, "patch": {}})
    snap = {"task_id": "t42", "status": "needsAction", "expected_status": "completed"}
    await _comp("restore_task_status").revert(snap, "u1")
    assert ("patch", {"tasklist": "@default", "task": "t42", "body": {"status": "needsAction"}}) in log


@pytest.mark.asyncio
async def test_revert_tache_refuse_si_la_tache_nest_pas_dans_letat_attendu(monkeypatch):
    # Le mode instantané journalise SANS avoir vu le résultat de l'outil : les
    # outils d'Ely rendent « Erreur … » en texte au lieu de lever. Une entrée
    # « Terminer la tâche » peut donc exister pour une action qui a échoué — et
    # sept jours plus tard, l'utilisateur a pu terminer la tâche lui-même.
    # Rouvrir détruirait SON geste. (02/09/2026)
    log = _install(monkeypatch, _TASKS, {"get": {"status": "needsAction"}, "patch": {}})
    snap = {"task_id": "t42", "status": "needsAction", "expected_status": "completed"}
    with pytest.raises(creg.CompensationRefused):
        await _comp("restore_task_status").revert(snap, "u1")
    assert "patch" not in {nom for nom, _ in log}


@pytest.mark.asyncio
async def test_verify_statut_tache_faux_si_toujours_terminee(monkeypatch):
    snap = {"task_id": "t42", "status": "needsAction"}
    _install(monkeypatch, _TASKS, {"get": {"status": "completed"}})
    assert await _comp("restore_task_status").verify(snap, "u1") is False
    _install(monkeypatch, _TASKS, {"get": {"status": "needsAction"}})
    assert await _comp("restore_task_status").verify(snap, "u1") is True


# ── Contacts : contact créé → contact supprimé ──────────────────────────


def test_capture_contact_retient_le_resource_name_et_pas_le_courriel():
    capture = _comp("delete_created_contact").capture
    out = capture(
        {"name": "Alice", "email": "alice@example.com"},
        "Contact créé : Alice (alice@example.com)\nresourceName: people/c99",
    )
    assert out == {"resource_name": "people/c99"}


def test_capture_contact_vide_sur_erreur():
    capture = _comp("delete_created_contact").capture
    assert capture({"name": "x"}, "Erreur lors de la création du contact : 403") == {}


@pytest.mark.asyncio
async def test_revert_contact_supprime_le_contact(monkeypatch):
    log = _install(monkeypatch, _PEOPLE, {"deleteContact": {}})
    await _comp("delete_created_contact").revert({"resource_name": "people/c99"}, "u1")
    assert log == [("deleteContact", {"resourceName": "people/c99"})]


@pytest.mark.asyncio
async def test_verify_contact_faux_si_toujours_present(monkeypatch):
    _install(monkeypatch, _PEOPLE, {"get": {"resourceName": "people/c99"}})
    assert await _comp("delete_created_contact").verify({"resource_name": "people/c99"}, "u1") is False
    _install(monkeypatch, _PEOPLE, {"get": _gone})
    assert await _comp("delete_created_contact").verify({"resource_name": "people/c99"}, "u1") is True


# ── Notes (base d'Ely) : note créée → note supprimée ────────────────────


@pytest_asyncio.fixture
async def db_ready():
    from app.database import init_db
    await init_db()


async def _make_note() -> tuple[str, str]:
    """Un utilisateur réel (la note a une clé étrangère) et sa note. -> (user_id, note_id)."""
    from app.database import async_session
    from app.models.note import Note
    from app.models.user import User

    uid = str(uuid.uuid4())
    # Deux transactions, et pas une : `Note` porte une clé étrangère vers
    # `users` mais AUCUNE relation SQLAlchemy, donc le tri des insertions ne
    # voit pas la dépendance et sortait la note AVANT l'utilisateur
    # (« FOREIGN KEY constraint failed », 02/09/2026).
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        ))
        await db.commit()
    async with async_session() as db:
        note = Note(user_id=uid, title="T", content="C")
        db.add(note)
        await db.commit()
        await db.refresh(note)
    return uid, note.id


async def _drop_user(user_id: str) -> None:
    from sqlalchemy import delete

    from app.database import async_session
    from app.models.note import Note
    from app.models.user import User
    async with async_session() as db:
        await db.execute(delete(Note).where(Note.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def _note_exists(note_id: str) -> bool:
    from app.database import async_session
    from app.models.note import Note
    async with async_session() as db:
        return await db.get(Note, note_id) is not None


async def _etoffer_la_note(note_id: str) -> None:
    """L'utilisateur reprend la note et l'enrichit, plus tard dans la semaine.

    On DATE l'édition explicitement : dans un test, l'édition suit la création
    de quelques millisecondes, en dessous de la tolérance qui absorbe l'écart
    naturel entre `created_at` et `updated_at` à l'insertion."""
    from datetime import timedelta

    from app.database import async_session
    from app.models.note import Note
    async with async_session() as db:
        note = await db.get(Note, note_id)
        note.content = "ce que l'utilisateur y a mis depuis"
        note.updated_at = note.created_at + timedelta(days=6)
        await db.commit()


def test_capture_note_retient_lid_et_pas_le_contenu():
    capture = _comp("delete_created_note").capture
    result = (
        "Note créée ✅\n"
        "ID: 6f1c2a3b-4d5e-4f60-8a91-2b3c4d5e6f70\n"
        "Titre: Courses\n"
        "Contenu: code de la porte 1234\n"
        "Créé: 02/09/2026 10:00"
    )
    out = capture({"title": "Courses", "content": "code de la porte 1234"}, result)
    assert out == {"note_id": "6f1c2a3b-4d5e-4f60-8a91-2b3c4d5e6f70"}
    assert "1234" not in str(out)


def test_capture_note_resiste_a_un_contenu_qui_imite_le_marqueur():
    # Le contenu vient APRÈS l'en-tête : c'est la PREMIÈRE ligne ID qui fait foi.
    capture = _comp("delete_created_note").capture
    result = "Note créée ✅\nID: aaaa-1111\nTitre: x\nContenu: ID: bbbb-2222\nCréé: x"
    assert capture({}, result) == {"note_id": "aaaa-1111"}


@pytest.mark.asyncio
async def test_revert_note_supprime_la_note(db_ready):
    uid, note_id = await _make_note()
    try:
        await _comp("delete_created_note").revert({"note_id": note_id}, uid)
        assert await _note_exists(note_id) is False
    finally:
        await _drop_user(uid)


@pytest.mark.asyncio
async def test_revert_note_refuse_une_note_etoffee_depuis_sa_creation(db_ready):
    # La note n'a NI corbeille NI suppression douce, et la fenêtre d'annulation
    # dure sept jours. Si l'utilisateur a écrit dedans, « Annuler » sur la ligne
    # de création détruirait son travail — exactement le cas qui a fait exclure
    # `gmail_create_draft`, `sheets_add_sheet` et `tasks_create_tasklist`.
    uid, note_id = await _make_note()
    try:
        await _etoffer_la_note(note_id)
        with pytest.raises(creg.CompensationRefused):
            await _comp("delete_created_note").revert({"note_id": note_id}, uid)
        assert await _note_exists(note_id) is True
    finally:
        await _drop_user(uid)


@pytest.mark.asyncio
async def test_le_refus_dannuler_une_note_est_un_echec_propre(db_ready, monkeypatch):
    # Un refus doit atterrir dans un ÉTAT du journal (`revert_failed`), pas
    # remonter une erreur opaque : la surface d'annulation doit pouvoir dire
    # pourquoi elle n'a rien fait, et l'entrée ne doit pas rester « annulable ».
    from sqlalchemy import delete

    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    from app.services import journal_service as js

    monkeypatch.setattr(js, "_enabled", lambda: True)
    uid, note_id = await _make_note()
    try:
        rid = await js.record_reversible(
            "notes_create", {"title": "T"}, f"Note créée ✅\nID: {note_id}\nTitre: T", uid, "fp",
        )
        assert rid is not None
        await _etoffer_la_note(note_id)

        out = await js.undo(rid, uid)
        assert out["ok"] is False
        assert out["reason"] == "revert_failed"
        assert out["error"] == "CompensationRefused"
        assert await _note_exists(note_id) is True
        async with async_session() as db:
            assert (await db.get(ReversibleActionRecord, rid)).status == "revert_failed"
    finally:
        async with async_session() as db:
            await db.execute(delete(ReversibleActionRecord).where(ReversibleActionRecord.user_id == uid))
            await db.commit()
        await _drop_user(uid)


@pytest.mark.asyncio
async def test_revert_note_refuse_la_note_dun_autre(db_ready):
    uid, note_id = await _make_note()
    try:
        with pytest.raises(PermissionError):
            await _comp("delete_created_note").revert({"note_id": note_id}, str(uuid.uuid4()))
        assert await _note_exists(note_id) is True
    finally:
        await _drop_user(uid)


@pytest.mark.asyncio
async def test_verify_note_faux_si_toujours_la(db_ready):
    uid, note_id = await _make_note()
    try:
        verify = _comp("delete_created_note").verify
        assert await verify({"note_id": note_id}, uid) is False
        await _comp("delete_created_note").revert({"note_id": note_id}, uid)
        assert await verify({"note_id": note_id}, uid) is True
    finally:
        await _drop_user(uid)


# ── Le journal, de bout en bout, sur une des nouvelles capacités ────────


@pytest.mark.asyncio
async def test_journal_enregistre_puis_annule_une_creation_devenement(db_ready, monkeypatch):
    from sqlalchemy import delete

    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    from app.services import journal_service as js

    monkeypatch.setattr(js, "_enabled", lambda: True)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("calendar_create_event", {"title": "Point"}, _EVENT_OK, uid, "fp")
        assert rid is not None

        _install(monkeypatch, _CALENDAR, {"delete": {}, "get": _gone})
        out = await js.undo(rid, uid)
        assert out["ok"] is True
        assert out["verified"] is True
    finally:
        async with async_session() as db:
            await db.execute(delete(ReversibleActionRecord).where(ReversibleActionRecord.user_id == uid))
            await db.commit()

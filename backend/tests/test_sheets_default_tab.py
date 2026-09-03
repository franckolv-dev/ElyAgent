# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sheets_default_tab.py
# @brief      Le premier onglet d'un tableur ne s'appelle PAS « Sheet1 » quand
#             le compte Google est en français — il s'appelle « Feuille 1 ».
#             Écrire dans un range codé en dur échoue en HTTP 400, le tableur
#             reste vide, et l'agent croit avoir réussi.
# @license    MIT
# =============================================================================
"""Le nom de l'onglet se LIT, il ne se devine pas (incident du 27/08/2026).

Mission « Prospection Print LinkedIn », 27/08 21h06 :

    sheets_create_spreadsheet -> HttpError 400
        "Unable to parse range: Sheet1!A1"

Le tableur était bien créé, mais l'écriture des valeurs échouait. Le fichier
exporté ensuite sur le Drive de l'utilisateur était donc VIDE, et la mission
s'est déclarée accomplie.

Deux pièges distincts, tous deux pinnés ici :
  1. le titre réel du premier onglet dépend de la LOCALE du compte ;
  2. un titre contenant une espace DOIT être quoté dans un range A1 —
     ``Feuille 1!A1`` échoue exactement comme ``Sheet1!A1``.
"""
from __future__ import annotations

import pytest

from app.agent.tools import sheets_tool


class _Exec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _FakeValues:
    def __init__(self):
        self.update_calls: list[dict] = []
        self.append_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _Exec({"values": [["Société", "Contact"], ["Acme", "Dupont"]]})

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _Exec({"updatedRows": len(kwargs.get("body", {}).get("values", []))})

    def append(self, **kwargs):
        self.append_calls.append(kwargs)
        return _Exec({"updates": {"updatedRows": 1}})


class _FakeSpreadsheets:
    def __init__(self, tab_title: str):
        self._tab_title = tab_title
        self._values = _FakeValues()

    def create(self, **_kwargs):
        return _Exec({
            "spreadsheetId": "ss-123",
            "sheets": [{"properties": {"title": self._tab_title, "sheetId": 0}}],
        })

    def get(self, **_kwargs):
        return _Exec({
            "spreadsheetId": "ss-123",
            "sheets": [{"properties": {"title": self._tab_title, "sheetId": 0}}],
        })

    def values(self):
        return self._values


class _FakeService:
    def __init__(self, tab_title: str):
        self._ss = _FakeSpreadsheets(tab_title)

    def spreadsheets(self):
        return self._ss


def _patch(monkeypatch, tab_title: str) -> _FakeService:
    svc = _FakeService(tab_title)

    async def _fake_get_service(_creds):
        return svc

    monkeypatch.setattr(sheets_tool, "_get_sheets_service", _fake_get_service)
    return svc


@pytest.mark.asyncio
async def test_create_ecrit_dans_l_onglet_reel_du_tableur(monkeypatch) -> None:
    """Compte en français : le premier onglet est « Feuille 1 »."""
    svc = _patch(monkeypatch, "Feuille 1")

    out = await sheets_tool.sheets_create_spreadsheet.coroutine(
        title="prospection", headers=["Société", "Contact"],
        rows=[["Acme", "Dupont"]],
    )

    calls = svc.spreadsheets().values().update_calls
    assert len(calls) == 1, "les valeurs doivent être écrites"
    assert "Sheet1" not in calls[0]["range"], (
        "le nom d'onglet ne doit plus être devine : c'est ce qui a produit "
        "le HTTP 400 « Unable to parse range: Sheet1!A1 »"
    )
    assert calls[0]["range"] == "'Feuille 1'!A1", (
        "un titre avec une espace doit être quoté, sinon le range est invalide"
    )
    assert "Lignes insérées : 2" in out


@pytest.mark.asyncio
async def test_create_quote_un_titre_contenant_une_apostrophe(monkeypatch) -> None:
    """« Ventes d'été » → l'apostrophe se double dans un range A1."""
    svc = _patch(monkeypatch, "Ventes d'été")

    await sheets_tool.sheets_create_spreadsheet.coroutine(
        title="x", headers=["a"], rows=None,
    )

    assert svc.spreadsheets().values().update_calls[0]["range"] == "'Ventes d''été'!A1"


@pytest.mark.asyncio
async def test_create_sans_donnees_n_ecrit_rien(monkeypatch) -> None:
    """Ni en-têtes ni lignes : aucun appel d'écriture, donc aucune erreur."""
    svc = _patch(monkeypatch, "Feuille 1")

    await sheets_tool.sheets_create_spreadsheet.coroutine(title="vide")

    assert svc.spreadsheets().values().update_calls == []


@pytest.mark.asyncio
async def test_append_resout_l_onglet_quand_il_n_est_pas_precise(monkeypatch) -> None:
    """`sheets_append_rows` sans `sheet_name` doit viser l'onglet RÉEL."""
    svc = _patch(monkeypatch, "Feuille 1")

    await sheets_tool.sheets_append_rows.coroutine(
        spreadsheet_id="ss-123", rows=[["Acme", "Dupont"]],
    )

    calls = svc.spreadsheets().values().append_calls
    assert len(calls) == 1
    assert calls[0]["range"] == "'Feuille 1'!A1", (
        "le défaut « Sheet1 » plante sur un compte non anglophone"
    )


@pytest.mark.asyncio
async def test_append_respecte_un_onglet_explicite(monkeypatch) -> None:
    """Un `sheet_name` fourni par l'appelant fait toujours autorité."""
    svc = _patch(monkeypatch, "Feuille 1")

    await sheets_tool.sheets_append_rows.coroutine(
        spreadsheet_id="ss-123", rows=[["x"]], sheet_name="Contacts",
    )

    assert svc.spreadsheets().values().append_calls[0]["range"] == "'Contacts'!A1"


@pytest.mark.asyncio
async def test_read_resout_l_onglet_quand_il_n_est_pas_precise(monkeypatch) -> None:
    """Relire un tableur sans préciser l'onglet doit viser le RÉEL.

    Symétrique de l'écriture : sans ça, la vérification d'un livrable
    échouerait sur la même erreur de plage que sa création.
    """
    svc = _patch(monkeypatch, "Feuille 1")

    await sheets_tool.sheets_read_spreadsheet.coroutine(spreadsheet_id="ss-123")

    assert svc.spreadsheets().values().get_calls[0]["range"] == "'Feuille 1'"

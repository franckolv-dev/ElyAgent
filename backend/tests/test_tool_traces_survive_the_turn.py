# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_traces_survive_the_turn.py
# @brief      Ce qu'un outil a produit survit au tour — le chemin d'un fichier
#             ne disparaît plus dès la question suivante.
# @license    MIT
# =============================================================================
"""Le trou mesuré le 29/07/2026, et sa fermeture.

La question de Franck
----------------------
    « Parfois j'ai l'impression que, dans une même conversation, elle ne se
      souvient pas de ce que j'ai demandé 3 ou 4 messages avant. »

Ce qui MARCHE, et qu'il ne faut plus suspecter
------------------------------------------------
``chat.py`` charge les **40 derniers messages** à chaque tour, et rien n'est
tronqué : les fenêtres réelles valent 1 000 000 tokens pour un prompt système
de 3 734. Mesuré sur une vraie conversation : 11 messages sur 12 arrivent au
modèle.

⛔ CE QUI NE MARCHAIT PAS
--------------------------
    messages en base par rôle : assistant 3649 · user 2993
    messages de rôle « tool » : 0   sur 6642

Les ``ToolMessage`` ne vivaient que le temps du tour. Au tour suivant il ne
restait que la reformulation d'Ely :

    msg 1  « convertis ce PDF »
           → l'outil rend /tmp/ely-docx/x.docx · 12 pages · 0 caractère perdu
           → Ely répond « c'est fait »
    msg 5  « dépose-le sur mon Drive »
           → elle ne voit QUE « c'est fait ». Le CHEMIN a disparu.

Elle n'oubliait pas l'utilisateur : elle oubliait **ce qu'elle avait fait**.

Deux pièges que ce lot doit éviter — vérifiés dans le code avant d'écrire
-------------------------------------------------------------------------
1. **L'API des conversations ne filtre aucun rôle**, et le composant
   ``MessageBubble`` affiche comme « assistant » tout ce qui n'est pas
   « user ». Persister ``role="tool"`` sans filtrer ferait apparaître les
   traces d'outils dans le chat de Franck.
2. **Un ``ToolMessage`` rechargé sans le ``AIMessage`` porteur de ses
   ``tool_calls`` fait REJETER la requête** par l'API du modèle. On ne les
   réinjecte donc pas comme ``ToolMessage`` : on en fait un bloc de contexte
   lisible.

Run with:  cd backend && python -m pytest tests/test_tool_traces_survive_the_turn.py -v
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ─────────────────────────────────────────────────────────────────────
# Ce qu'on garde d'un appel d'outil
# ─────────────────────────────────────────────────────────────────────


def test_a_trace_keeps_the_path_the_tool_produced():
    """LE cas de Franck. Le chemin du fichier est ce qu'il redemandera trois
    messages plus loin — c'est la seule chose qu'il ne faut surtout pas perdre."""
    from app.services.tool_traces import build_trace

    trace = build_trace(
        tool="pdf_to_docx",
        args={"source": "/app/uploads/manuscrit.pdf", "output_name": "manuscrit"},
        result=(
            "Document Word créé : /tmp/ely-docx/manuscrit.docx\n"
            "12 page(s) → 80 paragraphes (6 titre(s)) — 40 Ko\n"
            "Intégrité vérifiée : 6740 caractères, aucune perte."
        ),
    )

    assert "pdf_to_docx" in trace
    assert "/tmp/ely-docx/manuscrit.docx" in trace


def test_a_trace_stays_compact():
    """``pdf_read`` rend jusqu'à 15 000 caractères. Tout garder ferait grossir
    l'historique de chaque tour sans rien apporter : c'est le RÉSULTAT qui
    compte, pas le contenu qu'il a transporté."""
    from app.services.tool_traces import MAX_TRACE_CHARS, build_trace

    trace = build_trace(
        tool="pdf_read", args={"source": "/tmp/gros.pdf"}, result="x" * 15_000,
    )

    assert len(trace) <= MAX_TRACE_CHARS


def test_a_failed_tool_is_traced_too():
    """Savoir qu'une piste a échoué évite de la refaire au tour suivant — c'est
    autant une information que le succès."""
    from app.services.tool_traces import build_trace

    trace = build_trace(
        tool="drive_upload_local_file",
        args={"path": "/tmp/x.docx"},
        result="Erreur : quota Drive dépassé",
    )

    assert "drive_upload_local_file" in trace
    assert "quota" in trace.lower()


def test_secrets_in_arguments_never_reach_the_trace():
    """Une trace est persistée en clair et relue à chaque tour. Y laisser un
    identifiant Google, c'est le recopier dans le contexte envoyé au modèle à
    chaque message de la conversation."""
    from app.services.tool_traces import build_trace

    trace = build_trace(
        tool="drive_upload_local_file",
        args={
            "path": "/tmp/x.docx",
            "user_google_credentials_json": '{"refresh_token": "1//ABCDEF"}',
            "api_key": "sk-secret-value",
        },
        result="Fichier déposé.",
    )

    assert "1//ABCDEF" not in trace
    assert "sk-secret-value" not in trace
    assert "/tmp/x.docx" in trace, "les arguments utiles doivent rester"


# ─────────────────────────────────────────────────────────────────────
# Extraire les traces d'un tour
# ─────────────────────────────────────────────────────────────────────


def test_traces_are_extracted_from_the_turn_messages():
    from app.services.tool_traces import traces_from_messages

    messages = [
        HumanMessage(content="convertis ce PDF"),
        AIMessage(content="", tool_calls=[{
            "name": "pdf_to_docx", "args": {"source": "/tmp/a.pdf"}, "id": "c1",
        }]),
        ToolMessage(content="Document Word créé : /tmp/ely-docx/a.docx", tool_call_id="c1"),
        AIMessage(content="C'est fait."),
    ]

    traces = traces_from_messages(messages)

    assert len(traces) == 1
    assert "pdf_to_docx" in traces[0]
    assert "/tmp/ely-docx/a.docx" in traces[0]


def test_a_turn_without_tools_produces_no_trace():
    """Une conversation ordinaire ne doit rien coûter de plus."""
    from app.services.tool_traces import traces_from_messages

    assert traces_from_messages([
        HumanMessage(content="bonjour"), AIMessage(content="Bonjour Franck."),
    ]) == []


# ─────────────────────────────────────────────────────────────────────
# Le rechargement — sans casser l'appel au modèle
# ─────────────────────────────────────────────────────────────────────


def test_reloaded_traces_are_context_not_tool_messages():
    """⚠️ Le piège. Un ``ToolMessage`` sans le ``AIMessage`` porteur de ses
    ``tool_calls`` fait REJETER la requête par l'API du modèle. On rend donc un
    bloc de contexte, jamais un ``ToolMessage``."""
    from app.services.tool_traces import context_from_traces

    bloc = context_from_traces([
        "pdf_to_docx(source=/tmp/a.pdf) → Document Word créé : /tmp/ely-docx/a.docx",
    ])

    assert bloc is not None
    assert not isinstance(bloc, ToolMessage)
    assert "/tmp/ely-docx/a.docx" in bloc.content


def test_no_trace_means_no_context_block():
    """Ne pas polluer l'historique d'un bloc vide : un message de plus, c'est
    un message que le modèle doit lire à chaque tour."""
    from app.services.tool_traces import context_from_traces

    assert context_from_traces([]) is None


def test_the_context_block_says_what_it_is():
    """Sans étiquette, le modèle prendrait ces lignes pour une demande de
    l'utilisateur ou pour sa propre réponse."""
    from app.services.tool_traces import context_from_traces

    bloc = context_from_traces(["pdf_to_docx(...) → /tmp/x.docx"])

    assert "outil" in bloc.content.lower() or "action" in bloc.content.lower()


def test_only_the_most_recent_traces_are_reloaded():
    """Une conversation de 40 messages peut porter des dizaines d'appels. Les
    recharger tous ferait grossir chaque tour sans fin — ce sont les DERNIERS
    qui portent le contexte utile."""
    from app.services.tool_traces import MAX_RELOADED_TRACES, context_from_traces

    bloc = context_from_traces([f"outil_{i}(...) → resultat {i}" for i in range(40)])

    assert bloc.content.count("→") <= MAX_RELOADED_TRACES
    # Ce sont les plus RÉCENTS qui comptent, pas les premiers.
    assert "resultat 39" in bloc.content
    assert "resultat 0" not in bloc.content


# ---------------------------------------------------------------------------
# Une trace répétée mange le budget de rechargement
# ---------------------------------------------------------------------------
#
# ⛔ Mesuré le 01/08 sur la base réelle. Un tour a bouclé sur la même recherche
# infructueuse : **54 traces identiques** écrites d'un coup. Le tour suivant
# recharge les 8 dernières — il en a reçu 7 fois la même recherche ratée.
#
# La trace qui comptait, elle, était tombée du budget :
#
#     drive_create_file(name=Audit_Pro_BAT.md) → Fichier créé · Lien : https://…
#
# Ely a donc cherché le fichier dans ses conversations passées, ne l'a pas
# trouvé, a stagné, et le panel a fini par répondre qu'elle ne savait pas
# écrire de fichier — seize minutes après l'avoir écrit (#319).
#
# 👉 Une répétition n'apporte AUCUNE information et coûte une place à ce qui en
#    apporte. Le budget doit compter des actions DISTINCTES.

def test_a_repeated_trace_does_not_eat_the_reload_budget():
    """Sept fois la même recherche ratée ne valent pas sept places."""
    from app.services.tool_traces import MAX_RELOADED_TRACES, context_from_traces

    ratee = 'web_search(query=site:adobe.com "Share for Review") → aucun résultat'
    traces = [ratee] * 54 + [
        "drive_create_file(name=Audit_Pro_BAT.md) → Fichier créé · Lien : https://drive…",
    ]

    bloc = context_from_traces(traces)

    assert "Audit_Pro_BAT.md" in bloc.content, (
        "la seule action qui a produit quelque chose ne doit pas être évincée "
        "par des répétitions qui n'apprennent rien"
    )
    assert bloc.content.count(ratee) == 1, (
        "une trace répétée à l'identique n'est rendue qu'une fois"
    )
    assert bloc.content.count("→") <= MAX_RELOADED_TRACES


def test_the_reload_budget_counts_distinct_actions():
    """Le plafond porte sur des actions distinctes, pas sur des lignes."""
    from app.services.tool_traces import MAX_RELOADED_TRACES, context_from_traces

    # 20 actions distinctes, chacune répétée 5 fois, en ordre chronologique.
    traces = [f"outil_{i}(...) → resultat {i}" for i in range(20) for _ in range(5)]

    bloc = context_from_traces(traces)

    rendues = [ligne for ligne in bloc.content.splitlines() if ligne.startswith("- ")]
    assert len(rendues) == MAX_RELOADED_TRACES
    assert len(set(rendues)) == MAX_RELOADED_TRACES, (
        "le plafond doit compter des actions DISTINCTES. Compter des LIGNES "
        "laisse passer exactement le défaut visé : un tour qui boucle remplit "
        "le budget de la même ligne et évince tout le reste"
    )
    # Ce sont les huit actions les plus RÉCENTES : outil_12 … outil_19.
    for i in range(12, 20):
        assert f"resultat {i}" in bloc.content
    assert "resultat 11" not in bloc.content


@pytest.mark.asyncio
async def test_a_looping_turn_does_not_write_the_same_trace_fifty_times(monkeypatch):
    """Ce qu'on écrit en base est déjà dédoublonné, à la source.

    Dédoublonner au rechargement protège les conversations DÉJÀ écrites ; ne
    pas écrire les doublons évite de payer le stockage et l'index pour du bruit.
    Les deux sont utiles, et aucun ne remplace l'autre.
    """
    from app.services import tool_traces as tt

    ecrites: list[str] = []

    class _FakeDb:
        def add(self, msg):
            ecrites.append(msg.content)
        async def commit(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(tt, "async_session", lambda: _FakeDb())

    ratee = 'web_search(query=site:adobe.com) → aucun résultat'
    n = await tt.persist_traces("conv-x", [ratee] * 54 + ["drive_create_file(…) → ok"])

    assert ecrites == [ratee, "drive_create_file(…) → ok"], (
        "54 fois la même trace, c'est une trace"
    )
    assert n == 2

"""Execution contracts: recovery, evidence, memory isolation, reusable tools."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import conformity as conf
from app.agent.recovery import current_turn, successful_evidence, recovery_hint, recovered_in_turn
from app.agent.tool_failure import dit_un_echec


def attempt(name='lookup', args=None, result='Résultat trouvé', call_id='1', error=False):
    return [AIMessage(content='', tool_calls=[{'name': name, 'args': args or {}, 'id': call_id}]),
            ToolMessage(content=result, tool_call_id=call_id, status='error' if error else 'success')]


@pytest.mark.parametrize('value', ['Erreur: panne', '❌ Error: timeout', {'ok': False}, {'success': False},
    '{"status":"failed"}', 'Code refusé par le sandbox : import', "Impossible d'exécuter le code : x", 'Timeout : 30 secondes'])
def test_failure_forms_are_not_success(value):
    assert dit_un_echec(value)


@pytest.mark.parametrize('value', ['Le rapport décrit une erreur', {'success': True}, '{"error": null}', '0 erreur', ''])
def test_normal_results_stay_successful(value):
    assert not dit_un_echec(value)


def test_history_is_not_evidence_for_the_current_request():
    messages = [HumanMessage(content='Hier'), *attempt(), AIMessage(content='Terminé'),
                HumanMessage(content='Bonjour'), AIMessage(content='Bonjour !')]
    assert not conf.should_verify_conformity({'messages': messages})
    assert len(current_turn(messages)) == 2
    assert 'Résultat trouvé' not in conf._produced(messages)


def test_capability_excuse_is_verified_even_without_tools():
    assert conf.should_verify_conformity({'messages': [HumanMessage(content='Convertis ce document'),
        AIMessage(content="Je n’ai pas d’outil pour convertir ce fichier.")]})


def test_final_attempt_is_still_verified():
    state = {'messages': [HumanMessage(content='Travaille'), *attempt(), AIMessage(content='Fait')],
             'conformity_retries': conf.MAX_CONFORMITY_RETRIES}
    assert conf.should_verify_conformity(state)


def test_repeated_calls_are_not_progress_and_errors_are_excluded():
    messages = [HumanMessage(content='Cherche'), *attempt(), *attempt(call_id='2'),
                *attempt(name='broken', call_id='3', result='Error: no result')]
    assert len(successful_evidence(messages)) == 1


def test_correction_in_the_tool_loop_is_learning_material():
    messages = [HumanMessage(content='Fais-le'), *attempt(result='Erreur : paramètres'), *attempt(call_id='2')]
    assert recovered_in_turn(messages)
    from app.services.learning.skill_from_success import should_propose_skill_from_success, build_success_skill_prompt
    assert should_propose_skill_from_success(conforme=True, retries=0, recovered=True)
    assert not should_propose_skill_from_success(conforme=False, retries=2, recovered=True)
    assert 'Erreur : paramètres' in build_success_skill_prompt(messages)


def test_recovery_respects_permissions_and_uncertain_writes():
    assert 'Ne contourne pas' in recovery_hint('gmail', '403 permission denied')
    assert 'déjà abouti' in recovery_hint('gmail', 'timeout')


@pytest.fixture
def judge(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_llm_for_tier', lambda *_: object())
    monkeypatch.setattr(conf, 'log_response_usage', AsyncMock())
    monkeypatch.setattr(conf, '_try_escalation', AsyncMock(return_value=None))
    monkeypatch.setattr(conf, '_report_remaining_gaps', AsyncMock(return_value={'messages': []}))
    monkeypatch.setattr(conf, '_maybe_learn_from_success', lambda *a, **kw: False)
    def install(text):
        monkeypatch.setattr(conf, 'ainvoke_with_deadline', AsyncMock(return_value=AIMessage(content=text)))
    return install


@pytest.mark.asyncio
async def test_new_evidence_can_advance_the_same_open_requirement(judge):
    before = [HumanMessage(content='Trouve puis vérifie'), *attempt()]
    state = {'messages': [*before, *attempt(name='read_document', call_id='2'), AIMessage(content='En cours')],
        'conformity_gap_count': 1, 'conformity_retries': 1, 'conformity_evidence': successful_evidence(before)}
    judge('ÉCARTS:\n- vérification du document encore manquante')
    out = await conf.conformity_node(state)
    assert out['conformity_retries'] == 2
    assert out['conformity_unresolved']
    assert len(out['conformity_evidence']) == 2
    state.update(out)
    state['messages'] = [*before, *attempt(name='read_document', call_id='3'), AIMessage(content='Toujours pareil')]
    out = await conf.conformity_node(state)
    assert out.get('conformity_retries') is None  # No loop on repeated evidence.


@pytest.mark.asyncio
async def test_invalid_judge_cannot_clear_mission_gaps_or_train_a_skill(judge, monkeypatch):
    learn = AsyncMock()
    monkeypatch.setattr(conf, '_maybe_learn_from_success', learn)
    judge('Le contenu semble bien, peut-être conforme.')
    out = await conf.conformity_node({'messages': [HumanMessage(content='Fais-le'), *attempt(), AIMessage(content='Fait')]})
    assert out['conformity_unresolved']
    learn.assert_not_called()


@pytest.mark.asyncio
async def test_missing_judge_leaves_mission_unverified(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_llm_for_tier', lambda *_: None)
    out = await conf.conformity_node({'messages': [HumanMessage(content='Fais-le'), AIMessage(content='Fait')]})
    assert out['conformity_unresolved']


@pytest.mark.asyncio
async def test_panel_strategy_reenters_execution_only_once(monkeypatch):
    from app.agent.escalation import PanelResult
    monkeypatch.setattr('app.agent.escalation.escalate_to_panel', AsyncMock(return_value=PanelResult(
        answer='Utilise un autre convertisseur.', model='test-model', models_asked=2, cost_usd=0, skipped_for_budget=[])))
    messages = [HumanMessage(content='Convertis le fichier'), *attempt(), AIMessage(content='Incomplet')]
    out = await conf._try_escalation({'conformity_retries': 1}, messages, '- format manquant', 1, 1)
    assert isinstance(out['messages'][0], HumanMessage)
    assert out['conformity_escalated']
    assert out['conformity_unresolved']
    assert conf.route_after_conformity(out) == 'agent'


@pytest.mark.asyncio
async def test_memory_recall_on_opening_survives_one_store_failure(owners, monkeypatch):
    # 10/09/2026 : le dossier mémoire (`memory/context.py`) interroge ses
    # sources en parallèle ; une source en panne est signalée, les autres
    # restent lues — jamais un silence pris pour une absence de souvenirs.
    from app.services.memory import context as ctx
    from app.agent.builders.memory_snapshot import build_memory_snapshot

    async def offline(user_id, query):
        raise RuntimeError('offline')

    async def profil(user_id, query, scope):
        return [{'id': 'profile:1', 'text': 'projet: Projet lunaire, échéance vendredi', 'score': 1,
                 'scope': '', 'source': 'test · profil:1', 'observed_at': '2026-09-10', 'confirmed': True}]

    monkeypatch.setattr(ctx, 'vector_candidates', offline)
    monkeypatch.setattr(ctx, 'profile_candidates', profil)
    monkeypatch.setattr(ctx, 'document_candidates', AsyncMock(return_value=[]))
    snapshot, _ = await build_memory_snapshot(messages=[HumanMessage(content='Reprenons le projet')], user_id=owners[0],
        user_query='Reprenons le projet lunaire', memory=None, use_compact=False)
    assert 'Projet lunaire' in snapshot
    assert 'indisponibles : souvenirs' in snapshot


@pytest_asyncio.fixture
async def owners():
    from app.database import init_db, async_session
    from app.models.user import User
    await init_db()
    ids = [uuid.uuid4().hex, uuid.uuid4().hex]
    async with async_session() as db:
        db.add_all([User(id=uid, username=uid, email=f'{uid}@example.invalid', hashed_password='test-only') for uid in ids])
        await db.commit()
    return ids


@pytest.mark.asyncio
async def test_error_memory_is_searchable_and_strictly_user_scoped(owners):
    from app.database import async_session
    from app.services.memory.error_store import ErrorStore
    from app.services.memory.inspection import list_entries, forget_entry
    store = ErrorStore()
    async with async_session() as db:
        own = await store.store(db, user_id=owners[0], tool_name='sheets_read', args_redacted={}, error_type='Timeout', error_msg='Slow request')
        other = await store.store(db, user_id=owners[1], tool_name='sheets_read', args_redacted={}, error_type='PrivateError', error_msg='Other user detail')
        await db.commit()
    results = await store.get_relevant('sheets_read', owners[0])
    assert len(results) == 1 and results[0]['error_type'] == 'Timeout'
    entries, _ = await list_entries('error', owners[0])
    assert [e.id for e in entries] == [str(own)]
    assert not await forget_entry('error', str(other), owners[0])
    assert await forget_entry('error', str(own), owners[0])
    assert not await store.get_relevant('sheets_read', owners[0])


@pytest.mark.asyncio
async def test_program_create_test_reuse_and_user_isolation(owners):
    from app.agent.tools.sandbox_tools import sandbox_save_tool, sandbox_run_tool
    from app.database import async_session
    from app.models.learned_skill import LearnedSkill
    from sqlalchemy import select
    source = 'def run(arguments):\n    return sum(arguments["numbers"])'
    out = await sandbox_save_tool.ainvoke({'name':'total', 'description':'Addition de valeurs', 'source':source,
        'tests_json':json.dumps([{'input':{'numbers':[1,2,3]},'expected':6},{'input':{'numbers':[]},'expected':0}]), 'user_id':owners[0]})
    assert out.startswith('Outil '), out
    name = out.split()[1]
    assert await sandbox_run_tool.ainvoke({'name':name,'arguments_json':'{"numbers":[7,8]}','user_id':owners[0]}) == '15'
    denied = await sandbox_run_tool.ainvoke({'name':name,'arguments_json':'{}','user_id':owners[1]})
    assert denied.startswith('Erreur')
    async with async_session() as db:
        skill = (await db.execute(select(LearnedSkill).where(LearnedSkill.user_id==owners[0],LearnedSkill.name==name))).scalar_one()
        assert skill.use_count == 1
        skill.content = 'import os\ndef run(arguments): return os.getcwd()'
        await db.commit()
    assert (await sandbox_run_tool.ainvoke({'name':name,'arguments_json':'{}','user_id':owners[0]})).startswith('Erreur : programme refusé')


@pytest.mark.asyncio
async def test_wrong_expected_result_is_not_saved(owners):
    from app.agent.tools.sandbox_tools import sandbox_save_tool
    out = await sandbox_save_tool.ainvoke({'name':'wrong','description':'Test failure','source':'def run(arguments): return 7',
        'tests_json':'[{"input":{},"expected":8}]','user_id':owners[0]})
    assert out.startswith('Erreur : tests non validés'), out


@pytest.mark.parametrize('source', ['import os\ndef run(arguments): return 1',
    'from app.services.learning.learned_tool_dispatch import call_tool\ndef run(arguments): return 1',
    'def run(arguments): return arguments.__class__', 'def run(arguments): return eval("1")'])
def test_program_rejects_host_and_network_escape_paths(source):
    from app.agent.tools.sandbox_tools import validate_program
    assert validate_program(source)


@pytest.mark.asyncio
async def test_cancelling_a_computation_reaps_its_process(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.agent.tools.python_tool import python_execute
    proc = SimpleNamespace(returncode=None, kill=Mock(), communicate=AsyncMock(
        side_effect=[asyncio.CancelledError(), (b'', b'')]))
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=proc))
    with pytest.raises(asyncio.CancelledError):
        await python_execute.ainvoke({'code': 'print(1)'})
    proc.kill.assert_called_once()
    assert proc.communicate.await_count == 2


@pytest.mark.parametrize('source', [
    'def run(arguments):\n    reader = open\n    return reader("/etc/hosts").read()',
    'import re\ndef run(arguments): return re._compiler',
    'from collections import _sys\ndef run(arguments): return 1',
    'import json.tool\ndef run(arguments): return 1',
])
def test_program_rejects_alias_and_internal_module_traversal(source):
    from app.agent.tools.sandbox_tools import validate_program
    assert validate_program(source)

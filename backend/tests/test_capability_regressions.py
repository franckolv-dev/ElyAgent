"""Regression: an existing tool must remain reachable when a cloud judge fails."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from app.agent.conformity import conformity_node, route_after_conformity, _invoke_judge
from app.agent.nodes import _slm_toolset, _slm_discovered_extras
from app.agent import discovered_tools


def registry(*names):
    return SimpleNamespace(all_tools=[SimpleNamespace(name=n) for n in names])


@pytest.mark.parametrize(('query', 'anchor', 'action'), [
    ('Supprime les mails que je me suis envoyé', 'gmail_list_emails', 'gmail_trash_emails'),
    ('Tu as les outils pour mettre ces mails à la corbeille', 'gmail_list_emails', 'gmail_trash_emails'),
    ('Lis et résume mes mails', 'gmail_list_emails', 'gmail_read_email'),
    ('Supprime ce rendez-vous de mon agenda', 'calendar_list_events', 'calendar_delete_event'),
    ('Modifie cette tâche', 'tasks_list', 'tasks_update'),
    ('Supprime ma note de test', 'notes_create', 'notes_delete'),
])
def test_actions_are_bound_alongside_the_reader(query, anchor, action):
    r = registry('find_tool', anchor, action, 'qrcode_generate')
    assert {t.name for t in _slm_toolset(r, query)} == {'find_tool', anchor, action}


def test_discovered_conditional_tool_survives_a_follow_up():
    conv = 'conditional-follow-up'
    discovered_tools.add_discovered(conv, ['gmail_list_emails', 'find_tool'])
    try:
        extra = _slm_discovered_extras(registry('find_tool', 'gmail_list_emails'), conv, 'Oui, continue')
        assert [t.name for t in extra] == ['gmail_list_emails']
    finally:
        discovered_tools.discard_discovered(conv)


@pytest.mark.asyncio
async def test_denial_recovers_without_any_cloud_judge(monkeypatch):
    judge = AsyncMock(side_effect=RuntimeError('expired token'))
    monkeypatch.setattr('app.agent.conformity.ainvoke_with_deadline', judge)
    request = 'Supprime mes mails de test'
    state = {'messages': [HumanMessage(content=request), AIMessage(content="Je n’ai pas d’outil pour supprimer les emails.")]}
    update = await conformity_node(state)
    judge.assert_not_called()
    call = update['messages'][-1].tool_calls[0]
    assert call['name'] == 'find_tool' and call['args']['capability'] == request
    assert route_after_conformity(update) == 'tools'


@pytest.mark.asyncio
async def test_discovery_is_bounded_within_the_current_turn(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_llm_for_tier', lambda *_: None)
    messages = [HumanMessage(content='Supprime mes mails'),
        AIMessage(content='', tool_calls=[{'name':'find_tool','args':{'capability':'mails'},'id':'capability-test'}]),
        ToolMessage(content='Aucun résultat', name='find_tool', tool_call_id='capability-test'),
        AIMessage(content="Je n'ai pas d'outil.")]
    result = await conformity_node({'messages': messages})
    assert result['messages'] == [] and result['conformity_unresolved']


@pytest.mark.asyncio
async def test_previous_turn_lookup_does_not_disable_recovery(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_llm_for_tier', lambda *_: None)
    messages = [HumanMessage(content='Météo'),
        AIMessage(content='', tool_calls=[{'name':'find_tool','args':{},'id':'capability-old'}]),
        ToolMessage(content='weather_get', name='find_tool', tool_call_id='capability-old'),
        HumanMessage(content='Lis mes mails'), AIMessage(content="Je ne dispose d’aucun outil pour les mails.")]
    result = await conformity_node({'messages':messages,'capability_lookup_forced':True})
    assert result['messages'][0].tool_calls[0]['name'] == 'find_tool'


@pytest.mark.asyncio
async def test_search_for_one_part_does_not_cover_the_other_parts(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_llm_for_tier', lambda *_: None)
    messages = [HumanMessage(content='Lis mes mails et donne la météo'),
        ToolMessage(content='gmail_list_emails', name='find_tool', tool_call_id='manual-search'),
        AIMessage(content="Je n'ai pas d'outil pour la météo.")]
    result = await conformity_node({'messages':messages})
    assert result['messages'][0].tool_calls[0]['name'] == 'find_tool'


@pytest.mark.asyncio
async def test_expired_judge_uses_next_configured_provider(monkeypatch):
    primary, fallback = SimpleNamespace(name='expired'), SimpleNamespace(name='working')
    monkeypatch.setattr('app.services.llm_provider.describe_llm', lambda m: ('provider', m.name))
    monkeypatch.setattr('app.services.llm_provider.get_tier_config', lambda: {'complex': {'providers': ['p1', 'p2'], 'fallback_enabled': True}})
    monkeypatch.setattr('app.services.llm_provider.build_llm_for_provider', lambda p, *_: primary if p == 'p1' else fallback)
    invoke = AsyncMock(side_effect=[RuntimeError('401 token_expired'), AIMessage(content='CONFORME')])
    monkeypatch.setattr('app.agent.conformity.ainvoke_with_deadline', invoke)
    response, used = await _invoke_judge(primary, 'test', {})
    assert response.content == 'CONFORME' and used is fallback
    assert [c.args[0] for c in invoke.call_args_list] == [primary, fallback]


@pytest.mark.asyncio
async def test_disabled_fallback_does_not_call_another_provider(monkeypatch):
    monkeypatch.setattr('app.services.llm_provider.get_tier_config', lambda: {'complex': {'providers': ['p1', 'p2'], 'fallback_enabled': False}})
    build = AsyncMock()
    monkeypatch.setattr('app.services.llm_provider.build_llm_for_provider', build)
    monkeypatch.setattr('app.agent.conformity.ainvoke_with_deadline', AsyncMock(side_effect=RuntimeError('401')))
    with pytest.raises(RuntimeError): await _invoke_judge(SimpleNamespace(name='bad'), 'test', {})
    build.assert_not_called()

"""An incident correction reaches future tool bindings, not just its status."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from tests.test_patch_service import _seed_user, _seed_scheduled_incident, _db
from app.services.learning import binding_repair as repair
from app.services.learning.patch_service import propose_patch, apply_patch, revert_patch, PatchError
from app.database import async_session
from app.models.execution_outcome import ExecutionOutcome
from app.routers.learning_skills import list_incidents


@pytest.fixture
def tools(monkeypatch):
    names = ['find_tool', 'report_missing_capability', 'web_search', 'gmail_list_emails',
             'gmail_read_email', 'calendar_list_events', 'weather_get', 'news_get_headlines', 'qrcode_generate']
    tools = [SimpleNamespace(name=n) for n in names]
    monkeypatch.setattr('app.skills.registry.get_skill_registry', lambda: SimpleNamespace(all_tools=tools))
    return tools


@pytest.mark.asyncio
async def test_repair_persists_for_matching_requests_and_can_be_undone(tools):
    uid = await _seed_user()
    query = 'Résume mes mails, mon agenda, les news IA et la météo.'
    tid, _, did = await _seed_scheduled_incident(uid, prompt=query, category='binding')
    patch = await propose_patch(did)
    assert patch.kind == 'tool_binding' and patch.status == 'proposed'
    assert await repair.tools_for_request(uid, query, tools) == []
    names = set(json.loads(patch.new_value)['tools'])
    assert {'calendar_list_events', 'gmail_list_emails', 'gmail_read_email', 'weather_get', 'news_get_headlines'} <= names
    assert 'qrcode_generate' not in names
    assert (await propose_patch(did)).id == patch.id
    await apply_patch(patch.id)
    # A new session reads the persisted rule, with no conversation registry.
    bound = await repair.tools_for_request(uid, 'Aujourd’hui : '+query, tools)
    assert {t.name for t in bound} == names
    assert await repair.tools_for_request('another-user', query, tools) == []
    assert await repair.tools_for_request(uid, 'Crée un QR code', tools) == []
    with pytest.raises(PatchError): await apply_patch(patch.id)
    await revert_patch(patch.id)
    assert await repair.tools_for_request(uid, query, tools) == []


@pytest.mark.asyncio
async def test_applied_is_not_success_and_later_outcomes_are_visible(tools):
    uid = await _seed_user()
    tid, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda et mes mails', category='binding')
    patch = await propose_patch(did)
    await apply_patch(patch.id)
    async def rows():
        async with async_session() as db:
            return await list_incidents(status='all', user_id=uid, limit=100, _admin=SimpleNamespace(id='admin'), db=db)
    assert (await rows())[0].repair_verification == 'pending'
    for index, outcome in enumerate(['failed', 'succeeded']):
        async with async_session() as db:
            from app.models.conversation import Conversation, Message
            conv = Conversation(user_id=uid, title='Execution test')
            db.add(conv)
            await db.flush()
            db.add(Message(conversation_id=conv.id, role='user', content='Mon agenda et mes mails'))
            db.add(ExecutionOutcome(user_id=uid,source='scheduled',source_id=tid,conversation_id=conv.id,outcome=outcome,
                created_at=datetime.now(timezone.utc)+timedelta(seconds=index+1)))
            await db.commit()
        assert (await rows())[0].repair_verification == outcome


@pytest.mark.asyncio
async def test_provider_issue_does_not_offer_a_fake_prompt_repair(tools):
    uid = await _seed_user()
    _, _, did = await _seed_scheduled_incident(uid, category='config_tier')
    with pytest.raises(PatchError): await propose_patch(did)
    async with async_session() as db:
        rows = await list_incidents(status='open',user_id=uid,limit=100,_admin=SimpleNamespace(id='admin'),db=db)
    assert not rows[0].repair_available


@pytest.mark.asyncio
async def test_catalogue_changes_are_checked_at_application(tools):
    uid = await _seed_user()
    _, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda',category='binding')
    patch = await propose_patch(did)
    tools[:] = [t for t in tools if t.name != 'calendar_list_events']
    with pytest.raises(PatchError): await apply_patch(patch.id)


@pytest.mark.asyncio
async def test_disabled_tools_are_not_reenabled(tools, monkeypatch):
    uid = await _seed_user()
    _, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda et mes mails', category='binding')
    async def disabled(_): return {'calendar_list_events'}
    monkeypatch.setattr('app.skills.preferences_runtime.disabled_tool_names', disabled)
    patch = await propose_patch(did)
    assert 'calendar_list_events' not in json.loads(patch.new_value)['tools']
    async def changed(_): return {'gmail_list_emails'}
    monkeypatch.setattr('app.skills.preferences_runtime.disabled_tool_names', changed)
    with pytest.raises(PatchError): await apply_patch(patch.id)


@pytest.mark.asyncio
async def test_no_generic_binding_is_presented_as_a_missing_capability_fix(tools):
    uid = await _seed_user()
    _, _, did = await _seed_scheduled_incident(uid, prompt='Répare physiquement mon aspirateur', category='binding')
    with pytest.raises(PatchError, match='Aucun outil existant identifié'):
        await propose_patch(did)


@pytest.mark.asyncio
async def test_changed_task_does_not_falsely_verify_a_repair(tools):
    from app.models.scheduled_task import ScheduledTask
    uid = await _seed_user()
    tid, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda', category='binding')
    patch = await propose_patch(did)
    await apply_patch(patch.id)
    async with async_session() as db:
        task = await db.get(ScheduledTask, tid)
        task.prompt = 'Une demande différente'
        db.add(ExecutionOutcome(user_id=uid,source='scheduled',source_id=tid,outcome='succeeded',
            created_at=datetime.now(timezone.utc)+timedelta(seconds=1)))
        await db.commit()
        rows = await list_incidents(status='open',user_id=uid,limit=100,_admin=SimpleNamespace(id='admin'),db=db)
    assert rows[0].repair_verification == 'pending'


@pytest.mark.asyncio
async def test_stale_proposal_cannot_be_applied(tools):
    from app.models.scheduled_task import ScheduledTask
    uid = await _seed_user()
    tid, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda', category='binding')
    patch = await propose_patch(did)
    async with async_session() as db:
        task = await db.get(ScheduledTask, tid)
        task.prompt = 'Une autre demande'
        await db.commit()
    with pytest.raises(PatchError, match='demande a changé'):
        await apply_patch(patch.id)


@pytest.mark.asyncio
async def test_malformed_binding_does_not_disable_other_repairs(tools):
    from app.models.proposed_patch import ProposedPatch
    uid = await _seed_user()
    _, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda', category='binding')
    patch = await propose_patch(did)
    await apply_patch(patch.id)
    async with async_session() as db:
        db.add(ProposedPatch(user_id=uid, execution_diagnosis_id=did, kind='tool_binding',
            target_type='user_request', target_id='invalid', field='tools', new_value='[]', status='applied'))
        await db.commit()
    assert 'calendar_list_events' in {t.name for t in await repair.tools_for_request(uid, 'Mon agenda', tools)}


@pytest.mark.asyncio
async def test_verification_uses_executed_prompt_not_current_task(tools):
    from app.models.conversation import Conversation, Message
    uid = await _seed_user()
    tid, _, did = await _seed_scheduled_incident(uid, prompt='Mon agenda', category='binding')
    patch = await propose_patch(did)
    await apply_patch(patch.id)
    async with async_session() as db:
        conv = Conversation(user_id=uid, title='Different execution')
        db.add(conv)
        await db.flush()
        db.add(Message(conversation_id=conv.id, role='user', content='Une autre demande exécutée'))
        db.add(ExecutionOutcome(user_id=uid,source='scheduled',source_id=tid,conversation_id=conv.id,
            outcome='succeeded',created_at=datetime.now(timezone.utc)+timedelta(seconds=1)))
        await db.commit()
        rows = await list_incidents(status='open',user_id=uid,limit=100,_admin=SimpleNamespace(id=uid),db=db)
    assert rows[0].repair_verification == 'pending'

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from tests.test_patch_service import _db, _seed_user, _fake_admin
from app.database import async_session
from app.models.user_memory import UserProfile
from app.models.memory_context import MemorySelection, MemoryVersion
from app.services.memory.selection import needs_recall, eligible_payload, fuse_ranks, pack, tokens, REQUEST_SCOPE
from app.services.memory.context import profile_candidates, dossier, work_state
from app.services.memory._base import BaseStore


@pytest.mark.parametrize('query', ['Bonjour !','Combien font 7 × 8 ?', 'Peux-tu me dire : combien font 7 fois 8 ?', '42 + 67', 'Merci beaucoup'])
def test_no_memory_for_self_contained_query(query):
    assert not needs_recall(query)


@pytest.mark.parametrize('query', ['Reprends ma mission', 'Mon ancienne adresse ?', 'Bonjour, où sont mes factures ?', 'Et la suite ?', 'Rappelle-moi mes préférences'])
def test_contextual_requests_keep_recall(query):
    assert needs_recall(query)


@pytest.mark.parametrize('payload,scope,expected', [
    ({'user_id':'other'},'',False), ({'user_id':'u'},'',True),
    ({'user_id':'u','scope':'mission:A'},'mission:B',False),
    ({'user_id':'u','scope':'mission:A'},'mission:A',True),
    ({'user_id':'u','scope':'account:A'},'account:B',False),
    ({'user_id':'u','superseded':True},'',False),
    ({'user_id':'u','forgotten':True},'',False),
    ({'user_id':'u','expires_at':'2000-01-01'},'',False),
    ({'user_id':'u','expires_at':'broken'},'',False),
    ({'user_id':'u','created_at':'1990-01-01'},'',True),
])
def test_access_validity_before_model(payload,scope,expected):
    assert eligible_payload(payload,'u',scope) is expected


def test_rrf_union_not_intersection():
    result = dict(fuse_ranks([['dense','both'],['exact','both']]))
    assert set(result)=={'dense','both','exact'}
    assert result['both']>result['exact']


def test_budget_dedup_diversity_and_mandatory():
    items=[{'id':str(i),'source':'one' if i<7 else str(i),'text':f'Information {i} '+('é ' * 40)} for i in range(12)]
    text, selected=pack(items+items,350,'Accusé confirmé R42. Envoi R43 incertain, ne pas répéter.')
    assert tokens(text)<=350
    assert 'R42' in text and 'R43' in text
    assert sum(r['source']=='one' for r in selected)<=2
    assert len({r['id'] for r in selected})==len(selected)
    with pytest.raises(ValueError): pack(items,2,'État obligatoire trop long')


@pytest.mark.asyncio
async def test_fts_only_is_retrieved_and_other_owner_dropped(monkeypatch):
    monkeypatch.setattr('app.services.fts_store.get_fts_store',lambda:SimpleNamespace(search=AsyncMock(return_value=['exact','wrong'])))
    infra=SimpleNamespace(qdrant_candidates=AsyncMock(return_value=[]), points_by_ids=AsyncMock(return_value=[SimpleNamespace(id='exact',payload={'user_id':'u','content':'FAC-42'}),SimpleNamespace(id='wrong',payload={'user_id':'other','content':'secret'})]))
    hits=await BaseStore(infra)._search_hybrid('memories','FAC-42',[0.], 'u',3,.45,['content'])
    assert [h.id for h in hits]==['exact']
    assert infra.points_by_ids.call_args.args[2]=='u'


@pytest.mark.asyncio
async def test_profile_beyond_200_and_scope_and_expiry():
    uid=await _seed_user()
    async with async_session() as db:
        db.add_all([UserProfile(user_id=uid,key=f'noise{i}',value='Jardin') for i in range(230)])
        db.add_all([UserProfile(user_id=uid,key='facture_reference',value='FAC-42 dans Archives'),UserProfile(user_id=uid,key='facture_secret',value='FAC-42 confidentiel',scope='mission:B'), UserProfile(user_id=uid,key='facture_expire',value='FAC-42 périmé',expires_at=datetime.now(timezone.utc)-timedelta(days=1))])
        await db.commit()
    found=await profile_candidates(uid,'Où est la facture FAC-42 ?', '')
    assert any('Archives' in r['text'] for r in found)
    assert not any('confidentiel' in r['text'] or 'périmé' in r['text'] for r in found)


@pytest.mark.asyncio
async def test_topic_changes_same_conversation_and_correction_immediate(monkeypatch):
    monkeypatch.setattr("app.services.memory.editing.remove_profile_index", AsyncMock())
    uid=await _seed_user()
    async with async_session() as db:
        a=UserProfile(user_id=uid,key='adresse',value='Lyon')
        b=UserProfile(user_id=uid,key='repas',value='végétarien')
        db.add_all([a,b]);await db.commit()
    monkeypatch.setattr('app.services.memory.context.vector_candidates',AsyncMock(return_value=[]))
    monkeypatch.setattr('app.services.memory.context.document_candidates',AsyncMock(return_value=[]))
    monkeypatch.setattr('app.services.learning.active_skills.get_active_skills_for_user',AsyncMock(return_value=[]))
    first=await dossier(uid,'Mon adresse ?', 'same')
    second=await dossier(uid,'Quel repas ?', 'same')
    assert 'Lyon' in first and 'végétarien' not in first
    assert 'végétarien' in second and 'Lyon' not in second
    from app.services.memory.editing import edit, forget_profile
    assert await edit(uid,'profile',str(a.id),'Rennes','',True)
    assert 'Rennes' in await dossier(uid,'Mon adresse ?', 'same')
    assert await forget_profile(uid,str(a.id))
    assert 'Rennes' not in await dossier(uid,'Mon adresse ?', 'same')


@pytest.mark.asyncio
async def test_mission_state_keeps_proof_and_uncertain_across_restart():
    from tests.test_mission_assurance import mission
    from app.services.mission_assurance import reserve, finish
    m=await mission()
    proof,_=await reserve(m.id,m.user_id,'web_search',{'query':'demo'})
    await finish(proof,True,'Document rapport.pdf confirmé')
    uncertain,_=await reserve(m.id,m.user_id,'gmail_send_email',{'to':'example@example.test'})
    text,scope=await work_state(m.user_id,m.id)
    value=json.loads(text)
    assert value['last_verified_step']['receipt']==proof
    assert uncertain in value['uncertain_receipts']
    assert value['uncertain_count']==1
    assert 'aucune écriture' in value['next_step']
    assert await work_state(await _seed_user(),m.id)==('','')


@pytest.mark.asyncio
async def test_empty_memory_journal_and_ownership(monkeypatch):
    uid=await _seed_user()
    mocked=AsyncMock(side_effect=AssertionError('No retrieval for arithmetic'))
    monkeypatch.setattr('app.services.memory.context.vector_candidates',mocked)
    assert await dossier(uid,'7 × 8','c')==''
    from app.routers.memory import selections
    rows=await selections(_fake_admin(uid))
    assert rows[0]['tokens']==0 and rows[0]['selected']==[]
    assert await selections(_fake_admin(await _seed_user()))==[]


@pytest.mark.asyncio
async def test_version_trigger_and_forget_removes_history():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import text
    path=Path(__file__).resolve().parents[1]/'migrations/versions/0039_memory_context.py'
    spec=importlib.util.spec_from_file_location('migration_memory',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from app.database import engine
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async with engine.begin() as conn:
        def upgrade(sync):
            with Operations.context(MigrationContext.configure(sync)): module.upgrade()
        await conn.run_sync(upgrade)
    uid=await _seed_user()
    async with async_session() as db:
        p=UserProfile(user_id=uid,key='adresse',value='Paris');db.add(p);await db.commit()
        p.value='Lyon';await db.commit()
    found=await profile_candidates(uid,'Mon ancienne adresse ?', '')
    assert any('Paris' in r['text'] and 'Ancienne valeur' in r['text'] for r in found)
    from app.services.memory.editing import forget_profile
    assert await forget_profile(uid,str(p.id))
    async with async_session() as db:
        assert not (await db.execute(select(MemoryVersion).where(MemoryVersion.user_id==uid))).scalars().all()


def test_tool_budget_keeps_discovery_repairs_and_discovered():
    from langchain_core.tools import tool
    from app.agent.tool_budget import fit_tool_schemas
    tools=[]
    for name in ['find_tool','skill_view','repaired','discovered','optional']:
        def impl(value:str)->str: return value
        tools.append(tool(name,description='Description '+('longue '*100))(impl))
    selected=fit_tool_schemas(tools,'demande',{'repaired','discovered'},10)
    assert {t.name for t in selected}=={'find_tool','skill_view','repaired','discovered'}

@pytest.mark.asyncio
async def test_cache_owner_scope_version_and_mutation():
    from app.services.memory.query_cache import get_or_load, invalidate
    loader=AsyncMock(return_value=[{'id':'a','text':'ancien'}])
    assert (await get_or_load('u1','mission:A','adresse','test',loader))[0]['text']=='ancien'
    await get_or_load('u1','mission:A','adresse','test',loader)
    assert loader.await_count==1
    await get_or_load('u1','mission:B','adresse','test',loader)
    await get_or_load('u2','mission:A','adresse','test',loader)
    assert loader.await_count==3
    invalidate('u1')
    loader.return_value=[{'id':'a','text':'corrigé'}]
    assert (await get_or_load('u1','mission:A','adresse','test',loader))[0]['text']=='corrigé'
    assert loader.await_count==4


@pytest.mark.asyncio
async def test_checkpoint_idempotency_after_restart_and_forget(monkeypatch):
    from app.services.memory.consolidation import save_episode
    from app.models.memory_context import MemoryCheckpoint
    from unittest.mock import Mock
    uid=await _seed_user()
    client=SimpleNamespace(upsert=Mock())
    infra=SimpleNamespace(client=client,embed=AsyncMock(return_value=[0.]*384))
    monkeypatch.setattr('app.services.memory._infra.get_memory_infra',lambda:infra)
    monkeypatch.setattr('app.services.fts_store.get_fts_store',lambda:SimpleNamespace(store=AsyncMock()))
    key='unit:'+uuid.uuid4().hex
    assert await save_episode(uid,key,'v1','preuve','source')
    assert not await save_episode(uid,key,'v1','preuve','source')
    assert client.upsert.call_count==1
    async with async_session() as db:
        row=await db.get(MemoryCheckpoint,key);row.value='forgotten';await db.commit()
    assert not await save_episode(uid,key,'v2','nouvelle preuve','source')
    assert client.upsert.call_count==1


@pytest.mark.asyncio
async def test_account_scope_uses_owner_and_explicit_alias():
    from app.models.google_account import GoogleAccount
    from app.services.memory.scopes import account_scope
    from app.services.memory.editing import validate_scope
    uid=await _seed_user(); other=await _seed_user()
    async with async_session() as db:
        account=GoogleAccount(user_id=uid,alias='bureau',email='bureau@example.test',credentials_json='{}')
        db.add(account);await db.commit()
    assert await account_scope(uid,'Utilise mon compte bureau')==f'account:{account.id}'
    assert await account_scope(other,'Utilise mon compte bureau')==''
    assert await account_scope(uid,'Travail au bureau')==''
    with pytest.raises(ValueError): await validate_scope(other,f'account:{account.id}')

@pytest.mark.asyncio
async def test_cached_vector_hydrates_canonical_scope_expiry_and_owner():
    from app.services.memory.context import hydrate_candidates
    uid=await _seed_user();other=await _seed_user()
    async with async_session() as db:
        row=UserProfile(user_id=uid,key='adresse',value='Valeur corrigée',scope='mission:B')
        db.add(row);await db.commit()
    candidate={'id':f'profile:{row.id}','text':'Valeur périmée','source':'index','_profile_id':row.id,'scope':''}
    assert await hydrate_candidates(uid,'mission:A',[candidate])==[]
    assert await hydrate_candidates(other,'mission:B',[candidate])==[]
    result=await hydrate_candidates(uid,'mission:B',[candidate])
    assert 'Valeur corrigée' in result[0]['text'] and 'périmée' not in result[0]['text']


@pytest.mark.asyncio
async def test_scope_specific_values_of_same_profile_key():
    uid=await _seed_user()
    async with async_session() as db:
        db.add_all([UserProfile(user_id=uid,key='dossier',value='Compte A',scope='account:A'),UserProfile(user_id=uid,key='dossier',value='Compte B',scope='account:B')]);await db.commit()
    assert [r['text'] for r in await profile_candidates(uid,'Quel dossier ?', 'account:A')]==['dossier: Compte A']

@pytest.mark.asyncio
async def test_background_failures_are_checkpointed_and_bounded(monkeypatch):
    from app.models.memory_context import MemoryCheckpoint
    from app.services.memory.consolidation import drain_pending
    uid=await _seed_user();key='conversation:'+uuid.uuid4().hex
    async with async_session() as db:
        db.add(MemoryCheckpoint(key=key,value=json.dumps({'status':'pending','user_id':uid,'conversation_id':'test','attempts':0})));await db.commit()
    fake=SimpleNamespace(consolidate=AsyncMock(side_effect=RuntimeError('local model offline')))
    monkeypatch.setattr('app.services.memory.maintenance_rapid.get_maintenance_agent_rapid',lambda:fake)
    for _ in range(4): await drain_pending()
    assert fake.consolidate.await_count==3
    async with async_session() as db:
        data=json.loads((await db.get(MemoryCheckpoint,key)).value)
    assert data['status']=='failed' and data['attempts']==3

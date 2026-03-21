import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.auth.jwt import decode_token
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.security_filter import SecurityFilter
from app.services import ws_registry

router = APIRouter()

# One graph instance shared across all connections
_agent_graph = None

# One SecurityFilter per conversation (persists placeholders within a session)
_filters: dict[str, SecurityFilter] = {}


def get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

    await websocket.accept()
    ws_registry.register(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            user_content = msg.get("content", "")
            conversation_id = msg.get("conversation_id")

            async with async_session() as db:
                if not conversation_id:
                    conv = Conversation(user_id=user_id, title=user_content[:50])
                    db.add(conv)
                    await db.flush()
                    conversation_id = conv.id
                    await db.commit()

                user_msg = Message(
                    conversation_id=conversation_id, role="user", content=user_content
                )
                db.add(user_msg)
                await db.commit()

            # Anonymize input through per-conversation filter
            sf = _filters.setdefault(conversation_id, SecurityFilter())
            clean_content = sf.anonymize(user_content)

            agent = get_agent()
            await websocket.send_text(json.dumps({
                "type": "start",
                "conversation_id": conversation_id,
            }))

            result = await agent.ainvoke({
                "messages": [HumanMessage(content=clean_content)],
                "user_id": user_id,
                "conversation_id": conversation_id,
            })

            ai_content = result["messages"][-1].content
            # Restore real values in the response
            ai_content = sf.deanonymize(ai_content)

            async with async_session() as db:
                ai_msg = Message(
                    conversation_id=conversation_id, role="assistant", content=ai_content
                )
                db.add(ai_msg)
                await db.commit()

            await websocket.send_text(json.dumps({
                "type": "message",
                "role": "assistant",
                "content": ai_content,
                "conversation_id": conversation_id,
            }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_text(json.dumps({"type": "error", "content": str(e)}))
    finally:
        ws_registry.unregister(user_id)
        # Evict the filter for the current conversation to avoid unbounded growth.
        # A new filter will be created if the user reconnects to the same conversation.
        if conversation_id:
            _filters.pop(conversation_id, None)

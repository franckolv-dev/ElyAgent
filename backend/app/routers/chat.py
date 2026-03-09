import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage

from app.auth.jwt import decode_token
from app.database import get_db, async_session
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.agent.graph import build_agent_graph

router = APIRouter()

agent_graph = None


def get_agent():
    global agent_graph
    if agent_graph is None:
        agent_graph = build_agent_graph()
    return agent_graph


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    # Auth via query param
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
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            user_content = msg.get("content", "")
            conversation_id = msg.get("conversation_id")

            async with async_session() as db:
                # Create or get conversation
                if not conversation_id:
                    conv = Conversation(user_id=user_id, title=user_content[:50])
                    db.add(conv)
                    await db.flush()
                    conversation_id = conv.id
                    await db.commit()

                # Save user message
                user_msg = Message(
                    conversation_id=conversation_id, role="user", content=user_content
                )
                db.add(user_msg)
                await db.commit()

            # Run agent
            agent = get_agent()
            await websocket.send_text(json.dumps({
                "type": "start",
                "conversation_id": conversation_id,
            }))

            result = await agent.ainvoke({
                "messages": [HumanMessage(content=user_content)],
                "user_id": user_id,
                "conversation_id": conversation_id,
            })

            ai_content = result["messages"][-1].content

            # Save assistant message
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

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    # LOW-1: Do not expose service name or version to unauthenticated callers
    return {"status": "ok"}

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Uygulama açılırken bir kez çalışır: veritabanı tablolarını hazırlar."""
    init_db()
    yield


app = FastAPI(title="SecureKnowledge AI", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Uygulamanın ayakta olduğunu gösterir; sır veya iç ayrıntı döndürmez."""
    return {"status": "ok"}

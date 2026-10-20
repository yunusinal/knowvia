from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, documents
from app.db.session import init_db
from app.repositories.vector_store import get_vector_store


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Açılışta veritabanı tablolarını hazırlar; kapanışta Qdrant'ın klasör kilidini bırakır."""
    init_db()
    yield
    # Vektör deposu yalnızca ilk kullanıldığında açılır; açılmadıysa kapatılacak bir şey yok.
    if get_vector_store.cache_info().currsize:
        get_vector_store().close()


app = FastAPI(title="Knowvia", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(documents.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Uygulamanın ayakta olduğunu gösterir; sır veya iç ayrıntı döndürmez."""
    return {"status": "ok"}

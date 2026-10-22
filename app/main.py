from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import auth, chat, conversations, documents
from app.db.session import init_db
from app.repositories.vector_store import get_vector_store
from app.services.llm import LLMUnavailableError


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
app.include_router(chat.router)
app.include_router(conversations.router)


@app.exception_handler(LLMUnavailableError)
def llm_unavailable(_request: Request, error: LLMUnavailableError) -> JSONResponse:
    """Sağlayıcı hatası 503 olur; mesaj zaten güvenli (anahtar veya ham cevap içermez)."""
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    """Uygulamanın ayakta olduğunu gösterir; sır veya iç ayrıntı döndürmez."""
    return {"status": "ok"}

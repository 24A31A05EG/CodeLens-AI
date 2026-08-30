from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import init_db
from routers import ask, diagram, docs, explain, history, structure, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CodeLens AI API", lifespan=lifespan)

# Allow frontend dev servers and clients during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGIN", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(upload.router, tags=["upload"])
app.include_router(structure.router, prefix="/projects", tags=["structure"])
app.include_router(explain.router, prefix="/explain", tags=["explain"])
app.include_router(docs.router, prefix="/generate-docs", tags=["docs"])
app.include_router(diagram.router, prefix="/generate-diagram", tags=["diagram"])
app.include_router(history.router, tags=["history"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])

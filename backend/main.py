"""Cloud Agent v2 — FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import agent, audit, health, manifest, learn, certifications

app = FastAPI(title="Cloud Agent AWS v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "file://"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(agent.router,    prefix="/agent")
app.include_router(audit.router,    prefix="/audit")
app.include_router(manifest.router, prefix="/manifest")
app.include_router(learn.router,    prefix="/learn")
app.include_router(certifications.router, prefix="/certifications")

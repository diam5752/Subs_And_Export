import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.security import SecurityMiddleware

from .app.api.endpoints import auth, videos, tiktok, history
from .app import config

app = FastAPI(
    title="Greek Sub Publisher API",
    description="Backend API for Greek Sub Publisher Video Processing",
    version="2.0.0"
)


def _env_list(key: str, default: list[str]) -> list[str]:
    value = os.getenv(key)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

# Configure CORS
default_origins = [
    "http://localhost:3000",  # Next.js frontend
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
origins = _env_list("GSP_ALLOWED_ORIGINS", default_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

trusted_hosts = _env_list(
    "GSP_TRUSTED_HOSTS",
    ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

# Harden default security headers; CSP is conservative for API-only responses
app.add_middleware(
    SecurityMiddleware,
    sts_seconds=63072000,
    sts_include_subdomains=True,
    sts_preload=True,
    frame_deny=True,
    referrer_policy="strict-origin-when-cross-origin",
    content_security_policy="default-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'",
)

if os.getenv("GSP_FORCE_HTTPS", "0") == "1":
    app.add_middleware(HTTPSRedirectMiddleware)

# Mount Static Files (Uploads/Artifacts)
# config.PROJECT_ROOT is backend/app
DATA_DIR = config.PROJECT_ROOT.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=DATA_DIR), name="static")

# Include Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(videos.router, prefix="/videos", tags=["videos"])
app.include_router(tiktok.router, prefix="/tiktok", tags=["tiktok"])
app.include_router(history.router, prefix="/history", tags=["history"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "greek-sub-publisher-api"}

@app.get("/")
async def root():
    return {"message": "Welcome to the Greek Sub Publisher API"}


from contextlib import asynccontextmanager

from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import setup_logging

# Configure logging (JSON structured)
logger = setup_logging()

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from secure import (
    ContentSecurityPolicy,
    ReferrerPolicy,
    Secure,
    StrictTransportSecurity,
    XContentTypeOptions,
    XFrameOptions,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.app.api.endpoints import auth, dev, history, videos
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.gcs import generate_signed_download_url, get_gcs_settings
from backend.app.core.ratelimit import get_client_ip, limiter_static


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.db = Database()
    yield
    # Shutdown
    db: Database | None = getattr(app.state, "db", None)
    if db is not None:
        db.dispose()

app = FastAPI(
    title="Greek Sub Publisher API",
    description="Backend API for Greek Sub Publisher Video Processing",
    version="2.0.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
    lifespan=lifespan,
)

# Register Global Exception Handlers
register_exception_handlers(app)






def _env_list(key: str, default: list[str]) -> list[str]:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return default
    value = os.getenv(key)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

# Configure CORS (secure-by-default in production)
default_origins = (
    [
        "http://localhost:3000",  # Next.js frontend
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]
    if settings.is_dev
    else []
)
origins = _env_list("GSP_ALLOWED_ORIGINS", default_origins)
if not settings.is_dev and not origins:
    raise RuntimeError("GSP_ALLOWED_ORIGINS must be set in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Enable GZip compression for responses > 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)

default_trusted_hosts = (
    ["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "testserver"]
    if settings.is_dev
    else ["*.run.app", "*.a.run.app"]
)
trusted_hosts = _env_list("GSP_TRUSTED_HOSTS", default_trusted_hosts)
if not settings.is_dev and "*" in trusted_hosts:
    raise RuntimeError("GSP_TRUSTED_HOSTS cannot include '*' in production")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

# Harden default security headers; CSP is conservative for API-only responses
SECURE_HEADERS = Secure(
    hsts=StrictTransportSecurity().max_age(63072000).include_subdomains().preload(),
    xfo=XFrameOptions().deny(),
    referrer=ReferrerPolicy().strict_origin_when_cross_origin(),
    csp=ContentSecurityPolicy()
    .default_src("'self'")
    .img_src("'self'", "data:")
    .media_src("'self'", "blob:")
    .connect_src("'self'"),
    xcto=XContentTypeOptions().nosniff(),
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, secure_headers: Secure) -> None:
        super().__init__(app)
        self.secure_headers = secure_headers

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        await self.secure_headers.set_headers_async(response)
        # Avoid sending HSTS on cleartext requests to keep local dev/proxy setups flexible.
        if settings.is_dev and request.url.scheme not in ("https", "wss"):
            if "Strict-Transport-Security" in response.headers:
                del response.headers["Strict-Transport-Security"]

        # Security: Disable caching for sensitive API endpoints to prevent data leakage in shared caches
        if request.url.path.startswith(("/auth/", "/videos/", "/history/", "/jobs/")):
            response.headers["Cache-Control"] = "no-store"

        return response


app.add_middleware(
    # Use the dedicated `secure` package to apply hardened headers.
    SecurityHeadersMiddleware,
    secure_headers=SECURE_HEADERS,
)

if os.getenv("GSP_FORCE_HTTPS", "0") == "1":
    app.add_middleware(HTTPSRedirectMiddleware)

# Trust proxy headers only from known proxy networks (Cloud Run / local dev).
# Added last (executed first) so request.client.host & scheme are correct.
proxy_trusted_hosts: list[str] | str = (
    "*"
    if settings.is_dev
    else _env_list(
        "GSP_PROXY_TRUSTED_HOSTS",
        [
            "127.0.0.1",
            "::1",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ],
    )
)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=proxy_trusted_hosts)

# Mount Static Files with Directory Listing
# settings.project_root is the project root, e.g. /path/to/Subs_And_Export_Project
# Use project_root/data for all artifacts (consistent with videos.py)
DATA_DIR = settings.data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

# LRU cache for signed URLs (5 min TTL, shorter than signed URL expiry)
import time as time_module

_signed_url_cache: dict[str, tuple[str, float]] = {}
_SIGNED_URL_CACHE_TTL = 300  # 5 minutes

def _get_cached_signed_url(object_name: str, gcs_settings) -> str:
    """Get signed URL from cache or generate new one."""
    now = time_module.time()
    if object_name in _signed_url_cache:
        url, expires = _signed_url_cache[object_name]
        if now < expires:
            return url

    # Generate new signed URL
    url = generate_signed_download_url(settings=gcs_settings, object_name=object_name)
    _signed_url_cache[object_name] = (url, now + _SIGNED_URL_CACHE_TTL)

    # Cleanup old entries (simple garbage collection)
    if len(_signed_url_cache) > 1000:
        expired = [k for k, (_, exp) in _signed_url_cache.items() if now >= exp]
        for k in expired:
            del _signed_url_cache[k]

    return url


@app.get("/static/{file_path:path}")
async def serve_static(request: Request, file_path: str, download: bool = False):
    # Rate limit static file access to prevent egress abuse
    ip = get_client_ip(request)
    limiter_static.check(ip)

    full_path = DATA_DIR / file_path

    # Security: Prevent path traversal
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if full_path.is_file():
        # Force download for video files or when download=true
        filename = full_path.name
        content_disposition = None
        if download or filename.endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv')):
            content_disposition = f'attachment; filename="{filename}"'
        return FileResponse(full_path, headers={"Content-Disposition": content_disposition} if content_disposition else None)

    if full_path.is_dir():
        # Security: Disable directory listing to prevent information disclosure
        raise HTTPException(status_code=404, detail="Not found")

    gcs_settings = get_gcs_settings()
    if gcs_settings:
        object_name = f"{gcs_settings.static_prefix}/{file_path.strip('/')}"
        try:
            signed_url = _get_cached_signed_url(object_name, gcs_settings)
            return RedirectResponse(url=signed_url, status_code=302)
        except Exception:
            pass

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raise HTTPException(status_code=404, detail="Not found")

# Include Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(videos.router, prefix="/videos", tags=["videos"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(dev.router, prefix="/dev", tags=["dev"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "greek-sub-publisher-api", "app_env": settings.app_env.value}

@app.get("/")
async def root():
    return {"message": "Welcome to the Greek Sub Publisher API"}

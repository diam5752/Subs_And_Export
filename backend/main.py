import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

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
from fastapi.responses import FileResponse
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
from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.app.api.endpoints import auth, billing, billing_admin, history, videos
from backend.app.api.endpoints.file_utils import sanitize_download_filename
from backend.app.api.endpoints.processing_tasks import (
    reconcile_stranded_cancellations,
)
from backend.app.core.auth import SessionStore, User
from backend.app.core.cleanup import retention_worker
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import configured_erasure_journal
from backend.app.core.ratelimit import get_client_ip, limiter_static
from backend.app.core.workspace_deletion import reclaim_abandoned_lifecycle_locks
from backend.app.services.consumer_contracts import (
    assert_consumer_contract_registry_approved,
)
from backend.app.services.jobs import JobStore
from backend.app.services.startup_recovery import reconcile_interrupted_media_jobs


def assert_runtime_billing_configuration() -> None:
    """Validate both environment and code-owned paid-credit launch gates."""
    settings.assert_stripe_stage_configuration()
    settings.assert_paid_credits_configuration()
    if settings.paid_credit_checkout_enabled:
        assert_consumer_contract_registry_approved()


def assert_runtime_privacy_configuration() -> None:
    """Fail before health when live erasure continuity cannot be proven."""
    if not settings.retention_cleanup_enabled:
        if not settings.is_dev:
            raise RuntimeError(
                "Production media retention cannot be disabled.",
            )
        return
    if not settings.is_dev and not settings.erasure_journal_continuity_id:
        raise RuntimeError(
            "Production erasure journal continuity state is required.",
        )
    if not settings.is_dev and settings.erasure_journal_anchor_path is None:
        raise RuntimeError(
            "Production erasure journal external anchor path is required.",
        )
    configured_erasure_journal().read_all()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    assert_runtime_billing_configuration()
    assert_runtime_privacy_configuration()
    app.state.db = Database()
    retention_task: asyncio.Task[None] | None = None
    try:
        reclaimed_locks = reclaim_abandoned_lifecycle_locks(
            data_dir=settings.data_dir,
        )
        if reclaimed_locks:
            logger.warning(
                "Reclaimed abandoned media lifecycle locks before startup",
                extra={"reclaimed_locks": reclaimed_locks},
            )
        reconciled_cancellations = reconcile_stranded_cancellations(app.state.db)
        if reconciled_cancellations:
            logger.warning(
                "Recovered stranded media cancellations before startup",
                extra={"reconciled_cancellations": reconciled_cancellations},
            )
        reconciled_interrupted_jobs = reconcile_interrupted_media_jobs(
            app.state.db,
        )
        if reconciled_interrupted_jobs:
            logger.warning(
                "Failed and refunded media jobs interrupted by restart",
                extra={
                    "reconciled_interrupted_jobs": reconciled_interrupted_jobs,
                },
            )
        if settings.retention_cleanup_enabled:
            retention_task = asyncio.create_task(
                retention_worker(app.state.db),
                name="workspace-retention",
            )
        yield
    finally:
        if retention_task is not None:
            retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await retention_task
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
origins = settings.allowed_origins or default_origins
if not settings.is_dev and not origins:
    raise RuntimeError("GSP_ALLOWED_ORIGINS must be set in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "Stripe-Signature",
        "X-Gsubs-Upload-Metadata",
    ],
)

class PrivateMediaAwareGZipMiddleware:
    """Compress text/JSON without recompressing private media files."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1000) -> None:
        self.app = app
        self.compressed_app = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] == "http" and path.startswith("/static/"):
            await self.app(scope, receive, send)
            return
        await self.compressed_app(scope, receive, send)


# MP4/MOV files are already compressed and must retain exact byte ranges.
app.add_middleware(PrivateMediaAwareGZipMiddleware, minimum_size=1000)

default_trusted_hosts = (
    ["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "testserver"] if settings.is_dev else []
)
trusted_hosts = _env_list("GSP_TRUSTED_HOSTS", default_trusted_hosts)
if not settings.is_dev and not trusted_hosts:
    raise RuntimeError("GSP_TRUSTED_HOSTS must be set in production")
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
        cache_control = response.headers.get("Cache-Control", "")
        if request.headers.get("authorization") and "no-store" not in cache_control.lower():
            # Bearer-authenticated JSON can include profile, history, billing,
            # transcript, or project data. Keep it out of shared and browser
            # caches unless the endpoint already set an equally strict rule.
            response.headers["Cache-Control"] = "private, no-store"
        # Avoid sending HSTS on cleartext requests to keep local dev/proxy setups flexible.
        if settings.is_dev and request.url.scheme not in ("https", "wss"):
            if "Strict-Transport-Security" in response.headers:
                del response.headers["Strict-Transport-Security"]
        return response


app.add_middleware(
    # Use the dedicated `secure` package to apply hardened headers.
    SecurityHeadersMiddleware,
    secure_headers=SECURE_HEADERS,
)

if os.getenv("GSP_FORCE_HTTPS", "0") == "1":
    app.add_middleware(HTTPSRedirectMiddleware)

# Trust proxy headers only from known private proxy networks (or local dev).
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

# Serve owner-scoped local artifacts from the same data root used by processing.
DATA_DIR = settings.data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _media_session_token(request: Request) -> str | None:
    """Read media authentication from a bearer header or HttpOnly cookie."""
    authorization = request.headers.get("authorization", "")
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(auth.MEDIA_SESSION_COOKIE_NAME)


def _authenticate_media_request(request: Request) -> User:
    """Authenticate a private-media request against the app-scoped database."""
    token = _media_session_token(request)
    db: Database = request.app.state.db
    user = SessionStore(db=db).authenticate(token or "")
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _owned_artifact_parts(file_path: str, user: User, db: Database) -> list[str]:
    """Validate an exact artifact path and enforce its job ownership."""
    if "\\" in file_path:
        raise HTTPException(status_code=404, detail="File not found")
    parts = file_path.split("/")
    if (
        len(parts) < 3
        or parts[0] != "artifacts"
        or any(not part or part in {".", ".."} for part in parts)
    ):
        raise HTTPException(status_code=404, detail="File not found")

    job = JobStore(db).get_job(parts[1])
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="File not found")
    return parts


@app.get("/static/{file_path:path}")
async def serve_static(
    request: Request,
    file_path: str,
    download: bool = False,
    filename: str | None = None,
):
    # Rate limit static file access to prevent egress abuse
    ip = get_client_ip(request)
    limiter_static.check(ip)

    user = _authenticate_media_request(request)
    db: Database = request.app.state.db
    artifact_parts = _owned_artifact_parts(file_path, user, db)
    full_path = DATA_DIR.joinpath(*artifact_parts)

    # Constrain the resolved file to this exact owned job. A global DATA_DIR
    # check alone would allow a symlink to another user's artifact tree.
    artifacts_root = (DATA_DIR / "artifacts").resolve()
    owned_artifact_root = artifacts_root / artifact_parts[1]
    try:
        if owned_artifact_root.is_symlink():
            raise ValueError("symlinked job root")
        full_path.resolve().relative_to(owned_artifact_root.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")

    if full_path.is_file():
        # Force download for video files or when download=true
        force_download = download or full_path.suffix.lower() in {
            ".mp4",
            ".mov",
            ".avi",
            ".webm",
            ".mkv",
        }
        if force_download:
            download_name = sanitize_download_filename(filename, full_path.name)
            response = FileResponse(
                full_path,
                filename=download_name,
                content_disposition_type="attachment",
            )
        else:
            response = FileResponse(full_path)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    if full_path.is_dir():
        # Security: Disable directory listing to prevent information disclosure
        raise HTTPException(status_code=404, detail="Not found")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raise HTTPException(status_code=404, detail="Not found")


# Include Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(auth.media_router, tags=["auth"])
app.include_router(videos.router, prefix="/videos", tags=["videos"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])
app.include_router(
    billing_admin.router,
    prefix="/billing",
    tags=["billing-admin"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "greek-sub-publisher-api", "app_env": settings.app_env.value}


@app.get("/")
async def root():
    return {"message": "Welcome to the Greek Sub Publisher API"}

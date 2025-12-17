import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
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

from backend.app.api.endpoints import auth, dev, history, tiktok, videos
from backend.app.core import config
from backend.app.core.env import get_app_env, is_dev_env

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
    "http://localhost:8080",
    "http://127.0.0.1:8080",
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
    ["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "*"],  # Allow all for Cloud Run
)
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
        # Avoid sending HSTS on cleartext requests to keep dev/proxy setups flexible.
        if request.url.scheme not in ("https", "wss"):
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

# Ensure we trust X-Forwarded-For headers from Cloud Run Load Balancer
# This must be added last (executed first) to ensure request.client.host is correct
# for rate limiting and logging.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Mount Static Files with Directory Listing
# config.PROJECT_ROOT is the project root, e.g. /path/to/Subs_And_Export_Project
# Use PROJECT_ROOT/data for all artifacts (consistent with videos.py)
DATA_DIR = config.PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

from fastapi import HTTPException
from fastapi.responses import FileResponse


@app.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    full_path = DATA_DIR / file_path

    # Security: Prevent path traversal
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if full_path.is_file():
        return FileResponse(full_path)

    if full_path.is_dir():
        # Security: Disable directory listing to prevent information disclosure
        raise HTTPException(status_code=404, detail="Not found")

    raise HTTPException(status_code=404, detail="Not found")

# Include Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(videos.router, prefix="/videos", tags=["videos"])
app.include_router(tiktok.router, prefix="/tiktok", tags=["tiktok"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(dev.router, prefix="/dev", tags=["dev"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "greek-sub-publisher-api", "app_env": get_app_env().value}

@app.get("/")
async def root():
    return {"message": "Welcome to the Greek Sub Publisher API"}

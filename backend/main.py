import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
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
SECURE_HEADERS = Secure(
    hsts=StrictTransportSecurity().max_age(63072000).include_subdomains().preload(),
    xfo=XFrameOptions().deny(),
    referrer=ReferrerPolicy().strict_origin_when_cross_origin(),
    csp=ContentSecurityPolicy(
        "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'"
    ),
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

# Mount Static Files with Directory Listing
# config.PROJECT_ROOT is backend/app
DATA_DIR = config.PROJECT_ROOT.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

from fastapi.responses import FileResponse, HTMLResponse
from fastapi import HTTPException

@app.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    full_path = DATA_DIR / file_path
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    if full_path.is_file():
        return FileResponse(full_path)
        
    if full_path.is_dir():
        files = sorted(os.listdir(full_path))
        files_html = "".join(
            f'<li><a href="{f}/">{f}</a></li>' if (full_path / f).is_dir() else f'<li><a href="{f}">{f}</a></li>'
            for f in files if not f.startswith(".")
        )
        
        # Add "Go Up" link if not at root
        up_link = ""
        if file_path and file_path != ".":
             parent = str(Path(file_path).parent)
             if parent == ".": parent = ""
             up_link = f'<li><a href="/static/{parent}">.. (Up)</a></li>'

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Index of /static/{file_path}</title>
            <style>
                body {{ font-family: monospace; padding: 20px; }}
                ul {{ list-style-type: none; padding: 0; }}
                li {{ margin: 5px 0; }}
                a {{ text-decoration: none; color: #0066cc; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h2>Index of /static/{file_path}</h2>
            <hr>
            <ul>
                {up_link}
                {files_html}
            </ul>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    
    raise HTTPException(status_code=404, detail="Not found")

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

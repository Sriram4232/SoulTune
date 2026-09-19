"""FastAPI application factory: middleware, routers, lifecycle, and SPA delivery."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings, settings as default_settings
from ..infrastructure.storage import create_store
from .dependencies import API
from .middleware import BodyLimitMiddleware
from .routes.account import router as account_router
from .routes.auth import router as auth_router
from .routes.health import router as health_router
from .routes.library import router as library_router
from .routes.playlists import router as playlists_router
from .routes.queue import router as queue_router

logger = logging.getLogger("curator")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or default_settings

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = await run_in_threadpool(create_store, config)
        try:
            yield
        finally:
            await run_in_threadpool(application.state.store.close)

    app = FastAPI(
        title="AI Music Curator",
        version="1.0.0",
        lifespan=lifespan,
        description="Mood-based music curation, explainable recommendations, and local audio fallback.",
        docs_url="/docs" if config.environment != "production" else None,
        openapi_url="/openapi.json" if config.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = config

    # Middleware
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Range"],
        expose_headers=["Content-Disposition", "Content-Range", "Accept-Ranges", "Retry-After"],
    )

    @app.middleware("http")
    async def guard_browser_requests(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site")
            if (origin and origin.rstrip("/") not in config.allowed_origins) or (not origin and fetch_site == "cross-site"):
                response = JSONResponse({"detail": "This request origin is not allowed."}, status_code=403)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if request.url.path.startswith(API):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        elif request.url.path not in {"/docs", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; "
                "media-src 'self' blob: https:; connect-src 'self'; "
                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )

        if config.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response

    # Exception Handlers
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic includes submitted values by default. Never reflect passwords.
        issues = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": "Check the submitted information.", "errors": issues})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Request failed on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

    # Register Routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(queue_router)
    app.include_router(playlists_router)
    app.include_router(library_router)

    # SPA Frontend Delivery
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        """Serve the built SPA from the same origin as its protected API."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Endpoint not found.")
        dist = (config.project_root / "Frontend" / "dist").resolve()
        candidate = (dist / path).resolve()
        if not candidate.is_relative_to(dist):
            raise HTTPException(404, "File not found.")
        if candidate.is_file():
            response = FileResponse(candidate)
            if candidate.name == "favicon.svg":
                response.headers["Cache-Control"] = "no-cache"
            return response
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(
                404,
                "Frontend build not found. Start the Vite development server or build Frontend first.",
            )
        # Missing asset requests should fail, rather than return HTML as JavaScript.
        if path.startswith("assets/") or candidate.suffix:
            raise HTTPException(404, "File not found.")
        return FileResponse(index)

    return app

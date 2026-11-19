import asyncio
import logging
import sqlite3
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from .alerts import AlertEngine
from .api import install_api
from .config import Settings
from .db import Database
from .diagnostics import capture_logs
from .push import PushService
from .runtime import Runtime

logger = logging.getLogger(__name__)


class RuntimeLifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def current(self) -> list[dict[str, Any]]: ...


def create_app(
    settings: Settings | None = None,
    runtime_factory: Callable[[Settings, Database], RuntimeLifecycle] = Runtime,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def run_lifespan(app: FastAPI) -> AsyncGenerator[None]:
        db = Database(settings.data_dir / "sensogrid.sqlite3", settings)
        if settings.mode == "demo":
            db.seed_demo()
        runtime = runtime_factory(settings, db)
        app.state.db = db
        app.state.runtime = runtime
        app.state.settings = settings
        app.state.push = PushService(settings, db)
        app.state.alerts = AlertEngine(db, settings, app.state.push)
        await runtime.start()

        async def evaluate_alerts() -> None:
            while True:
                try:
                    await app.state.alerts.evaluate(runtime.current())
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.error("Alert evaluation failed")
                await asyncio.sleep(15)

        task = asyncio.create_task(evaluate_alerts())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await runtime.stop()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        with capture_logs(settings):
            try:
                async with run_lifespan(app):
                    yield
            except Exception:
                logger.exception("Application lifecycle failed")
                raise

    app = FastAPI(
        title="SensoGrid",
        version="1.0.1",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError | ValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        detail = "; ".join(".".join(str(x) for x in e["loc"]) + ": " + e["msg"] for e in errors)
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_error(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        return JSONResponse({"detail": "Conflicting resource or reference"}, status_code=409)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if length > 2_000_000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api") or request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    install_api(app)

    @app.get("/{path:path}")
    def static(path: str) -> FileResponse:
        from fastapi import HTTPException

        if path == "api" or path.startswith("api/") or "\\" in path or "\x00" in path:
            raise HTTPException(404, "Not found")
        root = settings.static_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404, "Not found")
        if target.is_file():
            return FileResponse(
                target,
                headers={
                    "Cache-Control": "no-cache"
                    if target.name in ("index.html", "sw.js", "manifest.webmanifest")
                    else "public, max-age=3600"
                },
            )
        if Path(path).suffix:
            raise HTTPException(404, "Not found")
        index = (root / "index.html").resolve()
        if index.is_relative_to(root) and index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        raise HTTPException(404, "Frontend is not built")

    return app


app = create_app()

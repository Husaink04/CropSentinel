"""FastAPI app factory for full backend and extracted service roles."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core import cors_middleware_kwargs as _cors_middleware_kwargs
from app.core import limiter, tenant_context_middleware
from app.edge import edge_middleware
from app.lifecycle import lifespan
from app.monitoring import init_sentry
from app.routers.registry import register_routers, route_family_names_for_role


def build_app(*, title: str, version: str = "2.1.0", role: str = "backend") -> FastAPI:
    _cors = _cors_middleware_kwargs()
    init_sentry()
    app = FastAPI(title=title, version=version, lifespan=lifespan)
    app.state.service_role = role
    app.state.route_families = route_family_names_for_role(role)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        **_cors,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(edge_middleware)
    app.middleware("http")(tenant_context_middleware)
    register_routers(app, role=role)
    return app

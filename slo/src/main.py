"""FastAPI entry point — ``/healthz`` only after sub-spec 02.a.

Sub-spec 02.a deletes the original 01.j lifespan hook that was going to
build a ``SloAgent`` singleton + a ``SessionStore``. The TUI runs the
agent in-process; this surface exists purely so ``slo serve`` has a
liveness check.
"""
from fastapi import FastAPI

from src.web_app import initialize_web_app


app: FastAPI = initialize_web_app(app=FastAPI(title="slo", version="0.1.0"))

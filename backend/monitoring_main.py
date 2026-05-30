"""Monitoring ingest service entrypoint."""

from app.app_factory import build_app
from app.logging_setup import configure_logging

configure_logging()
app = build_app(title="CropSentinel Monitoring Service", role="monitoring")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("monitoring_main:app", host="0.0.0.0", port=8000, reload=True)

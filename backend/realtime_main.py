"""Realtime session service entrypoint."""

from app.app_factory import build_app
from app.logging_setup import configure_logging

configure_logging()
app = build_app(title="CropSentinel Realtime Service", role="realtime")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("realtime_main:app", host="0.0.0.0", port=8000, reload=True)

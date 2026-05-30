"""CropSentinel FastAPI entrypoint."""

from app.app_factory import build_app
from app.logging_setup import configure_logging

configure_logging()
app = build_app(title="CropSentinel Monitoring API", role="backend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

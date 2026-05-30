"""Agent control service entrypoint."""

from app.app_factory import build_app
from app.logging_setup import configure_logging

configure_logging()
app = build_app(title="CropSentinel Agent Control Service", role="agent-control")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("agent_control_main:app", host="0.0.0.0", port=8000, reload=True)

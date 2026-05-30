from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


WIDTH = 2600
HEIGHT = 1820
BG = "#f4f7fb"
TEXT = "#17212e"
MUTED = "#5b6678"
SOFT = "#d7e0ec"
ARROW = "#4a6a97"
WHITE = "#ffffff"
PORTAL = "#e8f1ff"
GATEWAY = "#fff4d8"
SERVICE = "#eaf7ee"
DEVICE = "#f2ebff"
DATA = "#eef1ff"
SUPPORT = "#fff0ea"
NOTE = "#f8fbff"


def font(size: int, bold: bool = False):
    paths = []
    if bold:
        paths.extend(["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/arialbd.ttf"])
    paths.extend(["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"])
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


TITLE = font(54, True)
SUBTITLE = font(24)
H1 = font(28, True)
H2 = font(24, True)
BODY = font(20)
SMALL = font(18)


def rounded(draw: ImageDraw.ImageDraw, box, fill, outline=SOFT, width=3, radius=26):
    draw.rounded_rectangle(box, fill=fill, outline=outline, width=width, radius=radius)


def wrapped(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(wrap(paragraph, width=width) or [""])
    return lines


def card(draw: ImageDraw.ImageDraw, box, fill: str, title: str, body: str, body_width: int = 28):
    rounded(draw, box, fill=fill)
    x1, y1, x2, y2 = box
    draw.text((x1 + 20, y1 + 16), title, font=H2, fill=TEXT)
    y = y1 + 52
    for line in wrapped(body, body_width):
        draw.text((x1 + 20, y), line, font=BODY, fill=MUTED)
        y += BODY.size + 7


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], label: str | None = None):
    draw.line([start, end], fill=ARROW, width=5)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux = dx / length
    uy = dy / length
    size = 20
    p1 = (end[0] - ux * size - uy * size * 0.55, end[1] - uy * size + ux * size * 0.55)
    p2 = (end[0] - ux * size + uy * size * 0.55, end[1] - uy * size - ux * size * 0.55)
    draw.polygon([end, p1, p2], fill=ARROW)
    if label:
        bbox = draw.textbbox((0, 0), label, font=SMALL)
        cx = (start[0] + end[0]) / 2
        cy = (start[1] + end[1]) / 2
        pad_x = 10
        pad_y = 6
        label_box = (
            cx - (bbox[2] - bbox[0]) / 2 - pad_x,
            cy - (bbox[3] - bbox[1]) / 2 - pad_y,
            cx + (bbox[2] - bbox[0]) / 2 + pad_x,
            cy + (bbox[3] - bbox[1]) / 2 + pad_y,
        )
        rounded(draw, label_box, fill=WHITE, outline="#d8e2ef", width=2, radius=14)
        draw.text((label_box[0] + pad_x, label_box[1] + 4), label, font=SMALL, fill=MUTED)


def bullets(draw: ImageDraw.ImageDraw, x: int, y: int, items: list[str], width: int = 90):
    current_y = y
    for item in items:
        lines = wrapped(item, width)
        draw.text((x, current_y), "•", font=BODY, fill=TEXT)
        draw.text((x + 24, current_y), lines[0], font=BODY, fill=MUTED)
        current_y += BODY.size + 6
        for extra in lines[1:]:
            draw.text((x + 24, current_y), extra, font=BODY, fill=MUTED)
            current_y += BODY.size + 6
        current_y += 4
    return current_y


def main() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    draw.text((90, 48), "CropSentinel Current System Design", font=TITLE, fill=TEXT)
    draw.text(
        (90, 118),
        "Detailed plain-language view of what is running today, what each part does, and how information moves.",
        font=SUBTITLE,
        fill=MUTED,
    )

    # top row
    people_left = (90, 200, 470, 365)
    people_mid = (520, 200, 900, 365)
    web_portal = (980, 185, 1360, 380)
    platform_portal = (1410, 185, 1790, 380)
    gateway_box = (1860, 195, 2460, 370)

    card(draw, people_left, NOTE, "Team Leaders and Company Admins", "Use the main web portal to review activity, alerts, reports, and device health.", 28)
    card(draw, people_mid, NOTE, "Platform Operators", "Use a platform admin area to manage tenants, licenses, users, and shared product settings.", 28)
    card(draw, web_portal, PORTAL, "Main Web Portal", "The frontend used by each customer for dashboards, machine lists, alerts, DLP, reports, and live screens.", 28)
    card(draw, platform_portal, PORTAL, "Platform Admin Portal", "Runs from the same frontend codebase but shows platform-only pages such as tenant and subscription management.", 28)
    card(draw, gateway_box, GATEWAY, "Public Gateway", "The single public entry point. It sends each request to the right internal service and keeps the public URLs stable.", 34)

    # left agent
    agent_box = (90, 500, 520, 930)
    rounded(draw, agent_box, fill=DEVICE)
    draw.text((110, 520), "Monitored Device Agent", font=H1, fill=TEXT)
    agent_points = [
        "Runs on monitored employee devices.",
        "Collects browser, app, file, network, screenshot, and input activity based on policy.",
        "Registers the device, sends heartbeat check-ins, and can receive control settings.",
        "Keeps a local queue when the device is offline and syncs later.",
        "Supports live session traffic for admin view and remote actions.",
    ]
    bullets(draw, 112, 575, agent_points, 34)

    # center product services
    service_panel = (580, 470, 1790, 1140)
    rounded(draw, service_panel, fill=WHITE, outline="#b9c7db", width=4, radius=30)
    draw.text((605, 495), "Internal Product Services", font=H1, fill=TEXT)
    draw.text(
        (605, 537),
        "Today the product is still one codebase, but it can run as several internal services behind the gateway.",
        font=BODY,
        fill=MUTED,
    )

    main_backend = (620, 590, 1015, 820)
    agent_control = (1085, 590, 1480, 820)
    monitoring = (620, 870, 1015, 1100)
    realtime = (1085, 870, 1480, 1100)
    workers = (1550, 730, 1755, 1005)

    card(draw, main_backend, SERVICE, "Main Backend", "Handles most portal pages and business rules: analytics, alerts, settings, users, teams, tenants, reports, audit records, and security workflows.", 27)
    card(draw, agent_control, SERVICE, "Agent Control", "Owns device registration, heartbeat traffic, and the control settings that monitored devices need to keep running.", 27)
    card(draw, monitoring, SERVICE, "Monitoring Intake", "Receives the high-volume activity coming from devices and hands off heavier follow-up work so the live request path stays lighter.", 27)
    card(draw, realtime, SERVICE, "Live Updates", "Keeps admin web sockets, agent web sockets, live view sessions, and real-time status delivery working.", 27)
    card(draw, workers, SUPPORT, "Background Jobs", "Cleans up files, builds reports, writes event streams, and runs slower follow-up tasks outside the live user request.", 18)

    # data/support right column
    db_box = (1860, 500, 2460, 675)
    object_box = (1860, 715, 2460, 890)
    redis_box = (1860, 930, 2460, 1105)
    analytics_box = (1860, 1145, 2460, 1320)
    ops_box = (1860, 1360, 2460, 1590)

    card(draw, db_box, DATA, "Main Database (PostgreSQL)", "Stores tenants, users, devices, teams, alerts, settings, audit records, and the core day-to-day product data.", 33)
    card(draw, object_box, DATA, "File and Evidence Storage", "Stores screenshots, exports, report files, installers, and other larger objects that should not live inside normal database rows.", 33)
    card(draw, redis_box, DATA, "Fast Message and State Layer", "Supports quick fan-out, live status delivery, and internal coordination where low delay matters.", 33)
    card(draw, analytics_box, DATA, "Heavy Reporting and Event Stores", "Used for larger event flows and heavier reporting workloads so the main database is not asked to do everything.", 33)
    card(draw, ops_box, SUPPORT, "Operations, Monitoring, and Recovery", "Prometheus, Grafana, Loki, backups, and recovery status help operators watch the system and recover it when needed.", 32)

    # bottom notes
    note_left = (90, 1180, 1260, 1720)
    note_right = (1320, 1180, 1790, 1720)

    rounded(draw, note_left, fill=NOTE)
    draw.text((115, 1205), "What the data flow looks like", font=H1, fill=TEXT)
    flow_points = [
        "People open the portal in a browser.",
        "The public gateway forwards each request to the correct internal service.",
        "Monitored devices register, check in, and upload approved activity.",
        "The main backend serves most portal screens and business actions.",
        "Live sessions and real-time status move through the real-time service.",
        "Core records, large files, and heavy reporting data are stored in different places based on their job.",
    ]
    bullets(draw, 118, 1260, flow_points, 56)

    rounded(draw, note_right, fill=NOTE)
    draw.text((1345, 1205), "Honest notes about the current design", font=H1, fill=TEXT)
    honest_points = [
        "This is no longer just one simple backend. It is a split runtime behind one gateway.",
        "The main backend is still the center of most customer-facing portal APIs.",
        "The extra services mainly exist to separate device control, activity intake, and live traffic so they can scale more safely.",
        "Some support systems are mostly for speed, reliability, and operations rather than direct end-user features.",
        "The product still lives in one repo today, even though it can run as multiple services.",
    ]
    bullets(draw, 1348, 1260, honest_points, 40)

    # arrows
    arrow(draw, (470, 282), (980, 282), "Uses the portal")
    arrow(draw, (900, 282), (1410, 282), "Uses admin pages")
    arrow(draw, (1360, 282), (1860, 282), "Web requests")
    arrow(draw, (1790, 282), (1860, 282), "Admin requests")

    arrow(draw, (2460, 282), (1015, 700), "Portal traffic reaches services")
    arrow(draw, (520, 620), (1085, 690), "Register and check in")
    arrow(draw, (520, 735), (620, 985), "Upload activity")
    arrow(draw, (520, 855), (1085, 985), "Live sessions and status")

    arrow(draw, (1015, 695), (1860, 585), "Core records")
    arrow(draw, (1480, 695), (1860, 585), None)
    arrow(draw, (1015, 975), (1860, 800), "Evidence files")
    arrow(draw, (1480, 975), (1860, 1015), "Fast updates")
    arrow(draw, (1755, 865), (1860, 1230), "Heavy reporting")
    arrow(draw, (1755, 925), (1860, 1475), "Ops and backups")
    arrow(draw, (1480, 985), (1550, 865), "Async work")
    arrow(draw, (1015, 985), (1550, 915), None)

    # footer
    draw.text(
        (90, 1762),
        "Current repo evidence used: frontend portal + platform portal, gateway routing, split services (backend, agent-control, monitoring, realtime), PostgreSQL, file storage, Redis, reporting/event stores, and ops tooling in Docker Compose.",
        font=SMALL,
        fill=MUTED,
    )

    out = Path(__file__).with_name("cropsentinel-current-system-design-detailed.png")
    img.save(out, format="PNG", optimize=True)
    print(out)


if __name__ == "__main__":
    main()

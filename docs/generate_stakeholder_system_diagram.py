from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


WIDTH = 2200
HEIGHT = 1500
BG = "#f5f7fb"
TEXT = "#18212f"
MUTED = "#5b6678"
LINE = "#7b8aa3"
ARROW = "#44638f"
PANEL = "#ffffff"
PANEL_BORDER = "#cbd5e1"
PORTAL = "#e8f1ff"
GATEWAY = "#fff4d8"
SERVICE = "#e9f8ef"
DEVICE = "#f3ecff"
DATA = "#eef2ff"
OPS = "#fff0ea"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/seguisb.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
            ]
        )
    candidates.extend(
        [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


TITLE_FONT = load_font(50, bold=True)
SUBTITLE_FONT = load_font(24)
SECTION_FONT = load_font(24, bold=True)
LABEL_FONT = load_font(26, bold=True)
BODY_FONT = load_font(21)
SMALL_FONT = load_font(18)


def rounded_box(draw: ImageDraw.ImageDraw, box, fill, outline=PANEL_BORDER, radius=24, width=3):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text_block(draw: ImageDraw.ImageDraw, x: int, y: int, title: str, lines: list[str], title_font, body_font, fill=TEXT):
    draw.text((x, y), title, font=title_font, fill=fill)
    current_y = y + title_font.size + 12
    for line in lines:
        draw.text((x, current_y), line, font=body_font, fill=MUTED)
        current_y += body_font.size + 8


def wrapped_lines(text: str, width: int) -> list[str]:
    parts: list[str] = []
    for paragraph in text.split("\n"):
        parts.extend(wrap(paragraph, width=width) or [""])
    return parts


def box_with_copy(draw: ImageDraw.ImageDraw, box, fill: str, title: str, body: str):
    rounded_box(draw, box, fill=fill)
    x1, y1, x2, y2 = box
    title_y = y1 + 18
    draw.text((x1 + 22, title_y), title, font=LABEL_FONT, fill=TEXT)
    body_y = title_y + LABEL_FONT.size + 12
    for line in wrapped_lines(body, 26):
        draw.text((x1 + 22, body_y), line, font=BODY_FONT, fill=MUTED)
        body_y += BODY_FONT.size + 8


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], text: str | None = None):
    draw.line([start, end], fill=ARROW, width=5)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux = dx / length
    uy = dy / length
    size = 18
    left = (end[0] - ux * size - uy * size * 0.6, end[1] - uy * size + ux * size * 0.6)
    right = (end[0] - ux * size + uy * size * 0.6, end[1] - uy * size - ux * size * 0.6)
    draw.polygon([end, left, right], fill=ARROW)
    if text:
        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2
        bbox = draw.textbbox((0, 0), text, font=SMALL_FONT)
        pad_x = 10
        pad_y = 6
        label_box = (
            mid_x - (bbox[2] - bbox[0]) / 2 - pad_x,
            mid_y - (bbox[3] - bbox[1]) / 2 - pad_y,
            mid_x + (bbox[2] - bbox[0]) / 2 + pad_x,
            mid_y + (bbox[3] - bbox[1]) / 2 + pad_y,
        )
        rounded_box(draw, label_box, fill="#ffffff", outline="#d8e0eb", radius=12, width=2)
        draw.text((label_box[0] + pad_x, label_box[1] + 4), text, font=SMALL_FONT, fill=MUTED)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.text((100, 56), "CropSentinel: How the Product Works Today", font=TITLE_FONT, fill=TEXT)
    draw.text(
        (100, 122),
        "A plain-language view of the current product, the main parts inside it, and how information moves.",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )

    top_left = (100, 210, 520, 390)
    top_right = (610, 210, 1030, 390)
    gateway_box = (1110, 220, 1485, 380)
    device_box = (100, 530, 520, 760)
    service_panel = (610, 470, 1540, 1030)
    data_left = (1620, 250, 2080, 430)
    data_mid = (1620, 470, 2080, 650)
    data_right = (1620, 690, 2080, 870)
    ops_box = (1620, 910, 2080, 1090)
    note_box = (100, 1160, 2080, 1400)

    box_with_copy(draw, top_left, PORTAL, "Customer Portal", "Managers and admins review activity, alerts, reports, and device status in the web portal.")
    box_with_copy(draw, top_right, PORTAL, "Platform Admin Portal", "Platform staff manage tenants, users, plans, and shared product settings from the same frontend codebase.")
    box_with_copy(draw, gateway_box, GATEWAY, "Secure Gateway", "One public entry point that forwards each request to the right internal service.")
    box_with_copy(draw, device_box, DEVICE, "Monitored Device Agent", "Runs on employee devices, collects approved activity data, keeps a local queue, and sends updates when the device is online.")
    box_with_copy(draw, data_left, DATA, "Main Database", "Stores users, tenants, devices, alerts, settings, and other core business records.")
    box_with_copy(draw, data_mid, DATA, "File Storage", "Stores screenshots, report files, exports, installers, and other large evidence files.")
    box_with_copy(draw, data_right, DATA, "Reporting Store", "Supports heavier trend analysis and longer-range reporting without overloading the main database.")
    box_with_copy(draw, ops_box, OPS, "Monitoring and Recovery Tools", "Collect health data, logs, dashboards, backups, and recovery status for the running platform.")

    rounded_box(draw, service_panel, fill=PANEL, outline="#b8c7dc", radius=30, width=4)
    draw.text((service_panel[0] + 26, service_panel[1] + 20), "Product Services", font=SECTION_FONT, fill=TEXT)
    draw.text(
        (service_panel[0] + 26, service_panel[1] + 56),
        "These services stay inside the product but each one has a clear job.",
        font=BODY_FONT,
        fill=MUTED,
    )

    service_boxes = [
        ((650, 560, 1060, 760), "Main Backend", SERVICE, "Handles portal screens, reports, alerts, settings, and most business rules."),
        ((1090, 560, 1500, 760), "Agent Control", SERVICE, "Handles device registration, heartbeat checks, and control settings sent to agents."),
        ((650, 800, 1060, 1000), "Monitoring Intake", SERVICE, "Receives activity streams from devices and moves heavier work into background processing."),
        ((1090, 800, 1500, 1000), "Live Updates", SERVICE, "Keeps admin live sessions, web sockets, and real-time updates running."),
    ]
    for box, title, fill, body in service_boxes:
        box_with_copy(draw, box, fill, title, body)

    arrow(draw, (520, 300), (1110, 300), "Portal use")
    arrow(draw, (1030, 300), (1110, 300), "Platform admin use")
    arrow(draw, (1485, 300), (650, 660), "Sends work to product services")
    arrow(draw, (520, 645), (650, 900), "Uploads approved activity")
    arrow(draw, (520, 610), (1090, 660), "Registers and checks in")
    arrow(draw, (1280, 760), (1280, 800), "Live delivery")
    arrow(draw, (1540, 650), (1620, 340), "Core records")
    arrow(draw, (1540, 740), (1620, 560), "Files and evidence")
    arrow(draw, (1540, 900), (1620, 780), "Reports and trends")
    arrow(draw, (1540, 980), (1620, 1000), "Health and backups")

    rounded_box(draw, note_box, fill="#ffffff", outline="#d8e1ee", radius=24, width=3)
    draw.text((130, 1192), "How to read this diagram", font=SECTION_FONT, fill=TEXT)
    notes = [
        "1. People use a web portal, while monitored devices send updates through the same public gateway.",
        "2. Inside the product, the work is split so device control, data intake, live updates, and portal logic can scale separately.",
        "3. The platform stores records, large files, and reporting data in different places so day-to-day use stays responsive.",
    ]
    note_y = 1238
    for note in notes:
        draw.text((130, note_y), note, font=BODY_FONT, fill=MUTED)
        note_y += BODY_FONT.size + 14

    output = Path(__file__).with_name("cropsentinel-stakeholder-system-overview.png")
    image.save(output, format="PNG", optimize=True)
    print(output)


if __name__ == "__main__":
    main()

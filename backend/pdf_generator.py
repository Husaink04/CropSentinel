"""
CropSentinel - Professional PDF Report Generator
Clean, corporate-grade layout using ReportLab Platypus.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, HRFlowable, PageBreak, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.graphics.charts.barcharts import VerticalBarChart, HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from datetime import datetime, timezone
from pathlib import Path

# ── directories ───────────────────────────────────────────────────────────────
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ── brand palette ─────────────────────────────────────────────────────────────
C_NAVY      = colors.HexColor("#0F172A")
C_BLUE      = colors.HexColor("#2563EB")
C_BLUE_LITE = colors.HexColor("#EFF6FF")
C_GREEN     = colors.HexColor("#059669")
C_AMBER     = colors.HexColor("#D97706")
C_RED       = colors.HexColor("#DC2626")
C_PURPLE    = colors.HexColor("#7C3AED")
C_CYAN      = colors.HexColor("#0891B2")
C_SLATE     = colors.HexColor("#475569")
C_SLATE_LT  = colors.HexColor("#94A3B8")
C_BORDER    = colors.HexColor("#E2E8F0")
C_ROW_ALT   = colors.HexColor("#F8FAFC")
C_WHITE     = colors.white
C_CHART = [C_BLUE, C_GREEN, C_AMBER, C_RED, C_PURPLE, C_CYAN,
           colors.HexColor("#EC4899"), colors.HexColor("#84CC16")]

W, H = A4  # 595.28 x 841.89 pt

MARGIN_L = 1.8 * cm
MARGIN_R = 1.8 * cm
MARGIN_T = 2.8 * cm   # room for header bar
MARGIN_B = 2.2 * cm   # room for footer bar

CONTENT_W = W - MARGIN_L - MARGIN_R

# ── helper ────────────────────────────────────────────────────────────────────
def _hm(s):
    s = int(s or 0)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"

def _safe(v, maxlen=40):
    return str(v or "—")[:maxlen]

def _date(v):
    if not v:
        return "—"
    return str(v)[:10]

# ── styles ────────────────────────────────────────────────────────────────────
def _styles():
    base = dict(fontName="Helvetica", leading=14)
    H1   = ParagraphStyle("H1",   fontSize=20, fontName="Helvetica-Bold",
                           textColor=C_NAVY, spaceAfter=4,  leading=24)
    H2   = ParagraphStyle("H2",   fontSize=13, fontName="Helvetica-Bold",
                           textColor=C_NAVY, spaceBefore=14, spaceAfter=6, leading=16)
    H3   = ParagraphStyle("H3",   fontSize=10, fontName="Helvetica-Bold",
                           textColor=C_SLATE, spaceAfter=4,  leading=13,
                           textTransform="uppercase")
    BODY = ParagraphStyle("BODY", fontSize=9,  fontName="Helvetica",
                           textColor=C_NAVY,  leading=13)
    SMALL= ParagraphStyle("SMALL",fontSize=8,  fontName="Helvetica",
                           textColor=C_SLATE_LT, leading=11)
    SUB  = ParagraphStyle("SUB",  fontSize=10, fontName="Helvetica",
                           textColor=C_SLATE,  leading=14, spaceAfter=12)
    return H1, H2, H3, BODY, SMALL, SUB

# ── page callbacks ────────────────────────────────────────────────────────────
def _make_page_cb(company, generated_str):
    def cb(canvas, doc):
        canvas.saveState()
        # ── header bar
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, H - 36, W, 36, fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(MARGIN_L, H - 23, f"{company}  —  Employee Activity Report")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(W - MARGIN_R, H - 23, f"Generated  {generated_str}")
        # ── thin accent line under header
        canvas.setStrokeColor(C_BLUE)
        canvas.setLineWidth(2)
        canvas.line(0, H - 37, W, H - 37)
        # ── footer bar
        canvas.setFillColor(colors.HexColor("#F1F5F9"))
        canvas.rect(0, 0, W, 26, fill=1, stroke=0)
        canvas.setFillColor(C_SLATE)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGIN_L, 8, "CONFIDENTIAL  —  Internal Use Only")
        canvas.drawRightString(W - MARGIN_R, 8, f"Page {doc.page}")
        canvas.restoreState()
    return cb

# ── section divider ───────────────────────────────────────────────────────────
def _section_block(title, H2):
    return [
        Spacer(1, 0.3 * cm),
        HRFlowable(width="100%", thickness=1.5, color=C_BLUE, spaceAfter=5),
        Paragraph(title, H2),
    ]

# ── stat boxes row ────────────────────────────────────────────────────────────
def _stat_boxes(stats):
    """stats = list of (label, value, colour)"""
    n     = len(stats)
    w_col = CONTENT_W / n
    data  = [[Paragraph(f'<font size="8" color="#64748B"><b>{s[0].upper()}</b></font><br/>'
                         f'<font size="16" color="{s[2]}"><b>{s[1]}</b></font>', ParagraphStyle(
                             "stv", fontSize=16, leading=22))
              for s in stats]]
    t = Table(data, colWidths=[w_col] * n, rowHeights=[52])
    t.setStyle(TableStyle([
        ("BOX",        (0,0), (-1,-1), 0.5, C_BORDER),
        ("INNERGRID",  (0,0), (-1,-1), 0.5, C_BORDER),
        ("BACKGROUND", (0,0), (-1,-1), C_WHITE),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
    ]))
    return t

# ── table helpers ─────────────────────────────────────────────────────────────
_HDR_STYLE = TableStyle([
    ("BACKGROUND",   (0,0), (-1,0), C_NAVY),
    ("TEXTCOLOR",    (0,0), (-1,0), C_WHITE),
    ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE",     (0,0), (-1,-1), 8.5),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE, C_ROW_ALT]),
    ("GRID",         (0,0), (-1,-1), 0.4, C_BORDER),
    ("TOPPADDING",   (0,0), (-1,-1), 5),
    ("BOTTOMPADDING",(0,0), (-1,-1), 5),
    ("LEFTPADDING",  (0,0), (-1,-1), 7),
    ("RIGHTPADDING", (0,0), (-1,-1), 7),
    ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
])

# ── bar chart ─────────────────────────────────────────────────────────────────
def _bar_chart(labels, values, title, bar_color=None, width=CONTENT_W*0.88, height=140):
    if not labels:
        return None
    bar_color = bar_color or C_BLUE
    n  = len(labels)
    dw = float(width)
    dh = float(height) + 40
    d  = Drawing(dw, dh)

    chart_x, chart_y = 60, 30
    chart_w = dw - chart_x - 20
    chart_h = float(height)

    bc = VerticalBarChart()
    bc.x      = chart_x
    bc.y      = chart_y
    bc.width  = chart_w
    bc.height = chart_h
    bc.data   = [values]
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontSize  = 7
    bc.categoryAxis.labels.angle     = 30 if n > 6 else 0
    bc.categoryAxis.labels.dy        = -6
    bc.valueAxis.valueMin            = 0
    bc.valueAxis.labels.fontSize     = 7
    bc.bars[0].fillColor             = bar_color
    bc.bars[0].strokeColor           = None
    bc.barWidth                      = 0.6
    d.add(bc)

    if title:
        d.add(String(dw / 2, dh - 10, title, fontSize=9,
                     fillColor=C_SLATE, textAnchor="middle"))
    return d

# ── horizontal bar chart (for app usage) ─────────────────────────────────────
def _hbar_chart(labels, values, width=CONTENT_W*0.88, height=160):
    if not labels:
        return None
    n  = len(labels)
    dw = float(width)
    dh = float(height) + 10
    d  = Drawing(dw, dh)

    bc = HorizontalBarChart()
    bc.x      = 100
    bc.y      = 10
    bc.width  = dw - 120
    bc.height = float(height)
    bc.data   = [values]
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontSize  = 7.5
    bc.valueAxis.valueMin            = 0
    bc.valueAxis.labels.fontSize     = 7
    bc.bars[0].fillColor             = C_BLUE
    bc.bars[0].strokeColor           = None
    bc.barWidth                      = 0.5
    d.add(bc)
    return d

# ── pie chart ─────────────────────────────────────────────────────────────────
def _pie_chart(labels, values, size=150):
    if not labels or not any(v > 0 for v in values):
        return None
    d   = Drawing(size + 90, size)
    pie = Pie()
    pie.x      = 10
    pie.y      = 10
    pie.width  = size - 20
    pie.height = size - 20
    pie.data   = values
    pie.labels = [""] * len(labels)   # no inline labels — use legend instead
    pie.sideLabels = False
    for i, clr in enumerate(C_CHART[:len(labels)]):
        pie.slices[i].fillColor   = clr
        pie.slices[i].strokeColor = C_WHITE
        pie.slices[i].strokeWidth = 1
    d.add(pie)
    # legend
    for i, (lbl, val) in enumerate(zip(labels, values)):
        x = size + 5
        y = size - 14 - i * 16
        if y < 0:
            break
        d.add(Rect(x, y + 2, 9, 9, fillColor=C_CHART[i % len(C_CHART)], strokeColor=None))
        d.add(String(x + 13, y + 2, f"{lbl[:16]}: {_hm(val)}",
                     fontSize=7, fillColor=C_NAVY))
    return d

# ── line chart ────────────────────────────────────────────────────────────────
def _line_chart(hours_map, width=CONTENT_W*0.88, height=110):
    keys  = [str(h).zfill(2) for h in range(24)]
    vals  = [hours_map.get(k, 0) for k in keys]
    if not any(vals):
        return None
    dw, dh = float(width), float(height) + 30
    d  = Drawing(dw, dh)
    lc = HorizontalLineChart()
    lc.x      = 50
    lc.y      = 20
    lc.width  = dw - 70
    lc.height = float(height)
    lc.data   = [vals]
    lc.categoryAxis.categoryNames = [f"{h}" for h in range(24)]
    lc.categoryAxis.labels.fontSize  = 6
    lc.valueAxis.valueMin            = 0
    lc.valueAxis.labels.fontSize     = 7
    lc.lines[0].strokeColor = C_GREEN
    lc.lines[0].strokeWidth = 1.8
    d.add(lc)
    return d

# ── main entry point ──────────────────────────────────────────────────────────
def generate_report(machine, analytics, browser, apps, settings,
                    start_date=None, end_date=None):
    now        = datetime.now(timezone.utc)
    gen_str    = now.strftime("%Y-%m-%d  %H:%M UTC")
    company    = settings.get("company_name", "CropSentinel")
    hostname   = machine.get("hostname", "Unknown")
    filename   = f"CropSentinel_{hostname}_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath   = str(REPORTS_DIR / filename)

    H1, H2, H3, BODY, SMALL, SUB = _styles()
    page_cb = _make_page_cb(company, gen_str)

    # ── document with custom page template ───────────────────────────────────
    doc = BaseDocTemplate(
        filepath, pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T,  bottomMargin=MARGIN_B,
        title=f"{company} — Activity Report — {hostname}",
        author=company,
        subject="Employee Activity Report",
    )
    frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W, H - MARGIN_T - MARGIN_B,
                  id="main", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                        onPage=page_cb)])

    E = []   # elements list

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 1 — Cover / Summary
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(Spacer(1, 0.4*cm))

    # Title block
    date_range = (f"{start_date} → {end_date}" if start_date and end_date
                  else f"From {start_date}" if start_date
                  else f"All-time  ·  Generated {now.strftime('%d %B %Y')}")
    E.append(Paragraph(f"Activity Report", H1))
    E.append(Paragraph(date_range, SUB))

    # Decorative line
    E.append(HRFlowable(width="100%", thickness=2.5, color=C_BLUE, spaceAfter=12))

    # ── machine info table ────────────────────────────────────────────────────
    E += _section_block("Machine Information", H2)

    first_seen = _date(machine.get("first_seen"))
    last_seen  = _date(machine.get("last_seen"))
    consent_ts = _date(machine.get("consent_timestamp"))

    info_data = [
        ["Hostname",       _safe(machine.get("hostname")),
         "Username",       _safe(machine.get("username"))],
        ["Operating System", f"{machine.get('os','')} {machine.get('os_version','')}".strip(),
         "IP Address",     _safe(machine.get("ip_address"))],
        ["Machine ID",     _safe(machine.get("machine_id","")[:28]) + "…",
         "Agent Version",  _safe(machine.get("agent_version"))],
        ["First Seen",     first_seen, "Last Seen", last_seen],
        ["Consent Given",  "✓ Yes" if machine.get("consent_given") else "✗ No",
         "Consent Date",   consent_ts],
    ]
    col_w = [2.8*cm, 6.2*cm, 2.8*cm, 6.2*cm]
    info_t = Table(info_data, colWidths=col_w)
    info_t.setStyle(TableStyle([
        ("FONTNAME",     (0,0), (-1,-1), "Helvetica"),
        ("FONTNAME",     (0,0), (0,-1),  "Helvetica-Bold"),
        ("FONTNAME",     (2,0), (2,-1),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 8.5),
        ("TEXTCOLOR",    (0,0), (0,-1),  C_SLATE),
        ("TEXTCOLOR",    (2,0), (2,-1),  C_SLATE),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [C_WHITE, C_ROW_ALT]),
        ("GRID",         (0,0), (-1,-1), 0.4, C_BORDER),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
    ]))
    E.append(info_t)

    # ── summary stats ─────────────────────────────────────────────────────────
    E += _section_block("Activity Summary", H2)
    total_sec     = int(analytics.get("total_active_seconds", 0) or 0)
    browser_vis   = int(analytics.get("browser_visits", 0) or 0)
    top_app_name  = (analytics.get("app_usage") or [{}])[0].get("app_name", "—")
    top_dom_name  = (analytics.get("browser_usage") or [{}])[0].get("domain", "—")

    E.append(_stat_boxes([
        ("Total Active Time", _hm(total_sec),          "#2563EB"),
        ("Browser Visits",    str(browser_vis),         "#059669"),
        ("Top Application",   _safe(top_app_name, 16),  "#7C3AED"),
        ("Top Domain",        _safe(top_dom_name, 18),  "#D97706"),
    ]))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 2 — Application Usage
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section_block("Application Usage", H2)

    app_usage = analytics.get("app_usage") or []
    if app_usage:
        # ── horizontal bar chart ──────────────────────────────────────────────
        chart_apps  = app_usage[:10]
        bar_labels  = [a["app_name"][:18] for a in chart_apps]
        bar_values  = [int(a["total_seconds"] or 0) // 60 for a in chart_apps]
        hbar = _hbar_chart(bar_labels, bar_values, height=max(120, len(chart_apps) * 18))
        if hbar:
            E.append(hbar)
            E.append(Spacer(1, 0.3*cm))

        # ── pie + legend side-by-side ─────────────────────────────────────────
        pie_apps = app_usage[:8]
        pie      = _pie_chart(
            [a["app_name"][:14] for a in pie_apps],
            [int(a["total_seconds"] or 0) for a in pie_apps],
            size=140,
        )
        if pie:
            pie_t = Table([[pie]], colWidths=[CONTENT_W])
            E.append(KeepTogether([pie_t, Spacer(1, 0.4*cm)]))

        # ── applications table ────────────────────────────────────────────────
        E += _section_block("Top Applications — Detail", H2)
        rows = [["#", "Application", "Process", "Total Time", "Sessions"]]
        for i, a in enumerate(app_usage[:15], 1):
            rows.append([
                str(i),
                _safe(a.get("app_name"), 30),
                _safe(a.get("process_name"), 20),
                _hm(a.get("total_seconds", 0)),
                str(a.get("sessions", "—")),
            ])
        col_w2 = [0.7*cm, 5.5*cm, 4*cm, 3*cm, 2.5*cm]
        at = Table(rows, colWidths=col_w2)
        at.setStyle(_HDR_STYLE)
        at.setStyle(TableStyle([*_HDR_STYLE._cmds,
            ("ALIGN", (0,0), (0,-1),  "CENTER"),
            ("ALIGN", (3,0), (-1,-1), "CENTER"),
        ]))
        E.append(at)
    else:
        E.append(Paragraph("No application activity recorded for this period.", BODY))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 3 — Browser Activity
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section_block("Browser Activity", H2)

    browser_usage = analytics.get("browser_usage") or []
    if browser_usage:
        # ── domain bar chart ──────────────────────────────────────────────────
        dom_chart = browser_usage[:10]
        bar = _bar_chart(
            [d["domain"][:14] for d in dom_chart],
            [int(d.get("visits", 0)) for d in dom_chart],
            title="",
            bar_color=C_CYAN,
            height=120,
        )
        if bar:
            E.append(bar)
            E.append(Spacer(1, 0.3*cm))

        # ── domain summary table ──────────────────────────────────────────────
        dom_rows = [["#", "Domain", "Visits", "Total Time"]]
        for i, d in enumerate(browser_usage[:15], 1):
            dom_rows.append([
                str(i),
                _safe(d.get("domain"), 35),
                str(d.get("visits", 0)),
                _hm(d.get("total_seconds", 0)),
            ])
        dom_t = Table(dom_rows, colWidths=[0.7*cm, 9.5*cm, 2.5*cm, 3.3*cm])
        dom_t.setStyle(_HDR_STYLE)
        E.append(dom_t)
    else:
        E.append(Paragraph("No browser activity recorded for this period.", BODY))

    # ── recent browsing log ───────────────────────────────────────────────────
    if browser:
        E += _section_block("Recent Browser History (Last 20 Entries)", H2)
        br_rows = [["Timestamp", "Browser", "Domain", "Page Title", "Duration"]]
        for row in browser[:20]:
            ts = str(row.get("timestamp",""))[:16].replace("T", " ")
            br_rows.append([
                ts,
                _safe(row.get("browser"), 10),
                _safe(row.get("domain"),  22),
                _safe(row.get("title"),   38),
                _hm(row.get("duration_seconds", 0)),
            ])
        brt = Table(br_rows, colWidths=[3.2*cm, 1.8*cm, 3.8*cm, 5.5*cm, 1.7*cm])
        brt.setStyle(_HDR_STYLE)
        E.append(brt)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 4 — Activity Patterns
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section_block("Hourly Activity Pattern", H2)

    hourly = analytics.get("hourly_activity") or []
    hours_map = {r["hour"]: int(r.get("total_seconds", 0) or 0) // 60 for r in hourly}
    lc = _line_chart(hours_map, height=120)
    if lc:
        E.append(lc)
        E.append(Paragraph("Activity (minutes) by hour of day, 00:00 – 23:00.", SMALL))
        E.append(Spacer(1, 0.5*cm))
    else:
        E.append(Paragraph("No hourly activity data available.", BODY))

    # ── 30-day daily trend ────────────────────────────────────────────────────
    daily = analytics.get("daily_activity") or []
    if daily:
        E += _section_block("Daily Activity Trend", H2)
        d_labels = [r["date"][5:] for r in daily[:14]]   # MM-DD
        d_values = [int(r.get("total_seconds", 0) or 0) // 3600 for r in daily[:14]]
        bar2 = _bar_chart(d_labels, d_values, title="", bar_color=C_GREEN, height=110)
        if bar2:
            E.append(bar2)
            E.append(Paragraph("Hours of activity per day (last 14 days).", SMALL))
            E.append(Spacer(1, 0.4*cm))

    # ── daily table ───────────────────────────────────────────────────────────
    if daily:
        E += _section_block("Daily Breakdown", H2)
        d_rows = [["Date", "Active Time"]]
        for r in daily[:20]:
            d_rows.append([r["date"], _hm(r.get("total_seconds", 0))])
        # Two-column layout
        half = len(d_rows) // 2 + 1
        left_rows  = d_rows[:half]
        right_rows = d_rows[half:]
        # Pad right side
        while len(right_rows) < len(left_rows):
            right_rows.append(["", ""])
        combined = [[l[0], l[1], r[0], r[1]]
                    for l, r in zip(left_rows, right_rows)]
        dt = Table(combined, colWidths=[3*cm, 3*cm, 3*cm, 3*cm])
        dt.setStyle(TableStyle([
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND",   (0,0), (-1,0), C_NAVY),
            ("TEXTCOLOR",    (0,0), (-1,0), C_WHITE),
            ("FONTSIZE",     (0,0), (-1,-1), 8.5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE, C_ROW_ALT]),
            ("GRID",         (0,0), (-1,-1), 0.4, C_BORDER),
            ("TOPPADDING",   (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ("LEFTPADDING",  (0,0), (-1,-1), 8),
            ("ALIGN",        (1,0), (1,-1),  "CENTER"),
            ("ALIGN",        (3,0), (3,-1),  "CENTER"),
            ("LINEAFTER",    (1,0), (1,-1),  1, C_BORDER),
        ]))
        E.append(dt)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Last page — Disclaimer
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(Spacer(1, 0.8*cm))
    E.append(HRFlowable(width="100%", thickness=1, color=C_BORDER, spaceAfter=8))
    disc = (
        f"This report was automatically generated by the CropSentinel Employee Monitoring System. "
        f"All activity data is collected with prior employee consent in accordance with applicable "
        f"data-protection regulations. Access is restricted to authorised administrators of "
        f"<b>{company}</b>. Report generated on {now.strftime('%d %B %Y at %H:%M UTC')}."
    )
    E.append(Paragraph(disc, SMALL))

    # ── build ──────────────────────────────────────────────────────────────────
    doc.build(E)
    return filepath

"""Generate ARCHITECTURE.pdf with role → service flowchart layout."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "ARCHITECTURE.pdf"

# Colors
BLUE = colors.HexColor("#DBEAFE")
BLUE_DARK = colors.HexColor("#1E40AF")
GREEN = colors.HexColor("#D1FAE5")
PURPLE = colors.HexColor("#E0E7FF")
YELLOW = colors.HexColor("#FEF3C7")
GRAY = colors.HexColor("#64748B")
BORDER = colors.HexColor("#94A3B8")
WHITE = colors.white

styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Title", parent=styles["Title"], fontSize=22, textColor=colors.HexColor("#0F172A"), spaceAfter=6)
SUB = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, textColor=GRAY, spaceAfter=14)
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, textColor=BLUE_DARK, spaceBefore=16, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#334155"), spaceBefore=12, spaceAfter=6)
BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=6)
SMALL = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=GRAY, alignment=TA_CENTER)
CELL = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_CENTER)
CELL_L = ParagraphStyle("CellL", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_LEFT)
BOLD_CELL = ParagraphStyle("BoldCell", parent=CELL, fontName="Helvetica-Bold", fontSize=10)


def box(text, bg=BLUE, bold=True):
    style = BOLD_CELL if bold else CELL
    return Paragraph(f"<b>{text}</b>" if bold else text, style)


def arrow_row(cols=3):
    return Table(
        [[Paragraph("&#8595;", CELL) for _ in range(cols)]],
        colWidths=[5.6 * cm] * cols,
    )


def styled_table(data, col_widths, styles_list, row_heights=None):
    t = Table(data, colWidths=col_widths, rowHeights=row_heights)
    t.setStyle(TableStyle(styles_list))
    return t


def flow_box_table(label, subtitle=None, bg=BLUE, cols=3):
    content = f"<b>{label}</b>"
    if subtitle:
        content += f"<br/><font size='7' color='#64748B'>{subtitle}</font>"
    row = [Paragraph(content, CELL)] + [""] * (cols - 1)
    return styled_table(
        [row],
        [5.6 * cm] * cols,
        [
            ("SPAN", (0, 0), (cols - 1, 0)),
            ("BACKGROUND", (0, 0), (cols - 1, 0), bg),
            ("BOX", (0, 0), (cols - 1, 0), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ],
        row_heights=[1.2 * cm],
    )


def info_table(headers, rows, col_widths):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F8FAFC")]),
            ]
        )
    )
    return t


def build_flowchart():
    """Login → Role split → Service split."""
    elements = []
    cw3 = [5.6 * cm, 5.6 * cm, 5.6 * cm]

    elements.append(flow_box_table("Synthetic Focus Group App", "Entry point", BLUE, 3))
    elements.append(arrow_row(3))
    elements.append(flow_box_table("Login", "Email / password or social sign-in", BLUE, 3))
    elements.append(arrow_row(3))
    elements.append(flow_box_table("Role Selection", "User picks who they are", YELLOW, 3))
    elements.append(arrow_row(3))

    # Role split: Business (2 cols) | Buyer (1 col)
    role_data = [
        [
            Paragraph("<b>Business Owner</b><br/><font size='7' color='#64748B'>Sellers &amp; product teams</font>", CELL),
            Paragraph("<b>Business Owner</b><br/><font size='7' color='#64748B'>Sellers &amp; product teams</font>", CELL),
            Paragraph("<b>Buyer</b><br/><font size='7' color='#64748B'>Shoppers &amp; end customers</font>", CELL),
        ]
    ]
    elements.append(
        styled_table(
            role_data,
            cw3,
            [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (1, 0), GREEN),
                ("BACKGROUND", (2, 0), (2, 0), PURPLE),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ],
            row_heights=[1.4 * cm],
        )
    )
    elements.append(arrow_row(3))

    # Service split
    svc_data = [
        [
            Paragraph("<b>Service 1</b><br/>Price Bargaining", CELL),
            Paragraph("<b>Service 2</b><br/>Audience Discovery", CELL),
            Paragraph("<b>Service 3</b><br/>Local Deal Finder", CELL),
        ]
    ]
    elements.append(
        styled_table(
            svc_data,
            cw3,
            [
                ("BACKGROUND", (0, 0), (0, 0), GREEN),
                ("BACKGROUND", (1, 0), (1, 0), GREEN),
                ("BACKGROUND", (2, 0), (2, 0), PURPLE),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ],
            row_heights=[1.4 * cm],
        )
    )
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(
        Paragraph(
            "<i>Each service follows the same pipeline: Form → Live Data → 3-Agent Debate → Judge → Dashboard</i>",
            SMALL,
        )
    )
    return elements


def service_section(number, name, role, purpose, inputs, agents, output, api):
    """Build one full service explanation block."""
    el = []
    el.append(Paragraph(f"Service {number} — {name}", H1))
    el.append(Paragraph(f"<b>Role:</b> {role}", BODY))
    el.append(Paragraph(f"<b>Purpose:</b> {purpose}", BODY))
    el.append(Spacer(1, 0.15 * cm))

    el.append(Paragraph("User Inputs", H2))
    el.append(info_table(["Field", "Description"], inputs, [4 * cm, 12.8 * cm]))

    el.append(Paragraph("AI Agent Council (3 agents debate before Judge decides)", H2))
    el.append(info_table(["Agent", "What They Focus On"], agents, [5 * cm, 11.8 * cm]))

    el.append(Paragraph("Processing Pipeline", H2))
    pipeline = [
        ["1", "User submits the form"],
        ["2", "Backend fetches live market prices (SerpApi)"],
        ["3", "3 agents debate using real price data (Groq LLM)"],
        ["4", "Judge reads debate and outputs JSON verdict"],
        ["5", "Dashboard shows the final answer to the user"],
    ]
    el.append(info_table(["Step", "Action"], pipeline, [1.5 * cm, 15.3 * cm]))

    el.append(Paragraph("Final Output on Dashboard", H2))
    el.append(Paragraph(output, BODY))
    el.append(Paragraph(f"<b>API Route:</b> <font face='Courier'>{api}</font>", BODY))
    el.append(Spacer(1, 0.3 * cm))
    el.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=10))
    return el


def build_pdf():
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title="Synthetic Focus Group — Architecture",
    )
    story = []

    # Cover
    story.append(Paragraph("Synthetic Focus Group", TITLE))
    story.append(Paragraph("System Architecture Map · Version 2.0", SUB))
    story.append(
        Paragraph(
            "A multi-agent AI platform where 3 agents debate over live market data "
            "and a Judge delivers the final answer. Users pick a role, choose a service, "
            "and receive actionable results on their dashboard.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    # Main flowchart
    story.append(Paragraph("System Flowchart", H1))
    story.append(Paragraph("Login splits into roles. Each role leads to its own service(s).", BODY))
    story.extend(build_flowchart())
    story.append(PageBreak())

    # Shared pipeline
    story.append(Paragraph("Shared Pipeline (All Services)", H1))
    shared = [
        ["1 · Login", "User signs in"],
        ["2 · Role Pick", "User chooses Business Owner or Buyer"],
        ["3 · Service Pick", "User selects one of the 3 services below"],
        ["4 · Fill Form", "User enters details specific to that service"],
        ["5 · Live Sync", "Backend fetches real prices before AI runs"],
        ["6 · AI Debate", "3 specialized agents argue over the live data"],
        ["7 · Judge", "Judge agent produces structured JSON verdict"],
        ["8 · Dashboard", "User sees the final recommendation"],
    ]
    story.append(info_table(["Step", "What Happens"], shared, [3.5 * cm, 13.3 * cm]))
    story.append(PageBreak())

    # Service 1
    story.extend(
        service_section(
            1,
            "Price Bargaining",
            "Business Owner",
            "Help sellers find the optimal price for their product using live competitor data.",
            [
                ["Product Specs", "Key features, materials, and product details"],
                ["Estimated Price Range", "Minimum and maximum price under consideration"],
            ],
            [
                ["Premium Maximizer", "Argues for higher margins and premium positioning"],
                ["Volume Discounter", "Argues for lower prices to drive sales volume"],
                ["Market Benchmark Proxy", "Uses live competitor prices as neutral ground truth"],
            ],
            "Recommended selling price with confidence score, market comparison, and debate summary.",
            "POST /api/modes/price-bargaining",
        )
    )

    # Service 2
    story.extend(
        service_section(
            2,
            "Audience Discovery",
            "Business Owner",
            "Help sellers identify who would buy their product and why.",
            [
                ["Product Name", "Name of the product being analyzed"],
                ["Problem It Solves", "Primary problem the product addresses for customers"],
            ],
            [
                ["Demographic Scout", "Identifies age, income, location, and lifestyle segments"],
                ["Psychographic Analyst", "Analyzes values, motivations, and buying triggers"],
                ["Utility Specialist", "Evaluates practical use cases and feature fit"],
            ],
            "Three ideal buyer persona profiles with motivations, triggers, and channel recommendations.",
            "POST /api/modes/audience-discovery",
        )
    )

    # Service 3
    story.extend(
        service_section(
            3,
            "Local Deal Finder",
            "Buyer",
            "Help shoppers find the best real-world deal based on live local listings.",
            [
                ["Item Name", "Product the buyer wants to purchase"],
                ["Max Budget", "Maximum amount willing to spend (optional)"],
                ["Location", "City or region for localized price search"],
            ],
            [
                ["Thrift Advocate", "Finds the lowest price and best overall value"],
                ["Risk Analyst", "Evaluates vendor trust, warranty, and return policies"],
                ["Contextual Persona", "Matches the deal to buyer budget, location, and urgency"],
            ],
            "Buy or Pass verdict, best deal card (store, price, link), alternatives list, and agent reasoning.",
            "POST /api/modes/deal-finder",
        )
    )

    story.append(PageBreak())

    # Tech stack
    story.append(Paragraph("Tech Stack", H1))
    story.append(
        info_table(
            ["Layer", "Technology", "Purpose"],
            [
                ["Frontend", "React + Vite + TypeScript", "User dashboards and forms"],
                ["Backend API", "FastAPI (Python)", "Request routing and agent orchestration"],
                ["Live Prices", "Node.js + SerpApi", "Fetch real market listings before AI runs"],
                ["AI Engine", "Groq · Llama 3.3 70B", "Agent debates and Judge verdict"],
            ],
            [3.5 * cm, 5.5 * cm, 8 * cm],
        )
    )

    doc.build(story)
    print(f"Created {PDF_PATH}")


if __name__ == "__main__":
    build_pdf()

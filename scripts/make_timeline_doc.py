"""Generate the client-facing Query-to-Slide delivery-plan Word document."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1E, 0x3A, 0x8A)
BLUE = RGBColor(0x1E, 0x40, 0xAF)
AMBER = RGBColor(0xD9, 0x77, 0x06)
GRAY = RGBColor(0x64, 0x74, 0x8B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

doc = Document()

# base styles
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:fill"), hexcolor)
    tcPr.append(sh)


def set_cell_text(cell, text, bold=False, color=None, size=9.5, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    if align:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = color


def heading(text, size=15, color=NAVY, space_before=14, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = color
    return p


def meta_line(label, value):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(label + "  ")
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = BLUE
    v = p.add_run(value)
    v.font.size = Pt(10)


# ---- Title ----
title = doc.add_paragraph()
title.paragraph_format.space_after = Pt(2)
tr = title.add_run("Query-to-Slide Dashboard")
tr.bold = True
tr.font.size = Pt(22)
tr.font.color.rgb = NAVY

sub = doc.add_paragraph()
sub.paragraph_format.space_after = Pt(10)
sr = sub.add_run("Delivery Plan & Timeline")
sr.font.size = Pt(13)
sr.font.color.rgb = AMBER
sr.bold = True

# ---- Overview block ----
meta_line("Duration:", "6 weeks (30 working days). Achievable in 5 weeks if the dashboard build runs in parallel.")
meta_line("Scope:", "A self-service dashboard that keeps prescription-trend reports current — it flags when new "
                    "data arrives, refreshes saved reports on one click, and produces presentation-ready slides. "
                    "No spreadsheets, no formulas, no code for the business user.")
meta_line("Prerequisites at kickoff:", "data access, the reference PowerPoint, the existing calculation logic, "
                                       "and documented business rules.")

# ---- Section: Phase-by-phase ----
heading("Week-by-Week Plan", size=15)

phases = [
    ("Week 1 — Foundation: data & business rules",
     "We turn the raw data files and your business rules into a clean, reliable foundation. "
     "Nothing built later can be trusted until this is locked.",
     ["Confirm data access; check the data is complete and current.",
      "Map the data sources and define how they connect to each other.",
      "Translate your existing business rules into a reusable, documented rule library.",
      "Stand up automated data-quality checks that pause the system if data arrives in an unexpected shape.",
      ],
     "Milestone M1 — Data foundation locked."),

    ("Week 2 — Reporting engine: from question to validated result",
     "We build the core calculation logic for the first report and prove it against an existing slide.",
     ["Build the report logic for the first report, end-to-end.",
      "Reconcile the output against the existing slide — numbers must match exactly.",
      "Add automatic result checks and plain-English written takeaways for every result.",
      ],
     "Milestone M2 — Numbers match the source exactly."),

    ("Week 3 — Branded slides & report family",
     "We generate presentation-ready slides that match your template, and extend the logic across the report family.",
     ["Build the slide generator so output matches your branded reference deck.",
      "Review generated slides side-by-side against the reference and refine the styling.",
      "Extend the report logic across the wider report family, with capability-ready placeholders for future reports.",
      ],
     "Milestone M3 — Branded slides auto-built."),

    ("Week 4 — Dashboard: the refresh engine",
     "We build the behind-the-scenes engine that tracks data freshness and refreshes reports on demand.",
     ["Build data-freshness tracking and the status labels (in sync / data updated / fresh / stale).",
      "Build the three refresh depths: Check (look only), Update data (accept new data), Full refresh "
      "(recalculate reports and rebuild slides).",
      "Add a safe practice mode — simulate new data and reset back to the real numbers.",
      ],
     "Milestone M4 — Refresh engine operational."),

    ("Week 5 — Dashboard: the screens",
     "We build the screens the business user sees and connect everything end-to-end.",
     ["Build the four sections: data status, refresh, saved reports, and results.",
      "Add the status labels, trend charts, quality checks, and downloadable slides.",
      "Connect the screens to the engine and test the full click-through.",
      ],
     "Milestone M5 — Working dashboard, click-through complete."),

    ("Week 6 — Launch: testing, deployment & handover",
     "We harden the system, deploy it, and hand it over to your team.",
     ["Handle edge cases gracefully — unexpected data, interrupted jobs, held-back results.",
      "Deploy to a hosted environment and publish the built-in user guide; provide a live link.",
      "Run user-acceptance testing with your team and resolve the fix list.",
      "Train business users and the analytics contact; complete handover.",
      ],
     "Milestone M6 — Go-live & handover."),
]

for ptitle, intro, tasks, milestone in phases:
    heading(ptitle, size=12.5, color=BLUE, space_before=12, space_after=3)
    ip = doc.add_paragraph()
    ip.paragraph_format.space_after = Pt(4)
    ir = ip.add_run(intro)
    ir.italic = True
    ir.font.size = Pt(10)
    ir.font.color.rgb = GRAY
    for t in tasks:
        b = doc.add_paragraph(style="List Bullet")
        b.paragraph_format.space_after = Pt(1)
        b.add_run(t).font.size = Pt(10)
    mp = doc.add_paragraph()
    mp.paragraph_format.space_before = Pt(2)
    mr = mp.add_run(milestone)
    mr.bold = True
    mr.font.size = Pt(10)
    mr.font.color.rgb = AMBER

# ---- Section: Task table (Gantt-ready) ----
doc.add_page_break()
heading("Task Schedule (Gantt-ready)", size=15)
note = doc.add_paragraph()
note.paragraph_format.space_after = Pt(8)
nr = note.add_run("Day numbers are working days from kickoff (Day 1). Dependencies reference Task IDs.")
nr.italic = True
nr.font.size = Pt(9.5)
nr.font.color.rgb = GRAY

rows = [
    ("ID", "Task", "Phase", "Start", "Days", "Depends on", "Milestone"),
    ("1.1", "Data access & profiling", "Foundation", "D1", "2", "—", ""),
    ("1.2", "Map data sources & connections", "Foundation", "D3", "2", "1.1", ""),
    ("1.3", "Convert business rules to rule library", "Foundation", "D3", "3", "1.1", ""),
    ("1.4", "Automated data-quality checks", "Foundation", "D5", "1", "1.2, 1.3", "M1 (end Wk1)"),
    ("2.1", "Build report logic (first report)", "Engine", "D6", "3", "1.4", ""),
    ("2.2", "Reconcile numbers to existing slide", "Engine", "D9", "2", "2.1", "M2 (end Wk2)"),
    ("2.3", "Result checks & written takeaways", "Engine", "D9", "2", "2.1", ""),
    ("3.1", "Slide generator matching template", "Slides", "D11", "3", "2.2", ""),
    ("3.2", "Extend logic across report family", "Engine", "D11", "3", "2.2", ""),
    ("3.3", "Slide quality review vs reference", "Slides", "D14", "2", "3.1", "M3 (end Wk3)"),
    ("4.1", "Data-freshness tracking & labels", "Dashboard back-end", "D16", "2", "1.4", ""),
    ("4.2", "Three refresh depths", "Dashboard back-end", "D18", "3", "4.1, 3.2", ""),
    ("4.3", "Practice mode (simulate / reset)", "Dashboard back-end", "D21", "1", "4.1", "M4 (end Wk4)"),
    ("5.1", "Dashboard screens (4 sections)", "Dashboard front-end", "D21", "4", "4.2", ""),
    ("5.2", "Status labels, charts, slide download", "Dashboard front-end", "D25", "1", "5.1", ""),
    ("5.3", "End-to-end integration", "Dashboard front-end", "D25", "1", "5.2", "M5 (end Wk5)"),
    ("6.1", "Edge-case & safety handling", "Launch", "D26", "2", "5.3", ""),
    ("6.2", "Deploy + publish user guide", "Launch", "D26", "2", "5.3", ""),
    ("6.3", "Client UAT & fixes", "Launch", "D28", "2", "6.2", ""),
    ("6.4", "User training & handover", "Launch", "D30", "1", "6.3", "M6 (end Wk6)"),
]

table = doc.add_table(rows=len(rows), cols=7)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.style = "Table Grid"
widths = [Inches(0.4), Inches(2.1), Inches(1.3), Inches(0.5), Inches(0.4), Inches(0.8), Inches(0.9)]
for i, row in enumerate(rows):
    for j, val in enumerate(row):
        cell = table.cell(i, j)
        cell.width = widths[j]
        if i == 0:
            shade(cell, "1E3A8A")
            set_cell_text(cell, val, bold=True, color=WHITE, size=9)
        else:
            is_ms = bool(row[6])
            if is_ms:
                shade(cell, "FEF3C7")
            set_cell_text(cell, val, bold=(j == 0), size=9)

# ---- Section: Workstreams ----
heading("Workstream Summary (Gantt swimlanes)", size=14, space_before=16)
wrows = [
    ("Workstream", "Weeks", "Owner"),
    ("Foundation — data & business rules", "Week 1", "Business Analyst / Data Lead"),
    ("Reporting engine — logic & validation", "Weeks 2–3", "Analytics Developer"),
    ("Slides — branded deck generation", "Week 3", "Analytics Developer"),
    ("Dashboard — refresh engine (back-end)", "Week 4", "Developer"),
    ("Dashboard — screens (front-end)", "Week 5", "Front-end Developer"),
    ("Launch — testing, deploy, training", "Week 6", "Full team + Client"),
]
wt = doc.add_table(rows=len(wrows), cols=3)
wt.alignment = WD_TABLE_ALIGNMENT.CENTER
wt.style = "Table Grid"
wwidths = [Inches(3.2), Inches(1.2), Inches(2.4)]
for i, row in enumerate(wrows):
    for j, val in enumerate(row):
        cell = wt.cell(i, j)
        cell.width = wwidths[j]
        if i == 0:
            shade(cell, "1E3A8A")
            set_cell_text(cell, val, bold=True, color=WHITE, size=9.5)
        else:
            set_cell_text(cell, val, size=9.5)

# ---- Section: Notes ----
heading("Key Notes for the Client", size=14, space_before=16)
notes = [
    ("Critical path runs through Week 1.", " The business-rule library and data quality gate everything that "
     "follows. Clear rules and clean data at kickoff protect the entire timeline."),
    ("Weeks 4 and 5 can overlap.", " Running the refresh engine and the screens in parallel (two developers) "
     "brings delivery in at 5 weeks; running them sequentially (one developer) is the 6-week plan."),
    ("Week 6 carries the buffer.", " Any earlier slippage is absorbed here before go-live."),
    ("Six milestones, one per week.", " M1–M6 are natural check-in points for review and sign-off."),
]
for bold, rest in notes:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(bold)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = NAVY
    r2 = p.add_run(rest)
    r2.font.size = Pt(10)

out = r"C:\Users\RounakSuranshe\Documents\Abbvie-MRD-Automation\Query-to-Slide-Delivery-Plan.docx"
doc.save(out)
print("saved:", out)

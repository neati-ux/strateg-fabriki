"""Publish one reviewed project as an editable workbook, memo and briefing slides."""
import json
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import strateg as S
from calculations import calculate

TITLES = ("Решение", "Основания", "Варианты", "Продуктовая стратегия",
          "Коммуникация с клиентом", "План проверки")
MODELS = ("economics", "retention", "growth", "market-size")


def clean(text):
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"^(?:[-*>]+\s+|\d+\.\s+)", "", text.replace("**", "").replace("`", "")).strip()


def paragraphs(path):
    groups = []
    heading, lines = "", []
    content = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8-sig"), flags=re.S)
    for raw in content.splitlines():
        row = raw.strip()
        if row.startswith("#"):
            if lines:
                groups.append((heading, lines))
            heading, lines = clean(row.lstrip("# ")), []
        elif row.startswith("|"):
            cells = [clean(cell) for cell in row.strip("|").split("|") if cell.strip()]
            if cells and not re.fullmatch(r"[-: ]+", cells[0]):
                lines.append(" · ".join(cells))
        elif row and row != "---":
            lines.append(clean(row))
    if lines:
        groups.append((heading, lines))
    return groups


def short(text, limit):
    if len(text) <= limit:
        return text
    prefix = text[:limit + 1]
    breaks = [m.end() for m in re.finditer(r"[.!?](?=\s+[А-ЯЁ]|$)", prefix)]
    return prefix[:breaks[-1]] if breaks else prefix.rsplit(" ", 1)[0] + "…"


def model(project):
    sections = []
    for index, title in enumerate(TITLES):
        files = sorted((project / "outputs").glob(f"{index}-*.md"))
        if len(files) != 1:
            raise ValueError(f"Нужен один документ outputs/{index}-*.md, найдено {len(files)}")
        blocks = paragraphs(files[0])
        if not blocks:
            raise ValueError(f"{files[0].name} пуст")
        sections.append(dict(title=title, file=files[0].name, blocks=blocks))
    sources, claims = S.load(project)
    reports = []
    for path in sorted((project / "analysis").glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(report, dict) and report.get("calculation") in MODELS:
            kind = report["calculation"]
            data = report["inputs"]
            for name, inputs in [("База", data)] + [
                    (scenario, {**data, **changes}) for scenario, changes in data.get("scenarios", {}).items()]:
                reports.append((kind, name, path.name, inputs, calculate(kind, inputs)))
    # Publish the same computed rates captured in the editable workbook.
    for kind, name, filename, _, result in reports:
        if kind == "retention" and name == "База" and result["weighted_rate"] is not None:
            sections[1]["blocks"].append((filename, [f"Доля по всей группе — {result['weighted_rate']:.1%} ({result['retained']} из {result['size']})."]))
    return dict(project=project.name, sections=sections, claims=claims, sources=sources, reports=reports)


def highlights(section, limit):
    blocks = section["blocks"]
    # Each topic gets space before a second item of the same topic.
    selected = [(h, lines[0]) for h, lines in blocks][:limit]
    if len(selected) < limit:
        for h, lines in blocks:
            selected.extend((h, line) for line in lines[1:limit - len(selected) + 1])
    return selected[:limit]


def memo(data, path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    # Vera shipped by ReportLab lacks Cyrillic. Select an installed Unicode family.
    fonts = [("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
             ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
             ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")]
    family = next((pair for pair in fonts if all(Path(f).is_file() for f in pair)), None)
    if not family:
        raise ValueError("Для PDF требуется Arial или DejaVu Sans с поддержкой кириллицы")
    for name, filename in zip(("Committee", "CommitteeBold"), family):
        pdfmetrics.registerFont(TTFont(name, filename))
    pdf = Canvas(str(path), pagesize=A4)
    pdf.setTitle("Записка для комитета · " + data["project"])
    for i, section in enumerate(data["sections"], 1):
        pdf.setFillColorRGB(.08, .25, .28)
        pdf.setFont("Committee", 11)
        pdf.drawString(48, 791, data["project"])
        pdf.setFont("CommitteeBold", 26)
        pdf.drawString(48, 740, section["title"])
        y = 705
        for heading, line in highlights(section, 6):
            for value, face, size in [(short(heading, 84), "CommitteeBold", 12),
                                      (short(line, 485), "Committee", 11)]:
                paragraph = Paragraph(escape(value), ParagraphStyle("memo", fontName=face, fontSize=size, leading=size*1.4))
                _, height = paragraph.wrap(496, 700)
                if y-height < 64:
                    y = 0
                    break
                paragraph.drawOn(pdf, 48, y-height)
                y -= height+5
            if not y:
                break
            y -= 13
        pdf.setFont("Committee", 9)
        pdf.drawString(48, 40, section["file"])
        pdf.drawRightString(545, 40, f"{i} / 6")
        pdf.showPage()
    pdf.save()


def slides(data, path):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.33), Inches(7.5)

    def box(slide, x, y, w, h, value, size, color, bold=False):
        frame = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
        frame.word_wrap = True
        para = frame.paragraphs[0]
        run = para.add_run()
        run.text = value
        font = run.font
        font.name, font.size, font.bold = "Arial", Pt(size), bold
        font.color.rgb = RGBColor.from_string(color)
    for i, section in enumerate(data["sections"], 1):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        box(slide, .7, .38, 11, .45, data["project"], 15, "226D70")
        box(slide, .7, .91, 12, .8, section["title"], 39, "193840", True)
        for j, (heading, value) in enumerate(highlights(section, 3)):
            y = 1.97 + j*1.56
            box(slide, .7, y, 12, .43, short(heading, 75), 17, "226D70", True)
            box(slide, .7, y+.43, 11.9, 1.08, short(value, 205), 19, "193840")
        box(slide, .7, 7.02, 12, .32, f"{section['file']}     ·     {i} / 6", 10, "52696B")
    deck.save(path)


def export(project, output):
    from committee_workbook import workbook
    if output.exists():
        raise ValueError(f"Папка назначения уже существует: {output}")
    data = model(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp) / "files"
        stage.mkdir()
        workbook(data, stage / "Модель.xlsx")
        memo(data, stage / "Записка.pdf")
        slides(data, stage / "Презентация.pptx")
        stage.rename(output)


def cmd(args):
    project = S.project_dir(args.project)
    try:
        import delivery
        errors, _ = S.run_check(project)
        if errors:
            raise ValueError("Исправьте ошибки команды check перед выпуском")
        reviewed = project / "delivery-review.json"
        if not reviewed.exists() or json.loads(reviewed.read_text(encoding="utf-8")) != delivery.snapshot(project):
            raise ValueError("Сверьте документы и выполните delivery review перед выпуском")
        export(project, Path(args.output))
        print(Path(args.output).resolve())
    except ImportError as exc:
        S.die(f"Для экспорта нужны XlsxWriter, reportlab и python-pptx ({exc})")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        S.die(str(exc))

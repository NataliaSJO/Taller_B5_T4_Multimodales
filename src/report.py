"""Deliverables of a conversation: the PDF report and the text of the spoken summary."""

import io
import re
from datetime import date
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .conversation import CURRENCY_NAMES
from .models import Preferences, Proposal
from .recommender import CUTOFF, RISK

NAVY = colors.HexColor("#173553")
TEAL = colors.HexColor("#087f8c")
PALE = colors.HexColor("#f1f6f8")
DISCLAIMER = ("Preselección educativa basada en datos históricos. No es asesoramiento de inversión, "
              "no sustituye un test de idoneidad y no verifica comisiones ni tu situación personal. "
              "Las rentabilidades pasadas no garantizan rentabilidades futuras.")
ORDINALS = ("Primero", "Segundo", "Tercero", "Cuarto", "Quinto", "Sexto", "Séptimo")


def percents(weights) -> list[int]:
    """Whole percentages that add up to exactly 100 (largest remainder)."""
    raw = [weight * 100 for weight in weights]
    result = [int(value) for value in raw]
    by_remainder = sorted(range(len(raw)), key=lambda index: raw[index] - result[index], reverse=True)
    for index in by_remainder[:100 - sum(result)]:
        result[index] += 1
    return result


def _spoken(value: float) -> str:
    return f"{value * 100:.1f}".replace(".", ",").removesuffix(",0")


def summary_text(proposal: Proposal, preferences: Preferences, notes: list[str] = ()) -> str:
    """What the assistant says aloud: where to invest, given the conversation."""
    years = preferences.horizon_years
    currency = CURRENCY_NAMES.get(preferences.currency, preferences.currency)
    shares = percents(proposal.weights)
    what = f"los {preferences.amount:.0f} {currency}" if preferences.amount else "tu inversión"
    count = len(proposal.items)
    parts = [*notes, f"Con lo que me has contado, he buscado fondos en {currency} para un plazo de "
             f"{years} {'año' if years == 1 else 'años'} y un riesgo {preferences.risk}. "
             + (f"Te propongo repartir {what} entre {count} fondos." if count > 1
                else f"Solo un fondo cumple tus criterios, así que {what} iría a ese fondo.")]
    for index, (item, share) in enumerate(zip(proposal.items, shares)):
        ret, vol, _ = item.fund.metrics(years)
        amount = f", unos {preferences.amount * share / 100:.0f} {currency}" if preferences.amount else ""
        name = " ".join(re.sub(r"[^\w&.,' -]", " ", item.fund.name).split())
        parts.append(f"{ORDINALS[index]}, {name}, con el {share} por ciento{amount}. "
                     f"En {years} {'año' if years == 1 else 'años'} acumuló una rentabilidad del "
                     f"{_spoken(ret)} por ciento con una volatilidad del {_spoken(vol)} por ciento.")
    parts.append("Tienes el detalle en el documento PDF. Recuerda que es una preselección educativa "
                 "basada en datos históricos y no un asesoramiento financiero.")
    return " ".join(parts)


def _text(value) -> str:
    """Escape for Paragraph markup and keep to the characters Helvetica can draw."""
    return escape(str(value).encode("cp1252", "replace").decode("cp1252"))


def _pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    return (f"{value:+.1%}" if signed else f"{value:.1%}").replace(".", ",").replace("%", " %")


def _chart(proposal: Proposal, years: int) -> Drawing:
    drawing = Drawing(16 * cm, 6.2 * cm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 1.2 * cm, 0.8 * cm, 11.5 * cm, 4.8 * cm
    metrics = [item.fund.metrics(years) for item in proposal.items]
    chart.data = [[ret * 100 for ret, _, _ in metrics], [vol * 100 for _, vol, _ in metrics]]
    chart.categoryAxis.categoryNames = [f"Fondo {index}" for index in range(1, len(metrics) + 1)]
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.valueMin = min(0, *chart.data[0])
    chart.bars[0].fillColor, chart.bars[1].fillColor = TEAL, NAVY
    chart.bars.strokeColor = None
    legend = Legend()
    legend.x, legend.y, legend.fontSize, legend.alignment = 13.2 * cm, 4.6 * cm, 8, "right"
    legend.colorNamePairs = [(TEAL, f"Rentabilidad {years} a. (%)"), (NAVY, "Volatilidad (%)")]
    drawing.add(chart)
    drawing.add(legend)
    return drawing


def capital_evolution(proposal: Proposal, amount: float, years: int) -> list[tuple[float, float]]:
    """Monthly illustration using each fund's cumulative historical return, without rebalancing."""
    returns = [item.fund.metrics(years)[0] for item in proposal.items]
    return [
        (month / 12, amount * sum(
            weight * (1 + ret) ** (month / (12 * years))
            for weight, ret in zip(proposal.weights, returns)
        ))
        for month in range(years * 12 + 1)
    ]


def _capital_chart(points: list[tuple[float, float]], years: int, currency: str) -> Drawing:
    drawing = Drawing(16 * cm, 7 * cm)
    chart = LinePlot()
    chart.x, chart.y, chart.width, chart.height = 2.5 * cm, 1.2 * cm, 12.5 * cm, 4.8 * cm
    chart.data = [points]
    chart.lines[0].strokeColor = TEAL
    chart.lines[0].strokeWidth = 2
    chart.xValueAxis.valueMin, chart.xValueAxis.valueMax = 0, years
    chart.xValueAxis.valueSteps = list(range(years + 1))
    chart.xValueAxis.labels.fontSize = 8
    chart.yValueAxis.labels.fontSize = 8
    chart.yValueAxis.labelTextFormat = lambda value: f"{value:,.0f}".replace(",", ".")
    values = [value for _, value in points]
    padding = max((max(values) - min(values)) * 0.1, max(values) * 0.05, 1)
    chart.yValueAxis.valueMin = max(0, min(values) - padding)
    chart.yValueAxis.valueMax = max(values) + padding
    drawing.add(chart)
    drawing.add(String(2.5 * cm, 6.4 * cm, f"Capital ({currency})", fontSize=9, fillColor=NAVY))
    drawing.add(String(9 * cm, 0.3 * cm, "Años desde la inversión", fontSize=9, textAnchor="middle"))
    return drawing


def build_pdf(proposal: Proposal, preferences: Preferences, user_turns: list[str], source: str,
              notes: list[str] = (), criteria: str = "") -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    title = ParagraphStyle("title", parent=styles["Title"], textColor=NAVY, alignment=0, fontSize=20)
    heading = ParagraphStyle("heading", parent=styles["Heading2"], textColor=NAVY, fontSize=13, spaceBefore=12)

    years = preferences.horizon_years
    currency = preferences.currency
    shares = percents(proposal.weights)
    grid = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d6dc")),
    ])

    story = [Paragraph("FondoClaro · Propuesta de fondos", title),
             Paragraph(f"Generada el {date.today():%d/%m/%Y} · datos hasta el {CUTOFF:%d/%m/%Y} · {_text(source)}", small),
             Paragraph("Lo que nos has contado", heading)]
    story += [Paragraph(f"«{_text(turn)}»", body) for turn in user_turns]

    story.append(Paragraph("Perfil interpretado", heading))
    profile_rows = [("Horizonte", f"{years} {'año' if years == 1 else 'años'}"),
                    ("Riesgo aplicado", f"{preferences.risk} (volatilidad histórica hasta el {RISK[preferences.risk][1]:.0%})"),
                    ("Divisa", currency),
                    ("Importe", f"{preferences.amount:,.0f} {currency}".replace(",", ".") if preferences.amount else "no indicado")]
    profile_rows += [(name, value) for name, value in (("Región", preferences.region), ("Sector", preferences.sector),
                                                       ("Clase de activo", preferences.asset_class),
                                                       ("Diversificación", preferences.diversification),
                                                       ("Objetivo", preferences.objective),
                                                       ("Experiencia inversora", preferences.experience),
                                                       ("Ante una caída fuerte", preferences.loss_reaction)) if value]
    profile = Table(profile_rows, colWidths=[4 * cm, 12 * cm])
    profile.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                                 ("TEXTCOLOR", (0, 0), (0, -1), NAVY), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story.append(profile)
    story += [Paragraph(f"<b>Ajuste del asesor:</b> {_text(note)}", body) for note in notes]

    story.append(Paragraph("Cartera propuesta", heading))
    rows = [["#", "Fondo", "Peso", "Importe", f"Rent. {years} a.", "Volatilidad", "Sharpe"]]
    for index, (item, share) in enumerate(zip(proposal.items, shares), start=1):
        ret, vol, sharpe = item.fund.metrics(years)
        amount = f"{preferences.amount * share / 100:,.0f} {currency}".replace(",", ".") if preferences.amount else "—"
        rows.append([str(index), Paragraph(f"<b>{_text(item.fund.name)}</b><br/>{_text(item.fund.isin)}", cell),
                     f"{share} %", amount, _pct(ret, signed=True), _pct(vol),
                     "—" if sharpe is None else f"{sharpe:+.2f}".replace(".", ",")])
    table = Table(rows, colWidths=[0.7 * cm, 6.8 * cm, 1.4 * cm, 2.4 * cm, 1.8 * cm, 1.9 * cm, 1.4 * cm], repeatRows=1)
    table.setStyle(grid)
    story.append(table)
    weighted = sum(item.fund.metrics(years)[0] * weight for item, weight in zip(proposal.items, proposal.weights))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Rentabilidad acumulada histórica de la cartera a {years} "
                           f"{'año' if years == 1 else 'años'}, ponderada por peso: <b>{_pct(weighted, signed=True)}</b>.", body))
    if proposal.comment:
        story.append(Paragraph(_text(proposal.comment), body))
    story.append(_chart(proposal, years))

    story.append(Paragraph("Evolución ilustrativa de tu capital", heading))
    if preferences.amount is not None and preferences.amount > 0:
        points = capital_evolution(proposal, preferences.amount, years)
        story.append(Paragraph(
            "Simulación, no una previsión ni una serie histórica real. Se anualiza la rentabilidad "
            "acumulada de cada fondo en el período seleccionado y se supone que se repite de forma "
            "constante durante tu plazo. Se mantiene la inversión inicial en cada fondo, sin "
            "rebalanceos ni aportaciones adicionales. No se descuentan impuestos ni costes adicionales; "
            "no se representan fluctuaciones ni posibles pérdidas futuras.", small))
        story.append(_capital_chart(points, years, currency))
        initial, final = points[0][1], points[-1][1]
        story.append(Paragraph(
            f"Capital inicial: <b>{initial:,.2f} {_text(currency)}</b>. "
            f"Capital final en esta simulación a {years} años: <b>{final:,.2f} {_text(currency)}</b>.", body))
    else:
        story.append(Paragraph(
            "No se ha indicado un importe de inversión. Indica cuánto quieres invertir para "
            "incluir el gráfico de evolución del capital.", body))

    story.append(Paragraph("Por qué cada fondo", heading))
    for index, item in enumerate(proposal.items, start=1):
        story.append(Paragraph(f"<b>{index}. {_text(item.fund.name)}</b> — {_text(item.rationale)}", body))

    story.append(Paragraph("Cómo se ha calculado", heading))
    story.append(Paragraph(
        "Primero se descartan los fondos de otra divisa, con datos incompletos o desactualizados y los que superan "
        "el límite de volatilidad del perfil. Los restantes se puntúan por ajuste a la volatilidad objetivo, "
        "Sharpe y rentabilidad anualizada, con más peso de la rentabilidad si el objetivo es crecer y más peso "
        "de la estabilidad si es conservar. "
        "Las preferencias de zona, sector o clase de activo se comprueban con la ficha verificada del fondo o, "
        "si no existe, con su nombre. Solo se incluye una clase de participación por fondo. El catálogo no "
        "informa de mínimos de suscripción: se consideran todos los fondos y, por debajo de 100.000, entre las "
        "clases de un mismo fondo se prefiere la que no parece institucional. El mínimo real debe comprobarse "
        "en el folleto. "
        + (f"Antes de filtrar, el modelo decidió estos criterios, que se aplicaron a todo el catálogo: {_text(criteria)}. "
           if criteria else "")
        + f"Selección final y pesos: {_text(proposal.method)}. Cuando el modelo no propone un reparto válido, los pesos "
        "son inversamente proporcionales a la volatilidad de cada fondo. No se dispone de correlaciones entre fondos, "
        "por lo que el reparto no es una optimización de cartera completa.", body))
    story.append(Spacer(1, 8))
    story.append(Paragraph(DISCLAIMER, small))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=1.8 * cm, title="FondoClaro · Propuesta de fondos").build(story)
    return buffer.getvalue()

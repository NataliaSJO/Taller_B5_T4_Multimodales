"""Deliverables of a conversation: the PDF report and the text of the spoken summary."""

import io
import re
from bisect import bisect_left
from datetime import date
from decimal import Decimal
from math import fsum
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
from .models import Preferences, Proposal, metric_years
from .money import format_money, investment_allocation
from .recommender import CUTOFF, RISK

NAVY = colors.HexColor("#173553")
TEAL = colors.HexColor("#087f8c")
PALE = colors.HexColor("#f1f6f8")
DISCLAIMER = ("Preselección educativa basada en datos históricos. No es asesoramiento de inversión, "
              "no sustituye un test de idoneidad y no verifica comisiones ni tu situación personal. "
              "Las rentabilidades pasadas no garantizan rentabilidades futuras.")
ORDINALS = ("Primero", "Segundo", "Tercero", "Cuarto", "Quinto", "Sexto", "Séptimo")


def percents(weights, decimals: int = 0):
    """Display percentages adding up to 100; never used to calculate money."""
    scale = 10 ** decimals
    decimal_weights = [Decimal(str(weight)) for weight in weights]
    raw = [weight / sum(decimal_weights) * 100 * scale for weight in decimal_weights]
    result = [int(value) for value in raw]
    by_remainder = sorted(range(len(raw)), key=lambda index: raw[index] - result[index], reverse=True)
    for index in by_remainder[:100 * scale - sum(result)]:
        result[index] += 1
    return result if not decimals else [Decimal(value) / scale for value in result]


def _spoken(value: float) -> str:
    return f"{value * 100:.1f}".replace(".", ",").removesuffix(",0")


def summary_text(proposal: Proposal, preferences: Preferences, notes: list[str] = ()) -> str:
    """What the assistant says aloud: where to invest, given the conversation."""
    years = preferences.horizon_years
    currency = CURRENCY_NAMES.get(preferences.currency, preferences.currency)
    allocation = investment_allocation(proposal.weights, preferences.amount)
    shares = percents(allocation.weights, 2)
    what = f"los {format_money(preferences.amount, False).removesuffix(',00')} {currency}" if preferences.amount else "tu inversión"
    count = len(proposal.items)
    parts = [*notes, f"Con lo que me has contado, he buscado fondos en {currency} para un plazo de "
             f"{years} {'año' if years == 1 else 'años'} y un riesgo {preferences.risk}. "
             + (f"Te propongo repartir {what} entre {count} fondos." if count > 1
                else f"Te propongo invertir {what} en un fondo.")]
    if preferences.fund_count and count < preferences.fund_count:
        parts.append(f"Has pedido {preferences.fund_count} fondos, pero solo hay {count} disponibles tras los filtros.")
    for index, (item, share) in enumerate(zip(proposal.items, shares)):
        ret, vol, _ = item.fund.metrics(years)
        window = metric_years(years)
        amount = (f", {format_money(allocation.amounts[index], False).removesuffix(',00')} {currency}"
                  if allocation.amounts is not None else "")
        name = " ".join(re.sub(r"[^\w&.,' -]", " ", item.fund.name).split())
        parts.append(f"{ORDINALS[index]}, {name}, con aproximadamente el {str(share).replace('.', ',')} por ciento{amount}. "
                     f"En {window} {'año' if window == 1 else 'años'} acumuló una rentabilidad del "
                     f"{_spoken(ret)} por ciento con una volatilidad del {_spoken(vol)} por ciento.")
    parts.append("Tienes el detalle en el documento PDF. Recuerda que es una preselección educativa "
                 "basada en datos históricos y no un asesoramiento financiero.")
    return " ".join(parts)


def peer_share(peers, value: float) -> float | None:
    """Fraction of comparable funds that did worse than this return."""
    return bisect_left(peers, value) / len(peers) if peers else None


def peer_median(peers) -> float | None:
    return peers[len(peers) // 2] if peers else None


def _beaten(share: float) -> str:
    """«a la de más del 99,9 %» for the very top, «a la del 87,3 %» otherwise."""
    return "a la de más del 99,9 %" if share > 0.999 else "a la del " + f"{share * 100:.1f}".replace(".", ",") + " %"


def _round(value: float) -> str:
    return f"{value * 100:.0f}"


def brief_summary(proposal: Proposal, preferences: Preferences, notes: list[str] = (), analysis=None,
                  reviewed: int = 0, peers=()) -> str:
    """Under a minute, in plain words: what kind of portfolio this is and how it has behaved as a
    whole. Fund names and weights are on screen and in the PDF; they are told only if asked for."""
    years = preferences.horizon_years
    currency = CURRENCY_NAMES.get(preferences.currency, preferences.currency)
    count = len(proposal.items)
    weights = list(investment_allocation(proposal.weights, preferences.amount).weights)
    parts = [*notes]
    looked = f"Después de revisar {reviewed} fondos, " if reviewed else ""
    parts.append(f"{looked}{'he' if looked else 'He'} preparado una cartera de "
                 f"{'un fondo' if count == 1 else f'{count} fondos'} en {currency}, pensada para "
                 f"{years} {'año' if years == 1 else 'años'} y un riesgo {preferences.risk}.")

    kinds = {}
    for item in proposal.items:
        assets = item.fund.assets.lower()
        kind = ("mixtos" if "mixt" in assets or ("renta fija" in assets and "renta variable" in assets)
                else "de renta variable" if "renta variable" in assets
                else "de renta fija" if "renta fija" in assets
                else "monetarios" if "monetario" in assets else None)
        if kind:
            kinds[kind] = kinds.get(kind, 0) + 1
    if sum(kinds.values()) >= max(2, count - 1):      # only when the documents describe most of them
        mix = [f"{number} {kind}" for kind, number in sorted(kinds.items(), key=lambda pair: -pair[1])]
        parts.append("Son " + (", ".join(mix[:-1]) + " y " + mix[-1] if len(mix) > 1 else mix[0]) + ".")
    if count > 1:
        parts.append(f"El dinero queda repartido y ningún fondo pesa más del {_round(max(float(w) for w in weights))} por ciento.")

    if analysis:
        span = max(1, round(analysis.points[-1][0]))
        yearly = (1 + analysis.total_return) ** (1 / max(analysis.points[-1][0], 0.5)) - 1
        parts.append(f"En {'el último año' if span == 1 else f'los últimos {span} años'}, esta cartera en conjunto "
                     f"habría ganado un {_round(analysis.total_return)} por ciento, alrededor de un {_round(yearly)} "
                     f"por ciento al año. Por el camino llegó a caer un {_round(abs(analysis.max_drawdown))} por ciento "
                     "desde su punto más alto, así que hay que contar con baches así.")
        if analysis.worst_year is not None:
            parts.append(f"Su peor año fue de un {_round(analysis.worst_year)} por ciento "
                         f"y el mejor de un {_round(analysis.best_year)}.".replace("un -", "un menos "))
    else:
        window = metric_years(years)
        weighted = sum(item.fund.metrics(years)[0] * float(weight) for item, weight in zip(proposal.items, weights))
        parts.append(f"En {'el último año' if window == 1 else f'los últimos {window} años'}, estos fondos, con este "
                     f"reparto, acumularon una rentabilidad del {_round(weighted)} por ciento.")
    median = peer_median(peers)
    if median is not None:
        window = metric_years(years)
        mine = sum(item.fund.metrics(years)[0] * float(weight) for item, weight in zip(proposal.items, weights))
        parts.append(f"Para que te hagas una idea, lo normal entre los fondos parecidos fue "
                     f"{'ganar' if median >= 0 else 'perder'} un {_round(abs(median))} por ciento en "
                     f"{'ese año' if window == 1 else f'esos {window} años'}"
                     + ("; estos están entre los que mejor lo hicieron, así que no cuentes con que se repita."
                        if peer_share(peers, mine) >= 0.90 else "."))
    costs = [item.fund.costs for item in proposal.items if item.fund.costs is not None]
    if len(costs) >= max(2, count - 1):
        parts.append(f"Sus costes rondan el {_spoken(sum(costs) / len(costs) / 100)} por ciento al año.")
    parts.append("Tienes los fondos, los pesos y el informe en pantalla. Recuerda que es una orientación educativa, "
                 "no un asesoramiento. ¿Quieres que te cuente el detalle de cada fondo?")
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
    legend.colorNamePairs = [(TEAL, f"Rentabilidad {metric_years(years)} a. (%)"), (NAVY, "Volatilidad (%)")]
    drawing.add(chart)
    drawing.add(legend)
    return drawing


def capital_evolution(proposal: Proposal, amount: float, years: int) -> list[tuple[float, float]]:
    """Monthly illustration using each fund's cumulative historical return, without rebalancing."""
    returns = [item.fund.metrics(years)[0] for item in proposal.items]
    allocation = investment_allocation(proposal.weights, amount)
    window = metric_years(years)
    return [
        (month / 12, fsum(
            float(initial) * (1 + ret) ** (month / (12 * window))
            for initial, ret in zip(allocation.amounts, returns)
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


def scenario_points(rate: float, years: int, base: float) -> list[tuple[float, float]]:
    """Capital over the horizon if every year repeated the given yearly return."""
    return [(month / 12, base * (1 + rate) ** (month / 12)) for month in range(years * 12 + 1)]


def _scenario_chart(analysis, years: int, base: float, currency: str, typical: float, typical_label: str) -> Drawing:
    """Three lines: every year like the portfolio's worst and best, and a middle one (`typical`)."""
    drawing = Drawing(16 * cm, 7.4 * cm)
    chart = LinePlot()
    chart.x, chart.y, chart.width, chart.height = 2.5 * cm, 1.2 * cm, 9.6 * cm, 4.8 * cm
    scenarios = ((analysis.worst_year, colors.HexColor("#c0392b"), "Como el peor año"),
                 (typical, NAVY, typical_label),
                 (analysis.best_year, TEAL, "Como el mejor año"))
    chart.data = [scenario_points(rate, years, base) for rate, _, _ in scenarios]
    for index, (_, color, _) in enumerate(scenarios):
        chart.lines[index].strokeColor = color
        chart.lines[index].strokeWidth = 2
    chart.xValueAxis.valueMin, chart.xValueAxis.valueMax = 0, years
    chart.xValueAxis.valueSteps = list(range(0, years + 1, max(1, years // 10)))
    chart.xValueAxis.labels.fontSize = 8
    chart.yValueAxis.labels.fontSize = 8
    chart.yValueAxis.labelTextFormat = lambda value: f"{value:,.0f}".replace(",", ".")
    values = [value for line in chart.data for _, value in line]
    chart.yValueAxis.valueMin, chart.yValueAxis.valueMax = 0, max(values) * 1.05
    legend = Legend()
    legend.x, legend.y, legend.fontSize, legend.alignment = 12.6 * cm, 5.2 * cm, 8, "right"
    legend.colorNamePairs = [(color, f"{label} ({_pct(rate, signed=True)})") for rate, color, label in scenarios]
    drawing.add(chart)
    drawing.add(legend)
    drawing.add(String(2.5 * cm, 6.5 * cm, f"Capital ({currency})", fontSize=9, fillColor=NAVY))
    drawing.add(String(7.3 * cm, 0.3 * cm, "Años desde la inversión", fontSize=9, textAnchor="middle"))
    return drawing


def build_pdf(proposal: Proposal, preferences: Preferences, user_turns: list[str], source: str,
              notes: list[str] = (), criteria: str = "", others: list = (), analysis=None, peers=()) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    title = ParagraphStyle("title", parent=styles["Title"], textColor=NAVY, alignment=0, fontSize=20)
    heading = ParagraphStyle("heading", parent=styles["Heading2"], textColor=NAVY, fontSize=13, spaceBefore=12)

    years = preferences.horizon_years
    currency = preferences.currency
    allocation = investment_allocation(proposal.weights, preferences.amount)
    shares = percents(allocation.weights, 2)
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
                    ("Importe", f"{format_money(preferences.amount)} {currency}" if preferences.amount else "no indicado")]
    if preferences.fund_count:
        profile_rows.append(("Fondos solicitados", str(preferences.fund_count)))
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
    window = metric_years(years)
    rows = [["#", "Fondo", "Peso aprox.", "Importe", f"Rent. {window} a.", "Volatilidad", "Sharpe"]]
    for index, (item, share) in enumerate(zip(proposal.items, shares), start=1):
        ret, vol, sharpe = item.fund.metrics(years)
        amount = f"{format_money(allocation.amounts[index - 1])} {currency}" if allocation.amounts is not None else "—"
        rows.append([str(index), Paragraph(f"<b>{_text(item.fund.name)}</b><br/>{_text(item.fund.isin)}", cell),
                     f"{str(share).replace('.', ',')} %", amount, _pct(ret, signed=True), _pct(vol),
                     "—" if sharpe is None else f"{sharpe:+.2f}".replace(".", ",")])
    table = Table(rows, colWidths=[0.7 * cm, 6.8 * cm, 1.4 * cm, 2.4 * cm, 1.8 * cm, 1.9 * cm, 1.4 * cm], repeatRows=1)
    table.setStyle(grid)
    story.append(table)
    if preferences.fund_count and len(proposal.items) < preferences.fund_count:
        story.append(Paragraph(f"Se solicitaron {preferences.fund_count} fondos; solo hay "
                               f"{len(proposal.items)} disponibles tras los filtros.", body))
    story.append(Paragraph("Los porcentajes se muestran redondeados a dos decimales. Los cálculos usan "
                           "los importes asignados a céntimos cuando se indica una inversión.", small))
    weighted = sum(item.fund.metrics(years)[0] * weight for item, weight in zip(proposal.items, allocation.weights))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Rentabilidad acumulada histórica de la cartera a {window} "
                           f"{'año' if window == 1 else 'años'}, ponderada por peso: <b>{_pct(weighted, signed=True)}</b>.", body))
    median = peer_median(peers)
    if median is not None:
        top = peer_share(peers, weighted) >= 0.90
        story.append(Paragraph(
            "<b>Para ponerlo en contexto:</b> entre los " + f"{len(peers):,}".replace(",", ".")
            + " fondos comparables (misma divisa, datos completos y "
            + f"volatilidad dentro del perfil), la rentabilidad mediana en ese periodo fue del <b>{_pct(median, signed=True)}</b>. "
            + ("Los fondos de esta propuesta están entre los que mejor lo hicieron; es lo que ocurre al elegir mirando el "
               "pasado, y no hay que contar con que se repita." if top else
               "Las rentabilidades pasadas no anticipan las futuras."), body))
    if proposal.comment:
        story.append(Paragraph(_text(proposal.comment), body))
    story.append(_chart(proposal, years))

    if analysis:
        base = float(preferences.amount) if preferences.amount else 100.0
        points = [(elapsed, value * base) for elapsed, value in analysis.points]
        story.append(Paragraph("Cómo se habría comportado esta cartera", heading))
        together = (f" La correlación media entre los fondos fue de {analysis.mean_correlation:.2f}".replace(".", ",") + "."
                    if analysis.mean_correlation is not None else "")
        story.append(Paragraph(
            f"Serie histórica real, con los precios diarios de cada fondo durante {analysis.weeks} semanas: se compra "
            "la cartera al inicio con estos pesos y se mantiene, sin rebalanceos ni aportaciones. En conjunto tuvo una "
            f"volatilidad anual del <b>{_pct(analysis.volatility)}</b>, una caída máxima del "
            f"<b>{_pct(abs(analysis.max_drawdown))}</b> y una rentabilidad acumulada del "
            f"<b>{_pct(analysis.total_return, signed=True)}</b>.{together} No se descuentan impuestos ni costes "
            "adicionales y no es una previsión.", small))
        story.append(_capital_chart(points, max(1, round(points[-1][0])), currency if preferences.amount else "base 100"))
    if analysis and analysis.worst_year is not None:
        base = float(preferences.amount) if preferences.amount else 100.0
        unit = currency if preferences.amount else "base 100"
        if median is not None:      # the middle scenario is a typical comparable fund, not these past winners
            typical = (1 + median) ** (1 / window) - 1
            typical_label = "Como un fondo comparable típico"
            middle = (f"El escenario central no usa el año mediano de esta cartera (<b>{_pct(analysis.median_year, signed=True)}</b>), "
                      f"sino lo que ganó al año un fondo comparable típico (<b>{_pct(typical, signed=True)}</b>), porque estos "
                      "fondos se han elegido entre los que mejor lo hicieron. ")
        else:
            typical, typical_label, middle = analysis.median_year, "Como un año medio", ""
        ends = [scenario_points(rate, years, base)[-1][1] for rate in (analysis.worst_year, typical, analysis.best_year)]
        story.append(Paragraph("Escenarios: su peor año, un fondo típico y su mejor año", heading))
        story.append(Paragraph(
            f"De los {analysis.year_windows} periodos de doce meses que caben en el histórico real de la cartera, el peor "
            f"dio un <b>{_pct(analysis.worst_year, signed=True)}</b> y el mejor un "
            f"<b>{_pct(analysis.best_year, signed=True)}</b>. {middle}El gráfico muestra tu capital durante {years} "
            f"{'año' if years == 1 else 'años'} si todos los años se repitiera cada escenario: acabaría en "
            f"<b>{format_money(ends[0])}</b>, <b>{format_money(ends[1])}</b> y <b>{format_money(ends[2])}</b> {_text(unit)}. "
            "Es una ilustración para dimensionar el riesgo: repetir el peor o el mejor año todos los años es muy "
            "improbable, el pasado no anticipa el futuro y, como los fondos se han elegido por su buen comportamiento "
            "pasado, estas cifras tienden a ser optimistas.", small))
        story.append(_scenario_chart(analysis, years, base, unit, typical, typical_label))
    if analysis:
        pass    # the real series above replaces the illustrative simulation
    elif preferences.amount is not None and preferences.amount > 0:
        story.append(Paragraph("Evolución ilustrativa de tu capital", heading))
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
            f"Capital inicial: <b>{format_money(initial)} {_text(currency)}</b>. "
            f"Capital final en esta simulación a {years} años: <b>{format_money(final)} {_text(currency)}</b>.", body))
    else:
        story.append(Paragraph("Evolución ilustrativa de tu capital", heading))
        story.append(Paragraph(
            "No se ha indicado un importe de inversión. Indica cuánto quieres invertir para "
            "incluir el gráfico de evolución del capital.", body))

    story.append(Paragraph("Por qué cada fondo", heading))
    for index, item in enumerate(proposal.items, start=1):
        share = peer_share(peers, item.fund.metrics(years)[0])
        ranking = (f" Su rentabilidad superó {_beaten(share)} de los fondos comparables."
                   if share is not None else "")
        story.append(Paragraph(f"<b>{index}. {_text(item.fund.name)}</b> — {_text(item.rationale + ranking)}", body))

    if others:
        story.append(Paragraph("Otros fondos con folleto que encajan", heading))
        story.append(Paragraph("Cumplen la divisa, el riesgo oficial y las preferencias según su documentación, pero no "
                               "tienen histórico de precios en el catálogo: no se han puntuado ni entran en el reparto.", body))
        for doc in others:
            facts = ", ".join(fact for fact in (f"riesgo oficial {doc.sri} de 7",
                                                f"costes {doc.costs:.2f} %".replace(".", ",") if doc.costs is not None else "",
                                                doc.category) if fact)
            story.append(Paragraph(f"<b>{_text(doc.name)}</b> ({_text(doc.isin)}) — {_text(facts)}", body))

    story.append(Paragraph("Cómo se ha calculado", heading))
    story.append(Paragraph(
        "Primero se descartan los fondos de otra divisa, con datos incompletos o desactualizados y los que superan "
        "el límite de volatilidad del perfil. Los restantes se puntúan por ajuste a la volatilidad objetivo, "
        "Sharpe y rentabilidad anualizada, con más peso de la rentabilidad si el objetivo es crecer y más peso "
        "de la estabilidad si es conservar. "
        "Las preferencias de zona, sector o clase de activo se comprueban con la ficha verificada del fondo o, "
        "si no existe, con su nombre. Las posibles clases de un mismo fondo se agrupan por nombre; "
        "esta identificación es aproximada. Cuando se ha leído "
        "la documentación del fondo (DFI, KID o ficha), se descarta si su riesgo oficial supera el del perfil o si "
        "su inversión mínima supera el importe, y sus costes corrientes restan puntuación. Para el resto no hay "
        "mínimos: por debajo de 100.000, entre las clases de un mismo fondo se prefiere la que no parece "
        "institucional, y el mínimo real debe comprobarse en el folleto. "
        + (f"Antes de filtrar, el modelo decidió estos criterios, que se aplicaron a todo el catálogo: {_text(criteria)}. "
           if criteria else "")
        + f"Selección final y pesos: {_text(proposal.method)}. Cuando el modelo no propone un reparto válido, los pesos "
        "se calculan a partir de la inversa de la volatilidad, con un mínimo del 5 % y un máximo del 60 % "
        "por fondo (80 % si hay dos; 100 % si solo hay uno). Estos límites también se aplican a los pesos del modelo. "
        "No se dispone de correlaciones entre fondos, "
        "por lo que el reparto no es una optimización de cartera completa.", body))
    story.append(Spacer(1, 8))
    story.append(Paragraph(DISCLAIMER, small))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=1.8 * cm, title="FondoClaro · Propuesta de fondos").build(story)
    return buffer.getvalue()

"""Preprocess the downloaded fund documents into one row per fund for the app.

Reads the folder produced by descargar_folletos.py (with its indice.csv) and writes
data/private/folletos.csv, ignored by Git. From each fund's documents it takes:

  DFI / KID (PRIIPs)   riesgo oficial 1-7, periodo recomendado, costes corrientes, objetivo
  ficha (Deutsche Bank) inversión mínima, divisa, gastos corrientes
  folleto resumido SEC  objetivo y gastos anuales (en inglés)

Zona, sector y clase de activo se deducen del objetivo con las mismas palabras clave que usa
el recomendador. No se usa ningún modelo: son 17.000 documentos y las reglas tardan un minuto.
Se puede repetir mientras la descarga sigue: solo lee los fondos nuevos o con documentos nuevos,
e iniciar.bat lo ejecuta en cada arranque si encuentra la carpeta.

    python scripts/procesar_folletos.py ..\\datos\\folletos
"""

import argparse
import csv
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.preferences import normalize
from src.recommender import NAME_HINTS

HEADERS = ["isin", "nombre", "entidad", "fuente", "en_catalogo", "sri", "periodo_anios", "costes_pct",
           "inversion_minima", "divisa", "categoria", "activos", "regiones", "sectores", "objetivo", "url",
           "documentos"]
# In running text «financieros» and «financial intermediary» are everywhere: finance needs stronger words.
FINANCE_TEXT = re.compile(r"sector financiero|financial sector|financials\b|financial services|\bbanks?\b|bancos|banking|insurance|asegurador")
GROUPS = {"regiones": ("global", "europa", "estados unidos", "asia", "emergentes"),
          "sectores": ("tecnología", "salud", "energía", "finanzas"),
          "activos": ("renta fija", "renta variable", "mixto", "monetario")}
NUMBER = r"(\d{1,3}(?:[.,]\d{1,2})?)"

SRI = re.compile(r"clase\s+de\s+riesgo\s+(\d)\s+(?:en|de)\s+una\s+escala\s+de\s+7", re.I)
PERIOD = re.compile(r"(?:mantenimiento\s+recomendado|inversi[oó]n\s+recomendado(?:\s+es\s+de)?|mantendr[aá]\s+el\s+producto\s+durante)"
                    r"\D{0,30}(\d{1,2})\s+a[ñn]os?", re.I)
COSTS = re.compile(r"costes\s+administrativos\s+o\s+de\s+funcionamiento[\s\S]{0,260}?" + NUMBER + r"\s*%", re.I)
CNMV_TYPE = re.compile(r"Tipo:\s*Fondo de Inversi[oó]n\.\s*([^\n.]{3,80})")
OBJECTIVE = re.compile(r"\bObjetivos?(?:\s+de\s+inversi[oó]n)?(?:,\s*proceso\s+y\s+pol[ií]ticas)?\s*:?\s*([\s\S]{40,900})", re.I)
MINIMUM = re.compile(r"INVERSI[ÓO]N\s+M[ÍI]NIMA\s+([\d.]+(?:,\d+)?)\s+([A-Z]{3})")
FICHA_CURRENCY = re.compile(r"DIVISA\s+([A-Z]{3})\b")
FICHA_COSTS = re.compile(r"\(\d{2}/\d{2}/\d{4}\)\s*" + NUMBER + r"\s*%")
SEC_OBJECTIVE = re.compile(r"Investment\s+Objectives?\s*:?\s*([\s\S]{40,700})", re.I)
SEC_COSTS = re.compile(r"Total\s+Annual\s+(?:Fund\s+)?Operating\s+Expenses[^%]{0,120}?" + NUMBER + r"\s*%", re.I)


def pdf_text(path: Path, pages: int = 3) -> str:
    import fitz

    with fitz.open(path) as document:
        return "\n".join(document[index].get_text() for index in range(min(pages, len(document))))


def html_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    return html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", raw, flags=re.I)))


def number(text: str | None) -> float | None:
    if not text:
        return None
    if "," in text:                                   # 1.234,56
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):   # 35.000 (miles con punto)
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def sentence(text: str, limit: int = 400) -> str:
    """First sentences of a block, on one line."""
    clean = re.sub(r"^Objetivos?\s+", "", " ".join(text.split()))
    clean = re.split(r"Fees and Expenses|Fees and expenses|Proceso de inversi[oó]n", clean)[0]
    cut = clean[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > 80 else cut).strip()


def read_kid(text: str) -> dict:
    found = {}
    if match := SRI.search(text):
        found["sri"] = int(match.group(1))
    if match := PERIOD.search(text):
        found["periodo_anios"] = int(match.group(1))
    if (match := COSTS.search(text)) and (value := number(match.group(1))) is not None and value < 15:
        found["costes_pct"] = value
    if match := CNMV_TYPE.search(text):
        found["categoria"] = " ".join(match.group(1).split()).capitalize()
    if match := OBJECTIVE.search(text):
        found["objetivo"] = sentence(match.group(1))
    return found


def read_ficha(text: str) -> dict:
    found = {}
    if (match := MINIMUM.search(text)) and (value := number(match.group(1))) is not None:
        found["inversion_minima"] = value
    if match := FICHA_CURRENCY.search(text):
        found["divisa"] = match.group(1)
    if (match := FICHA_COSTS.search(text)) and (value := number(match.group(1))) is not None and value < 15:
        found["costes_pct"] = value
    return found


def read_sec(text: str) -> dict:
    found = {}
    if match := SEC_OBJECTIVE.search(text):
        found["objetivo"] = sentence(match.group(1))
    if (match := SEC_COSTS.search(text)) and (value := number(match.group(1))) is not None and value < 15:
        found["costes_pct"] = value
    return found


READERS = {"dfi": (pdf_text, read_kid), "kid": (pdf_text, read_kid), "ficha": (pdf_text, read_ficha),
           "folleto_resumido": (html_text, read_sec)}


def classify(text: str) -> dict:
    """Zona, sector y clase de activo mencionados en el objetivo o el nombre."""
    haystack = normalize(text)
    found = {}
    for column, values in GROUPS.items():
        hits = [value for value in values
                if (FINANCE_TEXT if value == "finanzas" else NAME_HINTS[value]).search(haystack)]
        if column == "activos" and {"renta fija", "renta variable"} <= set(hits):
            hits = ["mixto"]
        if hits:
            found[column] = "; ".join(hits)
    return found


def process(folder: Path, destination: Path) -> dict:
    with (folder / "indice.csv").open(encoding="utf-8") as handle:
        index = [row for row in csv.DictReader(handle) if row["estado"] == "ok" and row["archivo"]]
    by_isin = defaultdict(list)
    for row in index:
        if row["tipo_doc"] in READERS:
            by_isin[row["isin"]].append(row)

    # The download keeps growing: funds whose documents have not changed are not read again.
    previous = {}
    if destination.is_file():
        with destination.open(encoding="utf-8", newline="") as handle:
            previous = {row["isin"]: row for row in csv.DictReader(handle) if row.get("documentos")}

    stats = defaultdict(int)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for count, (isin, documents) in enumerate(sorted(by_isin.items()), start=1):
            first = documents[0]
            signature = "|".join(sorted(document["archivo"] for document in documents))
            if previous.get(isin, {}).get("documentos") == signature:
                writer.writerow({**previous[isin], "en_catalogo": first.get("en_catalogo", "")})
                stats["fondos"] += 1
                stats["sin cambios"] += 1
                continue
            fund = {"isin": isin, "nombre": first["nombre"], "entidad": first["entidad"], "fuente": first["fuente"],
                    "en_catalogo": first.get("en_catalogo", ""), "url": first["url"], "documentos": signature}
            # KID/DFI first: their values are the regulated ones and win over the others.
            for document in sorted(documents, key=lambda row: row["tipo_doc"] not in ("dfi", "kid")):
                extract, read = READERS[document["tipo_doc"]]
                try:
                    values = read(extract(folder / document["archivo"]))
                except Exception:
                    stats["documentos ilegibles"] += 1
                    continue
                for key, value in values.items():
                    fund.setdefault(key, value)
            fund.update({key: value for key, value in classify(f"{fund['nombre']} {fund.get('categoria', '')} "
                                                               f"{fund.get('objetivo', '')}").items()})
            writer.writerow(fund)
            stats["fondos"] += 1
            stats["leídos ahora"] += 1
            for key in ("sri", "costes_pct", "inversion_minima", "objetivo", "regiones", "sectores", "activos"):
                stats[key] += key in fund
            stats["fuera del catálogo"] += fund["en_catalogo"] == "no"
            if count % 2000 == 0:
                print(f"  {count} de {len(by_isin)} fondos...", flush=True)
    temporary.replace(destination)
    return dict(stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="carpeta folletos/ con su indice.csv")
    parser.add_argument("--output", type=Path, default=Path("data/private/folletos.csv"))
    args = parser.parse_args()
    for name, value in process(args.folder, args.output).items():
        print(f"{name}: {value}")
    print("Escrito", args.output)
    from src import semantic
    if semantic.installed():
        print("Índice para la búsqueda semántica (la primera vez tarda unos minutos)...")
        for name, value in semantic.build(args.output).items():
            print(f"{name}: {value}")

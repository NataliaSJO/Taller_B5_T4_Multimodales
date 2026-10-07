"""Convert the private, full EODHD Markdown into a compact CSV for the app.

The generated file remains outside version control. Do not publish provider data without
checking the applicable EODHD licence.
"""

import argparse
import csv
import re
from pathlib import Path

HEADERS = [
    "isin", "name", "currency", "provider_type", "strategy", "assets", "regions",
    "sectors", "source_url", "last_date",
    *[f"{field}_{years}y" for years in (1, 3, 5) for field in ("return", "vol", "sharpe")],
]
METRIC = re.compile(
    r"Rent\.\s*([+-]?\d+(?:,\d+)?)\s*%;\s*vol\.\s*(\d+(?:,\d+)?)\s*%;\s*Sharpe\s*([+-]?\d+(?:,\d+)?)?"
)
URL = re.compile(r"\]\((https?://[^)]+)\)")


def clean(value: str) -> str:
    slash = chr(92)
    value = value.replace(slash + "|", "|").replace(slash + slash, slash).strip()
    return "" if not value or value.lower().startswith("pendiente") or value == "—" else value


def metric(cell: str) -> tuple[str, str, str]:
    match = METRIC.search(cell)
    if not match:
        return "", "", ""
    ret, vol, sharpe = match.groups()
    return (str(float(ret.replace(",", ".")) / 100),
            str(float(vol.replace(",", ".")) / 100),
            sharpe.replace(",", ".") if sharpe else "")


def convert(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    seen = set()
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with source.open(encoding="utf-8") as incoming, temporary.open("w", encoding="utf-8", newline="") as outgoing:
        writer = csv.DictWriter(outgoing, fieldnames=HEADERS)
        writer.writeheader()
        for line in incoming:
            if not line.startswith("| ") or line.startswith("| ---") or line.startswith("| ISIN / ID"):
                continue
            cells = line.strip()[2:-2].split(" | ")
            if len(cells) != 16:
                raise ValueError(f"Fila Markdown con {len(cells)} campos; se esperaban 16")
            isin = cells[0]
            if isin in seen:
                raise ValueError(f"ISIN duplicado: {isin}")
            seen.add(isin)
            dates = cells[6].split("–")
            row = {"isin": isin, "name": clean(cells[1]), "currency": cells[3],
                   "provider_type": cells[4], "strategy": clean(cells[7]),
                   "assets": clean(cells[8]), "regions": clean(cells[9]),
                   "sectors": clean(cells[10]),
                   "source_url": (URL.search(cells[15]).group(1) if URL.search(cells[15]) else ""),
                   "last_date": dates[-1] if len(dates) == 2 else ""}
            for years, idx in ((1, 11), (3, 12), (5, 13)):
                values = metric(cells[idx])
                for field, value in zip(("return", "vol", "sharpe"), values):
                    row[f"{field}_{years}y"] = value
            writer.writerow(row)
            written += 1
    temporary.replace(destination)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/private/funds.csv"))
    args = parser.parse_args()
    print(f"{convert(args.markdown, args.output)} fondos importados en {args.output}")

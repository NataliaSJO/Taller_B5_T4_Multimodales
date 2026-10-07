"""Read the small bundled demo or an imported, private EODHD catalog."""

import csv
from pathlib import Path

from .models import Fund

NUMERIC = tuple(f"{field}_{years}y" for years in (1, 3, 5)
                for field in ("return", "vol", "sharpe"))


def _number(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def load_catalog(path: str | Path) -> list[Fund]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No existe el catálogo: {path}")
    funds = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"isin", "name", "currency", "provider_type", "last_date", *NUMERIC}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("El catálogo CSV no contiene las columnas necesarias")
        for row in reader:
            isin = row["isin"].strip()
            if not isin or isin in seen:
                raise ValueError(f"Identificador vacío o duplicado: {isin!r}")
            seen.add(isin)
            numeric = {column: _number(row.get(column)) for column in NUMERIC}
            funds.append(Fund(
                isin=isin,
                name=row["name"].strip(),
                currency=row["currency"].strip().upper(),
                provider_type=row["provider_type"].strip(),
                strategy=(row.get("strategy") or "").strip(),
                assets=(row.get("assets") or "").strip(),
                regions=(row.get("regions") or "").strip(),
                sectors=(row.get("sectors") or "").strip(),
                source_url=(row.get("source_url") or "").strip(),
                last_date=row["last_date"].strip(),
                **numeric,
            ))
    return funds

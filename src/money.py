"""Spanish monetary input and a single cent-accurate allocation for all outputs."""

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

SMALL = dict(zip(
    "cero un uno una dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
    "dieciseis diecisiete dieciocho diecinueve veinte veintiun veintiuno veintiuna veintidos veintitres "
    "veinticuatro veinticinco veintiseis veintisiete veintiocho veintinueve".split(),
    [0, 1, 1, 1, *range(2, 21), 21, 21, 21, *range(22, 30)]))
TENS = dict(zip("treinta cuarenta cincuenta sesenta setenta ochenta noventa".split(), range(30, 100, 10)))
HUNDREDS = dict(zip("cien ciento doscientos trescientos cuatrocientos quinientos seiscientos setecientos ochocientos novecientos".split(),
                    [100, *range(100, 1000, 100)]))
HUNDREDS.update({word[:-2] + "as": value for word, value in list(HUNDREDS.items()) if word.endswith("os")})
WORD = "(?:" + "|".join(sorted({*SMALL, *TENS, *HUNDREDS, 'mil', 'millon', 'millones', 'y'}, key=len, reverse=True)) + ")"
START_WORD = "(?:" + "|".join(sorted({*SMALL, *TENS, *HUNDREDS, 'mil', 'millon', 'millones'}, key=len, reverse=True)) + ")"
NUMBER = (rf"(?:[+-]?\d+(?:[.,]\d+)*(?:\s+\d{{3}})*(?:\s+(?:mil|millones?))?"
          rf"|(?:menos\s+)?{START_WORD}(?:\s+{WORD})*(?:\s+(?:coma|punto)\s+{START_WORD}(?:\s+{WORD})*)?)")
CURRENCY = r"(?:francos?\s+suizos?|dolar(?:es)?|euros?|libras?|eur|usd|gbp|chf)\b|[€$£]"
MONEY = re.compile(rf"(?<![\w.,+\-])(?P<number>{NUMBER})\s*(?:de\s+)?(?P<currency>{CURRENCY})")
PREFIX_MONEY = re.compile(rf"(?P<currency>\b(?:eur|usd|gbp|chf)\b|[€$£])\s*(?P<number>{NUMBER})(?![\w.,])")


def _under_thousand(words: list[str]) -> int:
    if not words:
        return 0
    total = 0
    if words[0] in HUNDREDS:
        total = HUNDREDS[words[0]]
        words = words[1:]
    if not words:
        return total
    if len(words) == 1 and words[0] in SMALL:
        return total + SMALL[words[0]]
    if words[0] in TENS:
        if len(words) == 1:
            return total + TENS[words[0]]
        if len(words) == 3 and words[1] == "y" and 1 <= SMALL.get(words[2], -1) <= 9:
            return total + TENS[words[0]] + SMALL[words[2]]
    raise ValueError("Número hablado no válido")


def _spoken_integer(words: list[str]) -> int:
    total = 0
    for scale_words, scale in (({"millon", "millones"}, 1_000_000), ({"mil"}, 1000)):
        positions = [i for i, word in enumerate(words) if word in scale_words]
        if positions:
            if len(positions) != 1:
                raise ValueError("Escala repetida")
            index = positions[0]
            total += (_under_thousand(words[:index]) if index else 1) * scale
            words = words[index + 1:]
    return total + _under_thousand(words)


def _number(raw: str) -> Decimal:
    raw = raw.strip()
    if raw.startswith("menos "):
        return -_number(raw[6:])
    if not re.search(r"\d", raw):
        decimal_parts = re.split(r"\s+(?:coma|punto)\s+", raw)
        if len(decimal_parts) == 2:
            fraction_words = decimal_parts[1].split()
            fraction = ("".join(str(SMALL[word]) for word in fraction_words)
                        if all(word in SMALL and SMALL[word] < 10 for word in fraction_words)
                        else str(_spoken_integer(fraction_words)))
            if len(fraction) > 2:
                raise ValueError("Demasiados decimales")
            return Decimal(_spoken_integer(decimal_parts[0].split())) + Decimal("0." + fraction)
        return Decimal(_spoken_integer(raw.split()))
    scaled = re.fullmatch(r"(.+)\s+(mil|millon|millones)", raw)
    if scaled:
        return _number(scaled[1]) * (1000 if scaled[2] == "mil" else 1_000_000)
    raw = raw.replace(" ", "")
    if "." in raw and "," in raw:
        decimal = "." if raw.rfind(".") > raw.rfind(",") else ","
        grouping = "," if decimal == "." else "."
        if not re.fullmatch(rf"[+-]?[1-9]\d{{0,2}}(?:{re.escape(grouping)}\d{{3}})+{re.escape(decimal)}\d{{1,2}}", raw):
            raise ValueError("Separadores no válidos")
        raw = raw.replace(grouping, "").replace(decimal, ".")
    elif "." in raw or "," in raw:
        separator = "." if "." in raw else ","
        if re.fullmatch(rf"[+-]?[1-9]\d{{0,2}}(?:{re.escape(separator)}\d{{3}})+", raw):
            raw = raw.replace(separator, "")
        elif re.fullmatch(rf"[+-]?\d+{re.escape(separator)}\d{{1,2}}", raw):
            raw = raw.replace(separator, ".")
        else:
            raise ValueError("Separadores no válidos")
    return Decimal(raw)


def _currency(raw: str) -> str:
    if raw in {"$", "usd"} or raw.startswith("dolar"):
        return "USD"
    if raw in {"£", "gbp"} or raw.startswith("libra"):
        return "GBP"
    if raw == "chf" or raw.startswith("franco"):
        return "CHF"
    return "EUR"


def parse_money(clean: str, allow_bare: bool = False) -> tuple[bool, float | None, str | None]:
    """Return (amount mentioned, valid amount, associated currency); input is normalized."""
    matches = sorted([*MONEY.finditer(clean), *PREFIX_MONEY.finditer(clean)], key=lambda m: m.start())
    # Overlapping prefix/suffix matches refer to the same quantity only once.
    if matches:
        match = matches[-1]
        raw, currency = match["number"], _currency(match["currency"])
        tail = clean[match.end():]
        # Never turn an unparsed compound number into just its trailing part.
        if re.search(rf"\b(?:\d+|{START_WORD}|coma|punto)\s+$", clean[:match.start()]):
            return True, None, currency
    elif allow_bare and re.fullmatch(NUMBER, clean.strip()):
        raw, currency, tail = clean.strip(), None, ""
    else:
        return False, None, None
    try:
        if raw.startswith(("-", "menos ")):
            raise ValueError("El importe no puede ser negativo")
        amount = _number(raw)
        cents = re.match(rf"\s+con\s+({NUMBER})\s+centimos?\b", tail)
        if cents:
            fraction = _number(cents[1])
            if not 0 <= fraction < 100 or fraction != fraction.to_integral_value() or amount != amount.to_integral_value():
                raise ValueError("Céntimos no válidos")
            amount += fraction / 100
        if not amount.is_finite() or not Decimal("0.01") <= amount < 1_000_000_000:
            raise ValueError("Importe fuera de rango")
        return True, float(amount), currency
    except (ValueError, ArithmeticError):
        return True, None, currency


def format_money(value, grouped: bool = True) -> str:
    text = f"{value:,.2f}" if grouped else f"{value:.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


@dataclass(frozen=True)
class Allocation:
    weights: tuple[float, ...]
    amounts: tuple[Decimal, ...] | None


def investment_allocation(weights, amount: float | None) -> Allocation:
    """Allocate actual cents once by a deterministic rule, respecting weight bounds."""
    from .recommender import allocation_limits, valid_allocation

    if not valid_allocation(weights, len(weights)):
        raise ValueError("Pesos de inversión no válidos")
    if amount is None:
        return Allocation(tuple(weights), None)
    total = Decimal(str(amount))
    if not total.is_finite() or total <= 0 or total != total.quantize(Decimal("0.01")):
        raise ValueError("Indica un importe positivo con un máximo de dos decimales.")
    cents = int(total * 100)
    lower, upper = allocation_limits(len(weights))
    minimum = int((Decimal(str(lower)) * cents).to_integral_value(rounding=ROUND_CEILING))
    maximum = int((Decimal(str(upper)) * cents).to_integral_value(rounding=ROUND_FLOOR))
    if minimum * len(weights) > cents or maximum * len(weights) < cents:
        raise ValueError("El importe es demasiado pequeño para este reparto. Aumenta el importe o pide menos fondos.")
    decimal_weights = [Decimal(str(weight)) for weight in weights]
    raw = [cents * weight / sum(decimal_weights) for weight in decimal_weights]
    units = [max(minimum, min(maximum, int(value))) for value in raw]
    while sum(units) != cents:
        if sum(units) < cents:
            index = max((i for i in range(len(units)) if units[i] < maximum), key=lambda i: raw[i] - units[i])
            units[index] += 1
        else:
            index = max((i for i in range(len(units)) if units[i] > minimum), key=lambda i: units[i] - raw[i])
            units[index] -= 1
    return Allocation(tuple(unit / cents for unit in units), tuple(Decimal(unit) / 100 for unit in units))

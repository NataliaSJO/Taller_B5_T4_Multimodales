"""Final fund selection by a language model, over candidates taken from the catalog.

The catalog has ~92.000 rows and does not fit in a model context, so the hard
constraints (divisa, datos recientes, límite de volatilidad) reduce it first and the
model chooses and weights among the best candidates. Figures and per-fund reasons
always come from the catalog, never from the model. Every answer is validated
locally; any failure falls back to the deterministic ranking.

Backends (variable AI_FILTER): «gpu» = Gemma 3 4B con PyTorch en la GPU; «local» = Gemma 3 1B
con llama.cpp en CPU; «claude» = API de Anthropic, deshabilitado salvo que se pida expresamente;
«off» = solo reglas. Por defecto «auto»: GPU si la hay, si no CPU, si no reglas.
Con Claude, ADVISOR_WEB=on le deja además buscar en la web datos de los candidatos.
"""

import json
import math
import os
from functools import lru_cache

from .models import Criteria, Preferences, Proposal, Recommendation, metric_years
from .hf_model import generate, gpu_available, parse_json
from .paths import GPU_LLM_PATH, LLM_PATH
from .preferences import normalize
from .recommender import RISK, WEIGHTS, allocate, allocation_limits, valid_allocation

# Candidates shown to the model. On CPU each one costs about half a second of prompt time.
CANDIDATES = {"gpu": 150, "local": 10, "claude": 150}
# Number of funds for each wanted degree of diversification (None = not stated).
FUNDS = {"baja": 2, "media": 4, None: 5, "alta": 7}


def requested_count(preferences: Preferences) -> int:
    if preferences.fund_count is not None:
        if type(preferences.fund_count) is not int or not 1 <= preferences.fund_count <= 7:
            raise ValueError("El número de fondos debe estar entre 1 y 7")
        return preferences.fund_count
    return FUNDS[preferences.diversification]


def _schema(count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "seleccion": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "peso": {"type": "integer"}},
                    "required": ["id", "peso"],
                    "additionalProperties": False,
                },
            },
            "comentario": {"type": "string"},
        },
        "required": ["seleccion", "comentario"],
        "additionalProperties": False,
    }


def available(name: str) -> bool:
    """Whether a backend can run on this machine as it is set up now."""
    if name == "off":
        return True
    if name == "claude":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if name == "gpu":
        return (GPU_LLM_PATH / "config.json").is_file() and gpu_available()
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return False
    return LLM_PATH.is_file()


def backend() -> str:
    """Backend that will actually run, after checking what is installed."""
    wanted = os.getenv("AI_FILTER", "auto").strip().lower()
    if wanted == "auto":
        return next(name for name in ("gpu", "local", "off") if available(name))
    return wanted if wanted in ("gpu", "local", "claude") and available(wanted) else "off"


def label(name: str | None = None) -> str:
    name = name or backend()
    return {"gpu": "Gemma 3 4B en GPU", "local": "Gemma 3 1B en CPU", "off": "reglas deterministas",
            "claude": f"Claude ({os.getenv('CLAUDE_MODEL', 'claude-opus-5-5')})"}[name]


def _prompt(candidates: list[Recommendation], preferences: Preferences, conversation: str, count: int) -> str:
    years = preferences.horizon_years
    target, ceiling = RISK[preferences.risk]
    lower_weight, upper_weight = allocation_limits(count)
    lines = []
    for index, item in enumerate(candidates, start=1):
        ret, vol, sharpe = item.fund.metrics(years)
        ratio = "sin dato" if sharpe is None else f"{sharpe:+.2f}"
        official = "".join((f" | riesgo oficial {item.fund.sri}/7" if item.fund.sri else "",
                            f" | costes {item.fund.costs:.2f}%" if item.fund.costs is not None else ""))
        lines.append(f"{index}. {item.fund.name} | rentabilidad {metric_years(years)} años {ret:+.1%} | "
                     f"volatilidad {vol:.1%} | Sharpe {ratio}{official}")
    wishes = [f"{name}: {value}" for name, value in (("zona geográfica", preferences.region), ("sector", preferences.sector),
                                                     ("clase de activo", preferences.asset_class)) if value]
    spread = {"baja": "quiere concentrar en pocos fondos", "media": "quiere una diversificación normal",
              "alta": "quiere diversificar mucho", None: "no ha indicado cuánto diversificar"}[preferences.diversification]
    return (
        "Eres un asesor financiero que construye una cartera de fondos para un cliente. "
        "Solo puedes elegir fondos de la lista numerada y solo puedes usar los datos que aparecen en ella.\n\n"
        f"Lo que ha dicho el cliente: {conversation}\n"
        f"Perfil: horizonte {years} años; riesgo {preferences.risk} (volatilidad ideal cerca del {target:.0%}, "
        f"máximo {ceiling:.0%}); divisa {preferences.currency}; {spread}"
        + (f"; preferencias: {'; '.join(wishes)}" if wishes else "")
        + "".join(f"; {name}: {value}" for name, value in (("objetivo", preferences.objective),
                                                          ("experiencia inversora", preferences.experience),
                                                          ("ante una caída fuerte", preferences.loss_reaction)) if value)
        + ".\n\n"
        "Fondos disponibles (ya cumplen la divisa y el máximo de volatilidad):\n" + "\n".join(lines) + "\n\n"
        f"Elige exactamente {count} fondos distintos y reparte la inversión entre ellos. Criterios, por este orden:\n"
        "1. Riesgo: prefiere volatilidades cercanas a la ideal del cliente.\n"
        "2. Preferencias de zona geográfica, sector o clase de activo, si las ha dado: guíate por el nombre del fondo.\n"
        "3. Objetivo del cliente: si quiere crecer, más rentabilidad histórica; si quiere conservar u obtener "
        "rentas, menos volatilidad y mejor Sharpe.\n"
        "4. A igualdad de lo demás, prefiere costes más bajos cuando el dato aparece.\n"
        f"5. Diversificación: evita repetir la misma gestora o la misma estrategia. "
        f"Asigna entre el {lower_weight:.0%} y el {upper_weight:.0%} a cada fondo.\n\n"
        "Devuelve JSON con «seleccion» (en «id», el número que el fondo tiene en la lista, no su nombre; "
        "en «peso», el porcentaje entero; los pesos suman 100) y "
        "«comentario» (una sola frase en español, de menos de 25 palabras, que explique la cartera al cliente)."
    )


@lru_cache(maxsize=1)
def _llama():
    from llama_cpp import Llama
    return Llama(model_path=str(LLM_PATH), n_ctx=4096, verbose=False)


def warm():
    """Load the GPU model ahead of the first proposal."""
    from .hf_model import load
    load(GPU_LLM_PATH, four_bit=True)


def _ask_gpu(prompt: str, schema: dict) -> dict:
    # 4-bit weights (about 3 GB of VRAM) leave room for the single-model page on the same card.
    return parse_json(generate(GPU_LLM_PATH, [{"type": "text", "text": prompt}], 300, four_bit=True))


def _ask_local(prompt: str, schema: dict) -> dict:
    response = _llama().create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object", "schema": schema},
        temperature=0.0,
        max_tokens=300,
    )
    return json.loads(response["choices"][0]["message"]["content"])


def web_enabled() -> bool:
    """Web search needs a model that can browse, so it only applies to the Claude backend."""
    return backend() == "claude" and os.getenv("ADVISOR_WEB", "off").strip().lower() == "on"


def _ask_claude(prompt: str, schema: dict | None, web: bool = False) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    request = {"model": os.getenv("CLAUDE_MODEL", "claude-opus-5-5"), "max_tokens": 16000}
    if not web:
        response = client.messages.create(
            **request, messages=[{"role": "user", "content": prompt}],
            **({"output_config": {"format": {"type": "json_schema", "schema": schema}}} if schema else {}),
        )
    else:
        # Search results carry citations, which cannot be combined with a JSON schema:
        # the JSON is requested in the prompt and validated locally like any other answer.
        prompt += ("\n\nAntes de decidir puedes buscar en la web información pública de los fondos de la lista "
                   "(categoría, zona, sector, comisiones). No añadas fondos que no estén en la lista. "
                   "Termina tu respuesta con el objeto JSON y nada más después.")
        messages = [{"role": "user", "content": prompt}]
        for _ in range(4):
            response = client.messages.create(
                **request, messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
            )
            if response.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"respuesta incompleta ({response.stop_reason})")
    text = [block.text for block in response.content if block.type == "text"][-1]
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


ASK = {"gpu": _ask_gpu, "local": _ask_local, "claude": _ask_claude}
CRITERIA_SCHEMA = {
    "type": "object",
    "properties": {
        "peso_riesgo": {"type": "integer"},
        "peso_sharpe": {"type": "integer"},
        "peso_rentabilidad": {"type": "integer"},
        "volatilidad_objetivo": {"type": "number"},
        "rentabilidad_minima_anual": {"type": ["number", "null"]},
        "palabras_clave": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["peso_riesgo", "peso_sharpe", "peso_rentabilidad", "volatilidad_objetivo",
                 "rentabilidad_minima_anual", "palabras_clave"],
    "additionalProperties": False,
}


def criteria_prompt(preferences: Preferences, conversation: str) -> str:
    target, ceiling = RISK[preferences.risk]
    known = "; ".join(f"{name}: {value}" for name, value in (
        ("zona", preferences.region), ("sector", preferences.sector), ("clase de activo", preferences.asset_class),
        ("diversificación", preferences.diversification), ("objetivo", preferences.objective),
        ("experiencia", preferences.experience), ("ante una caída fuerte", preferences.loss_reaction)) if value)
    return (
        "Eres un asesor financiero. Con lo que ha dicho el cliente vas a decidir los criterios de búsqueda; "
        "un programa los aplicará después a un catálogo de 92.000 fondos de inversión.\n\n"
        f"Lo que ha dicho el cliente: {conversation}\n"
        f"Perfil: horizonte {preferences.horizon_years} años; riesgo {preferences.risk} "
        f"(volatilidad anual máxima {ceiling:.0%}, habitual {target:.0%}); divisa {preferences.currency}"
        + (f"; {known}" if known else "") + ".\n\n"
        "Devuelve solo un objeto JSON con estas claves:\n"
        "- peso_riesgo, peso_sharpe, peso_rentabilidad: tres enteros que suman 100. Indican cuánto importa que el "
        "fondo se acerque a la volatilidad objetivo, que tenga buen ratio de Sharpe y que haya sido rentable.\n"
        f"- volatilidad_objetivo: volatilidad anual ideal para este cliente, en porcentaje, entre 1 y {ceiling * 100:.0f}.\n"
        "- rentabilidad_minima_anual: rentabilidad anual mínima que exiges a un fondo, en porcentaje, o null.\n"
        "- palabras_clave: solo si el cliente ha pedido un tema, sector, zona o tipo de activo concreto, las palabras "
        "que deben aparecer en el nombre del fondo, con variantes en español y en inglés porque casi todos los "
        "nombres están en inglés. Si no ha pedido nada concreto, lista vacía."
    )


def criteria_from(answer: dict, preferences: Preferences) -> Criteria:
    """Validate the model's criteria; out-of-range values fall back to the defaults of the profile."""
    target, ceiling = RISK[preferences.risk]
    raw = [answer.get(key) for key in ("peso_riesgo", "peso_sharpe", "peso_rentabilidad")]
    if all(isinstance(value, (int, float)) and value >= 0 for value in raw) and sum(raw) > 0:
        fit = max(raw[0] / sum(raw), 0.25)  # the client's risk always counts
        rest = (raw[1] + raw[2]) or 1
        weights = (fit, (1 - fit) * raw[1] / rest, (1 - fit) * raw[2] / rest)
    else:
        weights = WEIGHTS[preferences.objective]
    vol = answer.get("volatilidad_objetivo")
    floor = answer.get("rentabilidad_minima_anual")
    words = []
    for word in answer.get("palabras_clave") or []:
        word = " ".join(normalize(str(word)).split())
        if 3 <= len(word) <= 30 and word.replace(" ", "").isalnum() and word not in words:
            words.append(word)
    return Criteria(
        weights=weights,
        target_vol=min(vol / 100, ceiling) if isinstance(vol, (int, float)) and 1 <= vol <= 100 else target,
        min_annual_return=floor / 100 if isinstance(floor, (int, float)) and 0 < floor <= 15 else None,
        keywords=tuple(words[:15]),
        explanation=" ".join(str(answer.get("explicacion") or "").split())[:300],
    )


def understand(history: list[tuple[str, str]], known: Preferences, said: str) -> tuple[Preferences, str] | None:
    """Profile data and next question read by the model. None when no capable model is active or it fails."""
    from . import extraction

    name = backend()
    if name == "gpu":
        ask = lambda prompt: parse_json(generate(GPU_LLM_PATH, [{"type": "text", "text": prompt}], 400, four_bit=True))
    elif name == "claude":
        ask = lambda prompt: _ask_claude(prompt + "\nResponde solo con el objeto JSON.", None)
    else:
        return None
    try:
        new, question = extraction.read(ask(extraction.prompt(history, known, said)))
    except Exception:
        return None
    # In tests the model filled in traits nobody stated (experience, objective, asset class...),
    # and those change the advice. Only the concrete data is taken from it.
    return Preferences(horizon_years=new.horizon_years, risk=new.risk, currency=new.currency,
                       amount=new.amount, region=new.region, sector=new.sector), question


def decide(preferences: Preferences, conversation: str) -> Criteria | None:
    """Ask the model for search criteria. None when no capable model is active or it fails."""
    name = backend()
    if name not in ("gpu", "claude"):  # the 1B CPU model is too weak for this step
        return None
    try:
        return criteria_from(ASK[name](criteria_prompt(preferences, conversation), CRITERIA_SCHEMA), preferences)
    except Exception:
        return None


def _candidate_index(value, candidates: list[Recommendation]) -> int | None:
    """Position (from 1) of the candidate the model means. Without a schema to constrain it, the
    model sometimes answers with the fund's exact name instead of its number."""
    if type(value) is int:
        return value if 1 <= value <= len(candidates) else None
    if not isinstance(value, str) or value.strip().isdigit():
        return None
    wanted = normalize(value.strip())
    names = [normalize(item.fund.name) for item in candidates]
    exact = [index for index, name in enumerate(names, start=1) if name == wanted]
    return exact[0] if len(exact) == 1 else None


def _validated(answer: dict, candidates: list[Recommendation], preferences: Preferences, limit: int) -> tuple[list[Recommendation], list[float], str]:
    if not isinstance(answer, dict) or not isinstance(answer.get("seleccion"), list):
        raise ValueError("Selección no válida")
    chosen, weights, seen = [], [], set()
    for entry in answer["seleccion"]:
        if not isinstance(entry, dict):
            continue
        index = _candidate_index(entry.get("id"), candidates)
        if index is None or index in seen:
            continue
        seen.add(index)
        chosen.append(candidates[index - 1])
        weights.append(entry.get("peso"))
        if len(chosen) >= limit:
            break
    if not chosen:
        raise ValueError("el modelo no eligió ningún candidato válido")
    if len(chosen) < limit:  # repeated or invented ids: complete with the best remaining candidates
        chosen += [item for item in candidates if item not in chosen][:limit - len(chosen)]
        weights = []
    numeric = all(type(weight) in (int, float) and math.isfinite(weight) and weight > 0 for weight in weights)
    total = sum(weights) if numeric else 0
    shares = [weight / total for weight in weights] if total > 0 and math.isfinite(total) else []
    # A concentrated or degenerate split is replaced by the risk-based one.
    if not valid_allocation(shares, len(chosen)):
        shares = allocate(chosen, preferences.horizon_years)
    return chosen, shares, " ".join(str(answer.get("comentario") or "").split())[:400]


def select(candidates: list[Recommendation], preferences: Preferences, conversation: str) -> Proposal:
    """Choose and weight the funds of the proposal. `candidates` must be sorted best first."""
    years = preferences.horizon_years
    name = backend()
    count = min(requested_count(preferences), len(candidates))
    fallback = tuple(candidates[:count])
    if name == "off" or len(candidates) <= count:
        return Proposal(fallback, tuple(allocate(fallback, years)), "Reglas deterministas")
    pool = candidates[:max(CANDIDATES[name], count + 3)]
    try:
        prompt = _prompt(pool, preferences, conversation, count)
        answer = (_ask_claude(prompt, _schema(count), web_enabled()) if name == "claude"
                  else ASK[name](prompt, _schema(count)))
        chosen, shares, comment = _validated(answer, pool, preferences, count)
    except Exception as exc:  # any model failure must not block the proposal
        return Proposal(fallback, tuple(allocate(fallback, years)),
                        f"Reglas deterministas ({label(name)} no disponible: {type(exc).__name__})")
    return Proposal(tuple(chosen), tuple(shares), f"{label(name)} + validación local", comment)

"""The question loop: question -> model -> tool calls -> answer with its trace.

The model picks tools and writes the answer; the database computes every number.
Gemini is the main model. When every Gemini model is busy and a Groq key is
set, the same question goes to Groq (OpenAI-style API) with the same tools.
After the answer is written we look for each number in it among the rows the
tools returned, and flag any we cannot find, so a made-up figure is visible
instead of quietly trusted. Every question is logged in assistant_log.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from assistant import tools
from assistant.prompts import SYSTEM
from core import db
from core.config import settings

log = logging.getLogger("assistant")
MAX_STEPS = 6   # rounds of tool calls per question; keeps cost and loops bounded
# Tried in order when the configured model is busy or unavailable (free-tier
# models are often overloaded). A question sticks to the first model that answers.
FALLBACK_MODELS = ["gemini-3.1-flash-lite"]
TIMEOUT_MS = 45_000
BUSY_CODES = (404, 429, 500, 503, 504)
COOLDOWN_S = 600       # a model that just failed is skipped for this long
_busy_until: dict[str, float] = {}


@dataclass
class Answer:
    text: str
    calls: list[tools.Call] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)   # numbers not found in any tool result
    error: str | None = None
    model: str | None = None
    busy: bool = False   # the service was overloaded or timed out; another one may answer


def available() -> bool:
    return bool(settings.gemini_api_key or settings.groq_api_key)


# ------------------------------------------------------------------
# Talking to Gemini
# ------------------------------------------------------------------

def _jsonable(obj):
    """Tool results hold numpy and pandas values; Gemini wants plain JSON."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def ask(question: str, set_id: int, history: list[tuple[str, str]] = ()) -> Answer:
    """Answer one question about one polygon set. history = earlier (question, answer) pairs."""
    answer = _ask_gemini(question, set_id, history) if settings.gemini_api_key else None
    if (answer is None or answer.busy) and settings.groq_api_key:
        log.warning("Gemini unavailable, asking Groq")
        answer = _ask_groq(question, set_id, history)
    _log(question, set_id, answer)
    return answer


def _ask_gemini(question: str, set_id: int, history) -> Answer:
    # Imported here, so the app starts even when Gemini is not set up.
    from google import genai
    from google.genai import errors, types

    # Fail fast instead of the SDK's long default retries: the fallback model is the retry.
    client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(
        timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    models = [settings.gemini_model, *[m for m in FALLBACK_MODELS if m != settings.gemini_model]]
    ready = [m for m in models if _busy_until.get(m, 0) < time.time()]
    models = ready or models
    chosen: list[str] = []
    decls = [types.FunctionDeclaration(name=d["name"], description=d["description"],
                                       parameters_json_schema=d["parameters"]) for d in tools.DECLARATIONS]

    def config(allow_tools: bool):
        return types.GenerateContentConfig(
            system_instruction=SYSTEM, temperature=0.2, tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                mode="AUTO" if allow_tools else "NONE")))

    contents = []
    for q, a in list(history)[-4:]:   # a short memory, for follow-up questions
        contents += [types.Content(role="user", parts=[types.Part.from_text(text=q)]),
                     types.Content(role="model", parts=[types.Part.from_text(text=a)])]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))

    def generate(allow_tools: bool):
        if chosen:
            return client.models.generate_content(model=chosen[0], contents=contents, config=config(allow_tools))
        last = None
        for m in models:
            try:
                resp = client.models.generate_content(model=m, contents=contents, config=config(allow_tools))
                chosen.append(m)
                return resp
            except Exception as e:  # noqa: BLE001 - only busy, missing or timed-out models fall through
                timed_out = "timeout" in type(e).__name__.lower()
                if not timed_out and not (isinstance(e, errors.APIError) and e.code in BUSY_CODES):
                    raise
                _busy_until[m] = time.time() + COOLDOWN_S
                log.warning("model %s unavailable (%s), trying the next one", m, getattr(e, "code", "?"))
                last = e
        raise last

    calls: list[tools.Call] = []
    try:
        for step in range(MAX_STEPS + 1):
            resp = generate(allow_tools=step < MAX_STEPS)
            requested = resp.function_calls or []
            if not requested:
                break
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in requested:
                result, call = tools.call(fc.name, dict(fc.args or {}), set_id)
                calls.append(call)
                parts.append(types.Part.from_function_response(name=fc.name, response=_jsonable(result)))
            contents.append(types.Content(role="user", parts=parts))
        text = (resp.text or "").strip() or "I could not produce an answer to that."
        answer = Answer(text, calls, unmatched_numbers(text, calls, question), model=chosen[0])
    except Exception as e:  # noqa: BLE001 - quota, network or key problems are shown, not raised
        log.exception("assistant failed")
        code = getattr(e, "code", None)
        busy = code in BUSY_CODES or "timeout" in type(e).__name__.lower()
        msg = (f"The AI service is busy or rate-limited right now ({code}). Please try again in a minute."
               if busy else str(e)[:400])
        answer = Answer("", calls, error=msg, busy=busy)
    return answer


# ------------------------------------------------------------------
# Groq, the backup
# ------------------------------------------------------------------
# Groq serves open models through an OpenAI-style API, free with no card and no
# training on prompts. Its free tier has a low tokens-per-minute limit, so it is
# the backup rather than the main model. We call it with plain httpx (already
# installed with the Gemini SDK) instead of adding another client library.

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _ask_groq(question: str, set_id: int, history) -> Answer:
    import httpx

    tool_defs = [{"type": "function", "function": d} for d in tools.DECLARATIONS]
    messages = [{"role": "system", "content": SYSTEM}]
    for q, a in list(history)[-4:]:
        messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    messages.append({"role": "user", "content": question})

    calls: list[tools.Call] = []
    model = f"groq/{settings.groq_model}"
    try:
        headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
        with httpx.Client(timeout=TIMEOUT_MS / 1000, headers=headers) as http:
            for step in range(MAX_STEPS + 1):
                body = {"model": settings.groq_model, "messages": messages, "temperature": 0.2,
                        "tools": tool_defs, "tool_choice": "auto" if step < MAX_STEPS else "none"}
                r = http.post(GROQ_URL, json=body)
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                requested = msg.get("tool_calls") or []
                if not requested:
                    break
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": requested})
                for tc in requested:
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result, call = tools.call(tc["function"]["name"], args, set_id)
                    calls.append(call)
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(_jsonable(result))})
        text = (msg.get("content") or "").strip() or "I could not produce an answer to that."
        return Answer(text, calls, unmatched_numbers(text, calls, question), model=model)
    except Exception as e:  # noqa: BLE001 - shown on the page, not raised
        log.exception("groq failed")
        code = getattr(getattr(e, "response", None), "status_code", None)
        busy = code in BUSY_CODES or "timeout" in type(e).__name__.lower()
        msg = (f"The AI services are busy or rate-limited right now ({code}). Please try again in a minute."
               if busy else str(e)[:400])
        return Answer("", calls, error=msg, busy=busy, model=model)


def _log(question: str, set_id: int, a: Answer) -> None:
    try:
        db.execute("INSERT INTO assistant_log (set_id, question, tool_calls, answer, flags, model) "
                   "VALUES (%s, %s, %s, %s, %s, %s)",
                   (set_id, question, json.dumps([{"tool": c.tool, "args": c.args, "rows": len(c.rows),
                                                   "error": c.error} for c in a.calls], default=str),
                    a.text or None, json.dumps({"unmatched": a.unmatched, "error": a.error}),
                    a.model or settings.gemini_model))
    except Exception:  # noqa: BLE001 - a logging failure must not hide the answer
        log.exception("could not write assistant_log")


# ------------------------------------------------------------------
# Number check
# ------------------------------------------------------------------

# Numbers that belong to the method rather than the data: class ranges, pixel
# size, score scale, thresholds.
_FIXED = {10.0, 100.0, 250.0, 50.0, 0.5, 1.0, 2020.0}
_RANGES = re.compile(r"\b[1-6]\s*[-–]\s*[1-6]\b|\b[1-6]\s*(?:and|or|to)\s*[1-6]\b")
_NUM = re.compile(r"(?<![\w.#])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s*%)?")


def _values(calls: list[tools.Call]):
    for c in calls:
        yield float(len(c.rows))   # "11 polygons" is a row count, not a cell
        for v in c.rows.select_dtypes("number").to_numpy().ravel() if not c.rows.empty else []:
            if v == v:   # skip NaN
                yield float(v)


def unmatched_numbers(text: str, calls: list[tools.Call], question: str = "") -> list[str]:
    """Numbers in the answer that no tool returned (within rounding)."""
    values = list(_values(calls))
    pcts = [v * 100 for v in values if -1e-9 <= v <= 1.000001]
    asked = {float(m.group(1).replace(",", "")) for m in _NUM.finditer(question)}
    missing = []
    for m in _NUM.finditer(_RANGES.sub(" ", text)):
        whole, frac, pct = m.group(1).replace(",", ""), m.group(2) or "", m.group(3)
        n = float(whole + frac)
        if n in asked or (not pct and n in _FIXED) or (not pct and not frac and 2000 <= n <= 2035):
            continue
        tol = 0.51 * 10 ** -len(frac.lstrip(".")) if frac else 0.51
        pool = pcts + values if pct else values + pcts
        if not any(abs(p - n) <= max(tol, abs(n) * 0.005) for p in pool):
            missing.append(m.group(0).strip())
    return missing

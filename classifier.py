import json
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
FIELD_TYPES = {"choice", "list", "text", "number", "boolean"}
DEFAULT_THRESHOLD = 0.5

# Models like Jev and Mercury Decide answer typed questions on the decisions endpoint, not chat.
DECISION_MODEL_HINTS = ("typesafe/", "~typesafe/", "mercury-decide")
_learned_decision_models = set()


class ClassifyError(Exception):
    pass


class FatalApiError(ClassifyError):
    """Retrying won't help (no credits, daily limit, bad key, unknown model). The message is meant for the user."""


class WrongEndpoint(ClassifyError):
    """The model only works on the decisions endpoint."""


class SchemaError(ValueError):
    pass


def is_decision_model(model):
    return model in _learned_decision_models or any(hint in model for hint in DECISION_MODEL_HINTS)


def load_schema(text):
    try:
        schema = json.loads(text)
    except json.JSONDecodeError as e:
        raise SchemaError(f"schema is not valid JSON: {e}")

    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not fields or not isinstance(fields, list):
        raise SchemaError("schema needs a non-empty 'fields' list")

    seen = set()
    for f in fields:
        if not isinstance(f, dict) or not f.get("name"):
            raise SchemaError("every field needs a 'name'")
        if f["name"] in seen:
            raise SchemaError(f"duplicate field name: {f['name']}")
        seen.add(f["name"])
        if f.get("type") not in FIELD_TYPES:
            raise SchemaError(f"{f['name']}: type must be one of {sorted(FIELD_TYPES)}")
        if f["type"] == "choice" and not f.get("options"):
            raise SchemaError(f"{f['name']}: choice fields need 'options'")
    return schema


def api_key():
    return os.getenv("OPENROUTER_API_KEY")


# ---------------------------------------------------------------- chat models (JSON in a text reply)

def _describe(field):
    kind = field["type"]
    criteria = field.get("criteria") or {}
    if kind == "choice":
        hint = "one of: " + ", ".join(f"{o} ({criteria[o]})" if o in criteria else o for o in field["options"])
    elif kind == "list":
        hint = "list of short strings" + (", chosen from: " + ", ".join(field["options"]) if field.get("options") else "")
    else:
        hint = {"text": "short string", "number": "number", "boolean": "true or false"}[kind]
    line = f'  "{field["name"]}" ({hint})'
    if field.get("description"):
        line += f": {field['description']}"
    return line


def build_prompt(schema, rows):
    lines = [
        schema.get("description", "Classify the records below."),
        "Reply with a single JSON array and nothing else, one object per record in the same order.",
        "Every object needs these keys:",
        '  "id" (the record number as given)',
    ]
    lines += [_describe(f) for f in schema["fields"]]
    for n, row in enumerate(rows, 1):
        lines += ["", f"[{n}]"]
        lines += [f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in row.items()]
    return "\n".join(lines)


def _coerce(field, value):
    kind = field["type"]

    if value is None:
        if kind in ("text", "list"):
            return ""
        raise ClassifyError(f"{field['name']} is missing")

    if kind == "choice":
        allowed = {o.lower(): o for o in field["options"]}
        key = str(value).strip().lower()
        if key not in allowed:
            raise ClassifyError(f"{field['name']}: {value!r} is not an allowed option")
        return allowed[key]

    if kind == "list":
        if isinstance(value, str):
            value = [value]
        return ", ".join(str(v).strip() for v in value)

    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ClassifyError(f"{field['name']}: {value!r} is not a number")

    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes"):
            return True
        if text in ("false", "no"):
            return False
        raise ClassifyError(f"{field['name']}: {value!r} is not true/false")

    return str(value).strip()


def _parse_batch(schema, text, count):
    """One entry per record: a dict of values, or a ClassifyError for that record."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ClassifyError(f"no JSON array in reply: {text[:80]!r}")
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise ClassifyError(f"bad JSON in reply: {text[:80]!r}")

    by_id = {str(i.get("id")): i for i in items if isinstance(i, dict)}

    out = []
    for n in range(1, count + 1):
        item = by_id.get(str(n))
        if item is None:
            out.append(ClassifyError(f"no answer for record {n}"))
            continue
        try:
            out.append({f["name"]: _coerce(f, item.get(f["name"])) for f in schema["fields"]})
        except ClassifyError as e:
            out.append(e)
    return out


# ---------------------------------------------------------------- decision models (Jev, Mercury Decide)

def _decision_kind(field):
    """How a schema field is asked on the decisions endpoint, or None if the model can't produce it."""
    kind = field["type"]
    if kind == "choice":
        return "choice"
    if kind == "list" and field.get("options"):
        return "tags"
    if kind == "boolean":
        return "yesno"
    if kind == "number" and isinstance(field.get("criteria"), list) and field["criteria"]:
        return "score"
    return None


def build_questions(schema):
    """Turn the schema into decisions questions. Returns (questions, names of fields that are skipped)."""
    questions, skipped = {}, []
    for f in schema["fields"]:
        name, kind = f["name"], _decision_kind(f)
        about = f.get("description") or name
        criteria = f.get("criteria") or {}

        if kind == "choice":
            questions[name] = {
                "type": "choice",
                "instructions": about,
                "criteria": {o: (criteria.get(o, o) if isinstance(criteria, dict) else o) for o in f["options"]},
            }
        elif kind == "tags":
            for i, tag in enumerate(f["options"]):
                detail = criteria.get(tag, tag) if isinstance(criteria, dict) else tag
                questions[f"{name}__{i}"] = {
                    "type": "noul",
                    "instructions": f"Is the text about: {tag}?",
                    "criteria": {"true": f"The text is about {detail}.", "false": f"The text is not about {detail}."},
                }
        elif kind == "yesno":
            questions[name] = {
                "type": "noul",
                "instructions": about,
                "criteria": {"true": f"Yes: {about}", "false": "No."},
            }
        elif kind == "score":
            questions[name] = {"type": "score", "instructions": about, "criteria": f["criteria"]}
        else:
            skipped.append(name)
    return questions, skipped


def _parse_decision(schema, reply):
    answers = reply.get("answers") if isinstance(reply, dict) else None
    if not isinstance(answers, dict):
        raise ClassifyError("the reply has no answers")

    out = {}
    try:
        for f in schema["fields"]:
            name, kind = f["name"], _decision_kind(f)
            threshold = f.get("threshold", DEFAULT_THRESHOLD)
            if kind == "choice":
                out[name] = _coerce(f, answers[name]["choice"])
            elif kind == "tags":
                chosen = [t for i, t in enumerate(f["options"]) if answers[f"{name}__{i}"]["noul"] >= threshold]
                out[name] = ", ".join(chosen)
            elif kind == "yesno":
                out[name] = answers[name]["noul"] >= threshold
            elif kind == "score":
                out[name] = float(answers[name]["score"])
            else:
                out[name] = ""
    except (KeyError, TypeError, ValueError):
        raise ClassifyError("the reply is missing an expected answer")
    return out


def _decide_rows(schema, rows, model):
    """One decisions request per record. Returns (replies, cost in USD)."""
    questions, _ = build_questions(schema)
    replies, cost = [], 0.0
    for row in rows:
        try:
            reply = _send(DECISIONS_URL, model, {"model": model, "state": row, "questions": questions})
            cost += float((reply.get("usage") or {}).get("cost") or 0)
            replies.append(_parse_decision(schema, reply))
        except FatalApiError:
            raise
        except ClassifyError as e:
            replies.append(e)
    return replies, cost


# ---------------------------------------------------------------- talking to OpenRouter

def _api_message(resp):
    try:
        return str(resp.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return resp.text[:120]


def _wait_time(resp, attempt):
    try:
        return min(float(resp.headers["Retry-After"]), 30)
    except (KeyError, ValueError):
        return 2 ** (attempt + 1)


def _send(url, model, body, retries=3):
    """POST to OpenRouter and return the parsed JSON reply, retrying transient errors."""
    headers = {"Authorization": f"Bearer {api_key()}"}

    resp = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=180)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** (attempt + 1))
            continue

        code = resp.status_code
        if code == 401:
            raise FatalApiError("The AI service did not accept our access key, so the run could not continue. Please contact the person who set up this app.")
        if code == 402:
            raise FatalApiError("The AI service has run out of credit, so the run could not continue. Please contact the person who set up this app.")
        if code == 403:
            raise FatalApiError(f"The AI service did not accept the request, so the run could not continue. Please try again later. ({_api_message(resp)})")
        if code == 404:
            raise FatalApiError("The AI model we use is not available right now. Please try again later, or contact the person who set up this app.")

        if code == 429:
            reason = _api_message(resp).lower()
            if "per-day" in reason or "per day" in reason or "daily" in reason:
                raise FatalApiError(
                    "The free daily limit has been reached, so the run stopped. It starts again at midnight UTC, "
                    "so please try again tomorrow."
                )
        if code == 429 or code >= 500:
            time.sleep(_wait_time(resp, attempt))
            continue

        if code >= 400:
            message = _api_message(resp)
            if url == CHAT_URL and "decisions model" in message.lower():
                raise WrongEndpoint(message)
            raise ClassifyError(f"{model}: {message}")

        try:
            reply = resp.json()
        except ValueError:
            raise ClassifyError(f"{model} sent an unexpected reply")
        if isinstance(reply, dict) and "error" in reply:
            error = reply["error"]
            raise ClassifyError(f"{model}: {error.get('message', 'unknown error') if isinstance(error, dict) else error}")
        return reply

    if resp is None:
        raise ClassifyError("Could not reach the AI service. Please check your internet connection and try again.")
    if resp.status_code == 429:
        raise ClassifyError("The AI service is busy right now. Please wait a minute and try again.")
    raise ClassifyError(f"{model} kept failing (status {resp.status_code})")


def _call(model, prompt):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    reply = _send(CHAT_URL, model, body)
    try:
        return reply["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ClassifyError(f"{model} sent an unexpected reply")


def _answer(schema, rows, model):
    """Replies for a list of records from one model. Returns (replies, cost in USD)."""
    if not is_decision_model(model):
        try:
            return _parse_batch(schema, _call(model, build_prompt(schema, rows)), len(rows)), 0.0
        except WrongEndpoint:
            _learned_decision_models.add(model)
    return _decide_rows(schema, rows, model)


def classify_batch(schema, rows, models):
    """Ask each model in turn. Records a model got wrong go to the next model.

    Returns (results, errors, cost): results[i] is (values, model) or None, errors[i] is the reason it failed,
    cost is what the decision models charged in USD (chat models are not tracked).
    Raises FatalApiError only when every model hit an account-level problem (credits, daily limit, key).
    """
    results = [None] * len(rows)
    errors = [""] * len(rows)
    pending = list(range(len(rows)))
    fatal = []
    cost = 0.0

    for model in models:
        if not pending:
            break
        try:
            replies, spent = _answer(schema, [rows[i] for i in pending], model)
        except FatalApiError as e:
            fatal.append(e)
            for i in pending:
                errors[i] = str(e)
            continue
        except (ClassifyError, requests.RequestException) as e:
            for i in pending:
                errors[i] = str(e)
            continue

        cost += spent
        still_pending = []
        for i, reply in zip(pending, replies):
            if isinstance(reply, ClassifyError):
                errors[i] = str(reply)
                still_pending.append(i)
            else:
                results[i] = (reply, model)
        pending = still_pending

    if fatal and len(fatal) == len(models):
        raise fatal[0]
    return results, errors, cost


def daily_requests_left():
    """Free-model requests OpenRouter still allows today, or None if we can't tell."""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {api_key()}"},
            timeout=15,
        )
        return resp.json()["data"]["free_model_daily_requests"]["remaining"]
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None

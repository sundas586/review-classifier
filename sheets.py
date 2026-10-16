import csv
import io
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

import gspread
import pandas as pd
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DATA_TAB = "Data"  # the customer's reviews, never changed by the app
CATEGORIZATION_TAB = "Categorization"  # the reviews with the classification next to them
SUMMARY_TAB = "Summary"  # counts per field
DATA_COLUMNS = ["review_id", "product", "review_text"]  # the fixed format of the Data tab
TYPE_LABELS = {"choice": "choice", "list": "tags", "boolean": "yes/no", "text": "text"}


class SheetsError(Exception):
    """The message is written for the end user. `detail` is optional technical text for the administrator."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


# ---------------------------------------------------------------- connection

def _credentials_info():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if path and Path(path).is_file():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


SCRIPT_URL_PREFIX = "https://script.google.com/"


def _script_settings(script):
    """(url, token) of the Apps Script web app to use: the one given (from the page) or the server's, else None."""
    if script and script[0]:
        return script
    url = os.getenv("APPS_SCRIPT_URL")
    return (url, os.getenv("APPS_SCRIPT_TOKEN", "")) if url else None


def uses_script(script=None):
    """True when the Sheet is reached through an Apps Script web app (no Google key needed)."""
    return _script_settings(script) is not None


def can_write(script=None):
    """True when the app can write results into the sheet (Apps Script web app or service account key)."""
    if uses_script(script):
        return True
    info = _credentials_info()
    return bool(info and info.get("client_email") and info.get("private_key"))


def service_account_email():
    return (_credentials_info() or {}).get("client_email", "")


def _client():
    info = _credentials_info()
    if not info:
        raise SheetsError("Google Sheets is not set up on this server.")
    try:
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except (ValueError, KeyError):
        raise SheetsError("The Google service account key is not valid. Please contact the administrator.")
    return gspread.authorize(creds)


@contextmanager
def _friendly_errors():
    email = service_account_email()
    try:
        yield
    except SheetsError:
        raise
    except gspread.exceptions.NoValidUrlKeyFound:
        raise SheetsError("That does not look like a Google Sheets link. Copy the full link from your browser.")
    except gspread.exceptions.SpreadsheetNotFound:
        raise SheetsError(f"We could not find the sheet. Please check the link, and make sure it is shared with {email} as an Editor or with 'Anyone with the link' as Editor.")
    except gspread.exceptions.APIError as e:
        code = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status_code", None)
        if code in (403, 404):
            raise SheetsError(f"Google did not allow access to this sheet. Please share it with {email} as an Editor, or choose 'Anyone with the link' as Editor, and try again.")
        if code == 429:
            raise SheetsError("Google is limiting requests right now. Please wait a minute and try again.")
        raise SheetsError("Google Sheets returned an error. Please try again in a moment.")
    except requests.RequestException:
        raise SheetsError("Could not reach Google. Please check the connection and try again.")


def _open(url):
    if not url or not url.strip():
        raise SheetsError("Paste the link of your Google Sheet first.")
    return _client().open_by_url(url.strip())


def _find_tab(sheet, name):
    """The tab with this name (capital letters do not matter), or None."""
    return next((ws for ws in sheet.worksheets() if ws.title.strip().lower() == name.lower()), None)


# the Sheet is reached either through an Apps Script web app (no key) or a service account (key)

def _sheet_id(url):
    if not url or not url.strip():
        raise SheetsError("Paste the link of your Google Sheet first.")
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not match:
        raise SheetsError("That does not look like a Google Sheets link. Copy the full link from your browser.")
    return match.group(1)


def _snippet(response):
    """What Google answered, as short plain text, so a wrong reply can be understood."""
    text = re.sub(r"<(script|style).*?</\1>", " ", response.text or "", flags=re.S | re.I)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return f"HTTP {response.status_code}: {text[:400] or '(empty reply)'}"


def _script_call(url, payload, script=None):
    script_url, token = _script_settings(script)
    if not script_url.strip().startswith(SCRIPT_URL_PREFIX):  # the page lets users type this address
        raise SheetsError(f"The Google script address must start with {SCRIPT_URL_PREFIX} . Please check what you typed.")
    body = {"token": token, "sheetId": _sheet_id(url), **payload}
    try:
        response = requests.post(script_url.strip(), json=body, timeout=180)
    except requests.RequestException as e:
        raise SheetsError("Could not reach Google. Please check your internet connection and try again.", detail=repr(e)[:400])
    try:
        data = response.json()
    except ValueError:  # note: requests' own JSON error is also a RequestException, so it must not be caught above
        raise SheetsError(
            "Google answered, but not in the way the app expected. Please check that the Google script is deployed as a "
            "Web app that anyone can open, and that you copied the address that ends with /exec.",
            detail=_snippet(response),
        )
    if not isinstance(data, dict):
        raise SheetsError("Google answered, but not in the way the app expected.", detail=_snippet(response))
    if data.get("ok"):
        return data
    if data.get("error") == "bad_token":
        raise SheetsError("The password (token) was not accepted. Please check it and try again.")
    if data.get("error") == "no_access":
        raise SheetsError("We could not open your sheet. Please check the link. Then, in Google Sheets, click Share and choose 'Anyone with the link' as Editor.")
    raise SheetsError("Google Sheets returned an error. Please try again in a moment.", detail=str(data.get("message") or data.get("error") or ""))


def _read_public(url, name):
    """Read a tab of a sheet that is open to 'Anyone with the link', without any login.

    Google answers with the first tab when the name does not exist, so a missing tab shows up as wrong columns.
    """
    try:
        response = requests.get(
            f"https://docs.google.com/spreadsheets/d/{_sheet_id(url)}/gviz/tq",
            params={"tqx": "out:csv", "sheet": name}, timeout=60,
        )
    except requests.RequestException:
        raise SheetsError("Could not reach Google. Please check the connection and try again.")
    response.encoding = "utf-8"
    if response.status_code != 200 or response.text.lstrip().startswith("<"):
        raise SheetsError("We could not read your sheet. Please check the link. Then, in Google Sheets, click Share and choose 'Anyone with the link'.")
    return list(csv.reader(io.StringIO(response.text)))


def _read_tab(url, name, script=None):
    """All cells of a tab as rows of text, or None if the sheet has no such tab."""
    if uses_script(script):
        data = _script_call(url, {"action": "read", "tab": name}, script)
        return data["values"] if data.get("found") else None
    if not can_write():
        return _read_public(url, name)
    with _friendly_errors():
        ws = _find_tab(_open(url), name)
        return ws.get_all_values() if ws is not None else None


def _write_tab(url, name, rows, bold_rows=(), script=None):
    """Create the tab if needed, empty it and write the rows from A1. Values are stored as text, never read as formulas."""
    if not can_write(script):
        raise SheetsError("Writing to the sheet is not connected on this server.")
    width = max((len(r) for r in rows), default=1)
    padded = [list(r) + [""] * (width - len(r)) for r in rows]
    if uses_script(script):
        _script_call(url, {"action": "write", "tab": name, "rows": padded, "boldRows": list(bold_rows)}, script)
        return
    with _friendly_errors():
        sheet = _open(url)
        ws = _find_tab(sheet, name)
        if ws is None:
            ws = sheet.add_worksheet(title=name, rows=max(len(rows) + 20, 100), cols=max(width, 10))
        else:
            ws.clear()
            if ws.col_count < width:
                ws.add_cols(width - ws.col_count)
            if ws.row_count < len(rows):
                ws.add_rows(len(rows) - ws.row_count)
        ws.batch_update([{"range": f"A1:{rowcol_to_a1(len(rows), width)}", "values": padded}])
        for row in bold_rows:
            try:
                ws.format(f"A{row}:{rowcol_to_a1(row, width)}", {"textFormat": {"bold": True}})
            except Exception:  # bold text is only cosmetic
                pass


# ---------------------------------------------------------------- reading reviews

def _unique(names):
    seen, out = {}, []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name}_{count + 1}")
    return out


def _frame(values, tab):
    """Rows of a tab as a DataFrame of text: the first row holds the column names, empty rows at the end are dropped."""
    values = [list(row) for row in values]
    while values and not any(cell.strip() for cell in values[-1]):
        values.pop()
    if len(values) < 2:
        raise SheetsError(f"The '{tab}' tab is empty. Put the headings in the first row and your reviews in the rows below.")

    header = [h.strip() for h in values[0]]
    keep = [i for i, h in enumerate(header) if h]
    if not keep:
        raise SheetsError(f"The first row of the '{tab}' tab is empty. It must contain the column headings.")

    names = _unique([header[i] for i in keep])
    rows = [[row[i] if i < len(row) else "" for i in keep] for row in values[1:]]
    return pd.DataFrame(rows, columns=names, dtype=str)


def read_data(url, script=None):
    """The reviews from the Data tab. `script` is an optional (web app url, token) typed on the page."""
    values = _read_tab(url, DATA_TAB, script)
    if values is None:
        raise SheetsError(f"We could not find a tab named '{DATA_TAB}' in your Google Sheet. Please add it and put your reviews in it.")
    data = _frame(values, DATA_TAB)

    # the format is fixed: these columns must exist (capital letters and spaces in the header do not matter)
    lookup = {c.strip().lower().replace(" ", "_"): c for c in data.columns}
    missing = [c for c in DATA_COLUMNS if c not in lookup]
    if missing:
        raise SheetsError(
            f"The first row of your '{DATA_TAB}' tab must have these three headings: {', '.join(DATA_COLUMNS)}. "
            f"These are missing: {', '.join(missing)}."
        )
    data = data.rename(columns={lookup[c]: c for c in DATA_COLUMNS})

    # a row without review text cannot be classified (this also skips empty rows in the middle of the tab)
    data = data[data["review_text"].str.strip() != ""].reset_index(drop=True)
    if data.empty:
        raise SheetsError(f"The '{DATA_TAB}' tab has no reviews yet. Please fill in the review_text column.")
    return data


def read_categorization(url, script=None):
    """Results written by an earlier run, or None if there are none."""
    if not can_write(script):
        return None  # nothing is ever written in read-only mode, so there is nothing to reuse
    values = _read_tab(url, CATEGORIZATION_TAB, script) or []
    try:
        return _frame(values, CATEGORIZATION_TAB)
    except SheetsError:
        return None


def _restore(value, kind):
    value = value.strip() if isinstance(value, str) else value
    if kind == "boolean":
        return str(value).lower() in ("true", "yes", "1")
    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return ""
    return value


def with_previous_results(inputs, previous, schema):
    """Reuse results from the Categorization tab for reviews that are unchanged, so they are not processed again."""
    if previous is None:
        return inputs
    kinds = {f["name"]: f["type"] for f in schema["fields"]}
    carried = list(kinds) + ["status", "model"]
    if not all(c in previous.columns for c in list(inputs.columns) + list(kinds) + ["status"]):
        return inputs

    n = min(len(inputs), len(previous))
    current, earlier = inputs.iloc[:n].reset_index(drop=True), previous.iloc[:n].reset_index(drop=True)
    unchanged = (current == earlier[list(inputs.columns)]).all(axis=1) & (earlier["status"] == "done")

    frame = inputs.copy().astype(object)
    for col in carried:
        frame[col] = ""
        if col not in previous.columns:
            continue
        for i in unchanged[unchanged].index:
            frame.at[inputs.index[i], col] = _restore(earlier.at[i, col], kinds.get(col))
    return frame


# ---------------------------------------------------------------- writing results

def _text(value):
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value)


def write_categorization(url, result, script=None):
    """Write every review with its classification to the Categorization tab, replacing what was there."""
    columns = [c for c in result.columns if c != "latency_s"]
    rows = [columns] + [[_text(v) for v in row] for row in result[columns].itertuples(index=False)]
    _write_tab(url, CATEGORIZATION_TAB, rows, bold_rows=(1,), script=script)
    return len(result)


def write_summary(url, rows, script=None):
    """Write the summary tables to the Summary tab, replacing what was there."""
    bold = [i for i, r in enumerate(rows, start=1) if len(r) == 1 and r[0]] + [i for i, r in enumerate(rows, start=1) if r[:1] == ["Value"]]
    _write_tab(url, SUMMARY_TAB, [[_text(v) for v in r] for r in rows], bold_rows=bold, script=script)

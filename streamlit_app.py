import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from classifier import SchemaError, api_key, build_questions, daily_requests_left, is_decision_model, load_schema
from runner import run

BASE = Path(__file__).parent
SAMPLE_SCHEMA = BASE / "schemas" / "review_schema.json"
MAX_ROWS = int(os.getenv("MAX_ROWS", "1000"))
FREE_REQUESTS_PER_MIN = 20

st.set_page_config(page_title="Review Classifier", layout="wide")
st.title("Review Classifier")
st.caption("Upload a schema and a CSV, the model fills in the fields you defined.")

password = os.getenv("APP_PASSWORD")
if password and st.text_input("Access code", type="password") != password:
    st.stop()

with st.sidebar:
    st.header("Settings")
    model = st.text_input("Model", os.getenv("PRIMARY_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"))
    fallback = st.text_input("Fallback model (optional)", os.getenv("FALLBACK_MODEL", ""))
    workers = st.slider("Parallel requests", 1, 16, 4)
    rpm = st.number_input("Max requests per minute (0 = no limit)", 0, 600, 18 if model.endswith(":free") else 0)
    if is_decision_model(model):
        batch_size = 1  # a decision model answers about one review per request
    else:
        batch_size = st.number_input("Reviews per request", 1, 25, 10, help="More reviews per request means fewer requests, which matters on free models.")
    auto = st.checkbox("Auto-classify when a CSV is uploaded", True)

if model.endswith(":free"):
    st.markdown(
        "<div style='position:fixed; right:14px; bottom:8px; z-index:999; font-size:12px; color:#9ca3af'>"
        f"{FREE_REQUESTS_PER_MIN * batch_size} categorizations per minute is the limitation of our prototype.</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=20)
def requests_left_today():
    return daily_requests_left()


if model.endswith(":free") and api_key():
    left = requests_left_today()
    if left is not None:
        st.sidebar.caption(f"Free requests left today: {left} (resets 00:00 UTC)")


def read_csv(source):
    try:
        data = pd.read_csv(source, dtype=str).fillna("")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        st.error("This file could not be read as a CSV. In Excel use Save As > CSV UTF-8 and upload it again.")
        st.stop()
    if data.empty:
        st.error("The file has no data rows.")
        st.stop()
    return data


# 1. schema
st.subheader("1. Schema")
schema_choices = ["Sample schema", "Upload my own"] if SAMPLE_SCHEMA.exists() else ["Upload my own"]
schema_source = st.radio("Schema", schema_choices, horizontal=True, label_visibility="collapsed")
if schema_source == "Upload my own":
    uploaded = st.file_uploader("Schema (.json)", type="json")
    if uploaded is None:
        st.stop()
    schema_text = uploaded.getvalue().decode("utf-8", errors="replace")
else:
    schema_text = SAMPLE_SCHEMA.read_text(encoding="utf-8")

try:
    schema = load_schema(schema_text)
except SchemaError as e:
    st.error(str(e))
    st.stop()

with st.expander("View schema"):
    st.code(schema_text, language="json")
if SAMPLE_SCHEMA.exists():
    st.download_button("Download sample schema", SAMPLE_SCHEMA.read_bytes(), "review_schema.json")

if is_decision_model(model):
    skipped = build_questions(schema)[1]
    if skipped:
        st.info(
            f"{model} answers choices, yes/no questions and scores, not free text, so these fields stay empty: "
            + ", ".join(skipped)
            + ". A list field needs 'options' (the possible tags) to work with this model."
        )

# 2. data
st.subheader("2. Data")
uploaded = st.file_uploader("Upload your reviews (.csv)", type="csv")
if uploaded is None:
    st.session_state.pop("data_id", None)
    st.session_state.pop("result", None)
    st.info("Upload a CSV file to see your reviews and the results.")
    st.stop()
df = read_csv(uploaded)
data_id = ("upload", uploaded.name, uploaded.size, schema_text)

st.dataframe(df.head(10), width="stretch")
limit = min(len(df), MAX_ROWS)
rows = st.number_input(f"Rows to process (max {limit})", 1, limit, min(limit, 100))


def process(frame):
    if not api_key():
        st.error("OPENROUTER_API_KEY is not set.")
        st.stop()
    models = [m for m in (model, fallback) if m]

    pending = len(frame) if "status" not in frame else int((frame["status"] != "done").sum())
    needed = -(-pending // batch_size)
    if model.endswith(":free"):
        left = daily_requests_left()
        if left is not None and needed > left:
            st.error(f"This run needs about {needed} requests but only {left} are left today (resets 00:00 UTC).")
            st.stop()

    bar = st.progress(0.0)

    def update(n, total, _):
        bar.progress(n / total, text=f"{n} / {total}")

    try:
        result, stats = run(frame, schema, models, workers, rpm, update, batch_size=batch_size)
    except SchemaError as e:
        bar.empty()
        st.error(f"This schema cannot be used with {model}: {e}")
        st.stop()
    except Exception as e:
        bar.empty()
        st.error("Something unexpected went wrong while classifying. Please try again. "
                 "If it keeps happening, check the settings in the sidebar.")
        with st.expander("Technical details"):
            st.code(repr(e))
        st.stop()
    bar.empty()
    st.session_state["result"] = (result, stats)


# new data or schema: drop the old dashboard, and classify an uploaded CSV straight away
new_input = st.session_state.get("data_id") != data_id
if new_input:
    st.session_state["data_id"] = data_id
    st.session_state.pop("result", None)
auto_run = new_input and auto

# 3. run
st.subheader("3. Run")
if st.button("Classify", type="primary") or auto_run:
    process(df.head(rows))

if "result" not in st.session_state:
    st.stop()

result, stats = st.session_state["result"]

cols = st.columns(7 if stats["cost"] else 6)
cols[0].metric("Processed", f"{stats['done']} / {stats['attempted']}")
cols[1].metric("Failed", stats["failed"])
cols[2].metric("Requests used", stats["requests"])
cols[3].metric("Total time", f"{stats['elapsed_s']:.1f}s")
cols[4].metric("Records / sec", f"{stats['records_per_s']:.2f}")
cols[5].metric("Request latency avg / p95", f"{stats['avg_latency_s']:.1f}s / {stats['p95_latency_s']:.1f}s")
if stats["cost"]:
    cols[6].metric("Cost", f"${stats['cost']:.4f}", f"${stats['cost'] / max(stats['done'], 1) * 1000:.3f} per 1,000", delta_color="off")

if stats["stopped"]:
    st.warning(
        f"The run stopped early. {stats['stopped']}\n\n"
        f"Reviews already classified are kept. Use **Continue remaining rows** below to carry on from where it stopped."
    )

if (stats["failed"] or stats["not_processed"]) and st.button("Continue remaining rows"):
    process(result)
    st.rerun()

# results
st.subheader("Results")
done = result[result["status"] == "done"]
choice_fields = [f for f in schema["fields"] if f["type"] == "choice"]

table = done
with st.expander("Filters"):
    for f in choice_fields:
        picked = st.multiselect(f["name"], f["options"])
        if picked:
            table = table[table[f["name"]].isin(picked)]

st.dataframe(table, width="stretch")
st.download_button("Download results (CSV)", result.to_csv(index=False), "classified.csv", "text/csv")

# charts
st.subheader("Summary")
charts = []
for f in choice_fields:
    counts = done[f["name"]].value_counts().reset_index()
    counts.columns = [f["name"], "count"]
    if len(f["options"]) <= 3:
        charts.append(px.pie(counts, names=f["name"], values="count", title=f["name"]))
    else:
        charts.append(px.bar(counts, x=f["name"], y="count", title=f["name"]))

for f in schema["fields"]:
    if f["type"] == "list":
        tags = done[f["name"]].str.split(", ").explode()
        tags = tags[tags != ""].value_counts().head(15).reset_index()
        tags.columns = [f["name"], "count"]
        charts.append(px.bar(tags, x="count", y=f["name"], orientation="h", title=f"top {f['name']}"))

for i in range(0, len(charts), 2):
    row = st.columns(2)
    for col, fig in zip(row, charts[i:i + 2]):
        col.plotly_chart(fig, width="stretch")

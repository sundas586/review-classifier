import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from classifier import SchemaError, api_key, build_questions, daily_requests_left, is_decision_model, load_schema
from runner import run

BASE = Path(__file__).parent
DEFAULT_SCHEMA = BASE / "schemas" / "review_schema.json"

# Settings come from the environment (.env locally, Secrets when hosted), not from the page.
MODEL = os.getenv("PRIMARY_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
FALLBACK = os.getenv("FALLBACK_MODEL", "")
IS_FREE = MODEL.endswith(":free")
WORKERS = int(os.getenv("WORKERS", "4"))
RPM = int(os.getenv("MAX_REQUESTS_PER_MIN", "18" if IS_FREE else "0"))
BATCH_SIZE = 1 if is_decision_model(MODEL) else int(os.getenv("REVIEWS_PER_REQUEST", "10"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "1000"))
FREE_REQUESTS_PER_MIN = 20

WAIT_MESSAGE = "This is a prototype, so processing can take a little longer. Thank you for your patience."

PALETTE = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#8b5cf6", "#ec4899", "#64748b", "#84cc16", "#f97316"]
SENTIMENT_COLORS = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#94a3b8", "mixed": "#f59e0b"}

SCHEMA_EXAMPLE = """{
  "description": "Classify a customer review.",
  "fields": [
    { "name": "sentiment", "type": "choice", "options": ["positive", "negative", "neutral"],
      "description": "What is the overall tone of the review?" },
    { "name": "tags", "type": "list", "options": ["late delivery", "great quality", "good value"],
      "description": "Which tags apply to the review?" },
    { "name": "recommends", "type": "boolean",
      "description": "Does the reviewer recommend the product?" }
  ]
}"""

st.set_page_config(page_title="Review Classifier", layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
<style>
.block-container { max-width: 1150px; padding-top: 4rem; }
.hero { background: linear-gradient(135deg, #eaf1ff 0%, #f8fafc 100%); border: 1px solid #dbe5f5;
        border-radius: 16px; padding: 28px 32px; margin-bottom: 20px; }
.hero h1 { margin: 0 0 6px; font-size: 2.1rem; color: #1e3a8a; }
.hero p { margin: 0; color: #475569; font-size: 1.05rem; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 10px 0 18px; }
.card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 18px; }
.card .num { display: inline-block; width: 26px; height: 26px; line-height: 26px; text-align: center;
             background: #2563eb; color: #fff; border-radius: 50%; font-size: 0.85rem; margin-bottom: 8px; }
.card h4 { margin: 0 0 4px; color: #1e293b; font-size: 1.02rem; }
.card p { margin: 0; color: #64748b; font-size: 0.92rem; line-height: 1.45; }
@media (max-width: 800px) { .steps { grid-template-columns: 1fr; } }
</style>
<div class="hero">
  <h1>Review Classifier</h1>
  <p>Turn raw customer reviews into clear, structured insights: sentiment, topics, tags and more.</p>
</div>
""",
    unsafe_allow_html=True,
)

password = os.getenv("APP_PASSWORD")
if password and st.text_input("Access code", type="password") != password:
    st.stop()

if IS_FREE:
    st.markdown(
        "<div style='position:fixed; right:14px; bottom:8px; z-index:999; font-size:12px; color:#94a3b8; "
        "background:rgba(248,250,252,0.95); padding:3px 10px; border-radius:8px; border:1px solid #e2e8f0'>"
        f"{FREE_REQUESTS_PER_MIN * BATCH_SIZE} categorizations per minute is the limitation of our prototype.</div>",
        unsafe_allow_html=True,
    )

# about and how to use
st.markdown(
    "Upload a file of customer reviews and describe the details you want to know about each one "
    "(this description is called a **schema**). The app reads every review, fills in those details automatically, "
    "and gives you a table, summary charts and a CSV you can download."
)
st.markdown(
    """
<div class="steps">
  <div class="card"><span class="num">1</span><h4>Add your schema</h4>
    <p>A small JSON file that lists the fields you want, such as sentiment, category or tags. If you skip this, a default review schema is used.</p></div>
  <div class="card"><span class="num">2</span><h4>Upload your reviews</h4>
    <p>A CSV file with one review per row. Every column is used as context, so extra columns such as product or rating help.</p></div>
  <div class="card"><span class="num">3</span><h4>See the results</h4>
    <p>Processing starts automatically after the upload. When it finishes, explore the table and charts and download the results.</p></div>
</div>
""",
    unsafe_allow_html=True,
)
with st.expander("What is a schema? See an example"):
    st.write(
        "A schema is a list of fields. Each field has a **name**, a **type** and, for choices and tags, the allowed "
        "**options**. Types: `choice` (pick one option), `list` (pick several tags), `boolean` (yes or no), "
        "`number` and `text`."
    )
    st.code(SCHEMA_EXAMPLE, language="json")
with st.expander("Good to know"):
    st.markdown(
        "- This is a prototype, so larger files can take several minutes.\n"
        "- Results are shown only while this page stays open. Download the CSV before you leave.\n"
        "- Reviews are processed by an AI service, so please do not upload confidential information."
    )


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
uploaded_schema = st.file_uploader("Upload a schema (.json)", type="json")
if uploaded_schema is not None:
    schema_text = uploaded_schema.getvalue().decode("utf-8", errors="replace")
elif DEFAULT_SCHEMA.exists():
    schema_text = DEFAULT_SCHEMA.read_text(encoding="utf-8")
    st.caption("No schema uploaded, so the default review schema is used. Upload your own to change the fields.")
else:
    st.info("Upload a schema (.json) to continue.")
    st.stop()

try:
    schema = load_schema(schema_text)
except SchemaError as e:
    st.error(str(e))
    st.stop()

with st.expander("View the schema in use"):
    st.code(schema_text, language="json")
if DEFAULT_SCHEMA.exists():
    st.download_button("Download the default schema as a starting point", DEFAULT_SCHEMA.read_bytes(), "review_schema.json")

if is_decision_model(MODEL):
    skipped = build_questions(schema)[1]
    if skipped:
        st.info(
            "These fields cannot be filled in automatically and will stay empty: " + ", ".join(skipped)
            + ". A list field needs 'options' (the possible tags)."
        )

# 2. data
st.subheader("2. Your reviews")
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
rows = st.number_input(f"Number of reviews to process (up to {limit})", 1, limit, min(limit, 100))


def process(frame):
    if not api_key():
        st.error("The service is not configured yet. Please contact the administrator.")
        st.stop()
    models = [m for m in (MODEL, FALLBACK) if m]

    pending = len(frame) if "status" not in frame else int((frame["status"] != "done").sum())
    needed = -(-pending // BATCH_SIZE)
    if IS_FREE:
        left = daily_requests_left()
        if left is not None and needed > left:
            st.error(
                f"Today's free usage limit is almost reached: this run needs about {needed} requests and only {left} are "
                "left. The limit resets at 00:00 UTC. Try fewer reviews or come back tomorrow."
            )
            st.stop()

    note = st.info(WAIT_MESSAGE)
    bar = st.progress(0.0, text="Starting...")

    def update(n, total, _):
        bar.progress(n / total, text=f"Processed {n} of {total} reviews")

    try:
        result, stats = run(frame, schema, models, WORKERS, RPM, update, batch_size=BATCH_SIZE)
    except SchemaError as e:
        st.error(f"This schema cannot be used: {e}")
        st.stop()
    except Exception as e:
        st.error("Something unexpected went wrong while processing. Please try again in a moment.")
        with st.expander("Technical details"):
            st.code(repr(e))
        st.stop()
    finally:
        note.empty()
        bar.empty()
    st.session_state["result"] = (result, stats)


# new data or schema: drop the old results, and start processing an uploaded CSV straight away
new_input = st.session_state.get("data_id") != data_id
if new_input:
    st.session_state["data_id"] = data_id
    st.session_state.pop("result", None)

# 3. run
st.subheader("3. Results")
if st.button("Process again", type="secondary") or new_input:
    process(df.head(rows))

if "result" not in st.session_state:
    st.stop()

result, stats = st.session_state["result"]

cols = st.columns(7 if stats["cost"] else 6)
cols[0].metric("Processed", f"{stats['done']} / {stats['attempted']}")
cols[1].metric("Failed", stats["failed"])
cols[2].metric("Requests used", stats["requests"])
cols[3].metric("Total time", f"{stats['elapsed_s']:.1f}s")
cols[4].metric("Reviews / sec", f"{stats['records_per_s']:.2f}")
cols[5].metric("Request time avg / p95", f"{stats['avg_latency_s']:.1f}s / {stats['p95_latency_s']:.1f}s")
if stats["cost"]:
    cols[6].metric("Cost", f"${stats['cost']:.4f}", f"${stats['cost'] / max(stats['done'], 1) * 1000:.3f} per 1,000", delta_color="off")

if stats["stopped"]:
    st.warning(
        f"Processing stopped early. {stats['stopped']}\n\n"
        "Reviews already processed are kept. Use **Continue remaining reviews** below to carry on from where it stopped."
    )

if (stats["failed"] or stats["not_processed"]) and st.button("Continue remaining reviews"):
    process(result)
    st.rerun()

done = result[result["status"] == "done"]
choice_fields = [f for f in schema["fields"] if f["type"] == "choice"]

table = done
with st.expander("Filters"):
    for f in choice_fields:
        picked = st.multiselect(f["name"], f["options"])
        if picked:
            table = table[table[f["name"]].isin(picked)]

st.dataframe(table, width="stretch")
st.download_button("Download results (CSV)", result.to_csv(index=False), "classified.csv", "text/csv", type="primary")

# charts
st.subheader("Summary")
charts = []
for f in choice_fields:
    counts = done[f["name"]].value_counts().reset_index()
    counts.columns = [f["name"], "count"]
    if len(f["options"]) <= 3:
        charts.append(px.pie(counts, names=f["name"], values="count", color=f["name"], title=f["name"],
                             color_discrete_map=SENTIMENT_COLORS, color_discrete_sequence=PALETTE, template="plotly_white"))
    else:
        charts.append(px.bar(counts, x=f["name"], y="count", title=f["name"],
                             color_discrete_sequence=PALETTE[:1], template="plotly_white"))

for f in schema["fields"]:
    if f["type"] == "list":
        tags = done[f["name"]].str.split(", ").explode()
        tags = tags[tags != ""].value_counts().head(15).reset_index()
        tags.columns = [f["name"], "count"]
        charts.append(px.bar(tags, x="count", y=f["name"], orientation="h", title=f"top {f['name']}",
                             color_discrete_sequence=PALETTE[:1], template="plotly_white"))

for i in range(0, len(charts), 2):
    row = st.columns(2)
    for col, fig in zip(row, charts[i:i + 2]):
        col.plotly_chart(fig, width="stretch")

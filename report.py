import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")  # no screen needed on a server
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
import xlsxwriter  # noqa: E402

PALETTE = ["#8b7cf6", "#1c1c1e", "#a6c814", "#b8a9f8", "#6b6b73", "#d7f24d", "#f59e0b", "#0ea5e9", "#ec4899"]
SENTIMENT_COLORS = {
    "positive": "#a6c814", "negative": "#ef5350", "neutral": "#b8a9f8", "mixed": "#f5b942",
    "low": "#a6c814", "medium": "#f5b942", "high": "#ef5350", "yes": "#ef5350", "no": "#a6c814",
}
TOP_TAGS = 15


def _is_yes(value):
    return str(value).strip().lower() in ("true", "yes", "1")


def chart_specs(schema, done):
    """What to chart for the classified reviews: one dict per chart with kind, title, labels and values."""
    specs = []
    for f in schema["fields"]:
        name = f["name"]
        if f["type"] == "choice":
            counts = done[name].value_counts()
            kind, title = ("pie" if len(f["options"]) <= 3 else "bar"), name
        elif f["type"] == "list":
            tags = done[name].astype(str).str.split(", ").explode()
            counts = tags[tags != ""].value_counts()
            kind, title = "hbar", f"{name} (most common)"
        elif f["type"] == "boolean":
            counts = done[name].map(lambda v: "yes" if _is_yes(v) else "no").value_counts()
            kind, title = "pie", name
        else:
            continue
        if len(counts):
            specs.append({
                "kind": kind, "title": title, "field": name,
                "labels": [str(i) for i in counts.index], "values": [int(v) for v in counts.values],
            })
    return specs


def trimmed(spec):
    """Tag charts show only the most common tags."""
    if spec["kind"] != "hbar":
        return spec["labels"], spec["values"]
    return spec["labels"][:TOP_TAGS], spec["values"][:TOP_TAGS]


def colors_for(labels):
    return [SENTIMENT_COLORS.get(label, PALETTE[i % len(PALETTE)]) for i, label in enumerate(labels)]


def overview(result):
    status = result["status"].astype(str)
    total, done, failed = len(result), int((status == "done").sum()), int((status == "failed").sum())
    return {"total": total, "done": done, "failed": failed, "pending": total - done - failed}


def summary_rows(schema, result):
    """The Summary tab: overview numbers, then one small table per field."""
    o = overview(result)
    done = result[result["status"] == "done"]
    rows = [
        ["Review summary"],
        ["Last updated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")],
        [],
        ["Overview"],
        ["Reviews", o["total"]],
        ["Classified", o["done"]],
        ["Failed", o["failed"]],
        ["Not processed yet", o["pending"]],
        [],
    ]
    for spec in chart_specs(schema, done):
        rows.append([spec["title"]])
        rows.append(["Value", "Reviews", "Share of classified reviews"])
        for label, value in zip(spec["labels"], spec["values"]):
            rows.append([label, value, f"{value / max(o['done'], 1):.0%}"])
        rows.append([])
    return rows


def build_excel(schema, data, result):
    """The Excel file: tabs Data (the reviews as loaded), Categorization (with the answers) and Summary (the totals).

    Text is always stored as text, so a review that starts with '=' is never read as a formula.
    """
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True})
    header = book.add_format({"bold": True, "font_color": "#ffffff", "bg_color": "#1c1c1e"})
    bold = book.add_format({"bold": True})

    def add_tab(name, rows, header_row=False, bold_rows=()):
        ws = book.add_worksheet(name)
        widths = {}
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                fmt = header if (header_row and r == 0) else (bold if r in bold_rows else None)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value:
                    ws.write_number(r, c, value, fmt)
                else:
                    text = "" if value is None or value != value else str(value)
                    ws.write_string(r, c, text, fmt)
                    widths[c] = max(widths.get(c, 10), min(len(text) + 2, 60))
        for c, width in widths.items():
            ws.set_column(c, c, width)
        if header_row:
            ws.freeze_panes(1, 0)

    add_tab("Data", [list(data.columns)] + data.astype(object).values.tolist(), header_row=True)
    columns = [c for c in result.columns if c != "latency_s"]
    add_tab("Categorization", [columns] + result[columns].astype(object).values.tolist(), header_row=True)
    rows = summary_rows(schema, result)
    add_tab("Summary", rows, bold_rows=[i for i, r in enumerate(rows) if len(r) == 1 and r[0] or r[:1] == ["Value"]])
    book.close()
    return buffer.getvalue()


def build_pdf(schema, result, title="Review summary"):
    """The summary charts as a PDF (two charts per A4 page). Returns the file as bytes."""
    o = overview(result)
    specs = chart_specs(schema, result[result["status"] == "done"])
    buffer = io.BytesIO()

    with PdfPages(buffer) as pdf:
        pages = [specs[i:i + 2] for i in range(0, len(specs), 2)] or [[]]
        for number, group in enumerate(pages):
            fig, axes = plt.subplots(2, 1, figsize=(8.27, 11.69))
            fig.subplots_adjust(top=0.78 if number == 0 else 0.93, bottom=0.07, hspace=0.5, left=0.3, right=0.9)
            if number == 0:
                fig.text(0.08, 0.93, title, fontsize=22, fontweight="bold", color="#1e3a8a")
                fig.text(0.08, 0.905, datetime.now(timezone.utc).strftime("Created %Y-%m-%d %H:%M UTC"), fontsize=10, color="#64748b")
                fig.text(
                    0.08, 0.855,
                    f"Reviews: {o['total']}     Classified: {o['done']}     Failed: {o['failed']}     Not processed yet: {o['pending']}",
                    fontsize=11, color="#1e293b",
                )
                if not specs:
                    fig.text(0.08, 0.8, "No classified reviews yet, so there are no charts.", fontsize=11, color="#64748b")

            for ax, spec in zip(axes, group + [None] * (2 - len(group))):
                if spec is None:
                    ax.axis("off")
                    continue
                labels, values = trimmed(spec)
                colors = colors_for(labels)
                if spec["kind"] == "pie":
                    ax.pie(values, labels=labels, colors=colors, autopct="%1.0f%%", startangle=90, textprops={"fontsize": 10})
                elif spec["kind"] == "bar":
                    ax.bar(labels, values, color=PALETTE[0])
                    ax.tick_params(axis="x", labelrotation=30)
                    for tick in ax.get_xticklabels():
                        tick.set_horizontalalignment("right")
                else:
                    ax.barh(labels, values, color=PALETTE[0])
                    ax.invert_yaxis()
                if spec["kind"] != "pie":
                    ax.spines[["top", "right"]].set_visible(False)
                    (ax.xaxis if spec["kind"] == "hbar" else ax.yaxis).set_major_locator(MaxNLocator(integer=True))
                ax.set_title(spec["title"], fontsize=13, fontweight="bold", color="#1e293b")

            pdf.savefig(fig)
            plt.close(fig)
    return buffer.getvalue()

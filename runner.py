import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from classifier import FatalApiError, build_questions, classify_batch, is_decision_model

META_COLS = ["status", "model", "latency_s", "error"]


class Throttle:
    """Spaces out requests so we stay under a per-minute limit."""

    def __init__(self, per_minute):
        self.gap = 60 / per_minute if per_minute else 0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.gap
        time.sleep(start - now)


def prepare(df, schema):
    df = df.copy()
    for col in [f["name"] for f in schema["fields"]] + META_COLS:
        if col not in df.columns:
            df[col] = ""
    return df.astype(object)


def _work(schema, rows, models, throttle, stop):
    """Returns (results, errors, cost, latency, fatal). results is None if the batch was skipped or hit a fatal error."""
    if stop.is_set():
        return None, None, 0.0, 0.0, None
    throttle.wait()
    if stop.is_set():
        return None, None, 0.0, 0.0, None

    start = time.perf_counter()
    try:
        results, errors, cost = classify_batch(schema, rows, models)
    except FatalApiError as e:
        stop.set()
        return None, None, 0.0, time.perf_counter() - start, e
    return results, errors, cost, time.perf_counter() - start, None


def run(df, schema, models, workers=4, rpm=0, on_progress=None, limit=None, batch_size=10):
    """Classify rows that aren't 'done' yet (at most `limit`), `batch_size` rows per request.

    Returns (dataframe, speed stats). latency_s is the time of the request the row was part of.
    Decision models (Jev, Mercury Decide) take one record per request, so batch_size is ignored for them.
    If the API refuses to continue (no credits, daily limit...) the run stops early, rows already done
    are kept, and stats["stopped"] holds a message for the user.
    """
    if is_decision_model(models[0]):
        build_questions(schema)  # fails early with a SchemaError if the schema can't be asked as questions
        batch_size = 1

    df = prepare(df, schema)
    output_cols = [f["name"] for f in schema["fields"]] + META_COLS
    input_cols = [c for c in df.columns if c not in output_cols]

    todo = df.index[df["status"] != "done"].tolist()[:limit]
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    throttle = Throttle(rpm)
    stop = threading.Event()
    latencies, ok, failed, finished, not_sent, stopped, cost = [], 0, 0, 0, 0, None, 0.0
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_work, schema, [df.loc[i, input_cols].to_dict() for i in batch], models, throttle, stop): batch
            for batch in batches
        }
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                results, errors, spent, latency, fatal = fut.result()
            except Exception as e:  # one broken batch should not lose the rest of the run
                results, errors, spent, latency, fatal = [None] * len(batch), [f"unexpected error: {e}"] * len(batch), 0.0, 0.0, None

            cost += spent
            if fatal is not None and stopped is None:
                stopped = str(fatal)

            if results is None:
                if fatal is None:
                    not_sent += 1
                finished += len(batch)
                if on_progress:
                    on_progress(finished, len(todo), df)
                continue

            latencies.append(latency)

            for i, result, error in zip(batch, results, errors):
                if result is None:
                    failed += 1
                    df.at[i, "status"] = "failed"
                    df.at[i, "model"] = ""
                    df.at[i, "error"] = error
                else:
                    values, model = result
                    ok += 1
                    for key, value in values.items():
                        df.at[i, key] = value
                    df.at[i, "status"] = "done"
                    df.at[i, "model"] = model
                    df.at[i, "error"] = ""
                df.at[i, "latency_s"] = round(latency, 2)

            finished += len(batch)
            if on_progress:
                on_progress(finished, len(todo), df)

    elapsed = time.perf_counter() - started
    lat = pd.Series(latencies, dtype=float)
    stats = {
        "attempted": len(todo),
        "done": ok,
        "failed": failed,
        "not_processed": len(todo) - ok - failed,
        "stopped": stopped,
        "requests": len(batches) - not_sent,
        "cost": cost,
        "elapsed_s": elapsed,
        "records_per_s": len(todo) / elapsed if elapsed else 0,
        "avg_latency_s": lat.mean() if len(lat) else 0,
        "p95_latency_s": lat.quantile(0.95) if len(lat) else 0,
    }
    return df, stats

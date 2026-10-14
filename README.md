# Review Classifier (prototype)

Turns raw product reviews into structured data. You upload a **schema** (the fields you want) and a **CSV** (the reviews), the app asks an AI model on OpenRouter to fill in those fields for every row, and shows the results in a table, charts and a speed report.

The default model is **NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b:free`), a free chat model, so the prototype runs at no cost. It can be switched to **Jev** (`typesafe/jev-1.13`), a *decision model* that answers typed questions (pick one option, yes/no, score) and returns a probability for each answer. Jev is faster and cheap but not free; see "Models, speed and cost" below.

## How it works

1. You provide a schema (JSON) and a data file (CSV). Sample versions of both are built in, including a 1,000-review dummy dataset.
2. The app turns the schema into questions and sends each review to the model.
   - **Decision models (Jev, Mercury Decide):** one request per review. The model answers every question about that review at once.
   - **Chat models:** reviews are sent in **batches of 10 per request** and the model replies with a JSON list.
3. Each answer is checked against the schema (for example `sentiment` must be one of the allowed options), and anything invalid is marked `failed` instead of being guessed.
4. The results are shown as a filterable table, summary charts and a CSV download.

Example of what happens to two reviews:

```
Input rows:   R0042 | Steel Water Bottle 750ml | "Lid leaks in my bag, ruined my laptop sleeve"
              R0043 | Wireless Earbuds X2      | "Great sound, battery lasts all day"

Output rows:  R0042 -> sentiment=negative | category=quality     | priority=high | has_issue=True  | status=done
              R0043 -> sentiment=positive | category=performance | priority=low  | has_issue=False | status=done
```

**Resuming.** Every row has a `status` column. If a run stops halfway (closed browser, rate limit, network error), running it again only processes the rows whose status is not `done`, so finished work is never repeated and no requests are wasted.

### What happens in each request

Each request to OpenRouter is built in `classifier.py`:

- **Decision models** (`typesafe/jev-1.13`, `inception/mercury-decide:free`) are called on the Decisions endpoint (`/api/alpha/decisions`). The body holds the model name, the review's columns as the `state`, and the `questions` built from the schema. The reply holds a typed answer per question plus the cost of the request.
- **Chat models** are called on the chat endpoint (`/api/v1/chat/completions`). The body holds the model name, our prompt (the task, the schema fields and 10 reviews) and `temperature: 0`, which keeps answers as stable as possible. The model's text reply is parsed as a JSON list.

In both cases:

- **Headers:** the API key, sent as a Bearer token. It is read from the settings file or app secrets and never appears in the code.
- **Retries:** the app makes up to 3 attempts. If OpenRouter answers `429` (too many requests per minute), a server error (`500` and above) or the network drops, it waits 2, 4 and then 8 seconds (`2 ** (attempt + 1)`) before trying again. If OpenRouter says how long to wait (`Retry-After`), that time is used instead, up to 30 seconds.
- **Success:** the answer is checked against the schema, record by record.
- **Unexpected reply:** if the reply does not have the expected shape (for example there are no answers in it), or all 3 attempts fail, the request is reported as an error (`ClassifyError`). The affected reviews are marked `failed` and can be continued later.
- **No retry for account problems:** a rejected key, no credits, an unknown model or the daily limit would fail again on every attempt, so the run stops at once with a clear message (see "When a limit is reached").

## Using the app

| Step | What to do |
|---|---|
| 1. Schema | Use the sample schema, or upload your own `.json` |
| 2. Data | Pick a sample dataset, or upload a `.csv`. Uploading a new CSV starts classification automatically and replaces the previous dashboard |
| 3. Run | Press **Classify**. If some rows failed or the run stopped early, press **Continue remaining rows** to process only the rows that are not done yet |

The sidebar lets you change the model, an optional fallback model, the number of parallel requests and the requests-per-minute cap.

## File structures

### Input data file (CSV / Excel)

One row per review, with the column names in the first row. The app reads `.csv` files (UTF-8). If your data is in Excel, use **File > Save As > CSV UTF-8 (Comma delimited)** first; `.xlsx` files are not uploaded directly.

Any columns are allowed and **every column is sent to the model**, so put the review text and any helpful context (product, rating, date) in the file. The sample data has three:

| Column | Example | Meaning |
|---|---|---|
| `review_id` | `R0042` | Unique id of the review |
| `product` | `Steel Water Bottle 750ml` | Product the review is about |
| `review_text` | `Lid leaks in my bag, ruined my laptop sleeve` | The review itself |

```csv
review_id,product,review_text
R0042,Steel Water Bottle 750ml,"Lid leaks in my bag, ruined my laptop sleeve"
R0043,Wireless Earbuds X2,"Great sound, battery lasts all day"
```

Text that contains a comma must be wrapped in double quotes (Excel and most tools do this automatically).

### Output file (results CSV)

The downloaded file contains your original columns, then **one new column per schema field** (in the order of the schema), then four tracking columns. With the sample schema:

| Column | Filled by | Example |
|---|---|---|
| `review_id`, `product`, `review_text` | Your input | |
| `sentiment` | Model (`choice`) | `negative` |
| `category` | Model (`choice`) | `quality` |
| `tags` | Model (`list`, joined with commas) | `broke or stopped working, poor quality` |
| `priority` | Model (`choice`) | `high` |
| `has_issue` | Model (`boolean`) | `True` |
| `status` | App | `done` or `failed` |
| `model` | App | Model that produced the answer |
| `latency_s` | App | Seconds the request took (for chat models, shared by the reviews in the same batch) |
| `error` | App | Reason, only when `status` is `failed` |

### Schema file (JSON)

The schema tells the model which fields to fill in. Top level:

| Key | Required | Meaning |
|---|---|---|
| `description` | No (recommended) | One sentence telling the model the task |
| `fields` | Yes | List of fields to extract (at least one) |

Each entry in `fields`:

| Key | Required | Meaning |
|---|---|---|
| `name` | Yes | Name of the field. Must be unique. It becomes the column name in the results |
| `type` | Yes | One of the types below |
| `options` | For `choice`; for `list` with decision models | The allowed values (for a `list`, the possible tags). The model must pick from them |
| `description` | No (recommended) | The question asked about the review, or a hint on how to fill the field |
| `criteria` | No (recommended) | Explains each option so the model can tell them apart: `{ "option": "what it means" }` (for `number`: an ordered list of scale labels) |
| `threshold` | No (default 0.5) | For `list` and `boolean` fields on decision models: how sure (0 to 1) the model must be before a tag or `True` is recorded |

| Type | Chat models return | Decision models (Jev, Mercury Decide) | Stored as |
|---|---|---|---|
| `choice` | One value from `options` | One choice question; the most likely option wins | Text, exactly as written in `options` |
| `list` | A list of short strings | One yes/no question per entry in `options`; tags at or above `threshold` are kept | Text, comma-separated |
| `boolean` | `true` or `false` | One yes/no question; `True` at or above `threshold` | `True` / `False` |
| `number` | A number | Only if `criteria` is an ordered list: a score on that scale | Number |
| `text` | A short sentence | **Not supported** (decision models do not write text); the column stays empty | Text |

Example using the field types:

```json
{
  "description": "Classify an e-commerce product review.",
  "fields": [
    { "name": "sentiment", "type": "choice", "options": ["positive", "negative", "neutral"],
      "description": "What is the overall tone of the review?",
      "criteria": { "positive": "The customer is happy.", "negative": "The customer is unhappy.", "neutral": "Neither." } },
    { "name": "tags", "type": "list", "options": ["late delivery", "poor quality", "good value"], "threshold": 0.5,
      "description": "Which tags apply to the review?" },
    { "name": "mentions_refund", "type": "boolean", "threshold": 0.5,
      "description": "Does the customer ask for a refund?" },
    { "name": "satisfaction", "type": "number", "criteria": ["Very unhappy", "Unhappy", "Neutral", "Happy", "Very happy"],
      "description": "How satisfied is the customer?" },
    { "name": "key_issue", "type": "text", "description": "one short sentence, empty if none (chat models only)" }
  ]
}
```

If the schema is invalid (missing `name`, duplicate names, unknown `type`, `choice` without `options`) the app shows what is wrong before anything is sent to the model. When a decision model is selected, the app also lists any fields it will leave empty (for example a `text` field, or a `list` without `options`). If a chat model answers with a value that is not allowed (for example `sentiment = "angry"` when it must be positive, negative or neutral), that review is marked `failed` and can be retried. A complete working schema is in `schemas/review_schema.json`.

## Sample data

The app ships with two dummy datasets: `data/reviews.csv` (100 hand-written reviews) and `data/reviews_1000.csv` (1,000 reviews, used for the speed test). The 1,000-review file is created by `generate_data.py`: it keeps the 100 hand-written reviews and generates the other 900 from short sentence banks for 8 products.

To get a realistic mix of opinions, each generated review is given a target tone picked at random:

```python
tone = random.choices(["pos", "neg", "neu"], weights=[45, 35, 20])[0]
```

| Tone | Weight | Typical review |
|---|---|---|
| Positive | 45% | "Battery lasts all day and the case charges fast." |
| Negative | 35% | "The lid leaks when it's in my bag." |
| Neutral | 20% | "Average running shoes." |

So about 45 out of 100 generated reviews should come out positive, 35 negative and 20 neutral. Then, to make them look less repetitive:

- About 30% of positive and negative reviews get a second sentence of the same tone.
- Roughly 4 in 10 reviews get an extra remark about delivery, support or price, and some negative reviews end on a positive note ("But delivery was quick"), which makes them mixed.
- About 8% are written in lowercase without a full stop, and about 5% end with "!!".
- A fixed random seed (`random.seed(7)`) means re-running the script gives the same file.

The target tone is only used to generate the text. It is not saved in the file, so it is not a "correct answer" to score the model against, and the model's sentiment counts will only be roughly in line with 45 / 35 / 20 (the 100 hand-written reviews and mixed reviews shift them a little).

## Models, speed and cost

| Model | Type | Cost | Notes |
|---|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b:free` (default) | Chat model | Free | Reviews are sent in batches (10 by default, up to 25 per request). Free-tier limits apply (below). Slow: about 50 to 75 seconds per request. Tested: 25 of 25 reviews classified in one request |
| `typesafe/jev-1.13` | Decision model (Jev) | Billed on input tokens only; output tokens are free | One request per review. No free-tier request cap |
| `inception/mercury-decide:free` | Decision model | Free | Free-tier limits apply (below). In our tests from Pakistan it answered with a regional access block (HTTP 403), so it could not be used from there |
| `liquid/lfm-2.5-2.6b:free`, `cohere/north-mini-code:free` | Chat models | Free | Did not return valid JSON for a batch in our tests, so not recommended |
| `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free` | Chat models | Free | Answered "too many requests" for every call when tested, so not reliable at the moment |

**Free setup (default), measured:** with the sample schema, 25 reviews in one request took 50 to 75 seconds and all 25 were classified. At 25 reviews per request, 1,000 reviews need 40 requests; at 10 per request they need 100. With 4 parallel requests 1,000 reviews take roughly 10 to 15 minutes.

**Jev, measured** with the sample schema (5 classification fields, 14 possible tags, so 18 questions per review), 4 parallel requests:

| Measure | Result |
|---|---|
| Time per request (latency) | about 0.9 to 1.2 seconds |
| Throughput | about 3 to 5 reviews per second |
| Cost | about $0.06 per 1,000 reviews (about $0.00006 per review) |

Cost depends on how many questions the schema has and how long the reviews are, so measure on your own data. The app shows the real cost of every run (**Cost** box) and the cost per 1,000 reviews. 1,000 reviews take roughly 4 to 6 minutes with 4 parallel requests; more parallel requests make it faster.

### Free-model limits

Free models (names ending in `:free`) have request limits set by OpenRouter, not by this app:

| OpenRouter account | Requests per minute | Requests per day |
|---|---|---|
| Free (under $10 credits purchased) | 20 | 50 |
| With at least $10 credits purchased | 20 | 1,000 |

The limits count **requests**, not tokens or reviews. A free decision model needs one request per review, so it is limited to 20 reviews per minute and 50 per day. A free chat model can carry several reviews per request, which is why the default setup works within the free limits. When a `:free` model is selected the bottom-right corner of the app shows the ceiling (for example "200 categorizations per minute is the limitation of our prototype" at 10 reviews per request), and the sidebar shows **Free requests left today** (the counter resets at 00:00 UTC). The app refuses a run that needs more requests than are left, with a clear message.

**Budget for a 1,000-review test on a free account (50 requests per day):** at 25 reviews per request one full run uses 40 requests, so only one full run fits in a day and about 10 requests are left for small tests. At the default 10 per request a full run needs 100 requests, which does not fit in one day on a free account.

### Batching (chat models only)

**Why batching?** For chat models the free-model limit is on *requests* (20 per minute), not on reviews. Sending 10 reviews in one request means 1,000 reviews need about 100 requests instead of 1,000. If one record in a batch comes back invalid, only that record is marked `failed`; the other 9 are kept.

Because each request carries 10 reviews, the limits translate to:

| | Without batching | With batching (10 per request) |
|---|---|---|
| Requests for 1,000 reviews | 1,000 | about 100 |
| Fastest possible time at 20 requests/min | about 50 minutes | about 5 minutes |
| Reviews per day, free account | 50 | about 500 |
| Reviews per day, with $10 credits | 1,000 | about 10,000 |

With a free chat model the bottom-right message reads "200 categorizations per minute" (20 requests per minute x 10 reviews). It is a ceiling; in practice each request also takes a few seconds to answer, so the real rate is lower. Decision models cannot be batched because each request is about one review.

### When a limit is reached

The app never shows a technical error screen for limits. If OpenRouter refuses to continue, the run **stops early**, everything already classified is kept, and a message explains what happened. Press **Continue remaining rows** afterwards to carry on from where it stopped (from the command line, run the same command again).

| Situation | What you see | What to do |
|---|---|---|
| Daily free-request limit reached | "The daily limit for free requests has been reached. It resets at 00:00 UTC..." | Wait for the reset, or buy $10 of credits to raise it to 1,000 per day |
| Out of credits (paid model) | "This OpenRouter account has run out of credits..." | Add credits on OpenRouter, then continue |
| Too many requests per minute | The app waits and retries by itself; if it keeps failing the affected rows are marked `failed` with a message | Lower **Max requests per minute** in the sidebar and continue |
| API key rejected | "OpenRouter rejected the API key..." | Check the key in the settings file or app secrets |
| Model name unknown or unavailable | "The model '...' was not found..." (a fallback model is tried first if one is set) | Check the model name in the sidebar |
| No internet / provider error | Affected rows are marked `failed` with the reason | Continue remaining rows once the connection is back |
| Unreadable CSV or schema | A short message asking for a CSV UTF-8 file or a valid schema | Fix the file and upload it again |
| Anything unexpected | A short message, with details hidden in an expandable "Technical details" box | Try again |

### What the speed numbers mean

- **Request latency (avg / p95)** is how long the model takes to answer one request. It is a fair measure of model speed, because waiting for the rate limit is not counted. p95 means 95% of requests were faster than that value.
- **Total time** and **Records / sec** depend on the number of parallel requests and, on free models, are capped by the limits above, so they describe this setup, not the model's maximum throughput.
- **Cost** is the amount the model charged for the run, as reported by OpenRouter (decision models only).
- For a true throughput test, use a paid model (no platform request cap) and raise **Parallel requests**.

## Run it locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your values:

```
OPENROUTER_API_KEY=your-key
PRIMARY_MODEL=nvidia/nemotron-3-super-120b-a12b:free
FALLBACK_MODEL=
MAX_ROWS=1000
APP_PASSWORD=
```

Never commit `.env`. `MAX_ROWS` caps rows per run and `APP_PASSWORD` (optional) adds an access code, both useful on a hosted app that uses a shared key. `FALLBACK_MODEL` is an optional second model tried when the first one fails.

Quick check from the terminal (5 reviews), then start the app:

```powershell
python main.py --limit 5
streamlit run streamlit_app.py
```

Command-line options: `--data`, `--schema`, `--out`, `--model`, `--fallback`, `--limit`, `--workers`, `--rpm` (default 18; use `0` for a paid model), `--batch` (default 10, up to 25; chat models only).

## Files

In the order data moves through the project:

```
data + schema  ->  streamlit_app.py / main.py  ->  runner.py  ->  classifier.py  ->  OpenRouter  ->  results
```

| # | File | One-line purpose |
|---|---|---|
| 1 | `data/reviews.csv` | 100 hand-written reviews: the small test set and the base of the big one |
| 2 | `generate_data.py` | Expands those 100 into 1,000 realistic dummy reviews for the speed test |
| 3 | `data/reviews_1000.csv` | The 1,000-review dataset used to test speed |
| 4 | `schemas/review_schema.json` | Tells the model which fields to extract and which values are allowed |
| 5 | `streamlit_app.py` | The web app: choose or upload schema and data, start a run, show results, charts and speed |
| 6 | `main.py` | Command-line version of the app, for quick tests and batch runs |
| 7 | `runner.py` | Sends the reviews in parallel (batches of 10 for chat models, one per request for decision models), respects the rate limit, records status, speed and cost |
| 8 | `classifier.py` | Turns the schema into questions or a prompt, calls OpenRouter, and checks every answer against the schema |
| 9 | `data/classified.csv` | Output of `main.py`: your data plus the model's fields and a `status` per row |

Supporting files:

| File | One-line purpose |
|---|---|
| `requirements.txt` | The Python libraries to install |
| `.env` / `.env.example` | Your API key and settings (`.env` is private and never shared; `.env.example` is the empty template) |
| `.gitignore` | Keeps `.env` and other private files out of version control |
| `README.md` | This guide |

## Known limitations

- On the free setup a free account gets 50 requests per day, so one full 1,000-review run (40 requests at 25 reviews per request) fits in a day but leaves little room for repeat tests. Buying $10 of credits once raises the limit to 1,000 requests per day.
- The free Nemotron model is slow (50 to 75 seconds per request) and, as a free shared model, can be busy or rate limited at times. The app retries and then marks the affected reviews `failed`, and **Continue remaining rows** picks them up again.
- Chat models can return a value outside the allowed options; such reviews are marked `failed`, not guessed.
- Decision models (Jev, Mercury Decide) answer choices, yes/no questions and scores. They do not write free text, so `text` fields (such as a one-sentence summary of the problem) stay empty; use a chat model for those.
- A decision model needs one request per review and cannot be batched, so on a free model the limits above allow 20 reviews per minute and 50 (or 1,000 with credits) per day.
- `inception/mercury-decide:free` was not reachable from the developer's location in our tests (regional HTTP 403). Jev works there and costs about $0.06 per 1,000 reviews with the sample schema.
- Tags and `True`/`False` answers depend on the `threshold` (default 0.5). The best value differs per tag and should be tuned on a hand-labelled sample of 100 to 200 reviews; this has not been done for the sample schema.
- Model output quality varies. Accuracy has not been measured against a labelled dataset.
- Results live in the browser session; download the CSV before refreshing the page.
- Flat schemas only (no nested fields).

# Review Classifier (prototype)

Turns raw product reviews into structured data. The reviews live in a **Google Sheet**, an AI model on OpenRouter classifies and tags each one, the results are **written back into the same Google Sheet**, and the page shows a summary with charts that can be downloaded as a PDF.

The default model is **NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b:free`), a free chat model, so the prototype runs at no cost. It can be switched to **Jev** (`typesafe/jev-1.13`), a *decision model* that answers typed questions and returns a probability for each answer. Jev is fast and cheap but not free (see "Models, speed and cost").

## How it works

```
Google Sheet "Data"  ->  app  ->  AI model (OpenRouter)  ->  Sheet tabs "Categorization" + "Summary"  +  summary page / PDF
```

1. The customer puts the reviews in a tab named **Data** of a Google Sheet, sets the sheet's General access to *Anyone with the link* (Viewer is enough), pastes the link into the page and presses **Load / refresh data**. (Writing results back into the sheet is available when the administrator connects it, see "Connecting the app to Google Sheets"; for now customers download their results instead.)
2. The app reads the **Data** tab, classifies each review with a **fixed** set of questions (nothing to upload or configure), and checks every answer (for example `sentiment` must be one of the allowed options). Anything invalid is marked `failed` instead of being guessed.
3. When the run finishes, the app empties and refills two tabs in the same file:
   - **Categorization**: every review with its classification next to it.
   - **Summary**: an overview (reviews, classified, failed) and a small table per field (for example how many reviews are positive, negative, neutral).
4. The page shows the same results as a table, filters and charts. The charts can be downloaded as a **PDF**.

Example row in the **Categorization** tab:

```
review_id | product                  | review_text                                  | sentiment | category | tags         | priority | has_issue | status
R0042     | Steel Water Bottle 750ml | Lid leaks in my bag, ruined my laptop sleeve | negative  | quality  | leaks, ...   | high     | True      | done
```

**Refresh.** Every press of **Load / refresh data** reads the **Data** tab again and truncates and rewrites **Categorization** and **Summary**. To save requests, reviews that are unchanged since the last run (same row content, status `done` in Categorization) are not sent to the model again; new and changed reviews are. If a run stops halfway (rate limit, closed browser) press **Continue remaining reviews**, or refresh again. **Process all reviews again** redoes everything.

## Using the app

### 1. Prepare the Google Sheet

Create a **Data** tab. The **Categorization** and **Summary** tabs are only needed when writing back into the sheet is connected (otherwise the Excel file contains all three as sheets). The *About the app* page repeats these instructions under "Good to know":

| Tab | Content |
|---|---|
| **Data** | The reviews, always in the same format (below) |
| **Categorization** | Empty. The app fills it |
| **Summary** | Empty. The app fills it |

The **Data** tab has these columns in the first row, one review per row (capital letters in the header do not matter, extra columns are kept as context, rows without a `review_text` are skipped):

| review_id | product | review_text |
|---|---|---|
| R0042 | Steel Water Bottle 750ml | Lid leaks in my bag, ruined my laptop sleeve |
| R0043 | Wireless Earbuds X2 | Great sound, battery lasts all day |

The **Data** tab is only read, never changed. If the Categorization or Summary tab is missing, the app creates it.

Set the sheet's General access to **Anyone with the link** with the role **Editor** (Share button in Google Sheets). With Option B below you can instead share it with the service account email shown on the page. A sheet that is only *Viewer* can be read, but the results cannot be written back.

If the Data tab has an extra column with the same name as a result field (for example `category`), the app keeps your column and calls it `category_original`.

### 2. What gets classified

The classification is fixed, so the customer never uploads a schema. Each review gets:

| Field | Type | Values |
|---|---|---|
| `sentiment` | choice | positive, negative, neutral |
| `category` | choice | quality, shipping, price, packaging, size, fit, customer service, performance, design, other |
| `tags` | tags (several) | 14 tags such as "late delivery", "poor quality", "good value" |
| `priority` | choice | low, medium, high |
| `has_issue` | yes/no | True / False |

The administrator changes these in `defaults.py` (one place, applies to every customer).

### 3. Run and read the results

Paste the link and press **Load / refresh data**. Processing starts automatically and the results are written to the sheet when it finishes (if writing is connected, see below). A short message explains that this is a prototype and may take a little longer on a free model. Afterwards you see:

- **Four insight cards**: share of positive reviews, reviews with a problem, the most discussed category and the number of high priority reviews.
- **Speed numbers** (processed, failed, requests used, total time, reviews per second, request time).
- **Download your results** (a dark card above the tabs): **Download Excel file** gives `review_summary.xlsx` with three sheets, *Data* (the reviews as loaded), *Categorization* (every review with its answers) and *Summary* (totals and a table per field); **Download charts (PDF)** gives `review_summary.pdf` with the charts. Excel keeps the data editable and filterable, the PDF keeps the charts looking the same everywhere.
- Two tabs: **Summary & charts** (interactive charts, hover for exact numbers) and **Classified reviews** (a search box for words such as "refund", click-filters for sentiment, category and priority, and the table).
- **Open my Google Sheet** opens the file, **Write results to the sheet again** repeats the write-back (only when writing is connected), **Process all reviews again** redoes everything and **Continue remaining reviews** carries on after an early stop.

### The pages (left panel)

| Button | What it shows |
|---|---|
| **Use the App for free** | Connect a sheet, run, results |
| **About the app** | A short guide in plain English ("Good to know", what is analysed, how to read the results) and rotating testimonials at the bottom |
| **Messages** | An "under construction" page with a picture (marked SOON) |
| **Premium plans** | A "coming soon" page with a picture (marked SOON) |

On the first visit a welcome pop-up appears over a blurred page (once per visit). It offers **Show me around (1 minute)**, a 4-step guided tour (paste the link, let the app read the sheet, press Load / refresh data, see and download the results) with Back, Next, Skip and Finish buttons, or **Skip**. The tour can be opened again at any time with **Take the 1-minute tour** on the *Use the App for free* and *About the app* pages. The pop-up shows a number of teams that use the app: set the real number with `USERS_COUNT` in `.env` (the default `1,200` is a placeholder) and switch the pop-up off with `WELCOME_POPUP=0`. The testimonials are sample text in `TESTIMONIALS` in `streamlit_app.py`; replace them with real quotes before launch. The tour steps are in `TOUR_STEPS` in the same file.

## Connecting the app to Google Sheets (once, by the administrator)

Google does not allow anonymous writes, so saving results into the sheet needs one account that does the writing. **Without any setup the app works in read-only mode, which is what customers get for now**: it reads a sheet that is open to *Anyone with the link* (Viewer is enough), classifies the reviews, and shows the results and charts on the page, with the Excel and PDF downloads, but it does not write the Categorization and Summary tabs. To also write into the sheet use one of these two options; the page switches on writing by itself when either is configured.

### Option A (prototype, no Google Cloud, no key): Apps Script web app

The customer only pastes a link; their sheet must have General access **Anyone with the link: Editor**.

1. Open any Google Sheet with your own Google account, then **Extensions > Apps Script**.
2. Paste the contents of `apps_script/Code.gs`, and change `TOKEN` to a secret of your own.
3. **Deploy > New deployment > Web app**, *Execute as: Me*, *Who has access: Anyone*. Authorise when asked and copy the web app URL.
4. Set two values (in `.env` locally, in Secrets on Streamlit Cloud):
   ```
   APPS_SCRIPT_URL=https://script.google.com/macros/s/.../exec
   APPS_SCRIPT_TOKEN=the-secret-from-step-2
   ```

The script runs as you, so it can open any sheet that your account can edit (including sheets shared as Anyone with the link: Editor). The token stops other people from using the URL. For a production setup use Option B. If `APPS_SCRIPT_URL` is set it is used and any service account key is ignored.

**A customer's own Google connection (switched off in the page for now).** The page used to have an optional *Advanced* box where a user could paste the address and password of their own deployment of `apps_script/Code.gs`. It was removed so that customers only see the sheet link. The code behind it is still there (`read_data`, `write_categorization` and the other functions in `sheets.py` accept an optional `script=(address, password)`), so it can be shown again later. The address must start with `https://script.google.com/`.

### Option B: service account (key)

1. In Google Cloud Console create a project and enable the **Google Sheets API**. (The Drive API is not needed.)
2. Create a **service account** and add a **JSON key** to it. Keep the file private; never commit it.
3. Customers share their Google Sheet with the service account's `client_email` as **Editor** (the page displays this address), or set General access to Anyone with the link: Editor.
4. Give the app the key:
   - **Streamlit Cloud:** in the app's Secrets add the whole JSON as one value in triple single quotes:
     ```toml
     GOOGLE_SERVICE_ACCOUNT_JSON = '''{ "type": "service_account", ... }'''
     ```
   - **Locally:** save the file as `service_account.json` in the project folder (it is gitignored) and put `GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json` in `.env`.

The app only asks for the Sheets scope (`https://www.googleapis.com/auth/spreadsheets`). In both options results are written as plain text, so text that looks like a formula is never executed. If neither option is configured the app runs in read-only mode (see above) and the downloads are the way to get the results.

## File structures

### Categorization tab

Your original columns from **Data**, then one column per field, then tracking columns:

| Column | Filled by | Example |
|---|---|---|
| your columns | You | `review_id`, `product`, `review_text` |
| `sentiment`, `category`, `priority` | Model (`choice`) | `negative` |
| `tags` | Model (`tags`, comma-separated) | `broke or stopped working, poor quality` |
| `has_issue` | Model (`yes/no`) | `True` |
| `status` | App | `done` or `failed` |
| `model`, `error` | App | Model used, reason when `failed` |

### Summary tab

| Block | Content |
|---|---|
| Overview | Reviews, Classified, Failed, Not processed yet, and when it was last updated |
| One table per field | Value, number of reviews, share of classified reviews (for `tags`: every tag found, most common first) |

### Field types

| Type | Chat models return | Decision models (Jev, Mercury Decide) |
|---|---|---|
| `choice` | One value from the options | One choice question; most likely option wins |
| `tags` | A list from the options | One yes/no question per option; tags at or above the threshold are kept (default 0.5) |
| `yes/no` | true / false | One yes/no question; true at or above the threshold |
| `text` | A short sentence | Not supported (the column stays empty) |

The command-line tool (`main.py`) and the code accept the same settings as a JSON schema (`description` plus a list of `fields` with `name`, `type`, `options`, `description`, `criteria`, `threshold`). This is for developers only; customers never need it.

## Models, speed and cost

| Model | Type | Cost | Notes |
|---|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b:free` (default) | Chat model | Free | Reviews are sent in batches (25 per request by default). Free-tier limits apply (below). Slow: about 50 to 75 seconds per request. Tested: 25 of 25 reviews classified in one request |
| `typesafe/jev-1.13` | Decision model (Jev) | About $0.06 per 1,000 reviews with 18 questions | One request per review, about 0.9 to 1.2 s each. No free-tier request cap |
| `inception/mercury-decide:free` | Decision model | Free | In our tests from Pakistan it answered with a regional access block (HTTP 403) |
| `liquid/lfm-2.5-2.6b:free`, `cohere/north-mini-code:free` | Chat models | Free | Did not return valid JSON in our tests; not recommended |
| `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free` | Chat models | Free | Answered "too many requests" for every call when tested |

**Free setup:** at 25 reviews per request, 1,000 reviews need 40 requests; with 4 parallel requests this takes roughly 10 to 15 minutes.

**Jev:** about 3 to 5 reviews per second with 4 parallel requests, so 1,000 reviews take roughly 4 to 6 minutes. Cost depends on the number of questions and review length; the page shows the real cost of each run.

### Free-model limits

Set by OpenRouter, not by this app, and counted in **requests**:

| OpenRouter account | Requests per minute | Requests per day |
|---|---|---|
| Free (under $10 credits purchased) | 20 | 50 |
| With at least $10 credits purchased | 20 | 1,000 |

A free chat model carries several reviews per request, so one full 1,000-review run (40 requests) fits in a day on a free account but leaves about 10 requests for other tests. A free decision model needs one request per review, so it allows only 20 reviews per minute and 50 per day. The app checks the remaining daily requests before a run and refuses one that cannot finish, with a clear message. The counter resets at 00:00 UTC.

### When a limit is reached

The app never shows a technical error screen. If OpenRouter refuses to continue, the run **stops early**, everything already classified is kept (and written to the sheet), and a message explains why. Press **Continue remaining reviews** afterwards.

| Situation | What you see | What to do |
|---|---|---|
| Daily free-request limit | "The daily limit for free requests has been reached. It resets at 00:00 UTC..." | Wait for the reset, or buy $10 of credits |
| Out of credits (paid model) | "This OpenRouter account has run out of credits..." | Add credits, then continue |
| Too many requests per minute | The app waits and retries; rows that keep failing are marked `failed` | Press **Continue remaining reviews** |
| API key rejected | "OpenRouter rejected the API key..." | Administrator: check the key |
| Sheet not editable / wrong link | A message saying to check the link and set General access to Anyone with the link: Editor | Fix the sharing, check the link |
| Data tab missing or columns wrong | A message naming the missing tab or columns | Create the tab `Data` with review_id, product, review_text |

## Run it locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file:

```
OPENROUTER_API_KEY=your-key
PRIMARY_MODEL=nvidia/nemotron-3-super-120b-a12b:free
FALLBACK_MODEL=
MAX_ROWS=1000
APP_PASSWORD=
APPS_SCRIPT_URL=
APPS_SCRIPT_TOKEN=
# or, instead of the two lines above: GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

Never commit `.env` or `service_account.json`. `MAX_ROWS` caps rows per run, `APP_PASSWORD` (optional) adds an access code for a hosted app, `FALLBACK_MODEL` is an optional second model, `USERS_COUNT` is the number shown in the welcome pop-up and `WELCOME_POPUP=0` turns the pop-up off.

Optional tuning (defaults in brackets): `WORKERS` (4) parallel requests, `MAX_REQUESTS_PER_MIN` (18 for free models, otherwise 0 = no limit), `REVIEWS_PER_REQUEST` (25, chat models only). On Streamlit Cloud put the same names in the app's Secrets (top-level keys, values in quotes).

```powershell
streamlit run streamlit_app.py
```

Command line (CSV and a JSON schema file, developers only): `python main.py --data reviews.csv --schema schema.json --limit 5`. Options: `--data`, `--schema`, `--out`, `--model`, `--fallback`, `--limit`, `--workers`, `--rpm`, `--batch`.

## Files

| File | Purpose |
|---|---|
| `streamlit_app.py` | The web page: load the sheet, run, show results and charts, write back, PDF download |
| `sheets.py` | Google Sheets: read the Data tab, write the Categorization and Summary tabs, friendly errors |
| `report.py` | Summary numbers and charts: the Summary tab content, the PDF and the Excel file |
| `apps_script/Code.gs` | The Google Apps Script web app used to write into a sheet without a Google key |
| `assets/hero.svg` | The illustration behind the page title. To use your own picture, add `assets/hero.png` (or `.jpg`/`.webp`); it then replaces the illustration |
| `assets/welcome_bg.svg`, `assets/soon_messages.svg`, `assets/soon_premium.svg`, `assets/tour_1.svg` to `tour_4.svg` | Pictures for the welcome pop-up, the guided tour and the Messages and Premium plans pages |
| `defaults.py` | The built-in classification settings |
| `runner.py` | Runs the reviews in parallel, respects the rate limit, records status, speed and cost |
| `classifier.py` | Builds the prompt or questions, calls OpenRouter, checks every answer |
| `main.py` | Command-line version for quick tests |
| `requirements.txt`, `.streamlit/config.toml` | Libraries and light theme |

## Known limitations

- Free accounts get 50 requests per day, so repeat full runs need a new day or $10 of credits.
- The free Nemotron model is slow (50 to 75 seconds per request) and, as a shared free model, can be busy; affected reviews are marked `failed` and picked up by **Continue remaining reviews**.
- Chat models can return a value outside the allowed options; such reviews are marked `failed`, not guessed.
- Decision models cannot write free text, so `text` fields stay empty; they also need one request per review.
- Google does not allow anonymous writes: the app needs the Apps Script web app or a service account (see "Connecting the app to Google Sheets"). With the Apps Script option every customer sheet must be editable by anyone with the link, and that option has not been tested against real Google yet.
- Thresholds (default 0.5) and the built-in categories have not been tuned on a hand-labelled sample, and accuracy has not been measured.
- The **Categorization** and **Summary** tabs are rewritten on every run, so manual edits or extra columns added there are lost. Add your own analysis in another tab.
- Flat settings only (no nested fields). Results on the page stay while it is open and are also saved in the sheet.

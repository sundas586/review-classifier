# Data Quality Report: reviews in the "Data" tab

- **Source:** the public Google Sheet `1MOZK1XD...K1QC_lQ`, tab **Data** (read-only, no changes made)
- **Date of analysis:** 17 October 2026
- **Size:** 1,000 reviews, 3 columns (`review_id`, `product`, `review_text`)
- **How it was measured:** the sheet was read without login and checked with a script (counts, patterns, duplicates). "Positive / negative cues" below are a rough word list, not the AI model.

## 1. Summary

**Verdict: the file is clean and ready to use for the demo.** The structure is perfect and there is only one real defect (a broken character encoding in one review). The main limitation is not an error but the *nature* of the data: it is very repetitive, so it looks generated and will make the classification look easier than it would be on real customer reviews.

| Area | Result | Score |
|---|---|---|
| Structure (columns, blank rows, header) | No problems | Excellent |
| Completeness (empty values) | 0 empty cells | Excellent |
| ID quality (unique, format, gaps) | 1,000 unique IDs, R0001 to R1000, no gaps | Excellent |
| Product values (spelling, spaces, case) | 8 clean product names | Excellent |
| Text validity (encoding, HTML, links, personal data) | 1 broken encoding | Good |
| Uniqueness of the text | 0 exact copies, but 14.9% repeat once punctuation and capitals are ignored | Fair |
| Variety and realism | Short, repetitive, only 237 different sentences | Limited |

## 2. Structure and completeness

| Check | Result |
|---|---|
| Rows | 1,000 |
| Columns | 3 (`review_id`, `product`, `review_text`), exactly the format the app expects |
| Blank rows | 0 |
| Rows with a different number of columns | 0 |
| Spaces around headings | none |
| Empty values | `review_id` 0, `product` 0, `review_text` 0 |

## 3. Identifiers (`review_id`)

| Check | Result |
|---|---|
| Unique IDs | 1,000 of 1,000 (0 duplicates) |
| Format `R` + 4 digits | 1,000 of 1,000 |
| Range | R0001 to R1000, in order, with no missing numbers |

## 4. Products (`product`)

Eight products, evenly spread, with no spelling, spacing or capital-letter variants.

| Product | Reviews |
|---|---|
| Urban Commuter Backpack 20L | 133 |
| Lumio LED Desk Lamp | 130 |
| Wireless Earbuds X2 | 129 |
| Steel Water Bottle 750ml | 129 |
| BrewMate Coffee Maker | 129 |
| Grip Yoga Mat | 118 |
| ShieldFit Phone Case | 117 |
| Stride Running Shoes | 115 |

The review text matches the product it belongs to (no battery comments on a yoga mat, for example).

## 5. Review text (`review_text`)

### Length

| Measure | Characters | Words |
|---|---|---|
| Shortest | 2 | 1 |
| Average | 66.7 | 12.0 |
| Median | 66 | 12 |
| Longest | 136 | 24 |

Real customer reviews are often much longer. This data has no review over 136 characters, so long texts are **not tested**.

### Problems found

| Check | Count | Comment |
|---|---|---|
| **Broken character encoding** | **1** | **R0125** reads `Muy buena calidad, llegÃ³ rÃ¡pido.` and should be `Muy buena calidad, llegó rápido.` The file was probably saved or copied with the wrong encoding. This is the only real defect. |
| Not in English | 1 | The same review (R0125, Spanish). A useful test of how the AI handles other languages, once the encoding is fixed. |
| Very short (under 20 characters) | 10 | For example `ok`, `Does the job.`, `It's okay.` These carry little information (see R0322 `ok`). They are good edge cases, not errors. |
| Hidden spaces, double spaces, line breaks | 0 | Clean |
| HTML tags, links, e-mail addresses, phone numbers | 0 | No personal data found |
| Text starting with `=`, `+`, `-`, `@` (spreadsheet formula risk) | 0 | Safe |
| ALL CAPS, or no letters at all | 0 | Clean |

### Style differences (not errors, but realistic noise)

| Pattern | Count |
|---|---|
| Starts with a small letter and has no full stop at the end | 121 |
| Ends with `!!` or more | 88 |

## 6. Repetition (the main finding)

| Measure | Result |
|---|---|
| Exact copies of a review | 0 |
| Copies after ignoring capitals and punctuation | **149 reviews (14.9%)**, in 129 groups (278 reviews belong to a repeated group) |
| Different sentences in total | **237** (for 1,917 sentences written) |
| Reviews made only of sentences that appear elsewhere | **900 of 1,000** |
| Reviews that contain a sentence found nowhere else | 100 of 1,000 |

The most repeated sentences, each used 32 to 47 times:

| Sentence | Times |
|---|---|
| "Delivery was quick." | 47 |
| "Arrived a day early and well packed." | 47 |
| "Support answered within an hour." | 44 |
| "Great value for the money." | 42 |
| "Cheaper than the competition." | 41 |
| "Overpriced for what you get." | 38 |
| "The box arrived crushed." | 36 |
| "The seller replaced it without any fuss." | 32 |

**What this means:** exactly 900 reviews are built from a small set of ready-made sentences, and exactly 100 are individual. This is the pattern of a generated test file (100 hand-written reviews plus 900 generated ones). It is fine for showing how the app works. It is **not** a fair test of accuracy, because the AI sees the same sentences again and again.

## 7. Content balance (rough, from word cues)

| Cue found in the review | Reviews |
|---|---|
| Only positive words | 272 |
| Only negative words | 234 |
| Both (mixed reviews) | 20 |
| Neither (neutral or no clear word) | 474 |

Topics mentioned (a review can mention several): price or value 257, delivery or shipping 231, quality or durability 118, support 140, size or fit 105, battery 40.

This is a rough guide only. The real split will come from the AI classification. The data has a healthy mix of positive, negative and neutral reviews, and a small number of mixed ones, which is good for testing.

## 8. Data that is missing (limits of what can be analysed)

- **No star rating or date column,** so the AI results cannot be compared with a rating, and trends over time cannot be shown.
- **No customer or order information.**
- **No correct answers (labels)** for sentiment, category and priority, so the **accuracy of the AI cannot be measured yet.**

## 9. Run quality (from your earlier screenshot of a run)

This section comes from the screenshot of your own run, not from a new analysis, so please treat the numbers as indicative.

| Measure | Value |
|---|---|
| Reviews processed | 925 of 1,000 |
| Failed | 75 (7.5%) |
| Requests used | 40 (25 reviews per request) |
| Total time | about 26 minutes (1,569 seconds) |

A failure rate of 7.5% is normal for a free shared model, which sometimes returns an answer the app cannot read. The failed reviews are not guessed: they are marked `failed` and can be retried with **Continue remaining reviews**.

## 10. Recommendations

| Priority | Action |
|---|---|
| High | Fix R0125: retype `Muy buena calidad, llegó rápido.` in the sheet. When exporting files, save as **UTF-8** so accents survive. |
| High | For a **real accuracy test**, add 100 to 200 real customer reviews, or hand-label a sample (sentiment, category, priority) to compare with the AI. |
| Medium | Add some longer reviews (2 to 5 sentences) and a few more languages, to test the app on realistic text. |
| Medium | Keep the very short reviews (`ok`, `Does the job.`). They show how the AI deals with little information. |
| Low | Optionally add `rating` and `date` columns in the future for richer charts. |
| Low | When using this data for numbers shown to a client, mention that part of it is generated, so the counts are for demonstration. |

## 11. Final verdict

- **Use for the demo and the walkthrough video:** yes. Clean, correct format, no personal data.
- **Use to prove accuracy:** not yet. It is too repetitive and has no labels.
- **Effort to be fully clean:** one cell to correct (R0125).

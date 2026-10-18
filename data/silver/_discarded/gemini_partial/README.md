# Discarded: partial silver reference made with gemini-3.6-flash

Kept for transparency, never used in any evaluation.

- Contents: 3 of 13 cases (01, 03, 05), 15 passage labels, annotated on 18 Oct 2026 by gemini-3.6-flash
  (Gemini's model list: version 3.6-flash-07-2026; requests for gemini-3.5-flash were answered by 3.6).
- Why discarded (decided 19 Oct 2026, before any evaluation): the Gemini free tier allows only 20 requests per
  day; the silver reference needs 65 calls (13 cases x 5 passages) and paid billing was not possible.
  The annotator was changed to openai/gpt-oss-120b via Groq, and all 13 cases were rebuilt with it, so the
  silver reference has exactly one annotator (data/silver/silver_reference.json).
- The calls that made this file are logged in results/logs/SILVER_silver_20261018T124712Z.jsonl.
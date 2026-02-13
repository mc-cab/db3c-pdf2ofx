You are DocOps. DO NOT change code. Only add/update documentation files.

Goal: document the test suite so a maintainer can understand what each test file covers and how to run tests efficiently, without deep dev jargon.

Context:
- Repo: db3c-pdf2ofx
- We currently have ~8 test files.
- Tests are regularly updated; we want a durable, easy-to-skim catalog.

Deliverables (docs only):
1) Create `docs/TESTING.md` (primary reference)
2) Create/update `tests/README.md` (catalog/map)
3) Add a short section in `RUNBOOK_MAINTAINER.md` linking to `docs/TESTING.md` and listing any known caveats (e.g. the pypdfium2/Mindee integration crash), without duplicating the full catalog.

Style constraints:
- Audience: accounting-firm maintainers + dev (mixed). Keep it clear and readable.
- Avoid heavy technical jargon. Use short paragraphs + tasteful bullets.
- Be precise, not fluffy. Explain “what it verifies” and “how it verifies” in plain language.

Content requirements:

### docs/TESTING.md
Include sections:
- Purpose of the test suite (what we’re protecting)
- How to run tests:
  - full suite
  - single file
  - keyword selection
  - any markers/slow tests if present
- Test layers:
  - unit vs CLI-ish vs integration (if applicable)
  - what is mocked vs what touches real files/network
- Fixtures & patterns:
  - where fixtures live
  - how they’re used at a high level
- Known issues / exclusions:
  - e.g. `test_mindee_integration.py` may crash in some Windows envs (pypdfium2)
  - what to do if it happens (skip command / marker / env note)

### tests/README.md
Make a table catalog:
- Test file name
- “What it covers” (1–2 lines)
- “Key scenarios” (2–5 bullets)
- “Notes” (mocking, env constraints, why it exists)

Also include:
- A tiny “Where to add new tests” guidance (naming convention, where to put fixtures)

Process:
- Scan the `tests/` directory to list all test modules.
- For each module, infer intent by reading docstrings/test names/fixtures used.
- Do NOT invent behaviors; if unclear, state “(needs clarification)” briefly.

Output:
- Provide the full contents for each doc file in Markdown.
- Also provide a short summary of what you changed (file list + 3–6 bullets).
- Do NOT commit, do NOT create a PR.

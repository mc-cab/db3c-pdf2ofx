You are Codex. Implement a devtool POC named “pdf2ofx” in an existing repo.

ABSOLUTE RULES (do not violate)
- Do NOT implement any unrelated refactor. No coupling to other code outside this devtool.
- Do NOT add feature creep. Only implement what is explicitly required below.
- Do NOT hand-write an OFX SGML writer. OFX emission MUST be done via the `ofxtools` library.
- Target output format: OFX2 (real XML). Fallback: OFX1 via ofxtools.
- UX stack is mandatory: Typer + Rich + InquirerPy (with “q” shortcut to quit everywhere).
- No path-pasting UX: operator drops PDFs into input/ folder. Tool detects them.
- No sensitive transaction dumps to console. Only summary counts + filenames + stages.

PRE-READ REQUIRED (must do before coding)
1) Read Mindee docs (API + Python examples). You must understand:
   - How to send a document using polling
   - How to fetch result fields / JSON
   Docs: https://docs.mindee.com/
   In particular, the “Quick Start” shows Python V2 usage with ClientV2 + enqueue_and_get_inference. Use the official client library rather than inventing raw endpoints unless required.
2) Read ofxtools docs enough to:
   - Build bank statement objects
   - Emit OFX2 XML
   - Emit OFX1 as fallback
   (Do NOT write your own OFX string builder.)

PROJECT LOCATION / STRUCTURE (must match exactly)
Create/modify only inside:
  ./lab/pdf2ofx/

Notes:
- Keep this tool isolated: do not depend on other project modules.

Create this structure (files may be empty at first but must exist):
lab/pdf2ofx/
  README.md
  pyproject.toml
  pdf2ofx.py                      # Typer entry point

  input/
  output/
  tmp/

  handlers/
    mindee_handler.py             # Mindee API calls + polling + fetch JSON

  normalizers/
    canonicalize.py               # raw Mindee → canonical JSON statement
    fitid.py                      # FITID Strategy A (stable hash)

  validators/
    contract_validator.py         # hard constraints + coherence checks

  converters/
    ofx_emitter.py                # ofxtools-based OFX2 emit + OFX1 fallback

  helpers/
    fs.py                         # create dirs, safe delete tmp, naming, safe writes
    ui.py                         # Rich panels/tables/summary builder
    timing.py                     # perf timer helpers
    errors.py                     # stage error types + formatting

  tests/                          # tool-local tests (MUST)
    fixtures/                     # tool-local fixtures (MUST)

Additionally create at REPO ROOT:
  ofx.bat                         # runs tool in interactive mode (see below)

BATCH FILE (repo root)
Create repo-root ofx.bat that runs the tool in interactive mode from the repo root.
It must call:
  python .\lab\pdf2ofx\pdf2ofx.py
(or equivalent that works on Windows cmd)

DEPENDENCIES (critical)
- You MUST update BOTH:
  1) ./lab/pdf2ofx/pyproject.toml (local organization / future portability)
  2) repo-root requirements.txt (the runtime venv depends on it)
Add minimal deps:
- typer
- rich
- InquirerPy
- ofxtools
- mindee (Mindee Python client library; follow docs version guidance)
- requests OR httpx (only if needed; prefer Mindee client)
- python-dotenv (optional, only if you implement .env)
- pytest (required; for tool-local tests)

CONFIG / ENV VARS
- Read API key from env var: MINDEE_V2_API_KEY
- Read model id from env var: MINDEE_MODEL_ID
- Optional .env support (gitignored): load if present, but env vars override.
- Optional local persistence file (gitignored):
  ./lab/pdf2ofx/local_settings.json
Used only when required canonical account fields are missing/unusable.

DATA CONTRACT (authoritative)
You must normalize Mindee output into this canonical JSON object before OFX emission:

Statement:
- schema_version: “1.0”
- source: { origin: “mindee”, document_id?: str }
- account:
  - account_id: str (required)
  - bank_id: str (required-ish; stable dummy allowed)
  - account_type: str (required; default “CHECKING”)
  - currency: str (required; default “EUR”)
- period: { start_date?: date, end_date?: date } (optional but recommended)
- transactions: array of Transaction (required, len>0)

Transaction:
- fitid: str (required, unique within statement)
- posted_at: date (required)  # firm standard = OPERATION DATE
- amount: number (required, signed credit+, debit-)
- debit?: number (optional unsigned)
- credit?: number (optional unsigned)
- name: str (required-ish)
- memo?: str
- trntype?: str (optional; derive CREDIT/DEBIT from sign if missing)

HARD VALIDATION (must enforce)
- transactions exists and > 0
- each tx: posted_at parseable, amount parseable, fitid non-empty
- fitid unique within statement
- currency present (default EUR)

COHERENCE VALIDATION (recommended; choose behavior and be explicit)
- If debit != 0 ⇒ amount must be -abs(debit)
- If credit != 0 ⇒ amount must be +abs(credit)
- If both debit and credit non-zero ⇒ INVALID (simplest: fail the statement with an actionable message)
- If period missing ⇒ derive from min/max posted_at
- If period exists ⇒ warn if tx outside range

FITID STRATEGY (required)
Strategy A: stable hash of:
  account_id | posted_at | amount | normalized_label | seq
normalized_label = (name + “ “ + memo).strip(), collapse whitespace, uppercase, strip repeated punctuation.
seq = occurrence index when duplicates exist (0,1,2...).
Use SHA-1 or SHA-256; store 16–24 hex chars.

MINDEE INPUT SCHEMAS (must support at least one, ideally both)
A) Custom model output (fields with spaces / exact keys):
- Root keys: “Bank Name”, “Start Date”, “End Date”, “Starting Balance”, “Ending Balance”, “Transactions”
- Transactions items keys: “Operation Date”, “Value Date”, “Posting Date”, “Description”, “Amount Signed”, “Debit Amount”, “Credit Amount”, “Row Confidence Notes”
Normalization rules:
- posted_at = “Operation Date” preferred; else “Posting Date”; else “Value Date”
- amount = “Amount Signed” preferred; else compute from Debit/Credit
- name/memo from Description; optionally memo may append Row Confidence Notes (but do NOT print it to console)

B) Mindee default bank statement schema (optional support if easy):
- account_number, bank_name, currency, account_type, statement_period_start_date, statement_period_end_date, list_of_transactions[{date, description, amount}], branch_code
Normalization mapping accordingly.

If you cannot fully support B without docs/examples, implement A fully, and implement B as a clearly separated TODO parser with safe failure message (no silent wrong mapping).

OFX EMISSION REQUIREMENTS (via ofxtools)
- Default: write OFX2 XML
- Fallback: write OFX1 via ofxtools
- Minimal structure to satisfy importers:
  - CURDEF = account.currency
  - BANKACCTFROM: BANKID, ACCTID, ACCTTYPE
  - BANKTRANLIST: DTSTART/DTEND (from period or derived)
  - STMTTRN entries: DTPOSTED, TRNAMT, FITID, NAME, MEMO(optional), TRNTYPE(derived)

NOTE: We do NOT aim for strict DTD compliance. We aim for “Pennylane and ACD accept the import”.

PROMPT / FALLBACK POLICY (min friction, no overprompting)
- Prefer using extracted account fields if present.
- Only prompt operator if the run cannot proceed:
  - account.account_id missing/empty ⇒ prompt once (with option to save to local_settings.json)
  - bank_id missing ⇒ do NOT prompt by default; use stable dummy “DUMMY” and show warning in summary
  - currency missing ⇒ default EUR (no prompt)
  - account_type missing ⇒ default CHECKING (no prompt)
- local_settings.json (gitignored) can store defaults to avoid repeat prompts.
- Do NOT require manual input if Mindee provides fields.

TMP CLEANUP RULE (must implement exactly)
- Save raw Mindee response JSON to tmp/<pdf_stem>.json as soon as fetched.
- After processing all PDFs:
  - If ALL succeeded end-to-end (extract + normalize + validate + OFX written):
    delete tmp/ automatically.
  - If ANY failure:
    prompt: default KEEP tmp/, option delete anyway.
- If user aborts with “q”: do NOT delete tmp/.

INTERACTIVE UX FLOW (must implement)
1) Launch tool (interactive menu) [q quits]
2) Detect PDFs in ./lab/pdf2ofx/input/
   - If none: show message + exit
3) Batch process each PDF:
   - Mindee infer + poll + fetch
   - write tmp JSON
   - normalize → canonical
   - validate
   - collect failures but keep going
4) After batch:
   - choose output mode: A per-PDF (default) / B concat
   - choose output format: OFX2 (default) / OFX1 fallback
5) Emit OFX accordingly into ./lab/pdf2ofx/output/
6) Apply tmp cleanup rule
7) Print Rich summary table (scan-friendly):
   - PDFs processed count
   - per PDF: status (OK/FAIL), stage of failure, short hint
   - output mode, output format
   - OFX generated files list
   - execution time
   - warnings (bank_id dummy used, period derived, etc.)

ERROR HANDLING (must be readable/actionable)
Define stage errors: PREFLIGHT, MINDEE, NORMALIZE, VALIDATE, EMIT, WRITE.
Examples:
- missing env vars → tell exactly which and how to set
- Mindee 401/429/timeouts → actionable hint
- empty transactions → mark failed with hint
- schema mismatch → hint keys expected

TESTING REQUIREMENTS (MUST implement + run in your sandbox)
Even if you cannot call the real Mindee API (no API key), you MUST implement and run tests so we reduce review cycles.

1) All tests MUST be tool-local under:
  ./lab/pdf2ofx/tests/
and fixtures under:
  ./lab/pdf2ofx/tests/fixtures/
Do NOT put any new files under repo-root /tests.

2) Tests MUST cover:
- FITID determinism and uniqueness:
  - same input tx tuple yields same fitid
  - duplicates yield different fitids via seq
- Canonicalizer for Custom Schema A:
  - use a representative raw Mindee-like JSON fixture file stored in tests/fixtures/
  - posted_at selection: Operation Date > Posting Date > Value Date
  - amount selection: Amount Signed preferred; else from Debit/Credit
  - name/memo populated from Description
- Validator:
  - passes for valid canonical
  - fails for missing posted_at/amount/fitid
  - fails when debit and credit both non-zero (or whichever explicit behavior you chose)
- OFX emitter:
  - generates OFX2 output (bytes/string)
  - assert presence of required logical elements/tags
  - optionally parse back if feasible; otherwise tag assertions are fine

3) CLI smoke test (no Mindee):
- Use Typer’s CliRunner to run the CLI in a mode that does NOT call Mindee:
  - Implement a hidden/internal dev flag OR a test-only pathway to feed canonical JSON fixtures directly to the conversion layer.
  - The CLI smoke test should confirm:
    - summary renders (exit code ok)
    - output files written in expected location (use a tmp test dir)
    - tmp cleanup rule does not delete on simulated failures

4) You MUST run and finish with green tests:
  - `python -m pytest -q`
Exit condition: tests green.
Do NOT rewrite architecture to chase tests—fix the smallest thing that makes them pass.

IMPLEMENTATION QUALITY BAR
- Minimal but clean modules
- No circular imports
- No global state besides configuration
- Deterministic outputs
- Keep interactive UX consistent, “q” always works

ACCEPTANCE CHECKS (you must satisfy)
1) Put multiple PDFs into ./lab/pdf2ofx/input/
2) Run repo-root ofx.bat
3) Tool generates:
   - Mode A: ./lab/pdf2ofx/output/<pdf_stem>.ofx for each success
   - Mode B: ./lab/pdf2ofx/output/concat_<timestamp>.ofx
4) OFX2 default is produced; OFX1 fallback selectable
5) tmp deletion rules behave exactly as specified
6) Summary is readable and fast to scan
7) Tool-local tests pass in your sandbox (pytest)

DELIVERABLES
- All required files created + implemented under ./lab/pdf2ofx/
- repo-root requirements.txt updated (minimal deps incl pytest)
- repo-root ofx.bat created
- README.md inside ./lab/pdf2ofx explaining:
  - setup (env vars)
  - where to drop PDFs
  - output modes + formats
  - how tmp cleanup works
  - how to run (ofx.bat)
  - how to run tests (pytest)

Do not ask the user questions. Make reasonable assumptions and implement.

ADDENDUM — QUESTIONS / FAILING TESTS ESCALATION RULE

You MUST aim to finish with all tests green.

However, if tests fail and the only way to resolve them requires a policy/permission decision (i.e. you need to know what you are allowed to tweak or change), then DO NOT guess and DO NOT do a large refactor.

In that case:
1) Stop.
2) Summarize which tests failed (test names + failure messages).
3) Explain the most likely root cause(s).
4) Propose the minimal set of possible fixes, each labeled with what it would change (e.g. “change validator strictness”, “change FITID behavior”, “change output tag assertions”, “change CLI contract”).
5) Ask the user exactly what you need to know / what decision is required.

Only leave tests failing if blocked by that explicit user decision.
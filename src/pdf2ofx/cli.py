from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import typer
from dotenv import load_dotenv
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.panel import Panel

from pdf2ofx.converters.ofx_emitter import emit_ofx
from pdf2ofx.handlers.mindee_handler import infer_pdf
from pdf2ofx.helpers.errors import Stage, StageError
from pdf2ofx.helpers.fs import (
    ensure_dirs,
    ensure_recovery_dir,
    list_pdfs,
    list_tmp_jsons,
    load_local_settings,
    normalize_ofx_filename,
    open_path_in_default_app,
    read_tmp_meta,
    resolve_source_path_from_meta,
    safe_delete_dir,
    safe_write_bytes,
    save_local_settings,
    selective_tmp_cleanup,
    timestamp_slug,
    tmp_json_path,
    transaction_line_numbers,
    write_json,
    write_tmp_meta,
)
from pdf2ofx.helpers.reporting import Issue, Severity
from pdf2ofx.helpers.timing import Timer
from pdf2ofx.helpers.ui import PdfResult, render_banner, render_summary
from pdf2ofx.normalizers.canonicalize import NormalizationError, canonicalize_mindee
from pdf2ofx.sanity.checks import (
    SanityResult,
    compute_sanity,
    is_clean_for_tmp_delete,
    tmp_keep_reason,
)
from pdf2ofx.sanity.panel import render_sanity_panel
from pdf2ofx.normalizers.fitid import assign_fitids
from pdf2ofx.validators.contract_validator import ValidationError, validate_statement

app = typer.Typer(add_completion=False)
console = Console()


def _scan_ofx_fitids(ofx_path: Path) -> dict[str, int]:
    """Scan an OFX file and return {fitid: line_number}."""
    fitid_map: dict[str, int] = {}
    try:
        with ofx_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                stripped = line.strip()
                if stripped.startswith("<FITID>") and stripped.endswith("</FITID>"):
                    fitid = stripped[7:-8]
                    fitid_map[fitid] = line_num
    except Exception:
        pass
    return fitid_map


class UserAbort(Exception):
    pass


class RecoveryBackRequested(Exception):
    """Raised when operator chooses 'Back to list' from SANITY in recovery mode."""


@dataclass
class ProcessItem:
    name: str
    statement: dict


@dataclass
class RecoveryCandidate:
    """In-memory recovery candidate: raw + canonical + validation + sanity (reuse unless edited)."""
    path: Path
    raw: dict
    statement: dict
    validation_issues: list
    sanity_result: SanityResult
    label: str  # hash + period + count + quality; stem if available
    source_path: Path | None = None  # resolved PDF path from meta, or None for legacy tmp


def _prompt_select(message: str, choices: list[tuple[str, str]], default: str) -> str:
    options = [
        {"name": label, "value": value}
        for label, value in choices
        if value != "__quit__"
    ]
    options.append({"name": "Quit (q)", "value": "__quit__"})
    result = inquirer.select(message=message, choices=options, default=default).execute()
    if result == "__quit__":
        raise UserAbort()
    return result


def _prompt_text(message: str, default: str | None = None) -> str:
    result = inquirer.text(message=message, default=default or "").execute()
    if result.strip().lower() == "q":
        raise UserAbort()
    return result


def _prompt_confirm(message: str, default: bool) -> bool:
    choices = [("Yes", "yes"), ("No", "no")]
    default_value = "yes" if default else "no"
    result = _prompt_select(message, choices=choices, default=default_value)
    return result == "yes"


# Ignore-pair reasons: only these warning pairs skip the "open source PDF" prompt.
BOTH_DEBIT_CREDIT = "transaction has both debit and credit amounts"
SIGNED_VS_DEBIT = "signed amount does not match debit amount"
SIGNED_VS_CREDIT = "signed amount does not match credit amount"
_IGNORE_PAIRS = (
    {BOTH_DEBIT_CREDIT, SIGNED_VS_CREDIT},
    {BOTH_DEBIT_CREDIT, SIGNED_VS_DEBIT},
)


def _sanity_needs_visual_check(r: SanityResult) -> bool:
    """True if this sanity result has something that warrants opening the PDF."""
    if r.reconciliation_status in ("ERROR", "WARNING"):
        return True
    if r.deductions or r.warnings:
        return True
    return False


def _should_suggest_open_file(
    issues: list[Issue], sanity_results: list[SanityResult]
) -> bool:
    if any(_sanity_needs_visual_check(r) for r in sanity_results):
        return True
    reasons = {i.reason for i in issues}
    if reasons in _IGNORE_PAIRS:
        return False
    return bool(issues)


def _get_sources_to_open(
    issues: list[Issue],
    sanity_results: list[SanityResult],
    statements: list[ProcessItem],
    sources: list[Path],
) -> list[Path]:
    stem_to_source = {s.stem: s for s in sources}
    to_open: set[Path] = set()
    for i, r in enumerate(sanity_results):
        if _sanity_needs_visual_check(r):
            path = stem_to_source.get(statements[i].name)
            if path is not None:
                to_open.add(path)
    fitid_to_stem: dict[str, str] = {}
    for item in statements:
        for tx in item.statement.get("transactions", []):
            fid = tx.get("fitid")
            if fid:
                fitid_to_stem[fid] = item.name
    for issue in issues:
        if issue.reason in (BOTH_DEBIT_CREDIT, SIGNED_VS_DEBIT, SIGNED_VS_CREDIT):
            continue
        for fid in issue.fitids:
            stem = fitid_to_stem.get(fid)
            if stem is not None:
                path = stem_to_source.get(stem)
                if path is not None:
                    to_open.add(path)
    return list(to_open)


def _load_env() -> None:
    load_dotenv(override=False)


def _preflight(dev_mode: bool) -> tuple[str | None, str | None]:
    api_key = os.getenv("MINDEE_V2_API_KEY")
    model_id = os.getenv("MINDEE_MODEL_ID")
    if dev_mode:
        return api_key, model_id
    missing = []
    if not api_key:
        missing.append("MINDEE_V2_API_KEY")
    if not model_id:
        missing.append("MINDEE_MODEL_ID")
    if missing:
        raise StageError(
            stage=Stage.PREFLIGHT,
            message="Missing Mindee configuration.",
            hint=f"Set env vars: {', '.join(missing)}",
        )
    return api_key, model_id


def _sanitize_settings(settings: dict) -> dict:
    return {
        key: value
        for key, value in settings.items()
        if key in {"account_id", "bank_id", "currency", "account_type"}
    }


def _ensure_account_id(
    statement: dict, settings: dict, allow_prompt: bool
) -> tuple[dict, list[Issue]]:
    issues: list[Issue] = []
    account = statement.get("account") or {}
    account_id = account.get("account_id") or settings.get("account_id")
    if not account_id:
        if allow_prompt:
            account_id = _prompt_text(
                "Account ID missing. Enter account ID (or q to quit):"
            )
            if _prompt_confirm("Save account ID to local_settings.json?", False):
                settings["account_id"] = account_id
                save_local_settings(settings["settings_path"], _sanitize_settings(settings))
        else:
            account_id = "UNKNOWN"
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    reason="account_id missing; using UNKNOWN for dev mode",
                    count=0,
                )
            )
    account["account_id"] = account_id
    statement["account"] = account
    return statement, issues


def _resolve_account_defaults(settings: dict) -> dict:
    defaults = {
        "bank_id": "DUMMY",
        "currency": "EUR",
        "account_type": "CHECKING",
    }
    for key in defaults:
        if settings.get(key):
            defaults[key] = settings[key]
    return defaults


def _collect_missing_account_fields(statements: list[ProcessItem]) -> dict[str, int]:
    missing_counts = {"bank_id": 0, "currency": 0, "account_type": 0}
    for item in statements:
        account = item.statement.get("account") or {}
        for field in missing_counts:
            if not account.get(field):
                missing_counts[field] += 1
    return {field: count for field, count in missing_counts.items() if count}


def _apply_account_metadata(
    statements: list[ProcessItem], values: dict
) -> None:
    for item in statements:
        account = item.statement.get("account") or {}
        for field, value in values.items():
            if not account.get(field):
                account[field] = value
        item.statement["account"] = account


def _collect_posted_at_fallbacks(statement: dict) -> Issue | None:
    fallback_fitids: list[str] = []
    for tx in statement.get("transactions", []):
        source = tx.get("posted_at_source")
        if source and source != "operation":
            fitid = tx.get("fitid")
            if fitid:
                fallback_fitids.append(fitid)
    if not fallback_fitids:
        return None
    return Issue(
        severity=Severity.WARNING,
        reason="posted_at fallback used (operation date missing)",
        fitids=fallback_fitids,
        count=len(fallback_fitids),
    )


def _detect_fitid_collisions(transactions: list[dict]) -> tuple[int, list[str]]:
    seen: set[str] = set()
    duplicates: list[str] = []
    duplicate_count = 0
    for tx in transactions:
        fitid = tx.get("fitid")
        if not fitid:
            continue
        if fitid in seen:
            duplicate_count += 1
            if fitid not in duplicates:
                duplicates.append(fitid)
        else:
            seen.add(fitid)
    return duplicate_count, duplicates


def _process_raw_pdf(
    pdf_path: Path,
    api_key: str,
    model_id: str,
    tmp_json_path: Path,
    account_defaults: dict,
) -> tuple[dict, list[str], dict]:
    raw = infer_pdf(api_key, model_id, pdf_path)
    write_json(tmp_json_path, raw)
    normalization = canonicalize_mindee(raw, account_defaults=account_defaults)
    return normalization.statement, normalization.warnings, raw


def _process_dev_canonical(
    canonical_path: Path,
    tmp_json_path: Path,
) -> dict:
    with canonical_path.open("r", encoding="utf-8") as handle:
        statement = json.load(handle)
    write_json(tmp_json_path, {"dev_mode": True})
    return statement


def _run_sanity_stage(
    console: Console,
    statement: dict,
    pdf_name: str,
    extracted_count: int,
    raw_response: dict | None,
    validation_issues: list,
    dev_non_interactive: bool,
    source_path: Path | None = None,
    recovery_mode: bool = False,
) -> SanityResult:
    """Run the SANITY stage: compute, display, confirm.

    Returns the final SanityResult after operator confirmation.
    Does **not** mutate *statement* (caller may mutate after).
    When recovery_mode=True, "Back to list" raises RecoveryBackRequested.
    """
    result = compute_sanity(
        statement=statement,
        pdf_name=pdf_name,
        extracted_count=extracted_count,
        raw_response=raw_response,
        validation_issues=validation_issues,
    )
    render_sanity_panel(console, result)

    if dev_non_interactive:
        return result

    while True:
        choices: list[tuple[str, str]] = [
            ("Accept", "accept"),
            ("Edit balances", "edit"),
            ("Edit transactions", "edit_tx"),
            ("Skip reconciliation", "skip"),
        ]
        if source_path is not None and source_path.exists():
            choices.append(("Open source PDF", "open"))
        if recovery_mode:
            choices.append(("Back to list", "back_to_list"))
        action = _prompt_select(
            "Sanity check:",
            choices=choices,
            default="accept",
        )

        if action == "back_to_list":
            raise RecoveryBackRequested()

        if action == "open":
            open_path_in_default_app(source_path)
            continue

        if action == "skip":
            result = compute_sanity(
                statement=statement,
                pdf_name=pdf_name,
                extracted_count=extracted_count,
                raw_response=None,
                validation_issues=validation_issues,
            )
            result.skipped = True
            render_sanity_panel(console, result)
            return result

        if action == "edit":
            if source_path is not None and source_path.exists():
                open_path_in_default_app(source_path)
            edit_bal_choice = _prompt_select(
                "Edit balances:",
                choices=[
                    ("← Back (no change)", "back"),
                    ("Enter starting & ending balance", "edit"),
                ],
                default="back",
            )
            if edit_bal_choice == "back":
                continue
            start_str = _prompt_text("Starting balance (or Enter to skip):")
            end_str = _prompt_text("Ending balance (or Enter to skip):")

            start_bal: Decimal | None = None
            end_bal: Decimal | None = None
            if start_str.strip():
                try:
                    start_bal = Decimal(start_str.strip().replace(",", ""))
                except (InvalidOperation, ValueError):
                    console.print("[yellow]Invalid starting balance — ignored[/yellow]")
            if end_str.strip():
                try:
                    end_bal = Decimal(end_str.strip().replace(",", ""))
                except (InvalidOperation, ValueError):
                    console.print("[yellow]Invalid ending balance — ignored[/yellow]")

            result = compute_sanity(
                statement=statement,
                pdf_name=pdf_name,
                extracted_count=extracted_count,
                raw_response=raw_response,
                validation_issues=validation_issues,
                starting_balance=start_bal,
                ending_balance=end_bal,
            )
            render_sanity_panel(console, result)
            continue

        if action == "edit_tx":
            if source_path is not None and source_path.exists():
                open_path_in_default_app(source_path)
            transactions = statement.get("transactions", [])
            if not transactions:
                continue
            max_desc = 50

            def _tx_label(i: int, tx: dict) -> str:
                date_str = (tx.get("posted_at") or "?")[:10]
                amt = tx.get("amount")
                amt_str = f"{str(amt):>12}" if amt is not None else " " * 12
                desc = (tx.get("name") or tx.get("memo") or "-").strip()
                if len(desc) > max_desc:
                    desc = desc[: max_desc - 1] + "…"
                return f"{date_str}  {amt_str}  {desc}"

            edit_tx_action = _prompt_select(
                "Edit transactions:",
                choices=[
                    ("← Back", "back"),
                    ("Remove some transactions", "remove"),
                    ("Edit one transaction (date, amount, description)", "edit_one"),
                ],
                default="back",
            )
            if edit_tx_action == "back":
                continue
            if edit_tx_action == "remove":
                checkbox_choices = [
                    Choice(i, name=_tx_label(i, tx))
                    for i, tx in enumerate(transactions)
                ]
                to_remove = inquirer.checkbox(
                    message="Select transactions to REMOVE (Space to toggle, Enter to confirm):",
                    choices=checkbox_choices,
                ).execute()
                if to_remove is None:
                    continue
                if len(to_remove) == 0:
                    continue
                if len(to_remove) >= len(transactions):
                    console.print(
                        "[yellow]At least one transaction must remain.[/yellow]"
                    )
                    continue
                to_remove_set = set(to_remove)
                statement["transactions"] = [
                    t for i, t in enumerate(transactions) if i not in to_remove_set
                ]
                result = compute_sanity(
                    statement=statement,
                    pdf_name=pdf_name,
                    extracted_count=extracted_count,
                    raw_response=raw_response,
                    validation_issues=validation_issues,
                )
                render_sanity_panel(console, result)
                continue
            # edit_one
            _BACK_VALUE = "__back__"
            select_choices = [
                Choice(_BACK_VALUE, name="← Back"),
            ] + [
                Choice(i, name=_tx_label(i, tx))
                for i, tx in enumerate(transactions)
            ]
            try:
                idx = inquirer.select(
                    message="Select transaction to edit:",
                    choices=select_choices,
                ).execute()
            except Exception:
                continue
            if idx is None or idx == _BACK_VALUE:
                continue
            tx = statement["transactions"][idx]
            # Date
            date_default = (tx.get("posted_at") or "")[:10]
            date_str = _prompt_text("Date (YYYY-MM-DD):", default=date_default)
            if date_str.strip():
                try:
                    parsed_date = date.fromisoformat(date_str.strip())
                    tx["posted_at"] = parsed_date.isoformat()
                except ValueError:
                    console.print("[yellow]Invalid date — kept previous.[/yellow]")
            # Amount
            amt_default = str(tx.get("amount", ""))
            amt_str = _prompt_text("Amount:", default=amt_default)
            if amt_str.strip():
                try:
                    parsed_amt = Decimal(amt_str.strip().replace(",", ""))
                    tx["amount"] = parsed_amt
                    tx["trntype"] = "CREDIT" if parsed_amt >= 0 else "DEBIT"
                except (InvalidOperation, ValueError):
                    console.print("[yellow]Invalid amount — kept previous.[/yellow]")
            # Name
            name_val = _prompt_text("Name:", default=tx.get("name") or "")
            tx["name"] = name_val.strip() or tx.get("name")
            # Memo
            memo_val = _prompt_text("Memo:", default=tx.get("memo") or "")
            tx["memo"] = memo_val.strip() or tx.get("memo")
            result = compute_sanity(
                statement=statement,
                pdf_name=pdf_name,
                extracted_count=extracted_count,
                raw_response=raw_response,
                validation_issues=validation_issues,
            )
            render_sanity_panel(console, result)
            continue

        # action == "accept"
        if result.reconciliation_status == "ERROR":
            force = _prompt_confirm(
                "Reconciliation ERROR detected — force accept?", False,
            )
            if not force:
                continue
            result.forced_accept = True
        return result


# Legacy tmp backfill: stem -> source PDF name (for --backfill-tmp-meta)
_BACKFILL_TMP_META_MAPPING: dict[str, str] = {
    "e4e427277135": "deveil_09-2025.pdf",
    "e36118847891": "deveil_05-2025.pdf",
}


def _backfill_tmp_meta(console: Console, base_dir: Path) -> None:
    """Write missing tmp/<stem>.meta.json for known legacy tmp files (maintainer helper)."""
    paths = ensure_dirs(base_dir)
    tmp_dir = paths["tmp"]
    input_dir = paths["input"]
    processed_dir = paths["processed"]
    written: list[str] = []
    for stem, source_name in _BACKFILL_TMP_META_MAPPING.items():
        tmp_path = tmp_dir / f"{stem}.json"
        meta_path = tmp_dir / f"{stem}.meta.json"
        if not tmp_path.exists() or meta_path.exists():
            continue
        candidate: Path = input_dir / source_name
        if not candidate.exists() and processed_dir.exists():
            for sub in processed_dir.iterdir():
                if sub.is_dir():
                    c = sub / source_name
                    if c.exists():
                        candidate = c
                        break
        if not candidate.exists():
            candidate = input_dir / source_name
        write_tmp_meta(tmp_path, candidate)
        written.append(f"{stem}.json → {source_name}")
    if written:
        console.print("[dim]Backfill: wrote meta for " + ", ".join(written) + "[/dim]")
    else:
        console.print("[dim]Backfill: no missing meta to write.[/dim]")


def _run_recovery_mode(console: Console, base_dir: Path, dev_non_interactive: bool = False) -> None:
    """Recovery mode: list tmp/*.json, multi-select, SANITY, then convert from .canonical.json."""
    if dev_non_interactive:
        console.print(
            "[yellow]Recovery mode requires interactive prompts. Run without --dev-non-interactive.[/yellow]"
        )
        return
    paths = ensure_dirs(base_dir)
    tmp_dir = paths["tmp"]
    output_dir = paths["output"]
    recovery_dir = ensure_recovery_dir(tmp_dir)
    settings_path = base_dir / "local_settings.json"
    settings = load_local_settings(settings_path)
    settings["settings_path"] = settings_path
    account_defaults = _resolve_account_defaults(settings)
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / ".write_check").write_text("", encoding="utf-8")
        (output_dir / ".write_check").unlink()
    except OSError as e:
        console.print(f"[red]Output dir not writable: {output_dir}[/red] — {e}")
        return

    candidates_paths = list_tmp_jsons(tmp_dir)
    if not candidates_paths:
        console.print("No tmp/*.json found. Exiting.")
        return

    recovery_candidates: list[RecoveryCandidate] = []
    for path in candidates_paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            norm = canonicalize_mindee(raw, account_defaults=account_defaults)
            statement = norm.statement
        except NormalizationError:
            continue
        statement, _ = _ensure_account_id(statement, settings, allow_prompt=False)
        assign_fitids(statement["account"]["account_id"], statement["transactions"])
        try:
            validation = validate_statement(statement)
            statement = validation.statement
        except ValidationError:
            continue
        if not statement.get("transactions"):
            continue
        extracted = len(statement.get("transactions", []))
        sanity_result = compute_sanity(
            statement=statement,
            pdf_name=path.name,
            extracted_count=extracted,
            raw_response=raw,
            validation_issues=validation.issues,
        )
        period = statement.get("period") or {}
        start = period.get("start_date") or "?"
        end = period.get("end_date") or "?"
        period_str = f"{start} → {end}"
        meta = read_tmp_meta(path)
        source_path: Path | None = None
        if meta:
            source_path = resolve_source_path_from_meta(
                meta, paths["processed"], paths["input"]
            )
        label = f"{path.stem}  {period_str}  {extracted} tx  {sanity_result.quality_label} ({sanity_result.quality_score})"
        if source_path is None:
            label += "  (no source PDF)"
        recovery_candidates.append(
            RecoveryCandidate(
                path=path,
                raw=raw,
                statement=statement,
                validation_issues=validation.issues,
                sanity_result=sanity_result,
                label=label,
                source_path=source_path,
            )
        )

    if not recovery_candidates:
        console.print("No valid recovery candidates (normalize/validate failed). Exiting.")
        return

    choice_labels = [c.label for c in recovery_candidates]
    selected_indices: list[int] = []
    selected: list[RecoveryCandidate] = []

    while True:
        try:
            selected_indices = inquirer.checkbox(
                message="Select JSONs to recover (Space to toggle, Enter to confirm):",
                choices=[Choice(i, name=choice_labels[i]) for i in range(len(recovery_candidates))],
            ).execute()
        except Exception:
            return
        if not selected_indices:
            console.print("None selected. Exiting.")
            return

        selected = [recovery_candidates[i] for i in selected_indices]
        for c in selected:
            raw_path = recovery_dir / f"recover_{c.path.stem}.raw.json"
            canon_path = recovery_dir / f"recover_{c.path.stem}.canonical.json"
            write_json(raw_path, c.raw)
            write_json(canon_path, c.statement, decimal_to_str=True)

        modified: set[str] = set()
        while True:
            back_to_list = False
            for c in selected:
                canon_path = recovery_dir / f"recover_{c.path.stem}.canonical.json"
                statement = json.loads(canon_path.read_text(encoding="utf-8"))
                extracted = len(statement.get("transactions", []))
                try:
                    pdf_display_name = (c.source_path.name if c.source_path else c.path.name)
                    sanity_result = _run_sanity_stage(
                        console=console,
                        statement=statement,
                        pdf_name=pdf_display_name,
                        extracted_count=extracted,
                        raw_response=c.raw,
                        validation_issues=c.validation_issues,
                        dev_non_interactive=False,
                        source_path=c.source_path,
                        recovery_mode=True,
                    )
                    write_json(canon_path, statement, decimal_to_str=True)
                    modified.add(c.path.stem)
                    c.statement = statement
                    c.sanity_result = sanity_result
                except RecoveryBackRequested:
                    back_to_list = True
                    break
            if back_to_list:
                break
            choice = _prompt_select(
                "Recovery: next step",
                choices=[
                    ("Confirm & proceed to conversion", "confirm"),
                    ("Go back (re-run SANITY for modified)", "go_back"),
                ],
                default="confirm",
            )
            if choice == "confirm":
                break
            selected = [c for c in selected if c.path.stem in modified]
            if not selected:
                console.print("No modified items. Proceeding to conversion.")
                selected = [recovery_candidates[i] for i in selected_indices]
                break
        if not back_to_list:
            break

    output_mode = _prompt_select(
        "Output mode",
        choices=[("A) One OFX per file", "A"), ("B) Concatenate", "B")],
        default="A",
    )
    output_format = _prompt_select(
        "Output format",
        choices=[("OFX2 (XML)", "OFX2"), ("OFX1 (fallback)", "OFX1")],
        default="OFX2",
    )
    total_tx = 0
    summary_lines = [f"Output: {output_mode} — {output_format}", ""]
    for c in selected:
        n = len(c.statement.get("transactions", []))
        total_tx += n
        summary_lines.append(f"  {c.path.stem}.canonical.json  →  {n} transactions")
    summary_lines.append(f"\nTotal: {total_tx} transactions → {output_dir}")
    console.print(Panel.fit("\n".join(summary_lines), title="About to convert", style="dim"))
    output_files: list[str] = []
    if output_mode == "A":
        for c in selected:
            canon_path = recovery_dir / f"recover_{c.path.stem}.canonical.json"
            statement = json.loads(canon_path.read_text(encoding="utf-8"))
            validation = validate_statement(statement)
            statement = validation.statement
            payload = emit_ofx(statement, output_format)
            acct = statement.get("account", {})
            period = statement.get("period", {})
            ofx_name = normalize_ofx_filename(
                account_id=acct.get("account_id", "UNKNOWN"),
                period_end=period.get("end_date", "undated"),
                source_name=c.path.stem,
            )
            out_path = output_dir / ofx_name
            safe_write_bytes(out_path, payload)
            output_files.append(str(out_path))
    else:
        merged: dict = {}
        for c in selected:
            st = json.loads((recovery_dir / f"recover_{c.path.stem}.canonical.json").read_text(encoding="utf-8"))
            if not merged:
                merged = dict(st)
                merged["transactions"] = list(st.get("transactions", []))
            else:
                merged.setdefault("transactions", []).extend(st.get("transactions", []))
        if merged:
            validation = validate_statement(merged)
            merged = validation.statement
            payload = emit_ofx(merged, output_format)
            acct = merged.get("account", {})
            ofx_name = normalize_ofx_filename(
                account_id=acct.get("account_id", "UNKNOWN"),
                period_end=timestamp_slug(),
                source_name="concat",
            )
            out_path = output_dir / ofx_name
            safe_write_bytes(out_path, payload)
            output_files.append(str(out_path))
    console.print(f"[green]Wrote {len(output_files)} OFX file(s) to output/.[/green]")

    cleanup = _prompt_select(
        "Delete recovery copies in tmp/recovery/ or keep for analysis?",
        choices=[("Delete", "delete"), ("Keep", "keep")],
        default="keep",
    )
    if cleanup == "delete":
        for c in selected:
            (recovery_dir / f"recover_{c.path.stem}.raw.json").unlink(missing_ok=True)
            (recovery_dir / f"recover_{c.path.stem}.canonical.json").unlink(missing_ok=True)
    else:
        console.print("[dim]Recovery copies kept in tmp/recovery/[/dim]")


@app.command()
def main(
    dev_canonical: list[Path] = typer.Option(
        None,
        "--dev-canonical",
        help="(dev) Use canonical JSON instead of Mindee.",
        hidden=True,
    ),
    dev_non_interactive: bool = typer.Option(
        False,
        "--dev-non-interactive",
        help="(dev) Skip prompts and use defaults.",
        hidden=True,
    ),
    dev_simulate_failure: bool = typer.Option(
        False,
        "--dev-simulate-failure",
        help="(dev) Simulate a failure after validation.",
        hidden=True,
    ),
    base_dir: Path = typer.Option(
        Path.cwd(),
        "--base-dir",
        help="(dev) Override base directory.",
        hidden=True,
    ),
    backfill_tmp_meta: bool = typer.Option(
        False,
        "--backfill-tmp-meta",
        help="(maintainer) Write missing tmp/<hash>.meta.json for known legacy tmp files.",
        hidden=True,
    ),
) -> None:
    _load_env()
    render_banner(console)
    dev_mode = bool(dev_canonical)

    with Timer() as timer:
        try:
            if backfill_tmp_meta:
                _backfill_tmp_meta(console, base_dir)
            if not dev_non_interactive:
                choice = _prompt_select(
                    "Start pdf2ofx?",
                    choices=[
                        ("Process PDFs", "start"),
                        ("Recovery mode", "recovery"),
                    ],
                    default="start",
                )
                if choice == "recovery":
                    _run_recovery_mode(console, base_dir, dev_non_interactive=dev_non_interactive)
                    return

            paths = ensure_dirs(base_dir)
            api_key, model_id = _preflight(dev_mode)
            input_dir = paths["input"]
            output_dir = paths["output"]
            tmp_dir = paths["tmp"]

            results: list[PdfResult] = []
            result_index: dict[str, int] = {}
            output_files: list[str] = []
            issues: list[Issue] = []
            pdf_notes: dict[str, list[str]] = {}
            statements: list[ProcessItem] = []
            sanity_results: list[SanityResult] = []
            fitid_lines: dict[str, int] = {}
            json_transaction_lines: dict[str, list[int]] = {}
            stem_to_tmp_path: dict[str, Path] = {}

            settings_path = base_dir / "local_settings.json"
            settings = load_local_settings(settings_path)
            settings["settings_path"] = settings_path

            if dev_mode:
                sources = dev_canonical
            else:
                sources = list_pdfs(input_dir)

            if not sources:
                console.print("No PDFs found in input/. Exiting.")
                return

            for index, source in enumerate(sources):
                try:
                    tmp_path = tmp_json_path(tmp_dir, source.stem)
                    stem_to_tmp_path[source.stem] = tmp_path

                    if dev_mode:
                        statement = _process_dev_canonical(source, tmp_path)
                        per_warnings: list[str] = []
                        raw_response: dict | None = None
                    else:
                        statement, per_warnings, raw_response = _process_raw_pdf(
                            source, api_key, model_id, tmp_path, settings
                        )
                        write_tmp_meta(tmp_path, source)

                    json_transaction_lines[source.stem] = transaction_line_numbers(
                        tmp_path
                    )

                    statement, account_issues = _ensure_account_id(
                        statement, settings, allow_prompt=not dev_non_interactive
                    )
                    issues.extend(account_issues)

                    assign_fitids(statement["account"]["account_id"], statement["transactions"])
                    posted_at_issue = _collect_posted_at_fallbacks(statement)
                    if posted_at_issue:
                        issues.append(posted_at_issue)
                        pdf_notes.setdefault(source.name, []).append(
                            f"posted_at fallback used for {posted_at_issue.count} txs"
                        )
                    extracted_count = len(statement.get("transactions", []))
                    validation = validate_statement(statement)
                    statement = validation.statement
                    issues.extend(validation.issues)

                    if not statement.get("transactions"):
                        issues.append(
                            Issue(
                                severity=Severity.ERROR,
                                reason="no usable transactions after validation",
                                count=0,
                            )
                        )
                        results.append(
                            PdfResult(
                                name=source.name,
                                ok=False,
                                stage=Stage.VALIDATE.value,
                                message="No usable transactions after validation.",
                            )
                        )
                        continue

                    # ── SANITY stage ──────────────────────────
                    try:
                        sanity_result = _run_sanity_stage(
                            console=console,
                            statement=statement,
                            pdf_name=source.name,
                            extracted_count=extracted_count,
                            raw_response=raw_response,
                            validation_issues=validation.issues,
                            dev_non_interactive=dev_non_interactive,
                            source_path=source if not dev_mode else None,
                        )
                        sanity_results.append(sanity_result)
                    except UserAbort:
                        raise
                    except Exception as exc:
                        raise StageError(
                            stage=Stage.SANITY,
                            message=f"Sanity check failed: {exc}",
                            hint="Check raw Mindee response in tmp/",
                        ) from exc

                    if dev_simulate_failure and index == 0:
                        raise StageError(
                            stage=Stage.EMIT,
                            message="Simulated failure for dev mode.",
                            hint="Dev flag enabled.",
                        )

                    statements.append(ProcessItem(name=source.stem, statement=statement))
                    result_index[source.stem] = len(results)
                    results.append(PdfResult(name=source.name, ok=True, stage="OK", message=""))
                except StageError as exc:
                    result_index[source.stem] = len(results)
                    results.append(
                        PdfResult(
                            name=source.name,
                            ok=False,
                            stage=exc.stage.value,
                            message=exc.hint or exc.message,
                        )
                    )
                except NormalizationError as exc:
                    result_index[source.stem] = len(results)
                    results.append(
                        PdfResult(
                            name=source.name,
                            ok=False,
                            stage=Stage.NORMALIZE.value,
                            message=str(exc),
                        )
                    )
                except ValidationError as exc:
                    result_index[source.stem] = len(results)
                    results.append(
                        PdfResult(
                            name=source.name,
                            ok=False,
                            stage=Stage.VALIDATE.value,
                            message=str(exc),
                        )
                    )

            if not statements:
                issues.append(
                    Issue(
                        severity=Severity.ERROR,
                        reason="no transactions extracted in total",
                        count=0,
                    )
                )

            if statements:
                missing_fields = _collect_missing_account_fields(statements)
                if missing_fields:
                    default_values = _resolve_account_defaults(settings)
                    missing_lines = "\n".join(
                        f"- {field} (missing in {count} PDF(s))"
                        for field, count in missing_fields.items()
                    )
                    defaults_lines = "\n".join(
                        f"- {field}: {value}" for field, value in default_values.items()
                    )
                    console.print(
                        Panel.fit(
                            f"Missing fields from extraction:\n{missing_lines}\n\n"
                            f"Defaults that will be used:\n{defaults_lines}",
                            title="Account Metadata Summary",
                        )
                    )
                    if dev_non_interactive:
                        selected_values = default_values
                    else:
                        choice = _prompt_select(
                            "Use defaults?",
                            choices=[("Yes", "yes"), ("Override", "override")],
                            default="yes",
                        )
                        if choice == "override":
                            override_text = _prompt_text(
                                "Enter overrides as JSON (bank_id/currency/account_type):",
                                default=json.dumps(default_values),
                            )
                            try:
                                overrides = json.loads(override_text)
                                selected_values = {
                                    key: overrides.get(key, value)
                                    for key, value in default_values.items()
                                }
                            except json.JSONDecodeError:
                                selected_values = default_values
                                issues.append(
                                    Issue(
                                        severity=Severity.WARNING,
                                        reason="invalid account override input; using defaults",
                                        count=0,
                                    )
                                )
                        else:
                            selected_values = default_values

                        if _prompt_confirm(
                            "Save account metadata to local_settings.json?", False
                        ):
                            settings.update(selected_values)
                            save_local_settings(
                                settings["settings_path"], _sanitize_settings(settings)
                            )
                    _apply_account_metadata(statements, selected_values)

                if dev_non_interactive:
                    output_mode = "A"
                    output_format = "OFX2"
                else:
                    output_mode = _prompt_select(
                        "Output mode",
                        choices=[("A) One OFX per PDF", "A"), ("B) Concatenate", "B")],
                        default="A",
                    )
                    output_format = _prompt_select(
                        "Output format",
                        choices=[("OFX2 (XML)", "OFX2"), ("OFX1 (fallback)", "OFX1")],
                        default="OFX2",
                    )

                if output_mode == "A":
                    for item in statements:
                        try:
                            payload = emit_ofx(item.statement, output_format)
                            acct = item.statement.get("account", {})
                            period = item.statement.get("period", {})
                            ofx_name = normalize_ofx_filename(
                                account_id=acct.get("account_id", "UNKNOWN"),
                                period_end=period.get("end_date", "undated"),
                                source_name=item.name,
                            )
                            out_path = output_dir / ofx_name
                            safe_write_bytes(out_path, payload)
                            output_files.append(str(out_path))
                            fitid_lines.update(_scan_ofx_fitids(out_path))
                        except Exception as exc:
                            issues.append(
                                Issue(
                                    severity=Severity.ERROR,
                                    reason=f"failed to write OFX for {item.name}",
                                    count=0,
                                )
                            )
                            index = result_index.get(item.name)
                            if index is not None:
                                prev_name = results[index].name
                                results[index] = PdfResult(
                                    name=prev_name,
                                    ok=False,
                                    stage=Stage.WRITE.value,
                                    message=str(exc),
                                )
                else:
                    merged = statements[0].statement
                    for extra in statements[1:]:
                        if (
                            extra.statement.get("account", {}).get("account_id")
                            != merged.get("account", {}).get("account_id")
                        ):
                            issues.append(
                                Issue(
                                    severity=Severity.WARNING,
                                    reason="concat includes multiple account IDs",
                                    count=0,
                                )
                            )
                        merged["transactions"].extend(extra.statement["transactions"])
                    original_transactions = list(merged["transactions"])
                    collision_count, collision_fitids = _detect_fitid_collisions(
                        original_transactions
                    )
                    if collision_count:
                        issues.append(
                            Issue(
                                severity=Severity.WARNING,
                                reason=(
                                    "FITID collisions detected. Some importers may drop or "
                                    "overwrite transactions with duplicate FITIDs."
                                ),
                                fitids=collision_fitids,
                                count=collision_count,
                            )
                        )
                    validation = validate_statement(merged)
                    merged = validation.statement
                    issues.extend(validation.issues)
                    if collision_count:
                        # The validator deduplicates FITIDs (keeps first,
                        # drops subsequent).  We intentionally preserve all
                        # occurrences for collision FITIDs — the user was
                        # already warned.  Only restore collision duplicates
                        # that are individually valid, not every transaction
                        # the validator may have rejected for other reasons.
                        collision_set = set(collision_fitids)
                        validated_ids = {id(tx) for tx in merged["transactions"]}
                        for tx in original_transactions:
                            if id(tx) not in validated_ids and tx.get("fitid") in collision_set:
                                merged["transactions"].append(tx)
                    try:
                        payload = emit_ofx(merged, output_format)
                        acct = merged.get("account", {})
                        concat_name = normalize_ofx_filename(
                            account_id=acct.get("account_id", "UNKNOWN"),
                            period_end=timestamp_slug(),
                            source_name="concat",
                        )
                        out_path = output_dir / concat_name
                        safe_write_bytes(out_path, payload)
                        output_files.append(str(out_path))
                        fitid_lines.update(_scan_ofx_fitids(out_path))
                    except Exception as exc:
                        issues.append(
                            Issue(
                                severity=Severity.ERROR,
                                reason="failed to write concatenated OFX",
                                count=0,
                            )
                        )
                        for item in statements:
                            index = result_index.get(item.name)
                            if index is not None:
                                prev_name = results[index].name
                                results[index] = PdfResult(
                                    name=prev_name,
                                    ok=False,
                                    stage=Stage.WRITE.value,
                                    message=str(exc),
                                )
            else:
                output_mode = "N/A"
                output_format = "N/A"

            all_ok = all(result.ok for result in results)
            if all_ok:
                if dev_non_interactive:
                    safe_delete_dir(tmp_dir)
                else:
                    cleanup = _prompt_select(
                        "Delete tmp/ (Mindee JSON responses)?",
                        choices=[
                            ("Delete (default)", "delete"),
                            ("Keep for inspection", "keep"),
                        ],
                        default="delete",
                    )
                    if cleanup == "delete":
                        path_keep_reasons: list[tuple[Path, str | None]] = []
                        for i, item in enumerate(statements):
                            path = stem_to_tmp_path.get(item.name)
                            if path is None:
                                continue
                            result = sanity_results[i] if i < len(sanity_results) else None
                            if result is None:
                                path_keep_reasons.append((path, "SANITY absent (N_A)"))
                            elif is_clean_for_tmp_delete(result):
                                path_keep_reasons.append((path, None))
                            else:
                                path_keep_reasons.append((path, tmp_keep_reason(result)))
                        kept = selective_tmp_cleanup(path_keep_reasons)
                        if kept:
                            console.print(
                                Panel.fit(
                                    "\n".join(f"Kept: {line}" for line in kept),
                                    title="tmp/ files kept (not clean)",
                                    style="dim",
                                )
                            )
                    else:
                        console.print("[dim]tmp/ preserved for inspection[/dim]")
            else:
                if not dev_non_interactive:
                    keep = _prompt_select(
                        "Failures detected. Keep tmp/?",
                        choices=[("Keep tmp/ (default)", "keep"), ("Delete tmp/", "delete")],
                        default="keep",
                    )
                    if keep == "delete":
                        safe_delete_dir(tmp_dir)

            if not dev_mode and sources:
                run_date = date.today().isoformat()
                processed_dir = base_dir / "processed" / run_date
                failed_dir = base_dir / "failed" / run_date
                moved_ok = 0
                moved_fail = 0
                skipped_locked = 0
                for source_path, result in zip(sources, results):
                    if not source_path.exists():
                        continue
                    try:
                        if result.ok:
                            processed_dir.mkdir(parents=True, exist_ok=True)
                            shutil.move(
                                str(source_path),
                                str(processed_dir / source_path.name),
                            )
                            moved_ok += 1
                        else:
                            failed_dir.mkdir(parents=True, exist_ok=True)
                            shutil.move(
                                str(source_path),
                                str(failed_dir / source_path.name),
                            )
                            moved_fail += 1
                    except PermissionError:
                        skipped_locked += 1
                        console.print(
                            f"[yellow]Could not move {source_path.name} "
                            "(file in use — close the PDF viewer?).[/yellow]"
                        )
                if moved_ok or moved_fail or skipped_locked:
                    msg = (
                        f"[dim]Moved {moved_ok} to processed/{run_date}/, "
                        f"{moved_fail} to failed/{run_date}/[/dim]"
                    )
                    if skipped_locked:
                        msg += f" [yellow]{skipped_locked} could not be moved (file in use).[/yellow]"
                    console.print(msg)

            fitid_to_json: dict[str, tuple[str, int, int]] = {}
            for item in statements:
                lines_list = json_transaction_lines.get(item.name, [])
                tmp_path = stem_to_tmp_path.get(item.name)
                for idx, tx in enumerate(item.statement.get("transactions", [])):
                    fid = tx.get("fitid")
                    if not fid:
                        continue
                    one_based = idx + 1
                    json_line = lines_list[idx] if idx < len(lines_list) else 0
                    path_str = str(tmp_path) if tmp_path else ""
                    fitid_to_json[fid] = (path_str, one_based, json_line)

            render_summary(
                console,
                results=results,
                output_files=output_files,
                issues=issues,
                output_mode=output_mode,
                output_format=output_format,
                elapsed=timer.elapsed,
                pdf_notes=pdf_notes,
                total_transactions=sum(
                    len(item.statement.get("transactions", [])) for item in statements
                ),
                sanity_results=sanity_results,
                fitid_lines=fitid_lines,
                fitid_to_json=fitid_to_json,
            )
            if not output_files:
                console.print(
                    Panel.fit(
                        "No OFX files were generated — all PDFs failed or produced no "
                        "usable transactions.",
                        title="ERROR",
                        style="red",
                    )
                )
                raise typer.Exit(code=1)
        except UserAbort:
            console.print("Aborted by user. tmp/ preserved.")
            return
        except StageError as exc:
            console.print(str(exc))
            return


if __name__ == "__main__":
    app()

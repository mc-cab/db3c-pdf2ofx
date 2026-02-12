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
from rich.console import Console
from rich.panel import Panel

from pdf2ofx.converters.ofx_emitter import emit_ofx
from pdf2ofx.handlers.mindee_handler import infer_pdf
from pdf2ofx.helpers.errors import Stage, StageError
from pdf2ofx.helpers.fs import (
    ensure_dirs,
    list_pdfs,
    load_local_settings,
    normalize_ofx_filename,
    open_path_in_default_app,
    safe_delete_dir,
    safe_write_bytes,
    save_local_settings,
    timestamp_slug,
    tmp_json_path,
    transaction_line_numbers,
    write_json,
)
from pdf2ofx.helpers.reporting import Issue, Severity
from pdf2ofx.helpers.timing import Timer
from pdf2ofx.helpers.ui import PdfResult, render_banner, render_summary
from pdf2ofx.normalizers.canonicalize import NormalizationError, canonicalize_mindee
from pdf2ofx.sanity.checks import SanityResult, compute_sanity
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


@dataclass
class ProcessItem:
    name: str
    statement: dict


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
) -> SanityResult:
    """Run the SANITY stage: compute, display, confirm.

    Returns the final SanityResult after operator confirmation.
    Does **not** mutate *statement*.
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
            ("Skip reconciliation", "skip"),
        ]
        if source_path is not None and source_path.exists():
            choices.append(("Open source PDF", "open"))
        action = _prompt_select(
            "Sanity check:",
            choices=choices,
            default="accept",
        )

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

        # action == "accept"
        if result.reconciliation_status == "ERROR":
            force = _prompt_confirm(
                "Reconciliation ERROR detected — force accept?", False,
            )
            if not force:
                continue
        return result


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
) -> None:
    _load_env()
    render_banner(console)
    dev_mode = bool(dev_canonical)

    with Timer() as timer:
        try:
            if not dev_non_interactive:
                _prompt_select(
                    "Start pdf2ofx?",
                    choices=[("Process PDFs", "start")],
                    default="start",
                )

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
                        safe_delete_dir(tmp_dir)
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
                for source_path, result in zip(sources, results):
                    if not source_path.exists():
                        continue
                    if result.ok:
                        processed_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source_path), str(processed_dir / source_path.name))
                        moved_ok += 1
                    else:
                        failed_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source_path), str(failed_dir / source_path.name))
                        moved_fail += 1
                if moved_ok or moved_fail:
                    console.print(
                        f"[dim]Moved {moved_ok} to processed/{run_date}/, "
                        f"{moved_fail} to failed/{run_date}/[/dim]"
                    )

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

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
    safe_delete_dir,
    safe_write_bytes,
    save_local_settings,
    timestamp_slug,
    write_json,
)
from pdf2ofx.helpers.reporting import Issue, Severity
from pdf2ofx.helpers.timing import Timer
from pdf2ofx.helpers.ui import PdfResult, render_banner, render_summary
from pdf2ofx.normalizers.canonicalize import NormalizationError, canonicalize_mindee
from pdf2ofx.normalizers.fitid import assign_fitids
from pdf2ofx.validators.contract_validator import ValidationError, validate_statement

app = typer.Typer(add_completion=False)
console = Console()


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
    tmp_dir: Path,
    account_defaults: dict,
) -> tuple[dict, list[str]]:
    raw = infer_pdf(api_key, model_id, pdf_path)
    write_json(tmp_dir / f"{pdf_path.stem}.json", raw)
    normalization = canonicalize_mindee(raw, account_defaults=account_defaults)
    return normalization.statement, normalization.warnings


def _process_dev_canonical(
    canonical_path: Path,
    tmp_dir: Path,
) -> dict:
    with canonical_path.open("r", encoding="utf-8") as handle:
        statement = json.load(handle)
    write_json(tmp_dir / f"{canonical_path.stem}.json", {"dev_mode": True})
    return statement


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
                    if dev_mode:
                        statement = _process_dev_canonical(source, tmp_dir)
                        per_warnings: list[str] = []
                    else:
                        statement, per_warnings = _process_raw_pdf(
                            source, api_key, model_id, tmp_dir, settings
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
                            out_path = output_dir / f"{item.name}.ofx"
                            safe_write_bytes(out_path, payload)
                            output_files.append(str(out_path))
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
                        merged["transactions"] = original_transactions
                    payload = emit_ofx(merged, output_format)
                    out_path = output_dir / f"concat_{timestamp_slug()}.ofx"
                    safe_write_bytes(out_path, payload)
                    output_files.append(str(out_path))
            else:
                output_mode = "N/A"
                output_format = "N/A"

            all_ok = all(result.ok for result in results)
            if all_ok:
                safe_delete_dir(tmp_dir)
            else:
                if not dev_non_interactive:
                    keep = _prompt_select(
                        "Failures detected. Keep tmp/?",
                        choices=[("Keep tmp/ (default)", "keep"), ("Delete tmp/", "delete")],
                        default="keep",
                    )
                    if keep == "delete":
                        safe_delete_dir(tmp_dir)

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

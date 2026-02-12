from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pdf2ofx.helpers.reporting import Issue, Severity

if TYPE_CHECKING:
    from pdf2ofx.sanity.checks import SanityResult

@dataclass
class PdfResult:
    name: str
    ok: bool
    stage: str
    message: str


def render_banner(console: Console) -> None:
    console.print(Panel.fit("pdf2ofx — Mindee → JSON → OFX", style="bold cyan"))


_PDF_NAME_MAX = 50


def _truncate(text: str, max_len: int = _PDF_NAME_MAX) -> str:
    """Truncate text with ellipsis if it exceeds *max_len*."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _format_fitid(
    fitid: str,
    fitid_lines: dict[str, int] | None,
    fitid_to_json: dict[str, tuple[str, int, int]] | None = None,
) -> str:
    """Format a FITID with index, OFX line, and JSON path:line for navigation."""
    parts: list[str] = []
    json_info = (fitid_to_json or {}).get(fitid)
    if json_info:
        path_str, one_based_index, json_line = json_info
        parts.append(f"#{one_based_index}")
    parts.append(fitid)
    if fitid_lines and fitid in fitid_lines:
        parts.append(f"(OFX L:{fitid_lines[fitid]})")
    if json_info:
        _, _, json_line = json_info
        if json_line > 0:
            short = Path(path_str)
            display_path = f"{short.parent.name}/{_truncate(short.name, 45)}"
            parts.append(f"· {display_path}:{json_line}")
    if len(parts) == 1:
        return fitid
    return " ".join(parts)


def render_summary(
    console: Console,
    results: Iterable[PdfResult],
    output_files: list[str],
    issues: list[Issue],
    output_mode: str,
    output_format: str,
    elapsed: float,
    pdf_notes: dict[str, list[str]],
    total_transactions: int,
    sanity_results: list[SanityResult] | None = None,
    fitid_lines: dict[str, int] | None = None,
    fitid_to_json: dict[str, tuple[str, int, int]] | None = None,
) -> None:
    table = Table(title="Batch Summary", show_lines=True)
    table.add_column("Source PDF")
    table.add_column("Status")
    table.add_column("Stage")
    table.add_column("Hint")

    processed = 0
    for result in results:
        processed += 1
        status = "OK" if result.ok else "FAIL"
        table.add_row(_truncate(result.name), status, result.stage, result.message)

    console.print(table)
    console.print(
        Panel.fit(
            f"Processed: {processed}\n"
            f"Output mode: {output_mode}\n"
            f"Output format: {output_format}\n"
            f"Execution time: {elapsed:.2f}s",
            title="Run Info",
        )
    )
    if output_files:
        console.print(Panel.fit("\n".join(output_files), title="Generated OFX"))

    warning_count = sum(
        issue.count or len(issue.fitids)
        for issue in issues
        if issue.severity == Severity.WARNING
    )
    error_count = sum(
        issue.count or len(issue.fitids)
        for issue in issues
        if issue.severity == Severity.ERROR
    )
    ok_count = max(total_transactions - warning_count - error_count, 0)

    # Quality indicator — prefer sanity score, fall back to heuristic
    if sanity_results:
        worst = min(sanity_results, key=lambda r: r.quality_score)
        quality = worst.quality_label
        quality_detail = f"{quality} ({worst.quality_score}/100)"
        any_skipped = any(r.skipped for r in sanity_results)
        if any_skipped:
            quality_detail += " — SANITY skipped for some PDFs → downgraded"
        quality_style = {"GOOD": "green", "DEGRADED": "yellow", "POOR": "red"}.get(
            quality, "dim"
        )
    else:
        quality = "GOOD"
        if total_transactions:
            error_ratio = error_count / total_transactions
            warning_ratio = warning_count / total_transactions
            if error_ratio >= 0.2:
                quality = "POOR"
            elif warning_ratio >= 0.1:
                quality = "DEGRADED"
        quality_detail = f"{quality} (SANITY skipped → downgraded)"
        quality_style = "yellow"

    severity_table = Table(title="Validation Summary", show_lines=True)
    severity_table.add_column("Severity")
    severity_table.add_column("Affected Transactions")
    severity_table.add_column("FITIDs")

    severity_table.add_row("OK", str(ok_count), "-")
    for severity in (Severity.WARNING, Severity.ERROR):
        fitids: list[str] = []
        count = 0
        for issue in issues:
            if issue.severity != severity:
                continue
            count += issue.count or len(issue.fitids)
            fitids.extend(issue.fitids)
        formatted = [
            _format_fitid(f, fitid_lines, fitid_to_json) for f in fitids[:10]
        ]
        fitid_display = "\n".join(formatted) if formatted else "-"
        if len(fitids) > 10:
            fitid_display = f"{fitid_display}\n... (+{len(fitids) - 10} more)"
        severity_table.add_row(severity.value, str(count), fitid_display)

    console.print(severity_table)
    console.print(
        Panel.fit(f"Quality: {quality_detail}", title="Quality Indicator", style=quality_style)
    )

    if issues:
        for issue in issues:
            if issue.reason.startswith("FITID collisions detected"):
                formatted_col = [
                    _format_fitid(f, fitid_lines, fitid_to_json)
                    for f in issue.fitids[:10]
                ]
                fitid_display = ", ".join(formatted_col) if formatted_col else "-"
                if issue.fitids and len(issue.fitids) > 10:
                    fitid_display = (
                        f"{fitid_display}, ... (+{len(issue.fitids) - 10} more)"
                    )
                console.print(
                    Panel.fit(
                        f"FITID collisions detected: {issue.count}\n"
                        f"Affected FITIDs: {fitid_display}\n"
                        "Some importers may drop or overwrite transactions with duplicate "
                        "FITIDs.",
                        title="WARNING",
                        style="yellow",
                    )
                )
                break
        issues_table = Table(title="Issue Details", show_lines=True)
        issues_table.add_column("Severity")
        issues_table.add_column("Reason")
        issues_table.add_column("Count")
        issues_table.add_column("FITIDs")
        for issue in issues:
            formatted_ids = [
                _format_fitid(f, fitid_lines, fitid_to_json)
                for f in issue.fitids[:10]
            ]
            fitid_display = "\n".join(formatted_ids) if formatted_ids else "-"
            if issue.fitids and len(issue.fitids) > 10:
                fitid_display = f"{fitid_display}\n... (+{len(issue.fitids) - 10} more)"
            issues_table.add_row(
                issue.severity.value,
                issue.reason,
                str(issue.count or len(issue.fitids)),
                fitid_display,
            )
        console.print(issues_table)

    if pdf_notes:
        notes_lines = []
        for pdf_name, notes in pdf_notes.items():
            if notes:
                notes_lines.append(f"{pdf_name}: {', '.join(notes)}")
        if notes_lines:
            console.print(
                Panel.fit("\n".join(notes_lines), title="Per-PDF Warning Notes", style="yellow")
            )

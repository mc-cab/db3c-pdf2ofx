from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helpers.reporting import Issue, Severity

@dataclass
class PdfResult:
    name: str
    ok: bool
    stage: str
    message: str


def render_banner(console: Console) -> None:
    console.print(Panel.fit("pdf2ofx — Mindee → JSON → OFX", style="bold cyan"))


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
) -> None:
    table = Table(title="Batch Summary", show_lines=True)
    table.add_column("PDF")
    table.add_column("Status")
    table.add_column("Stage")
    table.add_column("Hint")

    processed = 0
    for result in results:
        processed += 1
        status = "OK" if result.ok else "FAIL"
        table.add_row(result.name, status, result.stage, result.message)

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

    quality = "GOOD"
    if total_transactions:
        error_ratio = error_count / total_transactions
        warning_ratio = warning_count / total_transactions
        if error_ratio >= 0.2:
            quality = "POOR"
        elif warning_ratio >= 0.1:
            quality = "DEGRADED"

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
        fitid_display = ", ".join(fitids[:10]) if fitids else "-"
        if len(fitids) > 10:
            fitid_display = f"{fitid_display}, ... (+{len(fitids) - 10} more)"
        severity_table.add_row(severity.value, str(count), fitid_display)

    console.print(severity_table)
    console.print(Panel.fit(f"Overall quality: {quality}", title="Quality Indicator"))

    if issues:
        for issue in issues:
            if issue.reason.startswith("FITID collisions detected"):
                fitid_display = ", ".join(issue.fitids[:10]) if issue.fitids else "-"
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
            fitid_display = ", ".join(issue.fitids[:10]) if issue.fitids else "-"
            if issue.fitids and len(issue.fitids) > 10:
                fitid_display = f"{fitid_display}, ... (+{len(issue.fitids) - 10} more)"
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

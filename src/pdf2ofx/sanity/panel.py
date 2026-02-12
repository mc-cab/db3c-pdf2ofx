"""Sanity & Reconciliation Layer — Rich panel rendering.

Display-only.  No computation, no mutations, no prompts.
"""
from __future__ import annotations

from decimal import Decimal

from rich.console import Console
from rich.panel import Panel

from pdf2ofx.sanity.checks import SanityResult


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_amount(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    sign = "+" if amount >= 0 else ""
    return f"{sign}{amount:,.2f}"


def _fmt_balance(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    return f"{amount:,.2f}"


def _recon_symbol(status: str) -> str:
    return {"OK": "✓", "WARNING": "⚠", "ERROR": "✗"}.get(status, "—")


def _panel_style(result: SanityResult) -> str:
    """Pick the panel border colour from the most severe signal."""
    if result.reconciliation_status == "ERROR":
        return "red"
    if result.reconciliation_status == "WARNING":
        return "yellow"
    if result.quality_label == "POOR":
        return "red"
    if result.quality_label == "DEGRADED":
        return "yellow"
    return "green"


def _quality_colour(label: str) -> str:
    return {"GOOD": "green", "DEGRADED": "yellow", "POOR": "red"}.get(label, "dim")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_sanity_panel(console: Console, result: SanityResult) -> None:
    """Display the structured sanity summary panel for one PDF."""
    period = f"{result.period_start or '?'} → {result.period_end or '?'}"
    tx_line = (
        f"Extracted {result.extracted_count} | "
        f"Kept {result.kept_count} | "
        f"Dropped {result.dropped_count}"
    )
    totals_line = (
        f"{_fmt_amount(result.total_credits)} | "
        f"{_fmt_amount(result.total_debits)} | "
        f"Net {_fmt_amount(result.net_movement)}"
    )

    lines = [
        f"Period:         {period}",
        f"Transactions:   {tx_line}",
        f"Totals:         {totals_line}",
        "",
        f"Starting balance:  {_fmt_balance(result.starting_balance)}",
        f"Ending balance:    {_fmt_balance(result.ending_balance)}",
    ]

    if result.reconciliation_status != "SKIPPED":
        lines.append(f"Reconciled end:    {_fmt_balance(result.reconciled_end)}")
        delta_display = _fmt_balance(
            abs(result.delta) if result.delta is not None else None
        )
        symbol = _recon_symbol(result.reconciliation_status)
        lines.append(f"Delta:             {delta_display}   {symbol}")
    else:
        lines.append("Reconciliation:    SKIPPED (balances not available)")

    lines.append("")
    q_colour = _quality_colour(result.quality_label)
    lines.append(
        f"Quality: [{q_colour}]{result.quality_label}[/{q_colour}] "
        f"({result.quality_score}/100)"
    )

    if result.deductions:
        for reason, points in result.deductions:
            lines.append(f"  [dim]{points:+d}  {reason}[/dim]")

    if result.warnings:
        lines.append("")
        for w in result.warnings:
            lines.append(f"  ⚠ {w}")

    console.print(
        Panel.fit(
            "\n".join(lines),
            title=f"SANITY: {result.pdf_name}",
            style=_panel_style(result),
        )
    )

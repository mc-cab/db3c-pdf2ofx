from __future__ import annotations

from unittest.mock import patch

from pathlib import Path

from typer.testing import CliRunner

from pdf2ofx.cli import _run_sanity_stage, app


def test_cli_smoke(tmp_path: Path) -> None:
    base_dir = tmp_path / "pdf2ofx"
    (base_dir / "input").mkdir(parents=True)
    (base_dir / "output").mkdir(parents=True)
    (base_dir / "tmp").mkdir(parents=True)

    fixture = Path(__file__).parent / "fixtures" / "canonical_statement.json"
    canonical_a = base_dir / "statement_a.json"
    canonical_b = base_dir / "statement_b.json"
    canonical_a.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    canonical_b.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--dev-canonical",
            str(canonical_a),
            "--dev-canonical",
            str(canonical_b),
            "--dev-non-interactive",
            "--dev-simulate-failure",
            "--base-dir",
            str(base_dir),
        ],
    )

    assert result.exit_code == 0
    ofx_files = list((base_dir / "output").glob("*.ofx"))
    assert len(ofx_files) == 1, f"Expected 1 OFX file, got {ofx_files}"
    assert ofx_files[0].name.startswith("ACC123_2024-01-31_")
    assert (base_dir / "tmp").exists()


def _minimal_statement() -> dict:
    return {
        "schema_version": "1.0",
        "account": {"account_id": "ACC-123", "bank_id": "B", "account_type": "CHECKING", "currency": "EUR"},
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {"fitid": "F1", "posted_at": "2024-01-05", "amount": "-10.00", "debit": "10.00", "credit": None, "name": "X", "memo": "", "trntype": "DEBIT"},
        ],
    }


def test_sanity_stage_includes_open_source_pdf_when_source_path_exists(tmp_path: Path) -> None:
    """With source_path set and existing, SANITY menu includes 'Open source PDF' (v0.1.2)."""
    from rich.console import Console

    source_pdf = tmp_path / "stmt.pdf"
    source_pdf.write_bytes(b"")
    captured_choices: list[list[tuple[str, str]]] = []

    def capture_and_accept(message: str, choices: list[tuple[str, str]], default: str) -> str:
        captured_choices.append(choices)
        return "accept"

    with patch("pdf2ofx.cli._prompt_select", side_effect=capture_and_accept):
        _run_sanity_stage(
            console=Console(),
            statement=_minimal_statement(),
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=source_pdf,
            recovery_mode=False,
        )
    assert len(captured_choices) >= 1
    choice_values = [v for _, v in captured_choices[0]]
    assert "open" in choice_values


def test_sanity_stage_auto_opens_pdf_on_edit_balances(tmp_path: Path) -> None:
    """When user chooses Edit balances and source_path exists, open_path_in_default_app is called (v0.1.2)."""
    from unittest.mock import MagicMock

    from rich.console import Console

    source_pdf = tmp_path / "stmt.pdf"
    source_pdf.write_bytes(b"")

    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit", "accept"]), patch(
        "pdf2ofx.cli._prompt_text", return_value=""
    ), patch("pdf2ofx.cli.open_path_in_default_app", MagicMock()) as mock_open:
        _run_sanity_stage(
            console=Console(),
            statement=_minimal_statement(),
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=source_pdf,
            recovery_mode=False,
        )
        mock_open.assert_called_once_with(source_pdf)


def test_sanity_stage_edit_balances_back_returns_to_menu(tmp_path: Path) -> None:
    """Edit balances → ← Back returns to SANITY menu without prompting for numbers (P0 UX)."""
    from rich.console import Console

    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "back", "accept"]):
        result = _run_sanity_stage(
            console=Console(),
            statement=_minimal_statement(),
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None


def test_sanity_stage_edit_tx_back_returns_to_menu(tmp_path: Path) -> None:
    """Edit transactions → ← Back returns to SANITY menu; then Accept completes (P0 UX)."""
    from rich.console import Console

    # Main menu → edit_tx, then submenu → back, then main menu → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit_tx", "back", "accept"]):
        result = _run_sanity_stage(
            console=Console(),
            statement=_minimal_statement(),
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None

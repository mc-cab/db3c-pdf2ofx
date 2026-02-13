from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _statement_with_three_tx() -> dict:
    """Statement with 3 transactions (indices 0, 1, 2) for triage tests."""
    return {
        "schema_version": "1.0",
        "account": {"account_id": "ACC-123", "bank_id": "B", "account_type": "CHECKING", "currency": "EUR"},
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {"fitid": "F1", "posted_at": "2024-01-05", "amount": "-10.00", "debit": "10.00", "credit": None, "name": "Tx0", "memo": "", "trntype": "DEBIT"},
            {"fitid": "F2", "posted_at": "2024-01-10", "amount": "50.00", "debit": None, "credit": "50.00", "name": "Tx1", "memo": "", "trntype": "CREDIT"},
            {"fitid": "F3", "posted_at": "2024-01-15", "amount": "-25.00", "debit": "25.00", "credit": None, "name": "Tx2", "memo": "", "trntype": "DEBIT"},
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


def test_sanity_triage_valid_then_edit_shows_only_non_valid(tmp_path: Path) -> None:
    """Mark some transactions valid via triage; Edit transactions shows only non-valid (v0.1.3)."""
    from rich.console import Console

    captured_select_choices: list[list] = []

    def mock_select(message=None, choices=None, **kwargs):
        captured_select_choices.append(choices)
        result = MagicMock()
        result.execute.return_value = "__back__"
        return result

    # Main → triage → Validate → checkbox [0] → confirm → main → edit_tx → edit_one (back)
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "triage", "triage_validate",
        "edit_tx", "edit_one",
        "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0]))), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
    ), patch("pdf2ofx.cli.inquirer.select", side_effect=mock_select):
        result = _run_sanity_stage(
            console=Console(),
            statement=_statement_with_three_tx(),
            pdf_name="stmt.pdf",
            extracted_count=3,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    # Edit-one select was called with choices: Back + filtered indices (only 1, 2)
    assert len(captured_select_choices) >= 1
    choices = captured_select_choices[-1]
    values = [getattr(c, "value", c) for c in choices]
    tx_values = [v for v in values if v != "__back__"]
    assert set(tx_values) == {1, 2}


def test_sanity_triage_flagged_then_edit_shows_only_flagged(tmp_path: Path) -> None:
    """Mark some transactions flagged via triage; Edit transactions shows only flagged (v0.1.3)."""
    from rich.console import Console

    captured_select_choices: list[list] = []

    def mock_select(message=None, choices=None, **kwargs):
        captured_select_choices.append(choices)
        result = MagicMock()
        result.execute.return_value = "__back__"
        return result

    # Main → triage → Flag → checkbox [0, 2] → confirm → main → edit_tx → edit_one (back)
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "triage", "triage_flag",
        "edit_tx", "edit_one",
        "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0, 2]))), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
    ), patch("pdf2ofx.cli.inquirer.select", side_effect=mock_select):
        result = _run_sanity_stage(
            console=Console(),
            statement=_statement_with_three_tx(),
            pdf_name="stmt.pdf",
            extracted_count=3,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    choices = captured_select_choices[-1]
    values = [getattr(c, "value", c) for c in choices]
    tx_values = [v for v in values if v != "__back__"]
    assert set(tx_values) == {0, 2}


def test_sanity_triage_flag_priority_over_valid(tmp_path: Path) -> None:
    """When both valid and flagged exist, Edit transactions shows only flagged (v0.1.3)."""
    from rich.console import Console

    captured_select_choices: list[list] = []

    def mock_select(message=None, choices=None, **kwargs):
        captured_select_choices.append(choices)
        result = MagicMock()
        result.execute.return_value = "__back__"
        return result

    # Main → triage → Validate [0,1] → triage → Flag [1,2] → main → edit_tx → edit_one (back)
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "triage", "triage_validate",
        "triage", "triage_flag",
        "edit_tx", "edit_one",
        "accept",
    ]), patch(
        "pdf2ofx.cli.inquirer.checkbox",
        side_effect=[
            MagicMock(execute=MagicMock(return_value=[0, 1])),  # validate
            MagicMock(execute=MagicMock(return_value=[1, 2])),  # flag
        ],
    ), patch("pdf2ofx.cli._prompt_confirm", return_value=True), patch(
        "pdf2ofx.cli.inquirer.select", side_effect=mock_select
    ):
        result = _run_sanity_stage(
            console=Console(),
            statement=_statement_with_three_tx(),
            pdf_name="stmt.pdf",
            extracted_count=3,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    choices = captured_select_choices[-1]
    values = [getattr(c, "value", c) for c in choices]
    tx_values = [v for v in values if v != "__back__"]
    assert set(tx_values) == {1, 2}


def test_sanity_triage_all_valid_then_edit_shows_empty_message(tmp_path: Path) -> None:
    """When all transactions are validated, Edit transactions shows empty message and returns to menu (v0.1.3)."""
    mock_console = MagicMock()

    # Main → triage → Validate [0,1,2] → confirm → main → edit_tx (empty filter) → main → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "triage", "triage_validate",
        "edit_tx",
        "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0, 1, 2]))), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
    ):
        result = _run_sanity_stage(
            console=mock_console,
            statement=_statement_with_three_tx(),
            pdf_name="stmt.pdf",
            extracted_count=3,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    messages = [str(c[0][0]) for c in mock_console.print.call_args_list if c[0]]
    assert any("No transactions match current triage filter" in m for m in messages)

from __future__ import annotations

from decimal import Decimal
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


def _statement_one_tx_amount_100() -> dict:
    """One transaction with amount 100 for invert-sign tests (v0.1.4)."""
    return {
        "schema_version": "1.0",
        "account": {"account_id": "ACC-123", "bank_id": "B", "account_type": "CHECKING", "currency": "EUR"},
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {"fitid": "F1", "posted_at": "2024-01-05", "amount": Decimal("100.00"), "debit": None, "credit": "100.00", "name": "Y", "memo": "", "trntype": "CREDIT"},
        ],
    }


def _statement_one_tx_debit_credit() -> dict:
    """One transaction with debit set for invert debit/credit swap test (v0.1.4)."""
    return {
        "schema_version": "1.0",
        "account": {"account_id": "ACC-123", "bank_id": "B", "account_type": "CHECKING", "currency": "EUR"},
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {"fitid": "F1", "posted_at": "2024-01-05", "amount": Decimal("-10.00"), "debit": "10.00", "credit": None, "name": "Z", "memo": "", "trntype": "DEBIT"},
        ],
    }


def test_sanity_stage_includes_open_source_pdf_when_source_path_exists(tmp_path: Path) -> None:
    """With source_path set and existing, SANITY menu includes Edit and Preview source file (v0.1.4)."""
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
    choice_labels = [lbl for lbl, _ in captured_choices[0]]
    choice_values = [v for _, v in captured_choices[0]]
    assert "edit" in choice_values
    assert any("Preview source file" in lbl for lbl in choice_labels)
    assert "open" in choice_values


def test_sanity_stage_auto_opens_pdf_on_edit_balances(tmp_path: Path) -> None:
    """When user chooses Edit then Edit balances and source_path exists, open_path_in_default_app is called (v0.1.4)."""
    from unittest.mock import MagicMock

    from rich.console import Console

    source_pdf = tmp_path / "stmt.pdf"
    source_pdf.write_bytes(b"")

    # Main → Edit → Edit submenu edit_bal → balance submenu edit → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_bal", "edit", "accept"]), patch(
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
    """Edit → Edit balances → ← Back returns to SANITY menu without prompting for numbers (P0 UX)."""
    from rich.console import Console

    # Main → Edit → Edit submenu back → accept
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
    """Edit → Edit transactions → ← Back returns to SANITY menu; then Accept completes (P0 UX)."""
    from rich.console import Console

    # Main → Edit → edit_tx → Edit transactions submenu back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_tx", "back", "accept"]):
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

    # Main → Edit → triage → Validate → checkbox [0] → confirm → main → Edit → edit_tx → edit_one (inquirer returns back) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "edit", "edit_tx", "edit_one",
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

    # Main → Edit → triage → Flag → checkbox [0, 2] → confirm → main → Edit → edit_tx → edit_one (inquirer returns back) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_flag",
        "edit", "edit_tx", "edit_one",
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

    # Main → Edit → triage → Validate [0,1] → Edit → triage → Flag [1,2] → main → Edit → edit_tx → edit_one (inquirer back) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "edit", "triage", "triage_flag",
        "edit", "edit_tx", "edit_one",
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

    # Main → Edit → triage → Validate [0,1,2] → confirm → main → Edit → edit_tx (empty filter) → main → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "edit", "edit_tx",
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


def test_sanity_hierarchical_menu_main_and_edit_submenu(tmp_path: Path) -> None:
    """Main menu has Accept, Edit, Preview source file, Skip; Edit submenu has Edit balances, Edit transactions, Transaction triage, Back (v0.1.4)."""
    from rich.console import Console

    source_pdf = tmp_path / "stmt.pdf"
    source_pdf.write_bytes(b"")
    captured: list[tuple[str, list[tuple[str, str]]]] = []
    sequence = iter(["edit", "back", "accept"])

    def capture_and_go(message: str, choices: list[tuple[str, str]], default: str) -> str:
        captured.append((message, list(choices)))
        return next(sequence)

    with patch("pdf2ofx.cli._prompt_select", side_effect=capture_and_go):
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
    main_choices = next((c for msg, c in captured if "Sanity check" in msg), None)
    assert main_choices is not None
    labels_main = [lbl for lbl, _ in main_choices]
    values_main = [v for _, v in main_choices]
    assert any("Accept" in lbl for lbl in labels_main)
    assert "edit" in values_main
    assert any("Preview source file" in lbl for lbl in labels_main)
    assert any("Skip" in lbl for lbl in labels_main)
    edit_choices = next((c for msg, c in captured if msg.strip() == "Edit:"), None)
    assert edit_choices is not None
    values_edit = [v for _, v in edit_choices]
    assert "edit_bal" in values_edit
    assert "edit_tx" in values_edit
    assert "triage" in values_edit
    assert "back" in values_edit


def test_sanity_invert_sign_negates_amount(tmp_path: Path) -> None:
    """Edit → Edit transactions → select tx → Invert sign: amount becomes -100 (v0.1.4)."""
    from rich.console import Console

    stmt = _statement_one_tx_amount_100()
    # Main → Edit → edit_tx → edit_one → select idx 0 → invert_sign → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "edit_tx", "edit_one",
        "invert_sign",
        "accept",
    ]), patch("pdf2ofx.cli.inquirer.select", return_value=MagicMock(execute=MagicMock(return_value=0))):
        result = _run_sanity_stage(
            console=Console(),
            statement=stmt,
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    assert stmt["transactions"][0]["amount"] == Decimal("-100.00")
    assert stmt["transactions"][0]["trntype"] == "DEBIT"


def test_sanity_invert_sign_swaps_debit_credit(tmp_path: Path) -> None:
    """Invert sign swaps debit/credit and keeps Decimal (v0.1.4)."""
    from rich.console import Console

    stmt = _statement_one_tx_debit_credit()
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "edit_tx", "edit_one",
        "invert_sign",
        "accept",
    ]), patch("pdf2ofx.cli.inquirer.select", return_value=MagicMock(execute=MagicMock(return_value=0))):
        result = _run_sanity_stage(
            console=Console(),
            statement=stmt,
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    tx = stmt["transactions"][0]
    assert tx["amount"] == Decimal("10.00")
    assert tx["trntype"] == "CREDIT"
    assert tx["debit"] is None
    assert tx["credit"] == "10.00"
    assert not isinstance(tx["amount"], float)


def test_sanity_triage_and_invert_sign_filter_unchanged(tmp_path: Path) -> None:
    """Flag one tx, edit → edit_tx, select it, invert sign; triage filter still shows only that tx (v0.1.4)."""
    from rich.console import Console

    captured_select_choices: list[list] = []

    def mock_select(message=None, choices=None, **kwargs):
        captured_select_choices.append(choices)
        # First call: transaction list (filtered to index 0) → select 0
        # Second call: after invert, we're back at main; user goes edit → edit_tx → list again → return back
        if len(captured_select_choices) == 1:
            return MagicMock(execute=MagicMock(return_value=0))
        return MagicMock(execute=MagicMock(return_value="__back__"))

    # Main → Edit → triage → Flag [0] → main → Edit → edit_tx → edit_one → select 0 → invert_sign → main → Edit → edit_tx → edit_one → back
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_flag",
        "edit", "edit_tx", "edit_one",
        "invert_sign",
        "edit", "edit_tx", "edit_one",
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
    assert len(captured_select_choices) >= 2
    # Second time we see the transaction list it should still be filtered to index 0 only
    second_list = captured_select_choices[1]
    values = [getattr(c, "value", c) for c in second_list]
    tx_values = [v for v in values if v != "__back__"]
    assert set(tx_values) == {0}

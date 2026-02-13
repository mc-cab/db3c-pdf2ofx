from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2ofx.cli import RecoveryBackRequested, _run_sanity_stage, app


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

    # L1 → Edit → edit_bal → balance edit → return to L2 → back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_bal", "edit", "back", "accept"]), patch(
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
    """Edit → Edit balances → ← Back returns to Edit submenu (L2); second Back to L1; then Accept (P0 UX)."""
    from rich.console import Console

    # L1 → Edit → L2 → Edit balances → Back (L2a→L2) → Back (L2→L1) → Accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_bal", "back", "back", "accept"]):
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
    """Edit → Edit transactions → ← Back returns to Edit submenu (L2); second Back to L1; then Accept (P0 UX)."""
    from rich.console import Console

    # L1 → Edit → L2 → edit_tx → L2b Back (→L2) → Back (→L1) → Accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_tx", "back", "back", "accept"]):
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

    # L1 → Edit → triage → Validate [0] → confirm → stay at L2 → edit_tx → edit_one (inquirer back) → back (L2b→L2) → back (L2→L1) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "edit_tx", "edit_one",
        "back", "back", "accept",
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

    # L1 → Edit → triage → Flag [0,2] → confirm → stay at L2 → edit_tx → edit_one (inquirer back) → back → back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_flag",
        "edit_tx", "edit_one",
        "back", "back", "accept",
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

    # L1 → Edit → triage Validate [0,1] → L2 → triage Flag [1,2] → L2 → edit_tx → edit_one (inquirer back) → back → back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "triage", "triage_flag",
        "edit_tx", "edit_one",
        "back", "back", "accept",
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

    # L1 → Edit → triage Validate [0,1,2] → confirm → L2 → edit_tx (empty filter, stay L2) → back (L2→L1) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_validate",
        "edit_tx",
        "back", "accept",
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
    # L1 → Edit → edit_tx → edit_one → select 0 → invert_sign → back at L3 → inquirer back → L2b back → L2 back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "edit_tx", "edit_one",
        "invert_sign",
        "back", "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.select", side_effect=[
        MagicMock(execute=MagicMock(return_value=0)),
        MagicMock(execute=MagicMock(return_value="__back__")),
    ]):
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
        "back", "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.select", side_effect=[
        MagicMock(execute=MagicMock(return_value=0)),
        MagicMock(execute=MagicMock(return_value="__back__")),
    ]):
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
        # First call: transaction list (filtered to index 0) → select 0. Second: after invert we're back at L3 → back
        if len(captured_select_choices) == 1:
            return MagicMock(execute=MagicMock(return_value=0))
        return MagicMock(execute=MagicMock(return_value="__back__"))

    # L1 → Edit → triage Flag [0] → L2 → edit_tx → edit_one → select 0 → invert_sign (return to L3) → back (L3→L2b) → back (L2b→L2) → back (L2→L1) → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_flag",
        "edit_tx", "edit_one",
        "invert_sign",
        "back", "back", "accept",
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


# --- Batch invert sign (v0.1.5) ---


def test_sanity_batch_invert_negates_multiple_tx(tmp_path: Path) -> None:
    """Edit → Invert transaction sign(s) → select multiple tx → confirm: amounts negated (v0.1.5)."""
    from rich.console import Console

    stmt = _statement_with_three_tx()
    # L1 → Edit → invert_sign_batch → checkbox [0, 2] → confirm → L2 → back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "invert_sign_batch",
        "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0, 2]))), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
    ):
        result = _run_sanity_stage(
            console=Console(),
            statement=stmt,
            pdf_name="stmt.pdf",
            extracted_count=3,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    assert result is not None
    # Tx0 was -10 DEBIT → +10 CREDIT; Tx2 was -25 DEBIT → +25 CREDIT
    assert stmt["transactions"][0]["amount"] == Decimal("10.00")
    assert stmt["transactions"][0]["trntype"] == "CREDIT"
    assert stmt["transactions"][2]["amount"] == Decimal("25.00")
    assert stmt["transactions"][2]["trntype"] == "CREDIT"
    # Tx1 unchanged (may still be string in statement)
    assert Decimal(str(stmt["transactions"][1]["amount"])) == Decimal("50.00")


def test_sanity_batch_invert_swaps_debit_credit(tmp_path: Path) -> None:
    """Batch invert swaps debit/credit fields correctly (v0.1.5)."""
    from rich.console import Console

    stmt = _statement_one_tx_debit_credit()
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "invert_sign_batch",
        "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0]))), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
    ):
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


def test_sanity_batch_invert_respects_triage_filter(tmp_path: Path) -> None:
    """Batch invert shows only triage-filtered transactions (e.g. flagged only) (v0.1.5)."""
    from rich.console import Console

    captured_choices: list[list] = []

    def capture_checkbox(message=None, choices=None, **kwargs):
        captured_choices.append(choices)
        # First call: triage flag → return [0, 2]. Second: batch invert → return [] (no mutate).
        if len(captured_choices) == 1:
            return MagicMock(execute=MagicMock(return_value=[0, 2]))
        return MagicMock(execute=MagicMock(return_value=[]))

    # L1 → Edit → triage Flag [0, 2] → L2 → invert_sign_batch (checkbox shows only 0, 2)
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "triage", "triage_flag",
        "invert_sign_batch",
        "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.checkbox", side_effect=capture_checkbox), patch(
        "pdf2ofx.cli._prompt_confirm", return_value=True
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
    # Second checkbox call is batch invert (first was triage flag)
    assert len(captured_choices) >= 2
    batch_choices = captured_choices[1]
    values = [getattr(c, "value", c) for c in batch_choices]
    assert set(values) == {0, 2}


def test_sanity_batch_invert_returns_to_l2(tmp_path: Path) -> None:
    """After batch invert, next prompt is L2 (Edit submenu), not L1 (v0.1.5)."""
    from rich.console import Console

    edit_prompts: list[str] = []

    def capture_edit(msg: str, choices: list[tuple[str, str]], default: str) -> str:
        if msg.strip() == "Edit:":
            edit_prompts.append(msg)
        return next(_batch_return_seq)

    _batch_return_seq = iter([
        "edit", "invert_sign_batch",
        "back", "accept",
    ])

    with patch("pdf2ofx.cli._prompt_select", side_effect=capture_edit), patch(
        "pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0]))
    ), patch("pdf2ofx.cli._prompt_confirm", return_value=True):
        _run_sanity_stage(
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
    # First Edit: when entering L2; second Edit: after batch invert (return to L2)
    assert len(edit_prompts) >= 2


# --- Navigation tests (hierarchical Back + return points) ---


def test_sanity_back_from_l4_returns_to_l3(tmp_path: Path) -> None:
    """Back from per-tx menu (L4) returns to transaction list (L3); then Back L3→L2b, L2b→L2, L2→L1, Accept."""
    from rich.console import Console

    captured: list[str] = []

    def capture_prompts(msg: str, choices: list[tuple[str, str]], default: str) -> str:
        captured.append(msg)
        return next(_back_l4_sequence)

    _back_l4_sequence = iter([
        "edit", "edit_tx", "edit_one",
        "back",   # L4 Back → L3 (inquirer next)
        "back", "back", "accept",  # L2b Back, L2 Back, L1 Accept
    ])

    with patch("pdf2ofx.cli._prompt_select", side_effect=capture_prompts), patch(
        "pdf2ofx.cli.inquirer.select",
        side_effect=[
            MagicMock(execute=MagicMock(return_value=0)),   # select tx (L3)
            MagicMock(execute=MagicMock(return_value="__back__")),  # L3 Back → L2b
        ],
    ):
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
    # After L4 Back we should see L3 again (inquirer), then L2b "Edit transactions:", then L2 "Edit:", then L1 "Sanity check:"
    assert "Edit transactions:" in captured
    assert "Edit:" in captured
    assert any("Sanity check" in m for m in captured)


def test_sanity_back_from_l3_returns_to_l2b(tmp_path: Path) -> None:
    """Back from Select transaction (L3) returns to Edit transactions menu (L2b); then Back→L2, Back→L1, Accept."""
    from rich.console import Console

    # L1 → Edit → edit_tx → edit_one → inquirer Back → L2b back → L2 back → accept
    with patch("pdf2ofx.cli._prompt_select", side_effect=[
        "edit", "edit_tx", "edit_one",
        "back", "back", "accept",
    ]), patch("pdf2ofx.cli.inquirer.select", return_value=MagicMock(execute=MagicMock(return_value="__back__"))):
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


def test_sanity_back_from_l2b_returns_to_l2(tmp_path: Path) -> None:
    """Back from Edit transactions (L2b) returns to Edit submenu (L2); then Back→L1, Accept."""
    from rich.console import Console

    with patch("pdf2ofx.cli._prompt_select", side_effect=["edit", "edit_tx", "back", "back", "accept"]):
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


def test_sanity_after_invert_returns_to_l3_not_l1(tmp_path: Path) -> None:
    """After Invert sign we return to transaction list (L3); next _prompt_select is L2b only after Back from L3."""
    from rich.console import Console

    order: list[str] = []

    def track(msg: str, choices: list[tuple[str, str]], default: str) -> str:
        order.append(msg.strip())
        return next(_invert_return_sequence)

    _invert_return_sequence = iter([
        "edit", "edit_tx", "edit_one",
        "invert_sign",
        "back", "back", "accept",
    ])

    with patch("pdf2ofx.cli._prompt_select", side_effect=track), patch("pdf2ofx.cli.inquirer.select", side_effect=[
        MagicMock(execute=MagicMock(return_value=0)),
        MagicMock(execute=MagicMock(return_value="__back__")),
    ]):
        _run_sanity_stage(
            console=Console(),
            statement=_statement_one_tx_amount_100(),
            pdf_name="stmt.pdf",
            extracted_count=1,
            raw_response=None,
            validation_issues=[],
            dev_non_interactive=False,
            source_path=None,
            recovery_mode=False,
        )
    # After invert we return to L3; when we Back from L3 we see L2b "Edit transactions:" before we Back to L1 "Sanity check:".
    # So the last "Edit transactions:" must appear before the last "Sanity check:".
    idx_edit_tx_last = max((i for i, m in enumerate(order) if m == "Edit transactions:"), default=None)
    idx_sanity_last = max((i for i, m in enumerate(order) if "Sanity check" in m), default=None)
    assert idx_edit_tx_last is not None and idx_sanity_last is not None
    assert idx_edit_tx_last < idx_sanity_last


def test_sanity_after_triage_confirm_returns_to_l2_not_l1(tmp_path: Path) -> None:
    """After triage Validate/Flag confirm we return to Edit submenu (L2); next prompt is Edit: with edit_tx/edit_bal/triage/back."""
    from rich.console import Console

    edit_prompts: list[tuple[str, list[tuple[str, str]]]] = []

    def capture_edit_prompts(msg: str, choices: list[tuple[str, str]], default: str) -> str:
        if msg.strip() == "Edit:":
            edit_prompts.append((msg, list(choices)))
        return next(_triage_return_sequence)

    _triage_return_sequence = iter([
        "edit", "triage", "triage_validate",
        "edit_tx", "back", "back", "accept",
    ])

    with patch("pdf2ofx.cli._prompt_select", side_effect=capture_edit_prompts), patch(
        "pdf2ofx.cli.inquirer.checkbox", return_value=MagicMock(execute=MagicMock(return_value=[0]))
    ), patch("pdf2ofx.cli._prompt_confirm", return_value=True):
        _run_sanity_stage(
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
    # First "Edit:" when we enter L2; second "Edit:" after triage confirm (return to L2, not L1).
    assert len(edit_prompts) >= 2
    _, choices_after_triage = edit_prompts[1]
    values = [v for _, v in choices_after_triage]
    assert "edit_tx" in values and "back" in values


def test_sanity_recovery_back_to_list_exits_sanity(tmp_path: Path) -> None:
    """In recovery_mode, choosing Back to list at L1 raises RecoveryBackRequested (exit SANITY to list)."""
    from rich.console import Console

    with patch("pdf2ofx.cli._prompt_select", return_value="back_to_list"):
        with pytest.raises(RecoveryBackRequested):
            _run_sanity_stage(
                console=Console(),
                statement=_minimal_statement(),
                pdf_name="stmt.pdf",
                extracted_count=1,
                raw_response=None,
                validation_issues=[],
                dev_non_interactive=False,
                source_path=None,
                recovery_mode=True,
            )

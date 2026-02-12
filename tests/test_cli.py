from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pdf2ofx.cli import app


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

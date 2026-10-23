"""Excel export of a collection run (phase 4)."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from condosys.models import Competence, RunResult


def build_output_path(output_dir: Path, competence: Competence, now: datetime) -> Path:
    """Builds ``output/notas_<AAAA-MM>_<AAAAMMDD-HHMMSS>.xlsx`` (no ``:``, Windows-safe)."""
    return output_dir / f"notas_{competence.slug}_{now:%Y%m%d-%H%M%S}.xlsx"


def export_results(results: Sequence[RunResult], competence: Competence, output_path: Path) -> Path:
    """Writes the "Notas", "Resumo" and "Erros" sheets.

    Args:
        results: One result per condominium.
        competence: Collected period.
        output_path: Destination file, usually from :func:`build_output_path`.

    Returns:
        The written file.
    """
    # TODO(fase 4): "Notas" (one row per invoice), "Resumo" (count and totals per
    # condominium), "Erros" (failed condominiums and why). Money cells as Decimal.
    raise NotImplementedError("Fase 4: exportação Excel.")

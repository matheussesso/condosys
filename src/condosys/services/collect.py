"""Orchestration: for each condominium → login → query → export (phases 2-4).

One condominium at a time, with a pause between them, never in parallel.
"""

from collections.abc import Sequence

from condosys.models import Competence, Condominium, RunResult
from condosys.settings import Settings


def collect_condominium(
    settings: Settings, condominium: Condominium, competence: Competence
) -> RunResult:
    """Collects the taken invoices of one condominium.

    Errors are captured in the result instead of raised, so one failure does not stop
    the batch.
    """
    # TODO(fase 2-3): open_issnet_session → TakenInvoicesPage.search → parsers.
    raise NotImplementedError("Fases 2 e 3: coleta das notas.")


def collect_all(
    settings: Settings, condominiums: Sequence[Condominium], competence: Competence
) -> list[RunResult]:
    """Collects every active condominium sequentially."""
    # TODO(fase 4): iterate active condominiums, sleep settings.between_condominiums_ms,
    # then exporters.excel.export_results.
    raise NotImplementedError("Fase 4: coleta em lote e exportação.")

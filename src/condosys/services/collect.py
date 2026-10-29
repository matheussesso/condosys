"""Collection: for each condominium → ADN sync with its own certificate → taken invoices.

One condominium at a time, with a pause between them, never in parallel. A failure is
recorded in its ``RunResult`` and the batch goes on.
"""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from condosys.adn import AdnError, AdnStore, same_cnpj_root, sync_documents
from condosys.certificates import CertificateError, LoadedCertificate, load_pfx
from condosys.credentials import CredentialStoreError, get_password
from condosys.models import Competence, Condominium, RunResult
from condosys.services.adn_invoices import taken_invoices
from condosys.settings import Settings

logger = logging.getLogger(__name__)

# (index starting at 1, total, condominium, phase message)
ProgressCallback = Callable[[int, int, Condominium, str], None]


class CollectError(RuntimeError):
    """A problem with one condominium, with a message meant for the user."""


def adn_store(settings: Settings, cnpj: str) -> AdnStore:
    """Local ADN store of a CNPJ."""
    return AdnStore(settings.data_dir / "adn" / cnpj)


def collect_condominium(
    settings: Settings,
    condominium: Condominium,
    competence: Competence,
    *,
    sync: bool = True,
    on_phase: Callable[[str], None] | None = None,
) -> RunResult:
    """Collects the taken invoices of one condominium; errors go into the result."""
    started = datetime.now()

    def phase(message: str) -> None:
        logger.info("%s: %s", condominium.name, message)
        if on_phase is not None:
            on_phase(message)

    try:
        store = adn_store(settings, condominium.cnpj)
        if sync:
            loaded = _load_certificate(settings, condominium)
            phase(f"baixando notas novas do ADN (a partir do NSU {store.last_nsu})")
            result = sync_documents(
                settings.adn_base_url,
                loaded,
                store,
                cnpj=None if loaded.info.cnpj == condominium.cnpj else condominium.cnpj,
                pause_s=settings.adn_pause_ms / 1000,
                max_batches=settings.adn_max_batches,
            )
            phase(f"{result.new_documents} documentos novos; último NSU {result.last_nsu}")
            if not result.finished:
                raise CollectError(
                    "ainda há documentos a baixar no ADN; rode de novo para completar "
                    f"(parou no NSU {result.last_nsu})"
                )
        invoices = taken_invoices(store.documents(), condominium.cnpj, competence)
        phase(f"{len(invoices)} notas tomadas em {competence.label}")
        return RunResult(
            condominium_name=condominium.name,
            condominium_cnpj=condominium.cnpj,
            success=True,
            invoices=invoices,
            started_at=started,
            finished_at=datetime.now(),
        )
    except (CollectError, AdnError, CredentialStoreError) as exc:
        logger.warning("%s: %s", condominium.name, exc)
        return RunResult(
            condominium_name=condominium.name,
            condominium_cnpj=condominium.cnpj,
            success=False,
            error=str(exc),
            started_at=started,
            finished_at=datetime.now(),
        )


def _load_certificate(settings: Settings, condominium: Condominium) -> LoadedCertificate:
    password = get_password(condominium.certificate)
    if password is None:
        raise CollectError(f"senha do certificado {condominium.certificate} não cadastrada")
    try:
        loaded = load_pfx(settings.certs_dir / condominium.certificate, password)
    except CertificateError as exc:
        raise CollectError(str(exc)) from exc
    if loaded.info.cnpj is None:
        raise CollectError(f"{condominium.certificate} não tem CNPJ (o ADN exige e-CNPJ)")
    if not same_cnpj_root(loaded.info.cnpj, condominium.cnpj):
        raise CollectError(
            f"{condominium.certificate} é de {loaded.info.holder_name}, não do condomínio "
            "(o ADN exige a mesma raiz de CNPJ)"
        )
    if loaded.info.is_expired():
        raise CollectError(f"certificado vencido em {loaded.info.not_after:%d/%m/%Y}")
    return loaded


def collect_all(
    settings: Settings,
    condominiums: Sequence[Condominium],
    competence: Competence,
    *,
    sync: bool = True,
    progress: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[RunResult]:
    """Collects the given condominiums sequentially."""
    results: list[RunResult] = []
    total = len(condominiums)
    for index, condominium in enumerate(condominiums, start=1):
        if should_stop is not None and should_stop():
            break
        if index > 1:
            time.sleep(settings.between_condominiums_ms / 1000)

        def on_phase(message: str, i: int = index, c: Condominium = condominium) -> None:
            if progress is not None:
                progress(i, total, c, message)

        results.append(
            collect_condominium(settings, condominium, competence, sync=sync, on_phase=on_phase)
        )
    return results

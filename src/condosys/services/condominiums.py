"""Condominium list: spreadsheet ``config/condominios.xlsx`` kept in sync with ``certs/``."""

import unicodedata
from dataclasses import dataclass, field

from condosys.config_loader import ConfigError, RowError, load_condominiums, save_condominiums
from condosys.models import Condominium
from condosys.services.certificates import list_certificates
from condosys.settings import Settings

# Certificate holders that are not condominiums (e.g. the accounting firm) are added as
# inactive, for a person to confirm.
_CONDOMINIUM_HINTS = ("CONDOMIN", "COND ", "COND.", "EDIFICIO", "RESIDENCIAL")


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def looks_like_condominium(holder_name: str) -> bool:
    """Whether the certificate holder name suggests a condominium."""
    name = f"{_plain(holder_name)} "
    return any(hint in name for hint in _CONDOMINIUM_HINTS)


@dataclass
class SyncSummary:
    """What :func:`sync_from_certificates` changed."""

    added: list[Condominium] = field(default_factory=list)
    updated: list[Condominium] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # certificates without password/CNPJ


def load_or_empty(settings: Settings) -> list[Condominium]:
    """Spreadsheet rows, or an empty list when the file does not exist yet.

    Raises:
        ConfigError: If the spreadsheet exists but is invalid.
    """
    if not settings.config_file.is_file():
        return []
    return load_condominiums(settings.config_file)


def sync_from_certificates(settings: Settings) -> SyncSummary:
    """Adds to the spreadsheet every certificate whose CNPJ is not listed yet.

    Rows are matched by CNPJ; an existing row pointing to a missing file gets the
    certificate of the same CNPJ. Other columns (ativo, nome, observacoes) are kept.

    Raises:
        ConfigError: If the current spreadsheet is invalid.
        CredentialStoreError: If the system keyring is unavailable.
    """
    current = load_or_empty(settings)
    by_cnpj = {c.cnpj: c for c in current}
    summary = SyncSummary()
    result = list(current)

    for status in list_certificates(settings):
        if status.info is None or status.info.cnpj is None:
            summary.skipped.append(status.file_name)
            continue
        cnpj = status.info.cnpj
        existing = by_cnpj.get(cnpj)
        if existing is None:
            is_condominium = looks_like_condominium(status.info.holder_name)
            added = Condominium(
                active=is_condominium,
                name=status.info.holder_name,
                cnpj=cnpj,
                certificate=status.file_name,
                notes="" if is_condominium else "verificar: o titular não parece um condomínio",
            )
            result.append(added)
            by_cnpj[cnpj] = added
            summary.added.append(added)
        elif not (settings.certs_dir / existing.certificate).is_file():
            updated = existing.model_copy(update={"certificate": status.file_name})
            result[result.index(existing)] = updated
            by_cnpj[cnpj] = updated
            summary.updated.append(updated)

    if summary.added or summary.updated or not settings.config_file.is_file():
        save_condominiums(settings.config_file, result)
    return summary


def active_condominiums(settings: Settings) -> list[Condominium]:
    """Active rows of a valid spreadsheet (certificates must exist).

    Raises:
        ConfigError: If the spreadsheet is missing or invalid.
    """
    if not settings.config_file.is_file():
        message = f"planilha não encontrada: {settings.config_file} (rode condosys config sync)"
        raise ConfigError([RowError(None, None, message)])
    return [c for c in load_condominiums(settings.config_file, settings.certs_dir) if c.active]

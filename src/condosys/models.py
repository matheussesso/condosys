"""Domain models shared across the application."""

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from condosys.documents import format_cnpj, normalize_cnpj, validate_cnpj

_COMPETENCE_RE = re.compile(r"^\s*(\d{1,2})\s*[/\-]\s*(\d{4})\s*$")


def parse_money(value: Any) -> Any:
    """Converts Brazilian-formatted money strings (``R$ 1.234,56``) to ``Decimal``.

    Floats are rejected on purpose: money must never pass through binary floating point.

    Args:
        value: A ``Decimal``, ``int`` or string.

    Returns:
        A ``Decimal`` for strings; other values are returned unchanged for Pydantic to check.

    Raises:
        ValueError: If the value is a float or a string that is not a valid amount.
    """
    if isinstance(value, float):
        raise ValueError("valores monetários não podem ser float; use Decimal ou str")
    if isinstance(value, str):
        text = value.replace("R$", "").replace("\xa0", "").strip()
        if not text:
            return Decimal("0")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"valor monetário inválido: {value!r}") from exc
    return value


def normalize_document(value: Any) -> Any:
    """Normalizes a CPF/CNPJ to uppercase characters without punctuation."""
    if isinstance(value, str | int):
        return normalize_cnpj(value)
    return value


Money = Annotated[Decimal, BeforeValidator(parse_money)]
Document = Annotated[str, BeforeValidator(normalize_document)]


class AccessMode(StrEnum):
    """How the portal is accessed for a condominium."""

    DIRECT = "DIRETO"
    PROXY = "PROCURACAO"


class Condominium(BaseModel):
    """A row of ``config/condominios.xlsx``.

    When validated with ``context={"certs_dir": Path}``, the certificate file must exist there.
    """

    model_config = ConfigDict(frozen=True)

    active: bool
    name: str = Field(min_length=1)
    cnpj: str
    access_mode: AccessMode
    certificate: str = Field(min_length=1)
    notes: str = ""
    row: int | None = None

    @field_validator("name", "certificate", "notes", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("cnpj", mode="before")
    @classmethod
    def _validate_cnpj(cls, value: Any) -> str:
        if not isinstance(value, str | int):
            raise ValueError("CNPJ ausente")
        return validate_cnpj(value)

    @field_validator("certificate")
    @classmethod
    def _certificate_exists(cls, value: str, info: ValidationInfo) -> str:
        if not value.lower().endswith((".pfx", ".p12")):
            raise ValueError(f"certificado deve ser um arquivo .pfx ou .p12: {value!r}")
        certs_dir = (info.context or {}).get("certs_dir")
        if certs_dir is not None and not (certs_dir / value).is_file():
            raise ValueError(f"certificado não encontrado em {certs_dir}: {value}")
        return value

    @property
    def cnpj_formatted(self) -> str:
        """CNPJ formatted for display."""
        return format_cnpj(self.cnpj)


class CertificateInfo(BaseModel):
    """Public data read from an A1 certificate (never the key or the password)."""

    model_config = ConfigDict(frozen=True)

    file_name: str
    holder_name: str
    cnpj: str | None = None
    issuer: str
    not_before: datetime
    not_after: datetime
    serial_number: str

    def days_to_expire(self, today: date | None = None) -> int:
        """Days until the certificate expires (negative when already expired)."""
        expiry = self.not_after.astimezone().date()  # local calendar day
        return (expiry - (today or date.today())).days

    def is_expired(self, today: date | None = None) -> bool:
        """Whether the certificate is already expired."""
        return self.days_to_expire(today) < 0


class Competence(BaseModel):
    """A tax period (month/year), e.g. ``09/2026``."""

    model_config = ConfigDict(frozen=True)

    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parses ``MM/YYYY`` (or ``MM-YYYY``).

        Raises:
            ValueError: If the text is not a valid competence.
        """
        match = _COMPETENCE_RE.match(text)
        if not match:
            raise ValueError(f"competência inválida (use MM/AAAA): {text!r}")
        return cls(month=int(match.group(1)), year=int(match.group(2)))

    @property
    def first_day(self) -> date:
        """First day of the period."""
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        """Last day of the period."""
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def label(self) -> str:
        """Display form, ``MM/YYYY``."""
        return f"{self.month:02d}/{self.year}"

    @property
    def slug(self) -> str:
        """File-name friendly form, ``YYYY-MM``."""
        return f"{self.year}-{self.month:02d}"


class Invoice(BaseModel):
    """A row of the "Documentos Fiscais" grid in "Consulta de Notas Tomadas"."""

    number: str
    issue_date: date
    amount: Money
    iss_amount: Money
    tax_withheld: bool
    provider_document: Document
    provider_name: str
    status: str
    version: str


class InvoiceDetail(Invoice):
    """A fully opened invoice (NFS-e), read from the HTML view or the XML."""

    service_code: str | None = None
    service_description: str = ""
    service_location: str = ""
    pis: Money = Decimal("0")
    cofins: Money = Decimal("0")
    csll: Money = Decimal("0")
    # "Contribuições Sociais — Retidas" (NT 07): PIS + COFINS + CSLL withheld.
    social_contributions_withheld: Money = Decimal("0")
    inss: Money = Decimal("0")
    irrf: Money = Decimal("0")
    iss_withheld: Money = Decimal("0")
    deductions: Money = Decimal("0")
    net_amount: Money
    taker_document: Document
    taker_name: str
    raw_source: Literal["html", "xml"]


class Severity(StrEnum):
    """Severity of a pre-analysis flag."""

    INFO = "INFO"
    WARNING = "ALERTA"
    ERROR = "ERRO"


class Flag(BaseModel):
    """A pre-analysis alert. The system flags; the employee decides."""

    code: str
    severity: Severity
    message: str


class RunResult(BaseModel):
    """Outcome of collecting one condominium."""

    condominium_name: str
    condominium_cnpj: str
    success: bool
    invoices: list[InvoiceDetail] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None

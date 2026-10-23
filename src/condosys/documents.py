"""CNPJ normalization, validation and formatting.

Supports both the classic numeric CNPJ and the alphanumeric CNPJ introduced by
IN RFB 2.229/2024 (issued from July 2026). Internally a CNPJ is always stored
normalized: 14 uppercase characters, no punctuation.
"""

import re

_STRIP_RE = re.compile(r"[.\-/\s]")
_NORMALIZED_RE = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_FIRST_WEIGHTS = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_SECOND_WEIGHTS = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


class InvalidCNPJError(ValueError):
    """Raised when a value is not a valid CNPJ."""


def normalize_cnpj(value: str | int) -> str:
    """Strips punctuation and whitespace and uppercases a CNPJ.

    Integers (e.g. a CNPJ typed as a number in Excel, which drops leading zeros)
    are left-padded back to 14 digits. Strings are never padded, so a CPF stays a CPF.

    Args:
        value: Raw CNPJ, formatted or not.

    Returns:
        The CNPJ without punctuation. It is not validated.
    """
    if isinstance(value, int):
        return str(value).zfill(14)
    return _STRIP_RE.sub("", value).upper()


def _check_digit(base: str, weights: tuple[int, ...]) -> str:
    # Alphanumeric CNPJ: each char is worth its ASCII code minus 48 (digits keep their value).
    total = sum((ord(char) - 48) * weight for char, weight in zip(base, weights, strict=True))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def is_valid_cnpj(value: str | int) -> bool:
    """Checks the format and both check digits of a CNPJ.

    Args:
        value: Raw CNPJ, formatted or not.

    Returns:
        True when the CNPJ is valid.
    """
    cnpj = normalize_cnpj(value)
    if not _NORMALIZED_RE.match(cnpj) or len(set(cnpj)) == 1:
        return False
    first = _check_digit(cnpj[:12], _FIRST_WEIGHTS)
    second = _check_digit(cnpj[:12] + first, _SECOND_WEIGHTS)
    return cnpj[12:] == first + second


def validate_cnpj(value: str | int) -> str:
    """Normalizes and validates a CNPJ.

    Args:
        value: Raw CNPJ, formatted or not.

    Returns:
        The normalized CNPJ.

    Raises:
        InvalidCNPJError: If the CNPJ is malformed or its check digits are wrong.
    """
    cnpj = normalize_cnpj(value)
    if not is_valid_cnpj(cnpj):
        raise InvalidCNPJError(f"CNPJ inválido: {value!r}")
    return cnpj


def format_cnpj(value: str) -> str:
    """Formats a normalized CNPJ as ``XX.XXX.XXX/XXXX-XX``.

    Args:
        value: CNPJ (normalized or not).

    Returns:
        The formatted CNPJ, or the input unchanged if it does not have 14 characters.
    """
    cnpj = normalize_cnpj(value)
    if len(cnpj) != 14:
        return value
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"

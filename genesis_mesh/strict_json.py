"""Strict JSON input (v1.2.0): refuse what parsers read differently.

The canonical form of a signed record is computed from parsed JSON, so every
implementation must parse a record to the same value. Some JSON does not: the
Python standard library keeps the last of two duplicate keys where the .NET
reader keeps both, reads ``NaN`` and ``1e400`` (and writes them back as
non-JSON), keeps a lone surrogate that Go replaces, and Rust reads an integer
beyond 64 bits as a float. Such input is refused here, as in every SDK, by a
named reason (the conformance suite ``canonical``):

``invalid_json``
    not JSON, including ``NaN`` and ``Infinity``, a byte order mark, text that
    is not UTF-8, and arrays or objects nested more than 64 deep;
``duplicate_key``
    an object names a key twice;
``non_finite_number``
    a number overflows a 64-bit float (``1e400``);
``integer_out_of_range``
    an integer outside ``-2**63 .. 2**64 - 1``;
``negative_zero``
    the integer ``-0``;
``lone_surrogate``
    a string or key holds half of a UTF-16 surrogate pair.
"""

from __future__ import annotations

import json
import math
from typing import Any

REASONS = (
    "invalid_json",
    "duplicate_key",
    "non_finite_number",
    "integer_out_of_range",
    "negative_zero",
    "lone_surrogate",
)

MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**64 - 1
#: Arrays and objects nested deeper are refused (every parser in the program
#: handles 64; .NET's reader stops there by default).
MAX_DEPTH = 64


class StrictJSONError(ValueError):
    """JSON refused as input to a signed record; ``reason`` is one of ``REASONS``."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _ in items:
        if key in seen:
            raise StrictJSONError("duplicate_key", f"key {key!r} appears twice")
        seen.add(key)
    return dict(items)


def _constant(name: str) -> Any:
    raise StrictJSONError("invalid_json", f"{name} is not JSON")


def _integer(literal: str) -> int:
    if literal == "-0":
        raise StrictJSONError("negative_zero", "the integer -0")
    if len(literal.lstrip("-")) > 20:  # before int(), which is slow and capped on long literals
        raise StrictJSONError("integer_out_of_range", "an integer longer than 20 digits")
    value = int(literal)
    if not MIN_INTEGER <= value <= MAX_INTEGER:
        raise StrictJSONError("integer_out_of_range", f"{literal} is outside the 64-bit range")
    return value


def _float(literal: str) -> float:
    value = float(literal)
    if math.isinf(value):
        raise StrictJSONError("non_finite_number", f"{literal} overflows a 64-bit float")
    return value


def _surrogates(value: Any) -> None:
    """Refuse a lone surrogate in any key or string (pairs were joined by the parser),
    and nesting deeper than ``MAX_DEPTH``."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            depth += 1
            if depth > MAX_DEPTH:
                raise StrictJSONError("invalid_json", f"arrays or objects nested more than {MAX_DEPTH} deep")
        if isinstance(item, str):
            texts = [item]
        elif isinstance(item, dict):
            texts = list(item)
            stack.extend((v, depth) for v in item.values())
        elif isinstance(item, list):
            texts = []
            stack.extend((v, depth) for v in item)
        else:
            continue
        for text in texts:
            if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
                raise StrictJSONError("lone_surrogate", "a string holds half of a surrogate pair")


def loads(text: str | bytes) -> Any:
    """Parse JSON for a signed record or a request body, refusing ambiguous input."""
    try:
        if isinstance(text, (bytes, bytearray)):
            text = bytes(text).decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_int=_integer,
            parse_float=_float,
        )
    except StrictJSONError:
        raise
    except (ValueError, RecursionError) as exc:
        raise StrictJSONError("invalid_json", str(exc)) from None
    _surrogates(value)
    return value

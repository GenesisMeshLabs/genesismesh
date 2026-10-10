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

Text with several faults is refused for the first one in text order, as
every SDK reads it (v1.3.0): one input, one reason, in every implementation.
"""

from __future__ import annotations

import json
import math
import re
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


_SPACE = re.compile(r"[ \t\n\r]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"-?[0-9]+")
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
#: A run of string text with nothing to check: no quote, backslash, control character or surrogate.
_PLAIN = re.compile(r'[^"\\\x00-\x1f\ud800-\udfff]*')
_ESCAPES = {'"': 0x22, "\\": 0x5C, "/": 0x2F, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9}
_LITERALS = ("true", "false", "null")


class _Scanner:
    """One pass over the text, refusing its first fault in text order, as the SDKs' scanners do."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.depth = 0

    def space(self) -> None:
        self.i = _SPACE.match(self.text, self.i).end()  # type: ignore[union-attr]

    def string(self, keep: bool) -> str:
        text, n = self.text, len(self.text)
        self.i += 1
        out: list[str] = []
        pending = -1  # a high surrogate waiting for its low half
        while True:
            run = _PLAIN.match(text, self.i).end()  # type: ignore[union-attr]
            if run > self.i:
                if pending >= 0:
                    raise StrictJSONError("lone_surrogate", "a high surrogate without its low half")
                if keep:
                    out.append(text[self.i:run])
                self.i = run
            if self.i >= n:
                raise StrictJSONError("invalid_json", "a string is not closed")
            unit = ord(text[self.i])
            if unit == 0x22:
                self.i += 1
                break
            if unit < 0x20:
                raise StrictJSONError("invalid_json", "a control character in a string")
            if unit == 0x5C:
                escape = text[self.i + 1] if self.i + 1 < n else ""
                if escape == "u":
                    digits = text[self.i + 2:self.i + 6]
                    if not _HEX4.fullmatch(digits):
                        raise StrictJSONError("invalid_json", "a malformed \\u escape")
                    unit = int(digits, 16)
                    self.i += 6
                else:
                    if escape not in _ESCAPES:
                        raise StrictJSONError("invalid_json", "an unknown escape")
                    unit = _ESCAPES[escape]
                    self.i += 2
            else:
                self.i += 1  # a raw surrogate (text decoded with surrogateescape)
            if pending >= 0:
                if not 0xDC00 <= unit <= 0xDFFF:
                    raise StrictJSONError("lone_surrogate", "a high surrogate without its low half")
                if keep:
                    out.append(chr(0x10000 + ((pending - 0xD800) << 10) + (unit - 0xDC00)))
                pending = -1
            elif 0xD800 <= unit <= 0xDBFF:
                pending = unit
            elif 0xDC00 <= unit <= 0xDFFF:
                raise StrictJSONError("lone_surrogate", "a low surrogate without its high half")
            elif keep:
                out.append(chr(unit))
        if pending >= 0:
            raise StrictJSONError("lone_surrogate", "a high surrogate without its low half")
        return "".join(out)

    def number(self) -> None:
        match = _NUMBER.match(self.text, self.i)
        if match is None:
            raise StrictJSONError("invalid_json", "a malformed number")
        literal = match.group()
        self.i = match.end()
        if _INTEGER.fullmatch(literal):
            _integer(literal)
        else:
            _float(literal)

    def value(self) -> None:
        self.space()
        text, i = self.text, self.i
        c = text[i] if i < len(text) else ""
        if c in ("{", "["):
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise StrictJSONError("invalid_json", f"arrays or objects nested more than {MAX_DEPTH} deep")
            self.container(c)
            self.depth -= 1
        elif c == '"':
            self.string(False)
        elif c == "-" or "0" <= c <= "9":
            self.number()
        else:
            for literal in _LITERALS:
                if text.startswith(literal, i):
                    self.i += len(literal)
                    return
            raise StrictJSONError("invalid_json", "no value" if not c else f"unexpected {c!r}")

    def expect(self, close: str) -> bool:
        """After a member or element: True at the closing bracket, False after a comma."""
        self.space()
        c = self.text[self.i] if self.i < len(self.text) else ""
        self.i += 1
        if c == ",":
            return False
        if c == close:
            return True
        raise StrictJSONError("invalid_json", f'expected "," or "{close}"')

    def container(self, c: str) -> None:
        self.i += 1
        self.space()
        close = "}" if c == "{" else "]"
        if self.text.startswith(close, self.i):
            self.i += 1
            return
        keys: set[str] = set()
        while True:
            if c == "{":
                self.space()
                if not self.text.startswith('"', self.i):
                    raise StrictJSONError("invalid_json", "expected a key")
                key = self.string(True)
                if key in keys:
                    raise StrictJSONError("duplicate_key", f"key {key!r} appears twice")
                keys.add(key)
                self.space()
                if not self.text.startswith(":", self.i):
                    raise StrictJSONError("invalid_json", 'expected ":"')
                self.i += 1
            self.value()
            if self.expect(close):
                return

    def scan(self) -> None:
        self.value()
        self.space()
        if self.i != len(self.text):
            raise StrictJSONError("invalid_json", "text after the value")


def loads(text: str | bytes) -> Any:
    """Parse JSON for a signed record or a request body, refusing ambiguous input.

    The text is scanned first, so that with several faults the first in text
    order is named, as in every SDK; then parsed.
    """
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            raise StrictJSONError("invalid_json", "the text is not UTF-8") from None
    _Scanner(text).scan()
    try:
        return json.loads(
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

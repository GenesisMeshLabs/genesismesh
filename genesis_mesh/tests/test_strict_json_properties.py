"""Property tests (hypothesis) for strict JSON input and the canonical form.

Every signed record is verified over ``json.dumps(value, sort_keys=True,
separators=(",", ":"))`` of the value ``strict_json.loads`` parsed, in every
SDK, so these properties are what interoperability rests on:

* any JSON value round-trips, as text or UTF-8 bytes, escaped or not;
* the canonical form is a fixed point and ignores key order and whitespace;
* a duplicate key is refused, however its name is escaped;
* a number lexeme is accepted exactly when RFC 8259 reads it whole and it is
  in range, and otherwise refused with the reason the module documents;
* a lone surrogate is refused, a surrogate pair is one character;
* ``loads`` (standard parser first, scanner only when it may refuse) names the
  same value or the same first fault as scanning the whole text first;
* a timestamp the reference writes is canonical; its other spellings are not.

Each test runs the active hypothesis profile's ``max_examples`` inputs
(conftest.py: fixed inputs in CI, random locally, ``HYPOTHESIS_PROFILE=deep``
for a long local run); a failure prints the smallest input that breaks the
property.
"""

from __future__ import annotations

import json
import os
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from hypothesis import assume, example, given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter

from genesis_mesh import strict_json
from genesis_mesh.models.canonical_registry import canonical_timestamp

PROPERTIES = settings()  # the active profile (conftest.py)

# The range every SDK reads exactly (strict_json docstring), written out: not read from the module.
MIN, MAX = -(2**63), 2**64 - 1

# Text without surrogates: the only strings a strict reader can return.
TEXT = st.text(st.characters(exclude_categories=["Cs"]), max_size=12)
SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(min_value=MIN, max_value=MAX)
    | st.floats(allow_nan=False, allow_infinity=False)
    | TEXT
)
VALUES = st.recursive(
    SCALARS,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(TEXT, inner, max_size=4),
    max_leaves=16,
)


def example_each(inputs: list[str]) -> Any:
    """``@example`` for each input: the edge cases run on every run, not only when drawn."""
    def decorate(test: Any) -> Any:
        for item in reversed(inputs):
            test = example(item)(test)
        return test
    return decorate


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def outcome(read: Any, text: str | bytes) -> tuple[str, Any]:
    try:
        return "value", canonical(read(text))
    except strict_json.StrictJSONError as exc:
        return "refused", exc.reason


def scan_first(text: str) -> Any:
    """The reference ``loads``: scan the whole text for its first fault, then parse."""
    strict_json._Scanner(text).scan()
    return json.loads(text)


def escape_all(key: str) -> str:
    """A JSON string literal spelling every UTF-16 unit of ``key`` as ``\\uXXXX``."""
    units = key.encode("utf-16-be")
    return '"' + "".join(f"\\u{units[i] << 8 | units[i + 1]:04x}" for i in range(0, len(units), 2)) + '"'


# -- round trip and canonical form -----------------------------------------------------------


@PROPERTIES
@given(VALUES, st.booleans())
def test_any_json_value_round_trips(value, ascii_only):
    text = json.dumps(value, ensure_ascii=ascii_only)
    assert strict_json.loads(text) == value
    assert strict_json.loads(text.encode("utf-8")) == value


@PROPERTIES
@given(VALUES)
def test_the_canonical_form_is_a_fixed_point(value):
    once = canonical(strict_json.loads(json.dumps(value)))
    assert canonical(strict_json.loads(once)) == once
    assert once.isascii()


def _reordered(value: Any, data: st.DataObject) -> Any:
    if isinstance(value, dict):
        keys = data.draw(st.permutations(list(value)))
        return {key: _reordered(value[key], data) for key in keys}
    if isinstance(value, list):
        return [_reordered(item, data) for item in value]
    return value


@PROPERTIES
@given(VALUES, st.data())
def test_the_canonical_form_ignores_key_order_and_whitespace(value, data):
    indent = data.draw(st.sampled_from([None, 0, 1, 2, "\t"]))
    text = json.dumps(_reordered(value, data), indent=indent, ensure_ascii=data.draw(st.booleans()))
    assert canonical(strict_json.loads(text)) == canonical(value)


# -- duplicate keys ---------------------------------------------------------------------------


@PROPERTIES
@given(st.dictionaries(TEXT, VALUES, min_size=1, max_size=4), st.data())
def test_a_duplicate_key_is_refused_however_it_is_spelled(obj, data):
    members = [f"{json.dumps(key)}:{json.dumps(value)}" for key, value in obj.items()]
    key = data.draw(st.sampled_from(sorted(obj)))
    spelled = data.draw(st.sampled_from([json.dumps(key), json.dumps(key, ensure_ascii=False), escape_all(key)]))
    members.insert(data.draw(st.integers(0, len(members))), f"{spelled}:{json.dumps(data.draw(VALUES))}")
    text = "{" + ",".join(members) + "}"
    wrapped = data.draw(st.sampled_from(["{}", '{{"outer":{}}}', "[1,{}]"])).format(text)
    assert outcome(strict_json.loads, wrapped) == ("refused", "duplicate_key")


# -- number lexemes ---------------------------------------------------------------------------


def number_reason(text: str) -> str | None:
    """What strict JSON makes of a text that holds one number lexeme, by RFC 8259
    and the rules in ``strict_json``'s docstring, written independently of it."""
    i, n, digits = 0, len(text), "0123456789"
    if i < n and text[i] == "-":
        i += 1
    if i < n and text[i] == "0":
        i += 1
    elif i < n and text[i] in "123456789":
        while i < n and text[i] in digits:
            i += 1
    else:
        return "invalid_json"
    integer = True
    if i < n and text[i] == ".":
        integer, i = False, i + 1
        if not (i < n and text[i] in digits):
            return "invalid_json"
        while i < n and text[i] in digits:
            i += 1
    if i < n and text[i] in "eE":
        integer, i = False, i + 1
        if i < n and text[i] in "+-":
            i += 1
        if not (i < n and text[i] in digits):
            return "invalid_json"
        while i < n and text[i] in digits:
            i += 1
    literal = text[:i]
    if integer:
        if literal == "-0":
            return "negative_zero"
        if len(literal.lstrip("-")) > 20 or not MIN <= int(literal) <= MAX:
            return "integer_out_of_range"
    elif math.isinf(float(literal)):
        return "non_finite_number"
    return None if i == n else "invalid_json"  # what follows a whole number is the next token


LEXEMES = ["-0", "-0.0", "0", "1.", ".5", "1e", "1E+", "1.e5", "-", "01", "-01", "1e400", "-1e400", "2e-400",
           "18446744073709551615", "18446744073709551616", "-9223372036854775808", "-9223372036854775809",
           "123456789012345678901", "00000000000000000000001"]


@PROPERTIES
@given(st.text("-+.eE0123456789", min_size=1, max_size=24))
@example_each(LEXEMES)
def test_a_number_lexeme_is_read_by_the_grammar_then_checked(text):
    reason = number_reason(text)
    if reason is None:
        value = strict_json.loads(text)
        assert value == (int(text) if text.lstrip("-").isdigit() else float(text))
        assert isinstance(value, int) == text.lstrip("-").isdigit()
    else:
        assert outcome(strict_json.loads, text) == ("refused", reason)
    # In a document the lexeme's fault comes first; a whole number lets the -0 after it be the first.
    assert outcome(strict_json.loads, f"[{text},-0]") == ("refused", reason or "negative_zero")


@PROPERTIES
@given(st.integers(min_value=MIN, max_value=MAX) | st.integers(max_value=MIN - 1) | st.integers(min_value=MAX + 1))
def test_integers_are_exact_within_64_bits_and_refused_beyond(number):
    if MIN <= number <= MAX:
        assert strict_json.loads(f"[{number}]") == [number]
    else:
        assert outcome(strict_json.loads, f"[{number}]") == ("refused", "integer_out_of_range")


@PROPERTIES
@given(st.floats(allow_nan=False, allow_infinity=False), st.sampled_from(["r", ".17g", ".17e", "f"]))
def test_finite_floats_read_back_exactly(number, form):
    text = repr(number) if form == "r" else format(number, form)
    assume("e" in text.lower() or "." in text)  # an integral form is an integer lexeme
    assert strict_json.loads(text) == float(text)


@PROPERTIES
@given(st.integers(1, 9), st.integers(309, 9999), st.sampled_from(["", "-"]))
def test_a_float_beyond_64_bits_is_not_finite(mantissa, exponent, sign):
    assert outcome(strict_json.loads, f"{sign}{mantissa}e{exponent}") == ("refused", "non_finite_number")


# -- unicode ----------------------------------------------------------------------------------


@PROPERTIES
@given(TEXT, st.booleans())
def test_strings_keep_every_code_point(text, ascii_only):
    assert strict_json.loads(json.dumps({text: text}, ensure_ascii=ascii_only)) == {text: text}
    assert strict_json.loads(escape_all(text)) == text


@PROPERTIES
@given(st.integers(0xD800, 0xDFFF), TEXT, TEXT, st.booleans())
def test_a_lone_surrogate_is_refused(unit, before, after, as_key):
    literal = json.dumps(before)[:-1] + f"\\u{unit:04x}" + json.dumps(after)[1:]
    text = "{" + literal + ":1}" if as_key else "[" + literal + "]"
    assert outcome(strict_json.loads, text) == ("refused", "lone_surrogate")


@PROPERTIES
@given(st.integers(0x10000, 0x10FFFF))
def test_a_surrogate_pair_is_one_character(code_point):
    high = 0xD800 + ((code_point - 0x10000) >> 10)
    low = 0xDC00 + ((code_point - 0x10000) & 0x3FF)
    assert strict_json.loads(f'"\\u{high:04x}\\u{low:04X}"') == chr(code_point)


@PROPERTIES
@given(st.binary(min_size=1, max_size=16))
def test_bytes_that_are_not_utf8_are_refused(raw):
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        assert outcome(strict_json.loads, b'"' + raw + b'"') == ("refused", "invalid_json")
    else:
        assume(False)


# -- the fast path decides as the scanner does -----------------------------------------------

TOKENS = [
    "{", "}", "[", "]", ",", ":", " ", "\n", '"', '"a"', '"b"', '"\\u0061"', '"\\ud83d\\ude00"', '"\\ud800"',
    '"\\udc00"', '"\ud800"', '"\x01"', '"\\x"', "\\", "0", "1", "-0", "-", ".", "e", "01", "1.5", "1e400",
    "18446744073709551616", "-9223372036854775809", "true", "fals", "null", "NaN", "Infinity", "é", "﻿",
]


@settings(max_examples=settings().max_examples * 5 // 2)
@given(st.lists(st.sampled_from(TOKENS), min_size=1, max_size=14).map("".join))
def test_loads_names_the_first_fault_as_scanning_first_does(text):
    assert outcome(strict_json.loads, text) == outcome(scan_first, text)


@PROPERTIES
@given(st.integers(1, 80), st.sampled_from(["[]", '{"k":}']))
def test_nesting_beyond_64_is_refused(depth, shape):
    open_, close = ("[", "]") if shape == "[]" else ('{"k":', "}")
    text = open_ * depth + "0" + close * depth
    if depth <= strict_json.MAX_DEPTH:
        assert outcome(strict_json.loads, text)[0] == "value"
    else:
        assert outcome(strict_json.loads, text) == ("refused", "invalid_json")


# -- canonical timestamps ---------------------------------------------------------------------

OFFSETS = st.none() | st.integers(-(24 * 60 - 1), 24 * 60 - 1).map(lambda m: timezone(timedelta(minutes=m)))
WRITE = TypeAdapter(datetime)


@PROPERTIES
@given(st.datetimes(min_value=datetime(1, 1, 2), max_value=datetime(9999, 12, 30)), OFFSETS)
def test_the_reference_writes_canonical_timestamps_only(moment, zone):
    written = WRITE.dump_python(moment.replace(tzinfo=zone), mode="json")
    assert canonical_timestamp(written)
    if moment.microsecond == 0:
        assert not canonical_timestamp(written[:19] + ".000000" + written[19:])
    if written.endswith("Z"):
        assert not canonical_timestamp(written[:-1] + "+00:00")
        assert not canonical_timestamp(written[:-1] + "z")


# -- the profile reaches every property test --------------------------------------------------


def test_every_property_test_runs_under_the_active_profile():
    """In CI (the ``ci`` profile) every test here draws the same inputs on every run."""
    active = settings()
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and hasattr(value, "_hypothesis_internal_use_settings")]
    assert len(tests) == 15
    for test in tests:
        used = test._hypothesis_internal_use_settings
        assert (used.derandomize, used.database) == (active.derandomize, active.database), test.__name__
    if os.environ.get("CI") and not os.environ.get("HYPOTHESIS_PROFILE"):
        assert active.derandomize and active.database is None

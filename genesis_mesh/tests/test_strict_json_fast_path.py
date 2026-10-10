"""Strict JSON reads valid input at the standard parser's speed (v1.3.1).

1.3.0 scanned every text in Python before parsing it, about four times
slower than 1.2 on a large request body, before authentication. The scanner
now runs only when the text may hold a fault; it still decides every
refusal, so every input gets the same value or the same first-fault reason
as before. These tests compare ``loads`` with the scan-first reference on
the conformance inputs and on faults placed around them.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

import pytest

from genesis_mesh import strict_json

VECTORS = Path(__file__).resolve().parents[2] / "conformance" / "vectors" / "canonical.json"


def _reference(text: str | bytes) -> Any:
    """``loads`` as 1.3.0 wrote it: scan the whole text first, then parse."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            raise strict_json.StrictJSONError("invalid_json", "the text is not UTF-8") from None
    strict_json._Scanner(text).scan()
    try:
        return json.loads(text, object_pairs_hook=strict_json._pairs, parse_constant=strict_json._constant,
                          parse_int=strict_json._integer, parse_float=strict_json._float)
    except strict_json.StrictJSONError:
        raise
    except (ValueError, RecursionError) as exc:
        raise strict_json.StrictJSONError("invalid_json", str(exc)) from None


def _outcome(read, text: str | bytes) -> tuple[str, str]:
    try:
        return "value", repr(read(text))
    except strict_json.StrictJSONError as exc:
        return "refused", exc.reason


def _inputs() -> list[str]:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]
    return [v["input"] for v in vectors if v["kind"] == "json"]


FAULTS = ['"\\ud800"', '"\\udc00"', "-0", "1e400", "NaN", "18446744073709551616", '"\\ud83dx"',
          "[" * 65 + "]" * 65, '"a\tb"', "01", '{"a":1,"a":2}', '"\ud800"', '"\ud83d\ude00"', '"\\ud83d\ude00"']


def _mutations(seed: int = 1310) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    for text in _inputs():
        out += [text[:i] for i in range(0, len(text), max(1, len(text) // 8))]
        for fault in FAULTS:
            out += [f"[{fault},{text}]", f"[{text},{fault}]", f'{{"k":{fault},"j":{text}}}']
            for _ in range(2):
                if text:
                    i = rng.randrange(len(text) + 1)
                    out.append(text[:i] + fault + text[i:])
    return out


@pytest.mark.parametrize("text", _inputs())
def test_each_conformance_input_reads_as_before(text):
    assert _outcome(strict_json.loads, text) == _outcome(_reference, text)


def test_faults_around_the_conformance_inputs_get_the_same_first_reason():
    differences = [t for t in _mutations() if _outcome(strict_json.loads, t) != _outcome(_reference, t)]
    assert not differences, differences[:5]


def test_bytes_read_as_before():
    for text in ['{"x":"\\ud800"}', '{"x":1}', "[" * 70 + "]" * 70]:
        data = text.encode("utf-8")
        assert _outcome(strict_json.loads, data) == _outcome(_reference, data)
    assert _outcome(strict_json.loads, b"\xff") == ("refused", "invalid_json")


def test_a_large_valid_body_is_not_scanned_in_python():
    text = "[" + ",".join("1" for _ in range(500_000)) + "]"
    start = time.perf_counter()
    strict_json.loads(text)
    fast = time.perf_counter() - start
    start = time.perf_counter()
    _reference(text)
    reference = time.perf_counter() - start
    assert fast < reference / 2, (fast, reference)

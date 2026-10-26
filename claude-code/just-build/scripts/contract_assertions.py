"""Bounded JSON observations for external contracts. No sandbox claim."""
from __future__ import annotations

import json
import math

JSON_MAX_BYTES = 4096
JSON_MAX_DEPTH = 20
JSON_MAX_NODES = 256


def json_expectation(value):
    """Validate and detach a whole JSON value, including scalar/null values."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > JSON_MAX_NODES:
            raise ValueError('JSON assertion exceeds the 256-node limit')
        kind = type(item)
        if kind in (dict, list):
            depth += 1
            if depth > JSON_MAX_DEPTH:
                raise ValueError('JSON assertion exceeds the 20-level limit')
            if len(item) > JSON_MAX_NODES:
                raise ValueError('JSON assertion exceeds the 256-node limit')
            if kind is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError('JSON object keys must be strings')
                pending.extend((key, depth) for key in item)
                pending.extend((child, depth) for child in item.values())
            else:
                pending.extend((child, depth) for child in item)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError('nonfinite JSON numbers are forbidden')
        elif kind is str and len(item) > JSON_MAX_BYTES:
            raise ValueError('JSON assertion exceeds the 4096-byte limit')
        elif kind is int and item.bit_length() > JSON_MAX_BYTES * 4:
            raise ValueError('JSON assertion exceeds the 4096-byte limit')
        elif kind not in (str, int, bool, type(None)):
            raise ValueError('JSON assertion must contain only JSON values')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode('utf-8')
        if len(encoded) > JSON_MAX_BYTES:
            raise ValueError('JSON assertion exceeds the 4096-byte limit')
        # A separate value prevents caller mutation of a normalized assertion.
        return json.loads(encoded)
    except (UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError('JSON assertion cannot be represented safely') from exc


def strict_json(data):
    """Read a complete UTF-8 JSON output without permissive Python extensions."""
    if isinstance(data, bytes):
        if len(data) > JSON_MAX_BYTES:
            raise ValueError('JSON output exceeds the 4096-byte limit')
        text = data.decode('utf-8', errors='strict')
    elif isinstance(data, str):
        if len(data.encode('utf-8')) > JSON_MAX_BYTES:
            raise ValueError('JSON output exceeds the 4096-byte limit')
        text = data
    else:
        raise ValueError('JSON output must be UTF-8 text')
    depth, quoted, escaped = 0, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in '[{':
            depth += 1
            if depth > JSON_MAX_DEPTH:
                raise ValueError('JSON output exceeds the 20-level limit')
        elif character in ']}':
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON keys are forbidden')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('nonfinite JSON numbers are forbidden')

    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON numbers are forbidden')
        return value

    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_float=finite, parse_constant=constant)
        return json_expectation(value)
    except RecursionError as exc:
        raise ValueError('JSON output exceeds the parser limit') from exc


def json_equal(actual, expected):
    """Compare whole JSON values, preserving bool/int/float distinctions."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            json_equal(actual[key], child) for key, child in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            json_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected

"""SemVer-style range matching for section numbers.

Section numbers are ``major.minor`` pairs (e.g. ``1.3``) -- there is no
patch component. Range syntax follows npm's semver ranges:

- ``||`` separates alternatives; a version matches if any alternative matches.
- Hyphen ranges: ``1.3 - 1.7`` (inclusive on both ends).
- Space-separated comparators that must all hold: ``>=1.3 <1.8`` with
  operators ``<``, ``<=``, ``>``, ``>=``, ``=`` (or no operator for an
  exact match).
- Wildcards: ``1.x`` / ``1.*`` (any minor within major 1), ``*`` / ``x``
  (any version).
- ``^1.3`` means ``>=1.3 <2.0``; ``~1.3`` means ``>=1.3 <1.4``.
"""
import re

_COMPARATOR_RE = re.compile(
    r"\s*(>=|<=|>|<|\^|~|=)?\s*(\d+(?:\.(?:\d+|[xX*]))?|[xX*])"
)


def parse_version(value):
    """Parse a concrete section number into a ``(major, minor)`` tuple."""
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?", text)
    if not match:
        raise ValueError(f"Invalid section number: {value!r}")
    return (int(match.group(1)), int(match.group(2) or 0))


def _partial_bounds(major):
    """Bounds for a major-only version: >=major.0 and <(major+1).0."""
    return (major, 0), (major + 1, 0)


def _comparator_to_bounds(op, token):
    """Expand one comparator into primitive ``(op, (major, minor))`` pairs.

    Primitive ops are limited to ``<``, ``<=``, ``>``, ``>=`` and ``==``.
    """
    if token.lower() in ("x", "*"):
        if op in (None, "="):
            return []
        raise ValueError(f"Operator {op!r} cannot be applied to a wildcard")

    if re.fullmatch(r"\d+(\.[xX*])?", token):
        major = int(token.split(".")[0])
        low, high = _partial_bounds(major)
        if op in (None, "=", "^", "~"):
            return [(">=", low), ("<", high)]
        if op == ">":
            return [(">=", high)]
        if op == ">=":
            return [(">=", low)]
        if op == "<":
            return [("<", low)]
        if op == "<=":
            return [("<", high)]

    version = parse_version(token)
    if op in (None, "="):
        return [("==", version)]
    if op in ("<", "<=", ">", ">="):
        return [(op, version)]
    if op == "^":
        return [(">=", version), ("<", (version[0] + 1, 0))]
    if op == "~":
        return [(">=", version), ("<", (version[0], version[1] + 1))]
    raise ValueError(f"Unknown operator: {op!r}")


def _parse_alternative(text):
    """Parse one ``||``-free clause into a list of primitive comparators."""
    hyphen = re.fullmatch(r"\s*(\S+)\s+-\s+(\S+)\s*", text)
    if hyphen:
        low_token, high_token = hyphen.groups()
        comparators = []
        if re.fullmatch(r"\d+(\.[xX*])?", low_token):
            comparators.append((">=", (int(low_token.split(".")[0]), 0)))
        else:
            comparators.append((">=", parse_version(low_token)))
        if re.fullmatch(r"\d+(\.[xX*])?", high_token):
            comparators.append(("<", (int(high_token.split(".")[0]) + 1, 0)))
        else:
            comparators.append(("<=", parse_version(high_token)))
        return comparators

    comparators = []
    pos = 0
    stripped = text.strip()
    while pos < len(stripped):
        match = _COMPARATOR_RE.match(stripped, pos)
        if not match:
            raise ValueError(f"Invalid section range: {text.strip()!r}")
        comparators.extend(_comparator_to_bounds(match.group(1), match.group(2)))
        pos = match.end()
    return comparators


def _satisfies(version, op, reference):
    if op == "==":
        return version == reference
    if op == "<":
        return version < reference
    if op == "<=":
        return version <= reference
    if op == ">":
        return version > reference
    if op == ">=":
        return version >= reference
    raise ValueError(f"Unknown primitive operator: {op!r}")


class Range:
    """A parsed section range; use :meth:`match` to test section numbers."""

    def __init__(self, alternatives):
        self._alternatives = alternatives

    def match(self, value):
        """Return True if the section number falls within this range.

        Raises ValueError if ``value`` is not a valid section number.
        """
        version = parse_version(value)
        return any(
            all(_satisfies(version, op, ref) for op, ref in alternative)
            for alternative in self._alternatives
        )


def parse_range(spec):
    """Parse a range specification string into a :class:`Range`.

    Raises ValueError if the specification is not valid.
    """
    text = str(spec).strip()
    if not text:
        return Range([[]])
    return Range([_parse_alternative(part) for part in text.split("||")])

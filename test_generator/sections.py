"""SemVer-style range matching for section numbers.

Section numbers are ``major.minor`` pairs (e.g. ``1.3``) -- there is no
patch component. Range syntax follows npm's semver ranges:

- ``||`` separates alternatives; a version matches if any alternative matches.
- Hyphen ranges: ``1.3 - 1.7`` (inclusive on both ends).
- Space-separated comparators that must all hold: ``>=1.3 <1.8`` with
  operators ``<``, ``<=``, ``>``, ``>=``, ``=`` (or no operator for an
  exact match).
- Wildcards: ``1.x`` / ``1.*`` (any minor within major 1), ``*`` / ``x``
  (any section, including labels).
- ``^1.3`` means ``>=1.3 <2.0``; ``~1.3`` means ``>=1.3 <1.4``.

A section can also be a *label*: a major followed by a non-numeric minor
(e.g. ``2.F``) for material outside the numbered topics. Labels have no
numeric order; a range matches one only when an alternative names it
exactly (e.g. ``2.1 - 2.8 || 2.F``) or is a ``*`` wildcard.
"""
import re

# A concrete section number as a comparable (major, minor) pair.
Version = tuple[int, int]
# A section: a numbered version or a non-numeric label such as "2.F".
Section = Version | str
# A primitive comparator: an operator ("<", "<=", ">", ">=", "==") and a bound.
Comparator = tuple[str, Version]
# One ``||`` alternative: comparators that must all hold, or an exact label.
Alternative = list[Comparator] | str

_COMPARATOR_RE = re.compile(
    r"\s*(>=|<=|>|<|\^|~|=)?\s*(\d+(?:\.(?:\d+|[xX*]))?|[xX*])"
)
# A label: a major, a dot, and a minor starting with a letter (not a wildcard).
_LABEL_RE = re.compile(r"\d+\.(?![xX]$)[A-Za-z][A-Za-z0-9_-]*")


def parse_section(value: str | float) -> Section:
    """Parse a section number or label.

    Raises ValueError if ``value`` is neither a ``major.minor`` number nor a
    label such as ``2.F``.
    """
    text = str(value).strip()
    if _LABEL_RE.fullmatch(text):
        return text
    return parse_version(text)


def section_sort_key(section: Section) -> tuple[int, Version, str, str]:
    """Sort key placing numbered sections in order, then labels alphabetically."""
    if isinstance(section, str):
        return (1, (0, 0), section.casefold(), section)
    return (0, section, "", "")


def format_section(section: Section) -> str:
    """Render a section as written in question files (e.g. ``1.10``, ``2.F``)."""
    if isinstance(section, str):
        return section
    return f"{section[0]}.{section[1]}"


def parse_version(value: str | float) -> Version:
    """Parse a concrete section number into a ``(major, minor)`` tuple."""
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?", text)
    if not match:
        raise ValueError(f"Invalid section number: {value!r}")
    return (int(match.group(1)), int(match.group(2) or 0))


def _partial_bounds(major: int) -> tuple[Version, Version]:
    """Bounds for a major-only version: >=major.0 and <(major+1).0."""
    return (major, 0), (major + 1, 0)


def _comparator_to_bounds(op: str | None, token: str) -> list[Comparator]:
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


def _parse_alternative(text: str) -> Alternative:
    """Parse one ``||``-free clause into primitive comparators or a label."""
    if _LABEL_RE.fullmatch(text.strip()):
        return text.strip()
    hyphen = re.fullmatch(r"\s*(\S+)\s+-\s+(\S+)\s*", text)
    if hyphen:
        low_token, high_token = hyphen.groups()
        comparators: list[Comparator] = []
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


def _satisfies(version: Version, op: str, reference: Version) -> bool:
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

    def __init__(self, alternatives: list[Alternative]) -> None:
        self._alternatives = alternatives

    def match(self, value: str | float) -> bool:
        """Return True if the section number or label falls within this range.

        A label matches only an alternative naming it exactly or a ``*``
        wildcard (an alternative with no comparators). Raises ValueError if
        ``value`` is not a valid section number or label.
        """
        section = parse_section(value)
        if isinstance(section, str):
            return any(
                alternative == section or alternative == []
                for alternative in self._alternatives
            )
        return any(
            all(_satisfies(section, op, ref) for op, ref in alternative)
            for alternative in self._alternatives
            if not isinstance(alternative, str)
        )

    def concrete_sections(self) -> set[Section] | None:
        """Every concrete section this range matches, or None if unbounded.

        A range is enumerable when each alternative names a label, pins
        exact versions, or has finite lower and upper bounds within a single
        major (e.g. ``1.3 - 1.7``). Wildcards, cross-major spans, and
        one-sided bounds (e.g. ``1.x``, ``>=1.3``) return None.
        """
        sections: set[Section] = set()
        for alternative in self._alternatives:
            if isinstance(alternative, str):
                sections.add(alternative)
                continue
            pins = {ref for op, ref in alternative if op == "=="}
            if pins:
                sections.update(
                    pin for pin in pins
                    if all(_satisfies(pin, op, ref) for op, ref in alternative)
                )
                continue
            lower: Version | None = None
            upper: Version | None = None
            for op, ref in alternative:
                if op in (">=", ">"):
                    bound = ref if op == ">=" else (ref[0], ref[1] + 1)
                    lower = bound if lower is None else max(lower, bound)
                else:  # "<" or "<="
                    if op == "<" and ref[1] == 0:
                        return None  # the last minor of the prior major is unknown
                    bound = ref if op == "<=" else (ref[0], ref[1] - 1)
                    upper = bound if upper is None else min(upper, bound)
            if lower is None or upper is None or lower[0] != upper[0]:
                return None
            sections.update((lower[0], m) for m in range(lower[1], upper[1] + 1))
        return sections


def parse_range(spec: str) -> Range:
    """Parse a range specification string into a :class:`Range`.

    Raises ValueError if the specification is not valid.
    """
    text = str(spec).strip()
    if not text:
        return Range([[]])
    return Range([_parse_alternative(part) for part in text.split("||")])

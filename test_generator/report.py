"""Post-generation summary report for a set of exam questions."""

from collections import Counter

from .core import Question, _question_sections
from .sections import parse_range

# DOK levels always shown in the histogram, even with zero questions.
DOK_LEVELS = (1, 2, 3, 4)


def _effective_dok(q: Question) -> int | None:
    """Return a question's DOK level.

    Question-level ``dok`` wins; a multipart question without one is rated
    by its hardest part. Returns ``None`` when no DOK is recorded.
    """
    if q.get("dok") is not None:
        return int(q["dok"])
    part_doks = [
        int(part["dok"])
        for part in (q.get("parts") or [])
        if part.get("dok") is not None
    ]
    return max(part_doks) if part_doks else None


def _histogram_lines(rows: list[tuple[str, int]]) -> list[str]:
    """Render ``(label, count)`` rows as bar-chart lines, labels padded."""
    width = max((len(label) for label, _ in rows), default=0)
    lines: list[str] = []
    for label, count in rows:
        columns = [label.ljust(width), "█" * count, str(count)]
        lines.append("  " + " ".join(c for c in columns if c))
    return lines


def format_report(questions: list[Question], sections: str | None = None) -> str:
    """Return a console report: section coverage, DOK histogram, average DOK.

    Each question counts once toward every section it covers (union across
    parts for multipart questions). When ``sections`` (a section range
    spec) is given and finitely enumerable, every section in the range is
    listed, including those with zero questions; DOK levels 1-4 are always
    listed. Questions without a DOK appear in an ``n/a`` row and are
    excluded from the average.
    """
    section_counts: Counter[tuple[int, int]] = Counter()
    dok_counts: Counter[int] = Counter()
    no_dok = 0
    for q in questions:
        section_counts.update(_question_sections(q))
        dok = _effective_dok(q)
        if dok is None:
            no_dok += 1
        else:
            dok_counts[dok] += 1

    section_domain = set(section_counts)
    if sections is not None:
        in_range = parse_range(sections).concrete_sections()
        if in_range is not None:
            section_domain |= in_range

    lines = [f"Test report: {len(questions)} question(s)"]

    lines.append("Section coverage:")
    section_rows = [
        (f"{major}.{minor}", section_counts[(major, minor)])
        for major, minor in sorted(section_domain)
    ]
    lines.extend(_histogram_lines(section_rows) or ["  (no sections listed)"])

    lines.append("DOK levels:")
    dok_rows = [
        (str(dok), dok_counts[dok])
        for dok in sorted(set(dok_counts) | set(DOK_LEVELS))
    ]
    if no_dok:
        dok_rows.append(("n/a", no_dok))
    lines.extend(_histogram_lines(dok_rows))

    rated = sum(dok_counts.values())
    if rated:
        average = sum(dok * n for dok, n in dok_counts.items()) / rated
        lines.append(f"Average DOK: {average:.2f}")
    else:
        lines.append("Average DOK: n/a")

    return "\n".join(lines)

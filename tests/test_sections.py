import pytest

from test_generator.sections import parse_range, parse_version


def test_parse_version() -> None:
    assert parse_version("1.3") == (1, 3)
    assert parse_version(1.3) == (1, 3)
    assert parse_version("2") == (2, 0)
    assert parse_version(" 1.12 ") == (1, 12)


@pytest.mark.parametrize("bad", ["", "abc", "1.2.3", "1.x", "-1.2"])
def test_parse_version_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_version(bad)


def test_exact_match() -> None:
    r = parse_range("1.3")
    assert r.match("1.3")
    assert not r.match("1.4")
    assert not r.match("2.3")


def test_exact_match_with_equals() -> None:
    r = parse_range("=1.3")
    assert r.match("1.3")
    assert not r.match("1.4")


def test_hyphen_range() -> None:
    r = parse_range("1.3 - 1.7")
    assert not r.match("1.2")
    assert r.match("1.3")
    assert r.match("1.5")
    assert r.match("1.7")
    assert not r.match("1.8")
    assert not r.match("2.0")


def test_hyphen_range_partial_ends() -> None:
    # A bare major on the high end means "anything in that major".
    r = parse_range("1.3 - 2")
    assert r.match("1.3")
    assert r.match("2.9")
    assert not r.match("3.0")


def test_comparators() -> None:
    r = parse_range(">=1.3 <1.8")
    assert not r.match("1.2")
    assert r.match("1.3")
    assert r.match("1.7")
    assert not r.match("1.8")

    r = parse_range(">1.3 <=1.8")
    assert not r.match("1.3")
    assert r.match("1.4")
    assert r.match("1.8")
    assert not r.match("1.9")


def test_or_alternatives() -> None:
    r = parse_range("1.3 || 1.7 - 1.9 || >=3.1")
    assert r.match("1.3")
    assert not r.match("1.4")
    assert r.match("1.8")
    assert not r.match("2.0")
    assert r.match("3.1")
    assert r.match("4.0")


def test_wildcards() -> None:
    r = parse_range("1.x")
    assert r.match("1.0")
    assert r.match("1.99")
    assert not r.match("2.0")

    assert parse_range("1.*").match("1.5")
    assert parse_range("*").match("7.2")
    assert parse_range("x").match("7.2")


def test_bare_major() -> None:
    r = parse_range("1")
    assert r.match("1.0")
    assert r.match("1.9")
    assert not r.match("2.0")


def test_caret_and_tilde() -> None:
    r = parse_range("^1.3")
    assert r.match("1.3")
    assert r.match("1.9")
    assert not r.match("1.2")
    assert not r.match("2.0")

    r = parse_range("~1.3")
    assert r.match("1.3")
    assert not r.match("1.4")
    assert not r.match("1.2")


def test_empty_spec_matches_everything() -> None:
    assert parse_range("").match("1.3")
    assert parse_range("  ").match("9.9")


@pytest.mark.parametrize("bad", ["abc", ">=", "1.3 -1.7", "1.3.5", ">*"])
def test_invalid_ranges(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_range(bad)


def test_match_invalid_version_raises() -> None:
    with pytest.raises(ValueError):
        parse_range("1.3").match("unknown")


def test_concrete_sections_hyphen_range() -> None:
    result = parse_range("1.3 - 1.7").concrete_sections()
    assert result == {(1, 3), (1, 4), (1, 5), (1, 6), (1, 7)}


def test_concrete_sections_exact_and_alternatives() -> None:
    assert parse_range("1.3").concrete_sections() == {(1, 3)}
    result = parse_range("1.3 || 2.1 - 2.2").concrete_sections()
    assert result == {(1, 3), (2, 1), (2, 2)}


def test_concrete_sections_unbounded() -> None:
    assert parse_range("*").concrete_sections() is None
    assert parse_range("1.x").concrete_sections() is None
    assert parse_range(">=1.3").concrete_sections() is None
    assert parse_range("1.3 - 2.4").concrete_sections() is None

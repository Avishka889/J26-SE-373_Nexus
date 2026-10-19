"""The check every quote must pass: in the notes, character for character."""

from c4.risk.notes import Section, locate, normalise, split_changelog

CHANGELOG = """\
# Changelog

All notable changes are documented here.

## [2.0.0] - 2026-01-01
- Removed `Client.connectLegacy()`; use `Client.connect()` instead.

## v1.5.0
- Deprecated `Pool.drain()`; it will be
  removed in 3.0.

### 1.4.2
- Fixed a crash.
"""


def test_each_release_heading_starts_a_section() -> None:
    sections = split_changelog(CHANGELOG)
    assert [section.version for section in sections] == ["2.0.0", "1.5.0", "1.4.2"]


def test_the_preamble_belongs_to_no_release() -> None:
    assert not any("notable changes" in section.text for section in split_changelog(CHANGELOG))


def test_a_rewrapped_quote_is_still_the_quote() -> None:
    """The model joined a wrapped line: a transcription, not an invention."""
    found = locate(
        "Deprecated `Pool.drain()`; it will be removed in 3.0.", split_changelog(CHANGELOG)
    )
    assert found is not None and found.version == "1.5.0"


def test_a_changed_word_is_not_the_quote() -> None:
    assert locate("Removed `Client.connectOld()`; use", split_changelog(CHANGELOG)) is None


def test_a_dropped_backtick_is_not_the_quote() -> None:
    assert locate("Removed Client.connectLegacy()", split_changelog(CHANGELOG)) is None


def test_an_ellipsis_is_not_the_quote() -> None:
    assert (
        locate("Removed `Client.connectLegacy()` ... instead.", split_changelog(CHANGELOG)) is None
    )


def test_an_empty_quote_is_in_nothing() -> None:
    assert locate("   ", [Section("1.0.0", "anything")]) is None


def test_normalising_only_touches_whitespace() -> None:
    assert normalise("  a\n\tb   c ") == "a b c"

"""version_order — release parsing, numeric ordering, zero padding, bump type."""

import re

import pytest

from claude_acc_manager.update.domain.services.version_order import (
    ReleaseType,
    is_newer,
    parse_release,
    release_type,
)


class TestParseRelease:
    def test_a_final_release_parses_to_an_int_tuple(self) -> None:
        # Arrange
        text = "1.1.0"

        # Act
        parsed = parse_release(text)

        # Assert
        assert parsed == (1, 1, 0)

    def test_two_components_are_a_release(self) -> None:
        assert parse_release("1.10") == (1, 10)

    @pytest.mark.parametrize(
        "text",
        [
            "1.2.0rc1",
            "1.2.0.dev3",
            "1.2.0.post1",
            "0.0.0+local",
            "v1.2.0",
            "1",
            "",
            "1.2.3\n",
            "1..2",
            "1.2.",
            "١.٢",
        ],
    )
    def test_anything_but_a_final_release_is_none(self, text: str) -> None:
        assert parse_release(text) is None


class TestIsNewer:
    def test_ordering_is_numeric_not_lexical(self) -> None:
        assert is_newer("1.9.0", "1.10.0") is True

    def test_an_equal_version_is_not_newer(self) -> None:
        assert is_newer("1.1.0", "1.1.0") is False

    def test_an_older_version_is_not_newer(self) -> None:
        assert is_newer("1.2.0", "1.1.9") is False

    @pytest.mark.parametrize(
        ("current", "candidate"),
        [("1.1", "1.1.0"), ("1.1.0", "1.1"), ("0.0", "0.0.0"), ("0.0.0", "0.0")],
    )
    def test_zero_padding_makes_lengths_equal(self, current: str, candidate: str) -> None:
        assert is_newer(current, candidate) is False

    def test_an_extra_nonzero_component_is_newer(self) -> None:
        assert is_newer("1.1.0", "1.1.0.1") is True

    @pytest.mark.parametrize(
        ("current", "candidate"),
        [("0.0.0+local", "1.1.0"), ("1.1.0", "1.2.0rc1"), ("1.1.0", "garbage")],
    )
    def test_a_malformed_side_is_never_an_update(self, current: str, candidate: str) -> None:
        assert is_newer(current, candidate) is False


class TestReleaseType:
    @pytest.mark.parametrize(
        ("current", "latest", "expected"),
        [
            ("1.9.9", "2.0.0", ReleaseType.MAJOR),
            # theirs' major equals ours' minor: only a same-index compare says MAJOR.
            ("1.2.0", "2.0.0", ReleaseType.MAJOR),
            ("1.1.9", "1.2.0", ReleaseType.MINOR),
            # theirs' patch equals ours' minor: only a same-index compare says MINOR.
            ("1.1.0", "1.2.1", ReleaseType.MINOR),
            ("1.1.0", "1.1.1", ReleaseType.PATCH),
            ("1.1", "1.1.1", ReleaseType.PATCH),
        ],
    )
    def test_the_first_differing_component_names_the_bump(
        self, current: str, latest: str, expected: ReleaseType
    ) -> None:
        assert release_type(current, latest) is expected

    @pytest.mark.parametrize(
        ("current", "latest", "offending"),
        [("0.0.0+local", "1.1.0", "0.0.0+local"), ("1.1.0", "2.0rc1", "2.0rc1")],
    )
    def test_a_non_release_raises_naming_the_value(
        self, current: str, latest: str, offending: str
    ) -> None:
        with pytest.raises(ValueError, match=re.escape(repr(offending))):
            release_type(current, latest)

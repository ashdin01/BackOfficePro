"""Tests for utils/text_search.py — shared multi-word client-side filter,
mirroring models.product.search()'s matching semantics."""
from utils.text_search import matches_all_words


class TestMatchesAllWords:
    def test_single_word_single_field_match(self):
        assert matches_all_words("oasis", "OASIS BEETROOT DIP") is True

    def test_single_word_no_match(self):
        assert matches_all_words("zzz", "OASIS BEETROOT DIP") is False

    def test_case_insensitive(self):
        assert matches_all_words("OASIS", "oasis beetroot dip") is True

    def test_multi_word_all_must_match_same_field(self):
        assert matches_all_words("oasis garlic", "OASIS GARLIC DIP") is True
        assert matches_all_words("oasis garlic", "OASIS BEETROOT DIP") is False

    def test_multi_word_can_match_across_different_fields(self):
        # "smith" in name, "acme" in code — an AND across fields, not just one column
        assert matches_all_words("smith acme", "John Smith", "ACME-001") is True

    def test_multi_word_one_missing_word_fails(self):
        assert matches_all_words("smith zzz", "John Smith", "ACME-001") is False

    def test_empty_term_matches_everything(self):
        assert matches_all_words("", "anything") is True
        assert matches_all_words("   ", "anything") is True

    def test_none_field_treated_as_empty(self):
        assert matches_all_words("smith", None, "John Smith") is True
        assert matches_all_words("zzz", None, None) is False

    def test_substring_not_prefix_only(self):
        assert matches_all_words("mith", "John Smith") is True

    def test_no_fields_given(self):
        assert matches_all_words("anything") is False

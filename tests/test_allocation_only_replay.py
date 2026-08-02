from scripts.run_allocation_only_replay import (
    DEFAULT_MAX_ENGLISH_WORDS,
    _manifest_max_english_words,
)


def test_missing_manifest_word_limit_uses_stable_cut_contract():
    assert DEFAULT_MAX_ENGLISH_WORDS == 16
    assert _manifest_max_english_words({}) == 16
    assert _manifest_max_english_words({"max_english_words": 19}) == 19


if __name__ == "__main__":
    test_missing_manifest_word_limit_uses_stable_cut_contract()
    print("Allocation-only replay contract tests passed.")

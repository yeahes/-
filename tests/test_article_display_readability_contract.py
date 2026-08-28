"""Regression contracts for frozen bilingual article display pages."""

from __future__ import annotations

from copy import deepcopy
import copy
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.stable_display_page_contract import (
    build_display_page_contract,
    display_page_id,
    validate_page_translation_response,
)
from app.core.subtitle_processor.stable_display_planner import (
    plan_word_page_span_frontier,
    plan_word_page_spans,
    spans_cover_words,
)
from app.core.utils import podcast_learning_video


HARD_CUE_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "display_page_hard_cues.json"
)

FONT_FLOOR_REGRESSION_CASES = (
    {
        "subtitle_id": "S0095",
        "english": (
            "It completely undermines the premise that studying at a foreign "
            "university provides a radically different environment."
        ),
        "chinese": "这彻底动摇了“到外国大学读书就能获得截然不同环境”的前提。",
        "word_ids": range(953, 969),
        "start_ms": (
            321575, 321675, 322215, 322656, 322776, 323216, 323837, 324277,
            324357, 324437, 324717, 325237, 325558, 325658, 326058, 326298,
        ),
        "end_ms": (
            321635, 322155, 322616, 322736, 323116, 323396, 324237, 324337,
            324397, 324677, 325197, 325538, 325578, 326018, 326278, 326798,
        ),
    },
    {
        "subtitle_id": "S0115",
        "english": (
            "Especially when the domestic alternative has improved at such a "
            "staggering rate."
        ),
        "chinese": "尤其是当国内高校以如此惊人的速度进步时。",
        "word_ids": range(1146, 1158),
        "start_ms": (
            389340, 389580, 389680, 389780, 390241, 390921,
            391141, 391682, 391822, 392022, 392142, 392722,
        ),
        "end_ms": (
            389560, 389660, 389740, 390201, 390881, 391061,
            391642, 391762, 392002, 392062, 392662, 392962,
        ),
    },
    {
        "subtitle_id": "S0120",
        "english": (
            "Right. Those are the massive state-sponsored initiatives where the "
            "Chinese government poured billions into elevating specific domestic "
            "universities to world-class status."
        ),
        "chinese": (
            "没错。那些都是政府大力支持的庞大计划，中国政府投入了数十亿美元，"
            "将特定的国内大学提升到世界一流水平。"
        ),
        "word_ids": range(1214, 1235),
        "start_ms": (
            413068, 413236, 413456, 413556, 413736, 414337, 415157,
            415698, 415878, 415978, 416338, 417099, 417499, 418259,
            418620, 419140, 419720, 420161, 421241, 421482, 422222,
        ),
        "end_ms": (
            413216, 413416, 413536, 413616, 414217, 415117, 415638,
            415858, 415938, 416298, 416698, 417359, 418099, 418520,
            419020, 419660, 420101, 420821, 421382, 422182, 422682,
        ),
    },
)

TIGHT_COMPLEMENT_BOUNDARY_CASES = (
    {
        "text": (
            "I mean, for decades, sending a kid abroad for university was like "
            "the ultimate flex for a Chinese family."
        ),
        "left": "abroad",
        "right": "for",
        "pause_ms": 20,
        "issue_codes": ("dependency_phrase_entrance_split",),
    },
    {
        "text": (
            "It is a total inversion of expectations for the student and just a "
            "devastating financial blow for the parents who footed the bill."
        ),
        "left": "expectations",
        "right": "for",
        "pause_ms": 40,
        "issue_codes": (
            "coordinated_constituent_split",
            "dependency_phrase_entrance_split",
        ),
    },
    {
        "text": (
            "Studying abroad no longer automatically translates into an ability "
            "to fit into a highly competitive domestic workplace."
        ),
        "left": "ability",
        "right": "to",
        "pause_ms": 60,
        "issue_codes": ("verb_complement_split",),
    },
    {
        "text": (
            "Right. Those are the massive state-sponsored initiatives where the "
            "Chinese government poured billions into elevating specific domestic "
            "universities to world-class status."
        ),
        "left": "billions",
        "right": "into",
        "pause_ms": 160,
        "issue_codes": (
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
        ),
    },
    {
        "text": (
            "In 2025, the administration of President Donald Trump announced that "
            "it would aggressively revoke visas for Chinese nationals studying in "
            "unspecified critical fields."
        ),
        "left": "visas",
        "right": "for",
        "pause_ms": 0,
        "issue_codes": (
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
        ),
    },
    {
        "text": (
            "Right. And when you compare 100 000 yuan total investment in Malaysia "
            "to the 605 000 yuan average cost for traditional Western foreign study, "
            "it just becomes a cold financial equation."
        ),
        "left": "investment",
        "right": "in",
        "pause_ms": 40,
        "issue_codes": ("dependency_phrase_entrance_split",),
    },
)


def _cue(
    text: str,
    subtitle_id: str,
    chinese: str = "测试中文。",
    *,
    word_timing=None,
    display_boundary_evidence=None,
):
    words = text.split()
    if word_timing is None:
        word_timing = tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.45,
                "end": index * 0.45 + 0.32,
            }
            for index, word in enumerate(words)
        )
    else:
        word_timing = tuple(word_timing)
    cue_start = float(word_timing[0]["start"])
    cue_end = float(word_timing[-1]["end"])
    return podcast_learning_video.Cue(
        int(subtitle_id[1:]),
        cue_start,
        cue_end,
        text,
        chinese,
        "male",
        subtitle_id=subtitle_id,
        word_timing=word_timing,
        display_boundary_evidence=display_boundary_evidence,
    )


def _plan(cue):
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    result = podcast_learning_video._build_article_english_page_plan(cue, draw)
    assert result["status"] == "ok"
    return result


def _page_starts(plan):
    return {page["word_start"] for page in plan["pages"][1:]}


def test_candidate_workspace_is_read_only_and_bounded():
    cue = _cue(
        "The domestic alternative has improved at a staggering rate, especially in the last decade.",
        "S0007",
    )
    before = deepcopy(cue.__dict__)
    workspace = podcast_learning_video.build_article_display_page_candidate_workspace(
        cue,
        min_page_count=2,
        max_page_count=4,
    )
    assert workspace["status"] == "candidate_workspace"
    assert 0 < len(workspace["candidates"]) <= 3
    assert all(2 <= candidate["page_count"] <= 4 for candidate in workspace["candidates"])
    assert cue.__dict__ == before


def test_candidate_workspace_allows_explicit_manual_six_page_search():
    cue = _cue(
        "one two three four five six seven eight nine ten eleven twelve",
        "S0008",
    )
    candidates = [
        {
            "page_count": page_count,
            "quality_cost": float(page_count),
            "plan": {},
            "pages": [],
        }
        for page_count in range(2, 7)
    ]
    with patch.object(
        podcast_learning_video,
        "_build_article_english_page_plan",
        return_value={
            "status": "candidate_bundle",
            "preferred_page_count": 2,
            "candidate_mode": "strict",
            "candidates": candidates,
        },
    ) as builder:
        workspace = (
            podcast_learning_video.build_article_display_page_candidate_workspace(
                cue,
                min_page_count=2,
                max_page_count=6,
            )
        )

    assert builder.call_args.kwargs["max_page_count"] == 6
    assert [candidate["page_count"] for candidate in workspace["candidates"]] == [
        2,
        3,
        4,
        5,
        6,
    ]


def _production_word_timing(words, word_ids, start_ms, end_ms):
    assert len(words) == len(word_ids) == len(start_ms) == len(end_ms)
    return tuple(
        {
            "word_id": word_id,
            "surface": word,
            "start": start / 1000.0,
            "end": end / 1000.0,
        }
        for word, word_id, start, end in zip(words, word_ids, start_ms, end_ms)
    )


def _word_timing_with_gaps(text: str, gaps_ms: dict[int, int] | None = None):
    words = text.split()
    gaps_ms = gaps_ms or {}
    cursor_ms = 0
    timing = []
    for index, word in enumerate(words):
        timing.append(
            {
                "word_id": index,
                "surface": word,
                "start": cursor_ms / 1000.0,
                "end": (cursor_ms + 220) / 1000.0,
            }
        )
        cursor_ms += 220 + int(gaps_ms.get(index, 80))
    return tuple(timing)


def _syntax_backed_cue(text: str, subtitle_id: str, *, word_timing=None):
    words = text.split()
    if word_timing is None:
        word_timing = tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.45,
                "end": index * 0.45 + 0.32,
            }
            for index, word in enumerate(words)
        )
    else:
        word_timing = tuple(word_timing)
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = 16
    editor._active_word_entries = [
        {
            "token": ScreenSubtitleEditor._word_tokens(word)[0],
            "surface": word,
            "start_time": round(float(timing["start"]) * 1000),
            "end_time": round(float(timing["end"]) * 1000),
            "alignment_source": "fixture",
        }
        for word, timing in zip(words, word_timing)
    ]
    editor._active_source_word_spans = {1: (0, len(words) - 1)}
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_soft_cut_issues = {}
    editor._orphaned_finite_predicate_cache = {}
    editor._syntax_nlp = None
    editor._prepare_syntax_cut_hints()
    local_evidence = editor._display_boundary_evidence_for_span(0, len(words) - 1)
    evidence = {
        str(word_timing[int(local_word_id)]["word_id"]): value
        for local_word_id, value in local_evidence.items()
    }
    cue = _cue(
        text,
        subtitle_id,
        word_timing=word_timing,
        display_boundary_evidence=evidence,
    )
    return editor, cue


def test_display_planning_does_not_mutate_frozen_cue_identity_text_or_timing():
    cue = _cue(
        "The research shows that Chinese businesses, collectively, spend less than "
        "one-tenth of what American firms spend on software.",
        "S0196",
        "研究显示，中国企业整体的软件支出还不到美国企业软件支出的十分之一。",
    )
    snapshot = (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, deepcopy(cue.word_timing))

    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])

    assert blueprint["render_plans"][0]["parent_subtitle_id"] == "S0196"
    assert (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, cue.word_timing) == snapshot


def test_numeric_magnitude_is_nonoverridable_at_display_page_boundary():
    decision = {
        "classification": "review",
        "issue_codes": ["numeric_unit_or_noun_split"],
        "strong_pause_evidence": True,
        "pause_ms": 900,
        "balanced_predicate_restart": True,
    }

    assert podcast_learning_video._article_nonoverridable_atomic_page_boundary_issues(
        decision
    ) == {"numeric_unit_or_noun_split"}
    assert not podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "billion people suddenly changed the market.",
            "boundary_before": decision,
        }
    )


def test_visual_planning_reuses_the_complete_frozen_page_projection():
    text = "Teams compare evidence before approving major policy changes."
    cue = _cue(text, "S9000", "团队会先比较证据，再批准重大政策调整。")
    words = text.split()
    split = 4
    frozen = {
        "status": "ok",
        "planner_version": "fixture-frozen-plan",
        "font_size": {"english": 50, "chinese": 46},
        "font_fallback": {
            "used": True,
            "from": 56,
            "to": 50,
            "reason": "no_safe_higher_font_layout",
        },
        "pages": [
            {
                "index": 0,
                "display_page_id": "S9000.P01",
                "parent_subtitle_id": "S9000",
                "en": " ".join(words[:split]),
                "zh": "团队会先比较证据，",
                "word_start": 0,
                "word_end": split - 1,
                "global_word_start": 0,
                "global_word_end": split - 1,
                "start": cue.start,
                "end": cue.word_timing[split]["start"],
                "en_lines": [" ".join(words[:split])],
                "english_font_size": 50,
                "en_width": 1260,
            },
            {
                "index": 1,
                "display_page_id": "S9000.P02",
                "parent_subtitle_id": "S9000",
                "en": " ".join(words[split:]),
                "zh": "再批准重大政策调整。",
                "word_start": split,
                "word_end": len(words) - 1,
                "global_word_start": split,
                "global_word_end": len(words) - 1,
                "start": cue.word_timing[split]["start"],
                "end": cue.end,
                "en_lines": [" ".join(words[split:])],
                "english_font_size": 50,
                "en_width": 1455,
            },
        ],
        "readability_warnings": [],
        "source": "frozen_display_page_artifact",
    }
    cue.article_page_plan = deepcopy(frozen)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with patch.object(
        podcast_learning_video,
        "_build_article_english_page_plan",
        side_effect=AssertionError("a frozen renderer projection must not be replanned"),
    ) as planner:
        result = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    planner.assert_not_called()
    assert result["source"] == frozen["source"]
    assert result["font_size"] == frozen["font_size"]
    assert len(result["pages"]) == len(frozen["pages"])
    identity_fields = (
        "display_page_id",
        "parent_subtitle_id",
        "english_font_size",
        "word_start",
        "word_end",
        "global_word_start",
        "global_word_end",
        "start",
        "end",
        "en",
        "zh",
    )
    for actual, expected in zip(result["pages"], frozen["pages"]):
        assert {key: actual[key] for key in identity_fields} == {
            key: expected[key] for key in identity_fields
        }


def test_subject_predicate_boundary_is_not_used_for_efficiency_gap_page_change():
    text = (
        "because I really want to understand how this massive efficiency gap is "
        "physically and mathematically possible."
    )
    words = text.split()
    # Production S0023 word timings: `gap | is` has the 600ms pause that made
    # the former v7 plan select this semantically poor subject-predicate split.
    editor, cue = _syntax_backed_cue(
        text,
        "S0023",
        word_timing=_production_word_timing(
            words,
            range(269, 285),
            [85358, 85618, 85858, 86198, 86378, 86498, 86939, 87099,
             87579, 88139, 88740, 89580, 90801, 91442, 91582, 92282],
            [85558, 85698, 86138, 86358, 86438, 86899, 87059, 87259,
             88079, 88700, 88980, 89720, 91382, 91522, 92222, 92722],
        ),
    )
    plan = _plan(cue)
    decision = podcast_learning_video._article_display_boundary_decision(
        cue, words.index("is")
    )
    efficiency_gap = editor._evaluate_stable_cut_boundary(
        words.index("efficiency"), words.index("gap")
    )

    assert decision["pause_ms"] == 600
    assert decision["classification"] == "review"
    assert "fronted_wh_clause_split" in efficiency_gap["hard_issues"]
    assert efficiency_gap["protected_syntax"] is True
    assert words.index("gap") not in _page_starts(plan)
    assert words.index("is") not in _page_starts(plan)
    # The subordinate wh clause must remain intact if the cue has to turn a page.
    assert not any(
        page["word_start"] > words.index("how")
        and page["word_start"] <= words.index("is")
        for page in plan["pages"][1:]
    )
    pages = plan["pages"]
    assert len(pages) == 2
    assert pages[1]["word_start"] == words.index("how")
    assert pages[0]["en"].endswith("understand")
    assert pages[1]["en"].startswith("how ")
    assert pages[1]["en"].endswith("possible.")
    assert " ".join(page["en"] for page in pages) == text


def test_zero_relative_tail_does_not_become_an_isolated_display_page():
    text = (
        "They basically commanded heavy industry to dial back consumption "
        "during the exact window the strait was shut."
    )
    words = text.split()
    _, cue = _syntax_backed_cue(text, "S0059")

    plan = _plan(cue)
    page_starts = _page_starts(plan)
    tail_start = next(
        index
        for index, (left, right) in enumerate(zip(words, words[1:]), 1)
        if left == "window" and right == "the"
    )

    assert tail_start not in page_starts
    assert all(page["en"] != "the strait was shut." for page in plan["pages"])
    assert " ".join(page["en"] for page in plan["pages"]) == text


def test_dominant_readability_selection_relieves_low_font_with_complete_phrases():
    cases = (
        {
            "subtitle_id": "S0059",
            "text": (
                "They basically commanded heavy industry to dial back consumption "
                "during the exact window the strait was shut."
            ),
            "chinese": "他们基本上下令重工业在海峡关闭期间减少消耗。",
            "word_ids": range(626, 643),
            "starts": (
                219847, 220007, 220487, 220967, 221307, 222068, 222388,
                222688, 222909, 223809, 224109, 224289, 224750, 225130,
                225250, 225510, 225650,
            ),
            "ends": (
                219967, 220447, 220867, 221227, 221748, 222168, 222648,
                222869, 223449, 224049, 224209, 224670, 225070, 225230,
                225470, 225610, 225871,
            ),
            "expected_pages": (
                "They basically commanded heavy industry to dial back consumption",
                "during the exact window the strait was shut.",
            ),
        },
        {
            "subtitle_id": "S0081",
            "text": (
                "I read it extracted up to 5.7 trillion from the global economy "
                "between 1970 and 2014."
            ),
            "chinese": "我读到1970至2014年，它从全球经济抽走最多5.7万亿美元。",
            "word_ids": range(873, 889),
            "starts": (
                303302, 303422, 303603, 303743, 304203, 304283, 304463,
                305364, 306404, 306524, 306625, 307025, 307485, 308206,
                308626, 308746,
            ),
            "ends": (
                303362, 303562, 303663, 304163, 304263, 304383, 304983,
                306344, 306504, 306605, 306985, 307425, 308166, 308586,
                308706, 309526,
            ),
            "expected_pages": (
                "I read it extracted up to 5.7 trillion",
                "from the global economy between 1970 and 2014.",
            ),
        },
    )
    for case in cases:
        timing = _production_word_timing(
            case["text"].split(),
            case["word_ids"],
            case["starts"],
            case["ends"],
        )
        _, cue = _syntax_backed_cue(
            case["text"],
            case["subtitle_id"],
            word_timing=timing,
        )
        cue.zh = case["chinese"]

        plan = _plan(cue)

        assert tuple(page["en"] for page in plan["pages"]) == case["expected_pages"]
        assert all(page["english_font_size"] == 56 for page in plan["pages"])
        assert all(page["end"] - page["start"] >= 0.9 for page in plan["pages"])
        assert all(len(page["en"].split()) >= 6 for page in plan["pages"])


def test_dominant_readability_selection_merges_a_comfortable_short_tail():
    text = (
        "Time that must be used to aggressively diversify supply sources and "
        "reduce overall consumption."
    )
    timing = _production_word_timing(
        text.split(),
        range(1436, 1450),
        (
            492769, 493190, 493330, 493530, 493730, 493890, 494050,
            494731, 495331, 495711, 496632, 496732, 497192, 497533,
        ),
        (
            493150, 493290, 493470, 493630, 493850, 493990, 494671,
            495291, 495671, 496052, 496692, 497092, 497513, 498033,
        ),
    )
    _, cue = _syntax_backed_cue(text, "S0135", word_timing=timing)
    cue.zh = "这段时间必须用来积极推进供应来源多元化，并降低整体消费。"

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [text]
    assert plan["pages"][0]["english_font_size"] == 56
    assert len(plan["pages"][0]["en_lines"]) <= 2


def test_wh_clause_boundary_is_not_used_for_chinese_businesses_page_change():
    text = (
        "The research shows that Chinese businesses, collectively, spend less than "
        "one-tenth of what American firms spend on software."
    )
    words = text.split()
    # Production S0196 timings with all ScreenSubtitleEditor syntax evidence
    # projected from local positions onto the global word IDs.
    _, cue = _syntax_backed_cue(
        text,
        "S0196",
        word_timing=_production_word_timing(
            words,
            range(2120, 2138),
            [728229, 728349, 728669, 728929, 729069, 729470, 730170,
             731131, 731431, 731651, 732031, 732672, 732772, 732932,
             733332, 733572, 733873, 733993],
            [728309, 728649, 728889, 729029, 729430, 729950, 730750,
             731371, 731611, 731791, 732632, 732732, 732892, 733272,
             733552, 733813, 733953, 734393],
        ),
    )
    cue.zh = "研究显示，中国企业整体的软件支出还不到美国企业软件支出的十分之一。"
    plan = _plan(cue)
    decision = podcast_learning_video._article_display_boundary_decision(
        cue, words.index("American")
    )

    pages = plan["pages"]
    assert len(pages) == 2
    assert pages[1]["word_start"] == words.index("spend")
    assert pages[0]["en"].endswith("collectively,")
    assert pages[1]["en"].startswith("spend ")
    assert " ".join(page["en"] for page in pages) == text
    assert words.index("American") not in _page_starts(plan)
    assert decision["pause_ms"] == 40
    assert decision["classification"] == "review"
    assert not any(
        page["word_start"] > words.index("what")
        and page["word_start"] <= words.index("American")
        for page in pages[1:]
    )


def test_unsplittable_infinitive_phrase_remains_renderable_at_the_52px_floor():
    text = (
        "Right. But these hardware constraints seem to have birthed an entirely "
        "different philosophical goal for AI."
    )
    editor, cue = _syntax_backed_cue(text, "S0161")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)
    words = text.split()
    evidence = editor._evaluate_stable_cut_boundary(
        words.index("seem"), words.index("to")
    )

    assert "verb_complement_split" in evidence["hard_issues"]
    assert plan["status"] == "ok"
    assert plan["font_size"]["english"] == 52
    assert plan["pages"]
    assert "seem to have birthed" in cue.en


def test_page_translation_contract_rejects_a_chinese_token_split_across_pages():
    contract = build_display_page_contract(
        [
            {
                "parent_subtitle_id": "S9001",
                "english": "Chinese businesses spend less on software.",
                "chinese": "中国企业的软件支出。",
                "word_start": 0,
                "word_end": 5,
                "pages": [
                    {
                        "display_page_id": display_page_id("S9001", 1),
                        "word_start": 0,
                        "word_end": 2,
                        "english": "Chinese businesses spend",
                        "start_ms": 0,
                        "end_ms": 1000,
                    },
                    {
                        "display_page_id": display_page_id("S9001", 2),
                        "word_start": 3,
                        "word_end": 5,
                        "english": "less on software.",
                        "start_ms": 1000,
                        "end_ms": 2000,
                    },
                ],
            }
        ],
        layout_profile={"template": "article", "english_font_size": 56, "chinese_font_size": 48},
    )

    result = validate_page_translation_response(
        contract,
        {
            "pages": [
                {"display_page_id": "S9001.P01", "zh": "中国企业的软"},
                {"display_page_id": "S9001.P02", "zh": "件支出。"},
            ]
        },
    )

    assert result["status"] == "ERROR"
    assert any(
        error.get("code") == "page_translation_chinese_token_split"
        for error in result.get("errors", [])
    )


def test_frozen_page_artifact_records_font_size_and_line_width_for_each_page():
    cue = _cue(
        "The research shows that Chinese businesses, collectively, spend less than "
        "one-tenth of what American firms spend on software.",
        "S0196",
        "研究显示，中国企业整体的软件支出还不到美国企业软件支出的十分之一。",
    )
    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    contract = build_display_page_contract(
        blueprint["parents"],
        layout_profile=blueprint["layout_profile"],
        planner_version=blueprint["planner_version"],
        render_plans=blueprint["render_plans"],
    )

    plan = contract["render_plans"][0]
    assert contract["layout_profile"]["english_font_size"] == 56
    assert contract["layout_profile"]["chinese_font_size"] == 50
    assert contract["layout_profile"]["chinese_letter_spacing"] == 0.0
    assert contract["layout_profile"]["english_font_fallback_sizes"] == [56, 54, 52]
    assert contract["layout_profile"]["english_emergency_fallback_sizes"] == []
    assert contract["layout_profile"]["english_legacy_readable_sizes"] == [50]
    assert contract["layout_profile"]["english_normal_min_size"] == 52
    assert contract["layout_profile"]["english_min_size"] == 52
    assert plan["english_font_size"] in podcast_learning_video.ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES
    assert plan["english_font_size"] == min(
        page["english_font_size"] for page in plan["pages"]
    )
    assert all(page["english_width"] > 0 for page in plan["pages"])


def test_article_chinese_font_keeps_sixteen_characters_inside_safe_width():
    draw = ImageDraw.Draw(Image.new("RGB", (1600, 900)))
    font = podcast_learning_video.article_cjk_font(
        podcast_learning_video.ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        700,
    )
    sample = "这是一条十六个汉字的中文显示字幕"

    assert len(sample) == 16
    assert podcast_learning_video.ARTICLE_SUBTITLE_ZH_FONT_SIZE == 50
    assert podcast_learning_video.ARTICLE_SUBTITLE_ZH_LETTER_SPACING == 0.0
    assert podcast_learning_video.article_subtitle_zh_text_w(draw, sample, font) <= (
        podcast_learning_video.acx(podcast_learning_video.ARTICLE_SUBTITLE_ZH_WIDTH)
    )


def test_article_chinese_subtitle_measurement_uses_default_letter_spacing():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    font = podcast_learning_video.article_cjk_font(
        podcast_learning_video.ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        700,
    )
    sample = "中文字幕字距测试"

    assert podcast_learning_video.article_subtitle_zh_text_w(draw, sample, font) == (
        podcast_learning_video.text_w(draw, sample, font)
    )
    assert podcast_learning_video.wrap_article_zh(
        draw,
        sample,
        font,
        podcast_learning_video.article_subtitle_zh_text_w(draw, sample, font),
    ) == [sample]


def test_page_span_score_prefers_balanced_legal_boundary_when_risk_is_equal():
    """A 4|20 page split must lose to 12|12 when syntax risk is identical."""
    readable = {(0, 4), (4, 24), (0, 12), (12, 24)}
    spans = plan_word_page_spans(
        24,
        2,
        cue_start=0.0,
        cue_end=20.0,
        span_is_readable=lambda start, end, _first, _paginated: (start, end)
        in readable,
        break_score=lambda end, _target: 0.0 if end in {4, 12} else None,
        span_score=lambda start, end: abs((end - start) - 12),
    )

    assert spans == [(0, 12), (12, 24)]


def test_page_span_frontier_retains_distinct_safe_visual_partitions():
    readable = {
        (0, 4),
        (4, 10),
        (0, 5),
        (5, 10),
        (0, 6),
        (6, 10),
    }

    frontier = plan_word_page_span_frontier(
        10,
        2,
        cue_start=0.0,
        cue_end=8.0,
        span_is_readable=lambda start, end, _first, _paginated: (start, end)
        in readable,
        break_score=lambda end, _target: 0.0 if end in {4, 5, 6} else None,
        span_score=lambda start, end: abs((end - start) - 5),
        max_candidates=3,
    )

    assert frontier == [
        [(0, 5), (5, 10)],
        [(0, 4), (4, 10)],
        [(0, 6), (6, 10)],
    ]
    assert all(
        spans_cover_words(spans, 10)
        for spans in frontier
    )


def test_reference_style_wrap_prefers_balanced_two_lines_before_wide_single_line():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "People today increasingly prefer simple local choices."

    lines = podcast_learning_video._article_fixed_english_lines(draw, text)
    font = podcast_learning_video.article_subtitle_en_font(56, 600)
    widths = [podcast_learning_video.text_w(draw, line, font) for line in lines]

    assert len(lines) == 2
    assert " ".join(lines) == text
    assert min(widths) / max(widths) >= 0.80
    assert not podcast_learning_video._has_discouraged_caption_break(text, lines)


def test_same_screen_wrap_does_not_favor_a_short_punctuation_prefix():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "But, you know, not by a massive increase in production."
    lines = podcast_learning_video._article_fixed_english_lines(
        draw,
        text,
        font_size=56,
        relax_same_screen_syntax=True,
    )

    assert lines == [
        "But, you know, not",
        "by a massive increase in production.",
    ]
    widths = [podcast_learning_video.text_w(draw, line, podcast_learning_video.article_en_font(56, 600)) for line in lines]
    assert min(widths) / max(widths) >= 0.50


def test_same_screen_rejects_severe_short_manual_page_fragment():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "Okay. He stated definitively that artificial intelligence systems,"
    cue = _cue(
        text,
        "S0006",
        display_boundary_evidence={
            str(split): {"hard_issues": ["protected_syntax_cut"]}
            for split in (2, 3, 4, 5, 6, 7)
        },
    )

    lines = podcast_learning_video._article_same_screen_english_lines(
        draw,
        cue,
        text.split(),
        0,
        len(text.split()),
        56,
    )

    assert lines == []


def test_severe_processing_module_page_is_replanned():
    text = (
        "They're creating a central memory bank where the AI pulls data from "
        "different processing modules simultaneously."
    )
    cue = _cue(
        text,
        "S0063",
        display_boundary_evidence={
            "11": {
                "hard_issues": [
                    "dependency_phrase_entrance_split",
                    "object_attached_modifier_split",
                    "predicate_attached_continuation_split",
                ],
                "pause_ms": 280,
            }
        },
    )

    plan = _plan(cue)
    assert all(
        not podcast_learning_video._article_layout_has_severe_imbalance(
            ImageDraw.Draw(Image.new("RGB", (1920, 1080))),
            page["en_lines"],
            page["english_font_size"],
        )
        for page in plan["pages"]
    )


def test_severe_public_psychology_page_is_replanned():
    text = (
        "And the deep connection formed by that physical proximity, it'll "
        "inevitably lead to a massive psychological shift in the public."
    )
    cue = _cue(
        text,
        "S0088",
        display_boundary_evidence={
            "17": {
                "hard_issues": ["dependency_phrase_entrance_split"],
                "pause_ms": 480,
            }
        },
    )

    plan = _plan(cue)
    assert all(
        not podcast_learning_video._article_layout_has_severe_imbalance(
            ImageDraw.Draw(Image.new("RGB", (1920, 1080))),
            page["en_lines"],
            page["english_font_size"],
        )
        for page in plan["pages"]
    )


def test_hyphenated_word_is_not_a_barrier_after_the_complete_token():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "Since China's self-interest temporarily saved the market,"
    lines = podcast_learning_video._article_fixed_english_lines(
        draw,
        text,
        font_size=56,
        boundary_penalty=lambda split: 7_200 if split in {3, 5} else 12_000,
        relax_same_screen_syntax=True,
    )

    assert lines == [
        "Since China's self-interest",
        "temporarily saved the market,",
    ]


def test_extreme_same_screen_imbalance_uses_50px_only_on_the_legacy_path():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "No, you use massive pre-existing terrestrial infrastructure."
    cue = _cue(text, "S0025")

    def fake_layout(_draw, _text, _key=None, *, font_size, **_kwargs):
        if font_size == 50:
            return [text]
        return []

    with patch.object(
        podcast_learning_video,
        "_article_fixed_english_lines",
        side_effect=fake_layout,
    ):
        automatic_layout = podcast_learning_video._article_final_page_layout(
            draw,
            cue,
            text.split(),
            0,
            len(text.split()),
        )
        legacy_layout = podcast_learning_video._article_final_page_layout(
            draw,
            cue,
            text.split(),
            0,
            len(text.split()),
            allow_legacy_fallback=True,
        )

    assert automatic_layout is None
    assert legacy_layout == (50, [text])


def test_three_english_lines_and_one_chinese_line_use_separate_vertical_origin():
    assert podcast_learning_video.article_subtitle_origins(3, 1) == (552, 774)
    assert podcast_learning_video.article_subtitle_origins(3, 2) == (552, 746)


def test_manual_page_proposal_requires_explicit_hard_boundary_override():
    text = "One two three four five six seven eight nine ten eleven twelve."
    words = text.split()
    cue = _cue(
        text,
        "S0026",
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.45,
                "end": index * 0.45 + 0.35,
            }
            for index, word in enumerate(words)
        ),
        display_boundary_evidence={
            str(index): {
                "hard_issues": ["atomic_of_complement_split"],
                "soft_issues": [],
                "pause_ms": 100,
            }
            for index in range(1, len(words))
        },
    )

    try:
        podcast_learning_video.propose_article_manual_page_word_ranges(
            cue,
            2,
            allow_review_boundary=True,
        )
    except podcast_learning_video.RenderStructuralOverflowError as exc:
        assert any(
            item.get("reason") == "manual_page_count_has_no_safe_partition"
            for item in exc.errors
        )
    else:
        raise AssertionError("automatic and review planning must keep hard cuts blocked")

    ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
        cue,
        2,
        allow_review_boundary=True,
        allow_hard_boundary=True,
    )

    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(words) - 1
    assert ranges[0][1] + 1 == ranges[1][0]
    assert abs(
        (ranges[0][1] - ranges[0][0] + 1)
        - (ranges[1][1] - ranges[1][0] + 1)
    ) <= 2


def test_automatic_page_limit_stays_four_while_manual_can_request_six():
    assert podcast_learning_video.ARTICLE_VISUAL_PAGE_MAX_PAGES == 4
    assert podcast_learning_video.ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES == 6
    words = [f"word{index}" for index in range(24)]
    cue = _cue(
        " ".join(words),
        "S0027",
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.55,
                "end": index * 0.55 + 0.4,
            }
            for index, word in enumerate(words)
        ),
    )

    six_spans = [(index * 4, (index + 1) * 4) for index in range(6)]
    with patch.object(
        podcast_learning_video,
        "_partition_article_english_pages",
        return_value=six_spans,
    ), patch.object(
        podcast_learning_video,
        "_schedule_article_page_boundaries",
        return_value=([index * 2.0 for index in range(7)], ""),
    ):
        ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
            cue,
            6,
            allow_review_boundary=True,
            allow_hard_boundary=True,
        )

    automatic_page_counts = []

    def reject_automatic(
        _draw,
        _cue_value,
        _words,
        page_count,
        _timing,
        _font_size,
        *_args,
        **_kwargs,
    ):
        automatic_page_counts.append(int(page_count))
        return None

    with patch.object(
        podcast_learning_video,
        "_partition_article_english_pages",
        side_effect=reject_automatic,
    ):
        podcast_learning_video._build_article_english_page_plan(
            cue,
            ImageDraw.Draw(Image.new("RGB", (1920, 1080))),
        )

    assert len(ranges) == 6
    assert max(automatic_page_counts) == 4


def test_production_candidate_bundle_keeps_a_bounded_visual_frontier():
    text = (
        "Customers save money every day, stores grow quickly across China, "
        "workers gain valuable experience, and communities receive reliable "
        "services nationwide."
    )
    words = text.split()
    cue = _cue(
        text,
        "S9303",
        display_boundary_evidence={
            str(index): {
                "hard_issues": [],
                "soft_issues": [],
                "pause_ms": 600,
            }
            for index in range(1, len(words))
        },
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    bundle = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
    )
    selected_page_counts = {
        candidate["page_count"] for candidate in bundle["candidates"]
    }
    assert len(selected_page_counts) == 1
    selected_page_count = next(iter(selected_page_counts))
    selected_candidates = [
        candidate
        for candidate in bundle["candidates"]
        if candidate["page_count"] == selected_page_count
    ]
    boundaries = {
        tuple(page["word_end"] for page in candidate["plan"]["pages"])
        for candidate in selected_candidates
    }

    assert 1 < len(selected_candidates) <= 4
    assert len(boundaries) == len(selected_candidates)
    assert selected_page_count >= bundle["preferred_page_count"]
    assert all(
        " ".join(page["en"] for page in candidate["plan"]["pages"])
        == text
        for candidate in selected_candidates
    )


def test_shadow_candidate_frontier_exposes_alternatives_without_changing_production():
    text = (
        "Customers save money every day, stores grow quickly across China, "
        "workers gain valuable experience, and communities receive reliable "
        "services nationwide."
    )
    words = text.split()
    cue = _cue(
        text,
        "S9305",
        display_boundary_evidence={
            str(index): {
                "hard_issues": [],
                "soft_issues": [],
                "pause_ms": 600,
            }
            for index in range(1, len(words))
        },
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    production_plan = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
    )
    bundle = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
    )

    assert bundle["status"] == "candidate_bundle"
    assert bundle["shadow_candidates"]
    selected_page_counts = {
        candidate["page_count"] for candidate in bundle["candidates"]
    }
    assert len(selected_page_counts) == 1
    assert next(iter(selected_page_counts)) >= bundle["preferred_page_count"]
    assert {
        candidate["page_count"] for candidate in bundle["shadow_candidates"]
    } >= {
        candidate["page_count"] for candidate in bundle["candidates"]
    }
    production_signature = tuple(
        (page["word_start"], page["word_end"], page["start"], page["end"])
        for page in production_plan["pages"]
    )
    shadow_signatures = {
        tuple(
            (page["word_start"], page["word_end"], page["start"], page["end"])
            for page in candidate["plan"]["pages"]
        )
        for candidate in bundle["shadow_candidates"]
    }
    assert production_signature in shadow_signatures
    assert all(
        " ".join(page["en"] for page in candidate["plan"]["pages"])
        == text
        for candidate in bundle["shadow_candidates"]
    )


def test_production_candidates_score_the_same_font_used_by_final_reflow():
    text = (
        "These systems are now being actively weaponized against returning "
        "students."
    )
    cue = _cue(
        text,
        "S9304",
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    bundle = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
    )

    assert bundle["status"] == "candidate_bundle"
    assert bundle["candidates"]
    for candidate in bundle["candidates"]:
        finalized = podcast_learning_video._finalize_article_same_screen_layout(
            cue,
            draw,
            candidate["plan"],
        )
        assert [
            page["english_font_size"]
            for page in candidate["plan"]["pages"]
        ] == [
            page["english_font_size"]
            for page in finalized["pages"]
        ]
        assert [
            page["en_lines"] for page in candidate["plan"]["pages"]
        ] == [
            page["en_lines"] for page in finalized["pages"]
        ]


def test_planning_and_final_same_screen_layout_share_one_contract():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    cases = (
        (
            "Especially when the domestic alternative has improved at such a "
            "staggering rate.",
            "S0115",
        ),
        (
            "They see the hyperscalers inevitably pulling away to build out that "
            "49% custom chip market we talked about.",
            "S0168",
        ),
        (
            "However, critics are increasingly throwing around the term circular "
            "financing.",
            "S0229",
        ),
    )

    for text, subtitle_id in cases:
        _, cue = _syntax_backed_cue(text, subtitle_id)
        words = text.split()

        planning = podcast_learning_video._article_planning_final_page_layout(
            draw,
            cue,
            words,
            0,
            len(words),
        )
        final = podcast_learning_video._article_final_page_layout(
            draw,
            cue,
            words,
            0,
            len(words),
        )

        assert planning == final, subtitle_id


def test_sub_14_word_cue_prefers_static_floor_over_medium_review_boundary():
    text = (
        "Research teams evaluate modern systems and recommend practical methods "
        "for classroom use worldwide."
    )
    words = text.split()
    timing = tuple(
        {
            "word_id": index,
            "surface": word,
            "start": index * 0.5,
            "end": index * 0.5 + 0.35,
        }
        for index, word in enumerate(words)
    )
    cue = _cue(
        text,
        "S9002",
        word_timing=timing,
        display_boundary_evidence={
            str(index): {
                "hard_issues": [],
                "soft_issues": ["coordinated_constituent_split"],
                "pause_ms": 150,
            }
            for index in range(1, len(words))
        },
    )

    plan = _plan(cue)

    assert plan["font_size"]["english"] == 52
    assert len(plan["pages"]) == 1
    assert plan["font_fallback"] == {
        "used": True,
        "from": 56,
        "to": 52,
        "reason": "no_safe_higher_font_layout",
    }
    assert " ".join(page["en"] for page in plan["pages"]) == text


def test_punctuated_coordinated_gerund_can_form_a_review_page_boundary():
    text = (
        "Because a huge part of the community involves physically going out, "
        "exploring overlooked corners, and abandoned neighborhoods."
    )
    words = text.split()
    split = words.index("exploring")
    timing = []
    cursor = 0.0
    for index, word in enumerate(words):
        if index == split:
            cursor += 0.30
        timing.append(
            {
                "word_id": index,
                "surface": word,
                "start": cursor,
                "end": cursor + 0.28,
            }
        )
        cursor += 0.32
    evidence = {
        str(index): {
            "hard_issues": (
                ["coordinated_constituent_split"] if index == split else []
            ),
            "soft_issues": [],
            "pause_ms": 300 if index == split else 40,
        }
        for index in range(1, len(words))
    }
    cue = _cue(
        text,
        "S9004",
        word_timing=tuple(timing),
        display_boundary_evidence=evidence,
    )

    decision = podcast_learning_video._article_display_boundary_decision(
        cue,
        split,
    )
    right_page = {
        "en": " ".join(words[split:]),
        "boundary_before": decision,
    }

    assert decision["classification"] == "review"
    assert decision["punctuated_coordinated_gerund_restart"] is True
    assert podcast_learning_video._article_secondary_review_boundary_is_complete(
        right_page
    )


def test_unpunctuated_coordinated_gerund_boundary_remains_hard():
    text = (
        "The community keeps physically going out and exploring overlooked "
        "corners across abandoned neighborhoods."
    )
    words = text.split()
    split = words.index("exploring")
    cue = _cue(
        text,
        "S9005",
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.4,
                "end": index * 0.4 + 0.3,
            }
            for index, word in enumerate(words)
        ),
        display_boundary_evidence={
            str(split): {
                "hard_issues": ["coordinated_constituent_split"],
                "soft_issues": [],
                "pause_ms": 300,
            }
        },
    )

    decision = podcast_learning_video._article_display_boundary_decision(
        cue,
        split,
    )

    assert decision["classification"] == "hard"
    assert decision.get("punctuated_coordinated_gerund_restart") is not True


def test_review_boundary_can_replace_a_static_layout_below_the_52px_floor():
    text = (
        "Research organizations comprehensively evaluate sophisticated modern "
        "systems and recommend practical implementation methods for educational "
        "institutions worldwide."
    )
    words = text.split()
    timing = tuple(
        {
            "word_id": index,
            "surface": word,
            "start": index * 0.5,
            "end": index * 0.5 + 0.35,
        }
        for index, word in enumerate(words)
    )
    cue = _cue(
        text,
        "S9003",
        word_timing=timing,
        display_boundary_evidence={
            str(index): {
                "hard_issues": ["subject_predicate_split"],
                "soft_issues": [],
                "pause_ms": 200,
            }
            for index in range(1, len(words))
        },
    )

    relaxed = podcast_learning_video._article_display_boundary_decision(cue, 5)
    plan = _plan(cue)

    assert relaxed["classification"] == "review"
    assert relaxed["raw_hard_issue_codes"] == ["subject_predicate_split"]
    assert relaxed["relaxed_raw_hard"] is True
    assert len(plan["pages"]) == 2
    assert plan["font_size"]["english"] == 56
    assert plan["pages"][1]["boundary_before"]["classification"] == "review"
    assert " ".join(page["en"] for page in plan["pages"]) == text


def test_article_english_font_profile_has_a_52px_automatic_floor():
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_FALLBACK_SIZES == (
        56,
        54,
        52,
    )
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES == ()
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_LEGACY_FALLBACK_SIZES == (50,)
    assert (
        podcast_learning_video.ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
        == (56, 54, 52, 50)
    )
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE == 52
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_MIN_SIZE == 50
    profile = podcast_learning_video.article_display_page_layout_profile()
    assert profile["english_font_fallback_sizes"] == [56, 54, 52]
    assert profile["english_emergency_fallback_sizes"] == []
    assert profile["english_legacy_readable_sizes"] == [50]
    assert profile["english_min_size"] == 52


def test_fourteen_fifteen_sixteen_word_readability_policy():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    assert podcast_learning_video.ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS == 14
    assert podcast_learning_video.ARTICLE_VISUAL_PAGE_REVIEW_WORDS == 15
    assert podcast_learning_video.ARTICLE_VISUAL_PAGE_SPLIT_PRIORITY_WORDS == 16
    assert podcast_learning_video._article_preferred_readability_page_count(
        draw,
        ["a"] * 14,
        "",
        cue_duration_ms=4_000,
    ) == 1
    assert podcast_learning_video._article_preferred_readability_page_count(
        draw,
        ["a"] * 15,
        "",
        cue_duration_ms=4_000,
    ) == 1
    assert podcast_learning_video._article_preferred_readability_page_count(
        draw,
        ["internationalization"] * 15,
        "",
        cue_duration_ms=4_000,
    ) > 1
    assert podcast_learning_video._article_preferred_readability_page_count(
        draw,
        ["a"] * 16,
        "",
        cue_duration_ms=4_000,
    ) == 2


def test_font_floor_regression_cues_prefer_pages_before_the_52px_floor():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    expected_sizes = {"S0095": 56, "S0115": 56, "S0120": 52}

    for case in FONT_FLOOR_REGRESSION_CASES:
        text = case["english"]
        timing = _production_word_timing(
            text.split(),
            case["word_ids"],
            case["start_ms"],
            case["end_ms"],
        )
        _, cue = _syntax_backed_cue(
            text,
            case["subtitle_id"],
            word_timing=timing,
        )
        cue.zh = case["chinese"]
        snapshot = (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, cue.word_timing)

        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)
        selected = plan["font_size"]["english"]

        assert plan["status"] == "ok", case["subtitle_id"]
        assert selected == expected_sizes[case["subtitle_id"]], case["subtitle_id"]
        assert selected in podcast_learning_video.ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES
        assert not any(
            warning.get("reason") == "emergency_font_fallback"
            for warning in plan["readability_warnings"]
        ), case["subtitle_id"]
        assert " ".join(page["en"] for page in plan["pages"]) == text
        assert (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, cue.word_timing) == snapshot

        if case["subtitle_id"] == "S0095":
            assert [page["en"] for page in plan["pages"]] == [
                "It completely undermines the premise",
                "that studying at a foreign university provides a radically different environment.",
            ]
        if case["subtitle_id"] == "S0120":
            assert max(len(page["en"].split()) for page in plan["pages"]) <= 14
            assert len(plan["pages"]) >= 2


def test_punctuated_pronoun_clause_uses_two_56px_pages_before_50px():
    text = (
        "To understand the mechanics of this, you really have to look at the "
        "Chinese stock market ecosystem."
    )
    _, cue = _syntax_backed_cue(text, "S0080")

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        "To understand the mechanics of this,",
        "you really have to look at the Chinese stock market ecosystem.",
    ]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])
    assert not any(
        warning.get("reason") == "emergency_font_fallback"
        for warning in plan["readability_warnings"]
    )


def test_punctuated_numeric_model_clause_uses_two_balanced_56px_pages():
    text = (
        "Exactly. So even if those custom chips are less powerful than an H 100, "
        "the cloud giants argue they still get significantly more computing power "
        "per dollar spent."
    )
    words = text.split()
    split = words.index("the", words.index("100,") + 1)
    timing = _word_timing_with_gaps(text, {split - 1: 746})
    _, cue = _syntax_backed_cue(text, "S0078", word_timing=timing)

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        " ".join(words[:split]),
        " ".join(words[split:]),
    ]
    assert [len(page["en"].split()) for page in plan["pages"]] == [14, 14]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])
    assert all(len(page["en_lines"]) <= 2 for page in plan["pages"])


def test_extended_numeric_range_does_not_create_a_five_word_tail_page():
    text = (
        "I mean, Bloomberg Intelligence put out estimates showing worldwide AI "
        "chip shipments growing from 15 million units this year to 28 million by 2030."
    )
    _, cue = _syntax_backed_cue(text, "S0101")

    plan = _plan(cue)

    assert [len(page["en"].split()) for page in plan["pages"]] == [7, 10, 7]
    assert plan["pages"][1]["en"].startswith("showing worldwide AI")
    assert plan["pages"][2]["en"].startswith("this year to 28 million")
    assert not any(page["en"].startswith("to 28 million") for page in plan["pages"])
    assert all(page["english_font_size"] == 56 for page in plan["pages"])
    assert all(len(page["en_lines"]) <= 2 for page in plan["pages"])


def test_participial_restart_accepts_compatible_dependency_evidence_only():
    page = {
        "en": (
            "showing worldwide AI chip shipments growing from 15 million units"
        ),
        "boundary_before": {
            "classification": "review",
            "issue_codes": [
                "dependency_phrase_entrance_split",
                "post_noun_participial_modifier_split",
            ],
        },
    }

    assert podcast_learning_video._article_complete_participial_restart(page)

    page["boundary_before"]["issue_codes"].append("numeric_unit_or_noun_split")
    assert not podcast_learning_video._article_complete_participial_restart(page)


def test_complete_five_word_terminal_phrase_is_a_reviewable_page_fallback():
    text = (
        "Wow. Okay, so a hyper-localized, vertically integrated supply chain "
        "is brilliant for business margins. It is."
    )
    words = text.split()
    timing = _production_word_timing(
        words,
        range(1643, 1659),
        (
            560015, 560455, 560715, 561116, 561356, 562497, 563017, 563517,
            563978, 564418, 564858, 565419, 565579, 565939, 566639, 566840,
        ),
        (
            560235, 560695, 560976, 561176, 562417, 562917, 563477, 563938,
            564278, 564498, 565379, 565539, 565899, 566319, 566699, 566980,
        ),
    )
    _, cue = _syntax_backed_cue(text, "S0160", word_timing=timing)
    cue.zh = "哇，高度本地化、垂直整合的供应链对利润率极为有利，确实如此。"

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        " ".join(words[:11]),
        "for business margins. It is.",
    ]
    assert [len(page["en"].split()) for page in plan["pages"]] == [11, 5]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])
    assert all(page["end"] - page["start"] >= 0.9 for page in plan["pages"])
    assert plan["pages"][1]["boundary_before"]["classification"] == "review"
    assert any(
        warning.get("reason") == "review_boundary_fallback"
        for warning in plan["readability_warnings"]
    )


def test_four_word_prepositional_tail_does_not_replace_balanced_review_pages():
    text = (
        "Because this source material involves some heavily politically charged "
        "policy actions from the Trump administration."
    )
    _, cue = _syntax_backed_cue(text, "S0017")

    plan = _plan(cue)

    assert [len(page["en"].split()) for page in plan["pages"]] == [5, 10]
    assert plan["pages"][1]["en"] == (
        "some heavily politically charged policy actions from the Trump "
        "administration."
    )
    assert not any(
        page["en"] == "from the Trump administration."
        for page in plan["pages"]
    )


def test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px():
    text = (
        "Because it's like a famous restaurant realizing they spend so much money "
        "on a specific rare ingredient that they decide it's cheaper to just buy "
        "the farm and grow it themselves."
    )
    _, cue = _syntax_backed_cue(text, "S0038")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    bundle = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
    )
    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    for result in (bundle, plan):
        assert result["status"] == "render_structural_overflow"
        assert result["errors"][0]["reason"] == (
            "no_complete_normal_font_page_partition"
        )


def test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint():
    text = (
        "Because it's like a famous restaurant realizing they spend so much money "
        "on a specific rare ingredient that they decide it's cheaper to just buy "
        "the farm and grow it themselves."
    )
    _, cue = _syntax_backed_cue(text, "S0038")

    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])

    assert blueprint["status"] == "PASS"
    assert blueprint["degraded_page_count"] == 1
    assert blueprint["total_parent_count"] == 1
    assert blueprint["degraded_parent_ratio"] == 1.0
    assert blueprint["degraded_page_threshold"] == 1
    assert blueprint["degraded_parents"] == [
        {
            "cue_index": cue.index,
            "parent_subtitle_id": "S0038",
            "reasons": ["no_complete_normal_font_page_partition"],
        }
    ]
    assert not blueprint.get("errors")
    plan = next(
        item
        for item in blueprint["render_plans"]
        if item["parent_subtitle_id"] == "S0038"
    )
    assert plan["renderable"] is True
    assert plan["degraded"] is True


def test_candidate_bundle_keeps_a_complete_short_cue_on_the_normal_path():
    cue = _cue(
        "A complete short sentence.",
        "S0199",
        chinese="一条完整的短句。",
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    bundle = podcast_learning_video._build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
    )

    assert bundle.get("fallback_review") is not True
    assert bundle["candidates"]
    assert bundle["candidates"][0]["page_count"] == 1
    assert bundle["candidates"][0]["incomplete_review_count"] == 0


def test_nonrenderable_page_seed_keeps_an_english_preview_line():
    text = (
        "Because the government shifted all its macroeconomic stabilization "
        "efforts over to the new 2018 survey rate."
    )
    _, cue = _syntax_backed_cue(text, "S0223")

    seed = podcast_learning_video._article_editable_page_seed_plan(
        cue,
        [{"cue_index": cue.index, "reason": "no_complete_normal_font_page_partition"}],
    )

    assert seed["renderable"] is False
    assert seed["pages"][0]["english_lines"] == [text]
    assert " ".join(seed["pages"][0]["english_lines"]).split() == text.split()


def test_v10_short_comfortable_cue_is_not_paginated_by_break_reward():
    """V10 pages 4-5: punctuation quality cannot decide page count."""
    text = "AI stocks in the U Japan, and South Korea just plummeted."
    _, cue = _syntax_backed_cue(text, "S0004")

    plan = _plan(cue)

    assert plan["font_size"]["english"] == 56
    assert [page["en"] for page in plan["pages"]] == [text]


def test_v10_dense_intro_and_main_clause_keep_two_readable_pages():
    """V10 pages 20-21 are an approved two-page display boundary."""
    text = (
        "Like Moonshot AI, the startup in Beijing, they launched their K 3 "
        "advanced model last month."
    )
    _, cue = _syntax_backed_cue(text, "S0018")

    plan = _plan(cue)

    assert plan["font_size"]["english"] == 56
    assert [page["en"] for page in plan["pages"]] == [
        "Like Moonshot AI, the startup in Beijing,",
        "they launched their K 3 advanced model last month.",
    ]


def test_v10_page_planner_prefers_complete_units_over_dependency_fragments():
    """Improve reviewed v10 bad pages using their frozen word timings."""
    cases = [
        {
            "text": (
                "Yeah, the export controls on advanced semiconductors fundamentally "
                "alter the physical architecture of Chinese data centers."
            ),
            "subtitle_id": "S0071",
            "word_ids": range(883, 899),
            "starts": [305724, 306165, 306365, 306725, 307125, 307225, 307545, 308506,
                       309187, 309447, 309567, 310027, 310668, 310788, 311168, 311468],
            "ends": [305984, 306285, 306685, 307065, 307185, 307525, 308306, 309086,
                     309427, 309527, 309927, 310607, 310728, 311148, 311448, 311868],
        },
        {
            "text": (
                "However, they will ruthlessly adopt a tool if it guarantees an "
                "immediate, measurable reduction in hard operating costs."
            ),
            "subtitle_id": "S0142",
            "word_ids": range(1676, 1694),
            "starts": [594718, 595038, 595178, 595399, 595959, 596299, 596379, 597040,
                       597140, 597240, 597780, 597880, 598521, 599021, 599481, 599621,
                       599902, 600302],
            "ends": [594998, 595158, 595359, 595919, 596239, 596319, 596699, 597100,
                     597200, 597600, 597840, 598361, 598961, 599441, 599581, 599822,
                     600262, 600682],
        },
        {
            "text": (
                "Like the July report that NVIDIA was in talks to underwrite a 250 "
                "billion chunk of a 500 billion data center project for OpenAI."
            ),
            "subtitle_id": "S0169",
            "word_ids": range(2019, 2043),
            "starts": [721343, 721503, 721623, 722024, 722404, 722624, 723024, 723205,
                       723305, 723665, 723885, 724365, 724505, 725426, 726227, 726527,
                       726627, 726747, 727307, 727648, 728508, 728788, 729229, 729449],
            "ends": [721483, 721583, 721964, 722364, 722524, 723004, 723144, 723265,
                     723625, 723765, 724325, 724425, 724966, 726167, 726487, 726587,
                     726667, 727267, 727628, 727988, 728748, 729209, 729369, 730069],
        },
    ]
    for case in cases:
        text = case["text"]
        words = text.split()
        word_timing = _production_word_timing(
            words,
            case["word_ids"],
            case["starts"],
            case["ends"],
        )
        _, cue = _syntax_backed_cue(
            text,
            case["subtitle_id"],
            word_timing=word_timing,
        )

        try:
            plan = _plan(cue)
        except podcast_learning_video.RenderStructuralOverflowError:
            ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
                cue,
                2,
                allow_review_boundary=True,
                allow_hard_boundary=True,
            )
            assert len(ranges) == 2
            continue

        assert plan["font_size"]["english"] >= 52
        assert " ".join(page["en"] for page in plan["pages"]) == text
        for page in plan["pages"][1:]:
            assert page["english_font_size"] in {56, 54, 52}


def test_v10_punctuated_discourse_marker_can_precede_complete_wh_page():
    """Improve reviewed v10 pages 208-210 without changing the parent cue."""
    text = (
        "Because investors finally stared at the sheer scale of the infrastructure "
        "required for AGI and asked the inevitable economic question like, what "
        "is the actual return on investment for a half-trillion dollar server farm?"
    )
    words = text.split()
    word_timing = _production_word_timing(
        words,
        range(2061, 2095),
        [735793, 736173, 736754, 737234, 737614, 737694, 737854, 738215,
         738715, 738815, 738975, 739616, 740136, 740376, 741537, 741777,
         741997, 742117, 742618, 743158, 743578, 744199, 744379, 744479,
         744639, 744939, 745360, 745420, 745900, 746040, 746100, 746720,
         747021, 747361],
        [736113, 736674, 737154, 737574, 737654, 737774, 738155, 738655,
         738775, 738895, 739556, 740056, 740276, 740897, 741617, 741957,
         742077, 742538, 743058, 743538, 743758, 744319, 744459, 744559,
         744899, 745340, 745400, 745860, 746020, 746060, 746720, 746860,
         747341, 747621],
    )
    _, cue = _syntax_backed_cue(text, "S0172", word_timing=word_timing)

    plan = _plan(cue)

    assert [page["en"].split()[0] for page in plan["pages"]] == [
        "Because",
        "and",
        "what",
    ]
    assert plan["pages"][1]["en"].endswith("like,")
    assert " ".join(page["en"] for page in plan["pages"]) == text


def test_v10_pages_174_to_176_reduce_to_two_complete_parent_pages():
    """Keep S0148 intact and collapse S0149's old two visual pages."""
    cases = (
        {
            "subtitle_id": "S0148",
            "text": (
                "Yeah. Or if an algorithm can optimize a shipping route to save "
                "15% on fuel costs"
            ),
            "word_ids": range(1750, 1766),
            "starts": [
                621396, 622257, 622477, 622617, 622797, 623297, 623518,
                623938, 623998, 624318, 624558, 624698, 625499, 625819,
                625939, 626219,
            ],
            "ends": [
                622237, 622297, 622577, 622677, 623257, 623417, 623878,
                623978, 624278, 624518, 624638, 624918, 625759, 625899,
                626179, 626500,
            ],
        },
        {
            "subtitle_id": "S0149",
            "text": (
                "across a massive fleet, logistics firms will gladly pay for it."
            ),
            "word_ids": range(1766, 1777),
            "starts": [
                626540, 626840, 626920, 627300, 627981, 628421, 628721,
                628901, 629281, 629502, 629742,
            ],
            "ends": [
                626800, 626880, 627140, 627600, 628361, 628701, 628881,
                629241, 629462, 629682, 629802,
            ],
        },
    )
    plans = []
    for case in cases:
        words = case["text"].split()
        word_timing = _production_word_timing(
            words,
            case["word_ids"],
            case["starts"],
            case["ends"],
        )
        _, cue = _syntax_backed_cue(
            case["text"],
            case["subtitle_id"],
            word_timing=word_timing,
        )
        plans.append(_plan(cue))

    assert [len(plan["pages"]) for plan in plans] == [1, 1]
    assert sum(len(plan["pages"]) for plan in plans) == 2
    assert [plan["pages"][0]["en"] for plan in plans] == [
        case["text"] for case in cases
    ]


def test_checkpoint_hard_page_cues_use_normal_fonts_or_fail_for_manual_takeover():
    """Replay the eight real hard-page failures without reading the work-dir."""
    fixture = json.loads(HARD_CUE_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    assert [case["subtitle_id"] for case in fixture["cases"]] == [
        "S0024",
        "S0087",
        "S0109",
        "S0166",
        "S0169",
        "S0198",
        "S0202",
        "S0203",
    ]
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    expected_manual_takeover = {
        "S0024": "no_complete_normal_font_page_partition",
        "S0203": "no_complete_normal_font_page_partition",
    }

    for case in fixture["cases"]:
        timing = tuple(
            {
                "word_id": int(word["word_id"]),
                "surface": str(word["surface"]),
                "start": int(word["start_ms"]) / 1000.0,
                "end": int(word["end_ms"]) / 1000.0,
            }
            for word in case["word_timing"]
        )
        cue = _cue(
            case["english"],
            case["subtitle_id"],
            case["chinese"],
            word_timing=timing,
            display_boundary_evidence=case["display_boundary_evidence"],
        )
        snapshot = (cue.en, cue.start, cue.end, deepcopy(cue.word_timing))
        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

        if case["subtitle_id"] in expected_manual_takeover:
            assert plan["status"] == "render_structural_overflow"
            assert plan["errors"][0]["reason"] == expected_manual_takeover[
                case["subtitle_id"]
            ]
            assert (cue.en, cue.start, cue.end, cue.word_timing) == snapshot
            continue
        assert plan["status"] == "ok", case["subtitle_id"]
        assert 1 <= len(plan["pages"]) <= 4, case["subtitle_id"]
        assert plan["font_size"]["english"] >= 52, case["subtitle_id"]
        assert all(
            page["english_font_size"] in {56, 54, 52}
            for page in plan["pages"]
        ), case["subtitle_id"]
        assert " ".join(page["en"] for page in plan["pages"]) == case["english"]
        assert all(page["end"] - page["start"] >= 0.9 for page in plan["pages"])
        assert (cue.en, cue.start, cue.end, cue.word_timing) == snapshot

        forced_boundaries = [
            page.get("boundary_before") or {}
            for page in plan["pages"][1:]
            if (page.get("boundary_before") or {}).get("forced_display_continuation")
        ]
        if forced_boundaries:
            assert any(
                warning.get("requires_review") is True
                for warning in plan["readability_warnings"]
            ), case["subtitle_id"]


def test_forced_page_break_rank_reuses_the_forced_decision_for_risk():
    words = "We build reliable systems that deliver measurable outcomes for every team".split()
    cue = _cue(" ".join(words), "S9003")
    timing = tuple(
        {
            "word_id": index,
            "surface": word,
            "start": index * 0.4,
            "end": index * 0.4 + 0.3,
        }
        for index, word in enumerate(words)
    )

    for forced_subject_predicate, minimum_risk in ((False, 3), (True, 4)):
        forced_decision = {
            "classification": "review",
            "confidence": "high",
            "issue_codes": ["forced_complete_continuation_page_split"],
            "forced_display_continuation": True,
            "forced_subject_predicate": forced_subject_predicate,
        }
        with patch.object(
            podcast_learning_video,
            "_article_forced_continuation_decision",
            return_value=forced_decision,
        ) as forced, patch.object(
            podcast_learning_video,
            "_article_display_boundary_decision",
            return_value={"classification": "allow"},
        ) as ordinary, patch.object(
            podcast_learning_video,
            "_article_page_has_tight_nonfinite_complement",
            return_value=False,
        ), patch.object(
            podcast_learning_video,
            "_article_page_break_is_forbidden",
            return_value=False,
        ):
            rank = podcast_learning_video._article_page_break_rank(
                cue,
                words,
                5,
                5,
                timing,
                allow_forced_continuation=True,
            )

        assert rank is not None
        assert rank[0] >= minimum_risk
        assert forced.call_count == 1
        assert ordinary.call_count == 0


def test_actual_plans_do_not_select_the_tight_complement_boundaries():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    for case_index, case in enumerate(TIGHT_COMPLEMENT_BOUNDARY_CASES, 1):
        words = case["text"].split()
        split = next(
            index
            for index in range(1, len(words))
            if words[index - 1] == case["left"] and words[index] == case["right"]
        )
        timing = []
        previous_end = 0.0
        for index, word in enumerate(words):
            gap = case["pause_ms"] / 1000.0 if index == split else 0.08
            start = 0.0 if index == 0 else previous_end + gap
            end = start + 0.24
            timing.append(
                {
                    "word_id": index,
                    "surface": word,
                    "start": start,
                    "end": end,
                }
            )
            previous_end = end
        cue = _cue(
            case["text"],
            f"S93{case_index:02d}",
            word_timing=timing,
            display_boundary_evidence={
                str(split): {
                    "hard_issues": list(case["issue_codes"]),
                    "soft_issues": [],
                    "pause_ms": case["pause_ms"],
                }
            },
        )

        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

        assert case["pause_ms"] <= 200, (case["left"], case["right"])
        assert plan["status"] == "ok", (case["left"], case["right"])
        assert split not in _page_starts(plan), (case["left"], case["right"])
        assert " ".join(page["en"] for page in plan["pages"]) == case["text"]


def test_display_page_keeps_multiword_work_title_atomic():
    text = (
        "Movies like Journey to the West and Escape from the 21 st Century "
        "heavily evoke early 2000 s culture,"
    )
    words = text.split()
    cue = _cue(text, "S0111")

    for split in (3, 5, 8, 9, 10, 11, 12):
        decision = podcast_learning_video._article_display_boundary_decision(
            cue,
            split,
        )
        assert decision["classification"] == "hard", (
            words[split - 1],
            words[split],
        )
        assert "protected_work_title_split" in decision["issue_codes"]

    join_decision = podcast_learning_video._article_display_boundary_decision(
        cue,
        6,
    )
    assert "protected_work_title_join_split" in join_decision["issue_codes"]

    outside = podcast_learning_video._article_display_boundary_decision(cue, 13)
    assert "protected_work_title_split" not in outside["issue_codes"]
    assert outside["complete_title_restart"] is True


def test_title_detection_does_not_cross_sentences_or_claim_numeric_condition():
    words = "Wow. Yeah. If 1.4 billion people changed the market.".split()

    assert podcast_learning_video._article_title_entity_spans(words) == ()
    assert not podcast_learning_video._article_boundary_inside_title_entity(words, 4)


def test_complete_from_gerund_can_relax_verb_preposition_evidence():
    words = "Demand jumped from eating one bar a year to a much higher level.".split()
    cue = _cue(" ".join(words), "S9401")
    split = words.index("from")
    right_word_id = cue.word_timing[split]["word_id"]
    cue.display_boundary_evidence = {
        str(right_word_id): {
            "hard_issues": [
                "predicate_attached_continuation_split",
                "verb_preposition_complement_split",
            ],
            "soft_issues": [],
            "pause_ms": 0,
        }
    }

    decision = podcast_learning_video._article_forced_continuation_decision(
        cue,
        words,
        split,
    )

    assert decision["classification"] == "review"
    assert decision["forced_complete_predicate_phrase"] is True
    assert decision["forced_display_continuation"] is True
    assert podcast_learning_video._article_page_break_score(
        cue,
        words,
        split,
        len(words) / 2,
        cue.word_timing,
        allow_forced_continuation=True,
    ) is not None


def test_page_boundary_risk_preserves_review_confidence_order():
    assert podcast_learning_video._article_page_boundary_risk(
        {"classification": "allow", "confidence": "low"},
        0,
    ) == 0
    assert podcast_learning_video._article_page_boundary_risk(
        {"classification": "review", "confidence": "low"},
        0,
    ) == 1
    assert podcast_learning_video._article_page_boundary_risk(
        {"classification": "review", "confidence": "medium"},
        0,
    ) == 2
    assert podcast_learning_video._article_page_boundary_risk(
        {"classification": "review", "confidence": "high"},
        0,
    ) == 3
    assert podcast_learning_video._article_page_boundary_risk(
        {
            "classification": "review",
            "confidence": "high",
            "strong_pause_evidence": True,
        },
        0,
    ) == 2
    assert podcast_learning_video._article_page_boundary_risk(
        {
            "classification": "review",
            "confidence": "high",
            "issue_codes": ["atomic_of_complement_split"],
            "forced_display_continuation": True,
        },
        0,
    ) == 5


def test_numeric_head_guard_does_not_absorb_a_following_preposition():
    words = "underwrite a 250 billion chunk of a 500 billion data center".split()

    assert not podcast_learning_video._looks_like_numeric_phrase_boundary(
        words,
        words.index("of"),
    )
    assert podcast_learning_video._looks_like_numeric_phrase_boundary(
        words,
        words.index("center"),
    )


def test_spaced_thousands_group_is_atomic_at_line_wrap():
    text = (
        "By 2025, that number had plummeted to 570 000 "
        "Which is the lowest level since 2016."
    )
    words = text.split()
    word_timing = _production_word_timing(
        words,
        range(1680, 1696),
        (
            576826, 577126, 578267, 578467, 578727, 578927, 579479, 579480,
            580060, 581209, 581409, 581529, 581629, 581909, 582130, 582570,
        ),
        (
            576946, 577907, 578427, 578687, 578827, 579479, 579480, 580060,
            580640, 581349, 581489, 581609, 581869, 582110, 582530, 583010,
        ),
    )
    _, cue = _syntax_backed_cue(text, "S0163", word_timing=word_timing)
    cue.zh = "到2025年，该数字骤降至57万人，为2016年以来最低。"

    plan = _plan(cue)
    line_boundaries = set()
    page_boundaries = set()
    for page_index, page in enumerate(plan["pages"]):
        lines = page["en_lines"]
        line_boundaries.update(
            (lines[index].split()[-1], lines[index + 1].split()[0])
            for index in range(len(lines) - 1)
        )
        if page_index:
            page_boundaries.add(
                (
                    plan["pages"][page_index - 1]["en"].split()[-1],
                    page["en"].split()[0],
                )
            )

    assert podcast_learning_video._looks_like_numeric_phrase_boundary(
        words,
        words.index("000"),
    )
    all_boundaries = line_boundaries | page_boundaries
    assert podcast_learning_video._article_line_boundary_penalty(
        cue,
        words.index("to"),
    ) >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    assert podcast_learning_video._article_line_boundary_penalty(
        cue,
        words.index("Which"),
    ) == 0
    assert ("570", "000") not in all_boundaries
    assert ("plummeted", "to") not in all_boundaries
    assert ("000", "Which") in all_boundaries
    assert all(
        not podcast_learning_video._has_discouraged_caption_break(
            page["en"],
            page["en_lines"],
        )
        for page in plan["pages"]
    )


def test_amount_frequency_phrase_stays_on_the_same_display_page():
    text = (
        "Right now, a Chinese graduate returning from an overseas university "
        "can expect an average starting salary of about 12 800 yuan a month, "
        "which is only marginally higher than the 10 700 yuan offered to "
        "someone who just stayed in China."
    )
    _, cue = _syntax_backed_cue(text, "S9201")

    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    automatic = podcast_learning_video._build_article_english_page_plan(cue, draw)
    assert automatic["status"] == "render_structural_overflow"
    ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
        cue,
        3,
        allow_review_boundary=True,
        allow_hard_boundary=True,
    )
    words = text.split()
    page_boundaries = {
        (words[ranges[index - 1][1]], words[word_start])
        for index, (word_start, _word_end) in enumerate(ranges)
        if index
    }
    phrase_start = words.index("12")
    phrase_end = words.index("month,")

    assert ("yuan", "a") not in page_boundaries
    assert any(
        word_start <= phrase_start and word_end >= phrase_end
        for word_start, word_end in ranges
    )
    assert " ".join(
        " ".join(words[word_start : word_end + 1])
        for word_start, word_end in ranges
    ) == text


def test_sequence_selection_relaxes_consecutive_dense_pages():
    dense_static = {
        "plan": {"pages": [{"en": "one " * 15, "start": 0.0, "end": 4.0}]},
        "page_count": 1,
        "font_reduction": 4,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "medium_risk_count": 0,
        "quality_cost": 300,
        "page_pressures": (1.28,),
    }
    relaxed_split = {
        "plan": {
            "pages": [
                {"en": "one " * 8, "start": 0.0, "end": 2.0},
                {"en": "one " * 7, "start": 2.0, "end": 4.0},
            ]
        },
        "page_count": 2,
        "font_reduction": 0,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "medium_risk_count": 0,
        "quality_cost": 700,
        "page_pressures": (0.72, 0.68),
    }
    following_dense = {
        "plan": {"pages": [{"en": "two " * 15, "start": 4.1, "end": 8.0}]},
        "page_count": 1,
        "font_reduction": 0,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "medium_risk_count": 0,
        "quality_cost": 200,
        "page_pressures": (1.25,),
    }

    selected = podcast_learning_video._select_article_page_plan_sequence(
        [[dense_static, relaxed_split], [following_dense]]
    )

    assert selected == [relaxed_split, following_dense]


def test_sequence_selection_avoids_an_abrupt_adjacent_pressure_jump():
    preceding = {
        "plan": {
            "pages": [
                {
                    "en": "a comfortable preceding page",
                    "english_font_size": 56,
                    "en_lines": ["a comfortable", "preceding page"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 0,
        "page_pressures": (0.72,),
    }
    abrupt_dense = {
        "plan": {
            "pages": [
                {
                    "en": "a suddenly dense but otherwise legal page",
                    "english_font_size": 56,
                    "en_lines": ["a suddenly dense", "but otherwise legal page"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 100,
        "page_pressures": (1.28,),
    }
    visually_steady = {
        "plan": {
            "pages": [
                {
                    "en": "the same legal content at a steadier density",
                    "english_font_size": 56,
                    "en_lines": ["the same legal content", "at a steadier density"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 500,
        "page_pressures": (0.84,),
    }

    selected = podcast_learning_video._select_article_page_plan_sequence(
        [[preceding], [abrupt_dense, visually_steady]]
    )

    assert selected == [preceding, visually_steady]


def test_sequence_selection_prefers_stable_56px_when_risk_is_equal():
    preceding = {
        "plan": {
            "pages": [
                {
                    "en": "a regular two line page",
                    "english_font_size": 56,
                    "en_lines": ["a regular", "two line page"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 0,
        "page_pressures": (0.90,),
    }
    smaller_font = {
        "plan": {
            "pages": [
                {
                    "en": "an equally safe candidate",
                    "english_font_size": 54,
                    "en_lines": ["an equally", "safe candidate"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 100,
        "page_pressures": (0.90,),
    }
    stable_font = {
        "plan": {
            "pages": [
                {
                    "en": "an equally safe candidate",
                    "english_font_size": 56,
                    "en_lines": ["an equally", "safe candidate"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 160,
        "page_pressures": (0.90,),
    }

    selected = podcast_learning_video._select_article_page_plan_sequence(
        [[preceding], [smaller_font, stable_font]]
    )

    assert selected == [preceding, stable_font]


def test_sequence_stability_cannot_create_a_short_lead_in_before_a_50px_tail():
    preceding = {
        "plan": {
            "pages": [
                {
                    "en": "a normal preceding page",
                    "english_font_size": 56,
                    "en_lines": ["a normal", "preceding page"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 0,
        "page_pressures": (0.80,),
    }
    compact_fallback = {
        "plan": {
            "pages": [
                {
                    "en": "one compact fallback page keeps its complete phrase together",
                    "english_font_size": 50,
                    "en_lines": ["one compact fallback", "page keeps its complete", "phrase together"],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 4_500,
        "page_pressures": (1.333333,),
    }
    artificial_lead_in = {
        "plan": {
            "pages": [
                {
                    "en": "one short lead in",
                    "english_font_size": 56,
                    "en_lines": ["one short lead in"],
                },
                {
                    "en": "the remaining dense phrase still needs the fallback",
                    "english_font_size": 50,
                    "en_lines": [
                        "the remaining dense",
                        "phrase still needs",
                        "the fallback",
                    ],
                },
            ]
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "quality_cost": 5_614,
        "page_pressures": (1.1956, 1.0),
    }
    following = {
        **preceding,
        "plan": {
            "pages": [
                {
                    "en": "a normal following page",
                    "english_font_size": 56,
                    "en_lines": ["a normal", "following page"],
                }
            ]
        },
    }

    selected = podcast_learning_video._select_article_page_plan_sequence(
        [[preceding], [compact_fallback, artificial_lead_in], [following]]
    )

    assert selected == [preceding, compact_fallback, following]


def test_sequence_downranks_an_incomplete_review_cut_before_visual_stability():
    risk_free = {
        "plan": {
            "pages": [
                {
                    "en": "a denser but semantically safe page",
                    "english_font_size": 50,
                    "en_lines": [
                        "a denser but",
                        "semantically safe",
                        "page",
                    ],
                }
            ]
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "low_risk_count": 0,
        "incomplete_review_count": 0,
        "quality_cost": 600,
        "page_pressures": (1.25,),
    }
    visually_smooth_review_cut = {
        "plan": {
            "pages": [
                {
                    "en": "a smooth first page",
                    "english_font_size": 56,
                    "en_lines": ["a smooth first page"],
                },
                {
                    "en": "with a review-only boundary",
                    "english_font_size": 56,
                    "en_lines": ["with a review-only boundary"],
                },
            ]
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "high_risk_count": 0,
        "medium_risk_count": 1,
        "low_risk_count": 0,
        "incomplete_review_count": 1,
        "quality_cost": 0,
        "page_pressures": (0.75, 0.78),
    }

    selected = podcast_learning_video._select_article_page_plan_sequence(
        [[risk_free, visually_smooth_review_cut]]
    )

    assert selected == [risk_free]


def test_54px_static_page_promotes_only_a_complete_56px_partition():
    static = {
        "plan": {
            "font_size": {"english": 54},
            "pages": [
                {
                    "en": "one two three four five six seven eight nine ten eleven twelve",
                    "start": 0.0,
                    "end": 4.0,
                }
            ],
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "page_pressures": (1.02,),
    }
    complete_partition = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six",
                    "start": 0.0,
                    "end": 2.0,
                },
                {
                    "en": "seven eight nine ten eleven twelve",
                    "start": 2.0,
                    "end": 4.0,
                    "boundary_before": {
                        "classification": "review",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
        "page_pressures": (0.68, 0.70),
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [static, complete_partition],
        total_word_count=12,
    )

    assert [candidate["page_count"] for candidate in promoted] == [2]


def test_duration_alone_does_not_paginate_a_readable_static_cue():
    text = (
        "they feed that curated, highly structured data to a new, smaller "
        "model, the student."
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    page_count = podcast_learning_video._article_preferred_readability_page_count(
        draw,
        text.split(),
        "他们把经精选、高度结构化的数据喂给更小的新模型，即学生",
        cue_duration_ms=6_324,
    )

    assert page_count == 1


def test_duration_alone_does_not_promote_an_equally_sized_partition():
    static = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one readable static page stays at the preferred font",
                    "english_font_size": 56,
                    "en_lines": [
                        "one readable static page",
                        "stays at the preferred font",
                    ],
                    "start": 0.0,
                    "end": 6.0,
                }
            ],
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }
    equally_sized_partition = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one readable static page",
                    "english_font_size": 56,
                    "en_lines": ["one readable static page"],
                    "start": 0.0,
                    "end": 3.0,
                },
                {
                    "en": "stays at the preferred font",
                    "english_font_size": 56,
                    "en_lines": ["stays at the preferred font"],
                    "start": 3.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [static, equally_sized_partition],
        total_word_count=9,
    )

    assert promoted == []


def test_complete_review_partition_remains_visible_after_strict_static_candidate():
    static = {
        "plan": {
            "font_size": {"english": 50},
            "pages": [
                {
                    "en": "one two three four five six seven eight nine ten eleven twelve",
                    "start": 0.0,
                    "end": 4.0,
                }
            ],
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }
    reviewed_partition = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six",
                    "start": 0.0,
                    "end": 2.0,
                },
                {
                    "en": "seven eight nine ten eleven twelve",
                    "start": 2.0,
                    "end": 4.0,
                    "boundary_before": {
                        "classification": "review",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": True,
        "severe_risk_count": 0,
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [static, reviewed_partition],
        total_word_count=12,
    )

    assert [candidate["page_count"] for candidate in promoted] == [2]
    assert promoted[0]["secondary_review_promoted"] is True


def test_multipage_50px_baseline_promotes_complete_56px_expansion():
    dense_baseline = {
        "plan": {
            "font_size": {"english": 50},
            "pages": [
                {
                    "en": "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen",
                    "english_font_size": 50,
                    "start": 0.0,
                    "end": 4.0,
                },
                {
                    "en": "sixteen seventeen eighteen nineteen twenty twenty-one",
                    "english_font_size": 56,
                    "start": 4.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }
    complete_expansion = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six seven",
                    "english_font_size": 56,
                    "start": 0.0,
                    "end": 2.0,
                },
                {
                    "en": "eight nine ten eleven twelve thirteen fourteen",
                    "english_font_size": 56,
                    "start": 2.0,
                    "end": 4.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
                {
                    "en": "fifteen sixteen seventeen eighteen nineteen twenty twenty-one",
                    "english_font_size": 56,
                    "start": 4.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 3,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [dense_baseline, complete_expansion],
        total_word_count=21,
    )

    assert [candidate["page_count"] for candidate in promoted] == [3]


def test_balanced_56px_multipage_baseline_is_not_over_paginated():
    baseline = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six seven eight nine",
                    "english_font_size": 56,
                    "start": 0.0,
                    "end": 3.0,
                },
                {
                    "en": "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen",
                    "english_font_size": 56,
                    "start": 3.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }
    extra_page = {
        **baseline,
        "page_count": 3,
        "plan": {
            **baseline["plan"],
            "pages": [
                {
                    "en": "one two three four five six",
                    "english_font_size": 56,
                    "start": 0.0,
                    "end": 2.0,
                },
                {
                    "en": "seven eight nine ten eleven twelve",
                    "english_font_size": 56,
                    "start": 2.0,
                    "end": 4.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
                {
                    "en": "thirteen fourteen fifteen sixteen seventeen eighteen",
                    "english_font_size": 56,
                    "start": 4.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [baseline, extra_page],
        total_word_count=18,
    )

    assert promoted == []


def test_long_56px_static_page_promotes_only_a_complete_readable_partition():
    static = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen",
                    "start": 0.0,
                    "end": 6.0,
                }
            ],
        },
        "page_count": 1,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }
    complete_partition = {
        "plan": {
            "font_size": {"english": 56},
            "pages": [
                {
                    "en": "one two three four five six seven",
                    "start": 0.0,
                    "end": 3.0,
                },
                {
                    "en": "eight nine ten eleven twelve thirteen fourteen fifteen",
                    "start": 3.0,
                    "end": 6.0,
                    "boundary_before": {
                        "classification": "allow",
                        "issue_codes": [],
                        "complete_page_clause_start": True,
                    },
                },
            ],
        },
        "page_count": 2,
        "forced_continuation": False,
        "severe_risk_count": 0,
    }

    promoted = podcast_learning_video._article_high_pressure_review_candidates(
        [static, complete_partition],
        total_word_count=15,
    )

    assert promoted == [
        {
            **complete_partition,
            "plan": {
                **complete_partition["plan"],
                "readability_warnings": [
                    {
                        "reason": "high_pressure_secondary_page_review",
                        "review_required": True,
                    }
                ],
            },
            "secondary_review_promoted": True,
        }
    ]


def test_blueprint_keeps_56px_when_a_safe_page_plan_exists():
    text = (
        "Like Moonshot AI, the startup in Beijing, they launched their K 3 "
        "advanced model last month."
    )
    _, cue = _syntax_backed_cue(text, "S9202")

    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    plan = blueprint["render_plans"][0]

    assert plan["english_font_size"] == 56
    assert [page["english"] for page in plan["pages"]] == [
        "Like Moonshot AI, the startup in Beijing,",
        "they launched their K 3 advanced model last month.",
    ]


def test_automatic_multipage_plan_assigns_font_from_each_final_page():
    text = (
        "extraordinary international semiconductor manufacturing capabilities "
        "require continuous investment, and it works well for everyone today."
    )
    _, cue = _syntax_backed_cue(text, "S9203")

    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    plan = blueprint["render_plans"][0]

    assert [page["english"] for page in plan["pages"]] == [
        "extraordinary international semiconductor manufacturing capabilities "
        "require continuous investment,",
        "and it works well for everyone today.",
    ]
    assert [page["english_font_size"] for page in plan["pages"]] == [52, 56]
    assert plan["english_font_size"] == 52


def test_high_pressure_single_pages_promote_only_complete_review_partitions():
    cases = (
        (
            "S9502",
            (
                "and two extra years of networking with local professors who "
                "have direct ties to local industry."
            ),
            {},
            (
                "and two extra years of networking with local professors",
                "who have direct ties to local industry.",
            ),
        ),
        (
            "S9503",
            (
                "Exactly. They shared formative, coming-of age experiences that "
                "gave them a baseline of mutual cultural understanding,"
            ),
            {},
            (
                "Exactly. They shared formative, coming-of age experiences",
                "that gave them a baseline of mutual cultural understanding,",
            ),
        ),
    )

    for subtitle_id, text, gaps_ms, expected_pages in cases:
        _, cue = _syntax_backed_cue(
            text,
            subtitle_id,
            word_timing=_word_timing_with_gaps(text, gaps_ms),
        )

        plan = podcast_learning_video.build_article_display_page_blueprint(
            [cue]
        )["render_plans"][0]

        assert tuple(page["english"] for page in plan["pages"]) == expected_pages
        assert all(page["english_font_size"] == 56 for page in plan["pages"])
        assert plan["pages"][1]["boundary_before"]["classification"] == "review"


def test_high_pressure_pause_does_not_outrank_a_strict_single_page():
    text = (
        "There was this young woman lamenting that her parents spent "
        "over 2 million yuan to send her abroad."
    )
    _, cue = _syntax_backed_cue(
        text,
        "S9501",
        word_timing=_word_timing_with_gaps(text, {5: 540}),
    )

    plan = podcast_learning_video.build_article_display_page_blueprint(
        [cue]
    )["render_plans"][0]

    assert tuple(page["english"] for page in plan["pages"]) == (text,)
    assert plan["pages"][0]["english_font_size"] == 56


def test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries():
    cases = (
        (
            "S9511",
            (
                "But wait, the counterargument is usually that the whole point "
                "of going abroad is the global experience,"
            ),
        ),
        (
            "S9512",
            (
                "They charged them international fees that are drastically "
                "higher than what domestic students pay."
            ),
        ),
        (
            "S9513",
            (
                "In 2025, the administration of Donald Trump announced that it "
                "would aggressively revoke visas for Chinese nationals studying "
                "in unspecified critical fields."
            ),
        ),
    )

    for subtitle_id, text in cases:
        _, cue = _syntax_backed_cue(
            text,
            subtitle_id,
            word_timing=_word_timing_with_gaps(text),
        )

        try:
            plan = podcast_learning_video.build_article_display_page_blueprint(
                [cue]
            )["render_plans"][0]
        except podcast_learning_video.RenderStructuralOverflowError as exc:
            if subtitle_id != "S9513":
                raise
            assert any(
                error.get("reason") == "no_complete_normal_font_page_partition"
                for error in exc.errors
            )
            ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
                cue,
                2,
                allow_review_boundary=True,
                allow_hard_boundary=True,
            )
            assert len(ranges) == 2
            continue

        assert [page["english"] for page in plan["pages"]] == [text]
        assert plan["pages"][0]["english_font_size"] in {56, 54, 52}


def test_secondary_page_promotion_distinguishes_safe_and_attached_boundaries():
    assert podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "you can pour whatever you want into it",
            "boundary_before": {
                "classification": "allow",
                "issue_codes": [],
            },
        }
    )

    assert not podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "to Navarro's objections would be the only answer",
            "boundary_before": {
                "classification": "review",
                "issue_codes": ["dependency_phrase_entrance_split"],
                "tight_complete_phrase_start": True,
            },
        }
    )


def test_open_parent_coordinated_comma_restart_beats_dense_single_page():
    text = (
        "They analyzed the exact same global trade networks, and they found "
        "about 40 billion worth of Chinese goods were,"
    )
    _, cue = _syntax_backed_cue(
        text,
        "S9701",
        word_timing=_word_timing_with_gaps(text, {7: 60}),
    )

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        "They analyzed the exact same global trade networks,",
        "and they found about 40 billion worth of Chinese goods were,",
    ]
    assert min(page["english_font_size"] for page in plan["pages"]) >= 52


def test_parallel_noun_list_uses_comma_page_boundaries_without_splitting_predicate():
    text = (
        "Well, the goal would be to constantly monitor the origin of every "
        "single component, the digital routing of every shipping container, "
        "and the exact nationality of the capital financing these factories."
    )
    words = text.split()
    _, cue = _syntax_backed_cue(
        text,
        "S9702",
        word_timing=_word_timing_with_gaps(
            text,
            {words.index("component,"): 180, words.index("container,"): 361},
        ),
    )

    plan = _plan(cue)

    assert [page["word_start"] for page in plan["pages"]] == [0, 14, 21]
    assert "would be to constantly monitor" in plan["pages"][0]["en"]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])


def test_balanced_predicate_restart_beats_attached_preposition_restart():
    text = (
        "Because the only coherent answer to Navarro's objections would be to "
        "set a strict, legally defined maximum threshold for Chinese content."
    )
    words = text.split()
    _, cue = _syntax_backed_cue(
        text,
        "S9703",
        word_timing=_word_timing_with_gaps(
            text,
            {words.index("objections"): 321, words.index("strict,"): 401},
        ),
    )

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        "Because the only coherent answer to Navarro's objections",
        "would be to set a strict, legally defined maximum threshold for Chinese content.",
    ]
    assert all("strict, legally" in page["en"] for page in plan["pages"][1:])
    assert not podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "for Chinese nationals studying in critical fields",
            "boundary_before": {
                "classification": "review",
                "issue_codes": [
                    "dependency_phrase_entrance_split",
                    "object_attached_modifier_split",
                ],
                "tight_complete_phrase_start": True,
            },
        }
    )
    assert podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "from paying any royalties for the first three years",
            "boundary_before": {
                "classification": "review",
                "issue_codes": [
                    "dependency_phrase_entrance_split",
                    "object_attached_modifier_split",
                ],
                "tight_complete_phrase_start": True,
            },
        }
    )


def test_complete_from_gerund_page_beats_single_50px_fallback():
    text = (
        "the parent company completely exempts franchisees from paying any "
        "royalties for the first three years of operation."
    )
    _, cue = _syntax_backed_cue(
        text,
        "S9519",
        word_timing=_word_timing_with_gaps(text),
    )

    plan = podcast_learning_video.build_article_display_page_blueprint(
        [cue]
    )["render_plans"][0]

    assert [page["english"] for page in plan["pages"]] == [
        "the parent company completely exempts franchisees",
        "from paying any royalties for the first three years of operation.",
    ]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])


def test_complete_prepositional_page_can_relax_predicate_chain_evidence():
    text = (
        "Because if you actually look closely at these meticulously "
        "reconstructed digital environments, you realize something shocking."
    )
    words = text.split()
    split = words.index("at")
    evidence = {
        str(index): {
            "hard_issues": (
                ["predicate_complement_chain_split"]
                if index == split
                else ["protected_syntax_cut"]
            ),
            "soft_issues": [],
            "pause_ms": 40,
        }
        for index in range(1, len(words))
    }
    cue = _cue(
        text,
        "S9518",
        word_timing=_word_timing_with_gaps(text, {split: 40}),
        display_boundary_evidence=evidence,
    )

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        "Because if you actually look closely",
        (
            "at these meticulously reconstructed digital environments, "
            "you realize something shocking."
        ),
    ]
    assert all(page["english_font_size"] in {56, 54, 52} for page in plan["pages"])
    boundary = plan["pages"][1]["boundary_before"]
    assert boundary["classification"] == "review"
    assert boundary["forced_display_continuation"] is True


def test_predicate_chain_evidence_stays_hard_without_a_complete_phrase():
    words = "Analysts can inspect detailed results carefully today.".split()
    split = words.index("results")
    cue = _cue(
        " ".join(words),
        "S9517",
        display_boundary_evidence={
            str(split): {
                "hard_issues": ["predicate_complement_chain_split"],
                "soft_issues": [],
                "pause_ms": 40,
            }
        },
    )

    decision = podcast_learning_video._article_forced_continuation_decision(
        cue,
        words,
        split,
    )

    assert decision["classification"] == "hard"
    assert not decision.get("forced_display_continuation")


def test_forced_subject_predicate_candidate_survives_completeness_filter():
    text = (
        "But what pushes it over the edge into that Dreamcore aesthetic is "
        "how those synths are amplified by audio samples of children playing "
        "in the distance."
    )
    words = text.split()
    split = words.index("is")
    cue = _cue(
        text,
        "S9516",
        display_boundary_evidence={
            str(index): {
                "hard_issues": (
                    ["subject_finite_verb_split"]
                    if index == split
                    else ["open_subordinate_prefix_fragment"]
                ),
                "soft_issues": [],
                "pause_ms": 0,
            }
            for index in range(1, len(words))
        },
    )

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        "But what pushes it over the edge into that Dreamcore aesthetic",
        (
            "is how those synths are amplified by audio samples of children "
            "playing in the distance."
        ),
    ]
    assert plan["pages"][1]["boundary_before"]["forced_subject_predicate"] is True


def test_complete_infinitive_page_can_relax_relative_subject_evidence():
    text = (
        "It's a walking simulator where the entire premise is allowing a new "
        "generation of players to slowly explore China-eyes millennium-era "
        "city streets."
    )
    words = text.split()
    split = words.index("to")
    cue = _cue(
        text,
        "S9515",
        display_boundary_evidence={
            str(index): {
                "hard_issues": (
                    ["relative_clause_subject_verb_split"]
                    if index == split
                    else ["open_subordinate_prefix_fragment"]
                ),
                "soft_issues": [],
                "pause_ms": 0,
            }
            for index in range(1, len(words))
        },
    )

    plan = _plan(cue)

    assert [page["en"] for page in plan["pages"]] == [
        (
            "It's a walking simulator where the entire premise is allowing a "
            "new generation of players"
        ),
        "to slowly explore China-eyes millennium-era city streets.",
    ]
    boundary = plan["pages"][1]["boundary_before"]
    assert boundary["forced_complete_to_phrase"] is True
    assert boundary["classification"] == "review"


def test_nested_continuation_clause_starts_after_punctuation_not_introducer():
    text = (
        "We need to pause and establish exactly what Mixue Bingcheng is, "
        "because if you aren't familiar with the Asian food and beverage "
        "market, the scale of this company is going to sound totally "
        "fabricated."
    )
    _, cue = _syntax_backed_cue(
        text,
        "S9520",
        word_timing=_word_timing_with_gaps(text, {10: 160, 22: 521}),
    )

    plan = podcast_learning_video.build_article_display_page_blueprint(
        [cue]
    )["render_plans"][0]

    assert [page["english"] for page in plan["pages"]] == [
        "We need to pause and establish exactly what Mixue Bingcheng is,",
        "because if you aren't familiar with the Asian food and beverage market,",
        "the scale of this company is going to sound totally fabricated.",
    ]
    assert all(page["english_font_size"] == 56 for page in plan["pages"])


def test_three_line_fallback_promotes_complete_two_page_alternative():
    cases = (
        (
            "S9521",
            (
                "Last year, Mixue Bingcheng officially overtook McDonald's "
                "to become the world's largest fast-food operator by number "
                "of locations."
            ),
            "to become the world's largest fast-food operator by number of locations.",
        ),
        (
            "S9522",
            (
                "You're getting plugged directly into the most aggressive "
                "expansion engine in the modern food and beverage industry."
            ),
            (
                "into the most aggressive expansion engine in the modern "
                "food and beverage industry."
            ),
        ),
    )

    for subtitle_id, text, expected_second_page in cases:
        _, cue = _syntax_backed_cue(
            text,
            subtitle_id,
            word_timing=_word_timing_with_gaps(text),
        )

        try:
            plan = podcast_learning_video.build_article_display_page_blueprint(
                [cue]
            )["render_plans"][0]
        except podcast_learning_video.RenderStructuralOverflowError as exc:
            assert any(
                error.get("reason") == "no_complete_normal_font_page_partition"
                for error in exc.errors
            )
            ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
                cue,
                2,
                allow_review_boundary=True,
                allow_hard_boundary=True,
            )
            assert len(ranges) == 2
            continue

        assert len(plan["pages"]) == 2
        assert plan["pages"][1]["english"] == expected_second_page
        assert all(len(page["english_lines"]) <= 2 for page in plan["pages"])


def test_forced_predicate_page_accepts_complete_adverb_preposition_phrase():
    text = (
        "You're getting plugged directly into the most aggressive expansion "
        "engine in the modern food and beverage industry."
    )
    _, cue = _syntax_backed_cue(
        text,
        "S9523",
        word_timing=_word_timing_with_gaps(text),
    )
    words = podcast_learning_video._article_boundary_words(cue)
    split = words.index("into")

    decision = podcast_learning_video._article_forced_continuation_decision(
        cue,
        words,
        split,
    )

    assert decision["classification"] == "review"
    assert decision["forced_complete_predicate_phrase"]
    assert "verb_adverb_preposition_split" in decision["issue_codes"]
    assert not podcast_learning_video._article_nonoverridable_atomic_page_boundary_issues(
        decision
    )

    decision["issue_codes"] = [
        *decision["issue_codes"],
        "numeric_unit_or_noun_split",
    ]
    assert podcast_learning_video._article_nonoverridable_atomic_page_boundary_issues(
        decision
    ) == {"numeric_unit_or_noun_split"}


def test_complete_prepositional_and_coordinated_continuations_survive_page_filter():
    cases = (
        (
            "S9801",
            "So the company is bypassing foreign giants by internalizing the most critical parts of manufacturing,",
        ),
        (
            "S9802",
            "A vertically integrated supply chain is brilliant for business margins. It is.",
        ),
        (
            "S9803",
            "People are aggressively skipping dinners out and forcing large chains into discount wars,",
        ),
    )
    draw = ImageDraw.Draw(
        Image.new(
            "RGB",
            (
                podcast_learning_video.ARTICLE_WIDTH,
                podcast_learning_video.ARTICLE_HEIGHT,
            ),
        )
    )

    for subtitle_id, text in cases:
        _, cue = _syntax_backed_cue(
            text,
            subtitle_id,
            word_timing=_word_timing_with_gaps(text, {8: 420}),
        )
        bundle = podcast_learning_video._build_article_english_page_plan(
            cue,
            draw,
            _return_candidates=True,
        )

        assert bundle["status"] == "candidate_bundle"
        assert bundle["candidates"]


def test_complete_attached_continuations_remain_reviewable_at_normal_font():
    cases = (
        (
            "S9811",
            (
                "Exactly. And that single confusing label is actually currently "
                "sitting at the center of a massive global trade dispute involving "
                "billions of dollars."
            ),
            "complete_prepositional_continuation",
        ),
        (
            "S9812",
            (
                "Because this source material involves some heavily politically "
                "charged policy actions from the current administration."
            ),
            "complete_object_continuation",
        ),
        (
            "S9813",
            (
                "Which really brings us to a daunting question about the future of "
                "global commerce based on all this."
            ),
            "complete_prepositional_continuation",
        ),
    )

    for subtitle_id, text, expected_evidence in cases:
        _, cue = _syntax_backed_cue(
            text,
            subtitle_id,
            word_timing=_word_timing_with_gaps(text),
        )

        plan = _plan(cue)

        assert len(plan["pages"]) == 2
        assert all(page["english_font_size"] in {56, 54, 52} for page in plan["pages"])
        boundary = plan["pages"][1]["boundary_before"]
        assert boundary["classification"] == "review"
        assert boundary[expected_evidence] is True
        assert podcast_learning_video._article_secondary_review_boundary_is_complete(
            plan["pages"][1]
        )


def test_attached_continuation_requires_complete_terminal_object():
    assert not podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "about the future of global commerce and",
            "boundary_before": {
                "classification": "review",
                "issue_codes": ["dependency_phrase_entrance_split"],
                "complete_prepositional_continuation": True,
            },
        }
    )

    _, short_governor = _syntax_backed_cue(
        (
            "Right. Which totally shatters the current economic model of how "
            "these systems are actually supposed to generate revenue."
        ),
        "S9814",
    )
    decision = podcast_learning_video._article_display_boundary_decision(
        short_governor,
        4,
    )
    assert decision["complete_object_continuation"] is False

    quantified = (
        "Teams can integrate an optimized system into every facet of their "
        "economy without requiring a centralized platform."
    )
    _, quantified_cue = _syntax_backed_cue(quantified, "S9815")
    quantified_words = quantified.split()
    quantified_split = quantified_words.index("of")
    quantified_decision = podcast_learning_video._article_display_boundary_decision(
        quantified_cue,
        quantified_split,
    )
    assert quantified_decision["complete_prepositional_continuation"] is False
    assert not podcast_learning_video._article_secondary_review_boundary_is_complete(
        {
            "en": "some heavily disputed policy actions without a conclusion",
            "boundary_before": {
                "classification": "review",
                "issue_codes": [
                    "short_verb_complement_split",
                    "short_verb_object_split",
                ],
                "complete_object_continuation": True,
            },
        }
    )


def test_line_wrap_downranks_page_syntax_without_blocking_same_screen_lines():
    cue = _cue(
        "Domestic universities now offer stronger programs.",
        "S9004",
        display_boundary_evidence={
            "1": {
                "hard_issues": ["subject_predicate_split"],
                "soft_issues": [],
                "pause_ms": 0,
            },
            "3": {
                "hard_issues": ["verb_preposition_complement_split"],
                "soft_issues": [],
                "pause_ms": 0,
            },
        },
    )

    assert 0 < podcast_learning_video._article_line_boundary_penalty(
        cue,
        1,
    ) < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    assert podcast_learning_video._article_line_boundary_penalty(
        cue,
        3,
    ) >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY


def test_same_screen_subject_predicate_wrap_keeps_preferred_font():
    case = next(
        item for item in FONT_FLOOR_REGRESSION_CASES
        if item["subtitle_id"] == "S0115"
    )
    words = case["english"].split()
    timing = _production_word_timing(
        words,
        case["word_ids"],
        case["start_ms"],
        case["end_ms"],
    )
    cue = _cue(
        case["english"],
        case["subtitle_id"],
        case["chinese"],
        word_timing=timing,
        display_boundary_evidence={
            "1151": {
                "hard_issues": [
                    "subject_finite_verb_split",
                    "fronted_wh_clause_split",
                ],
                "soft_issues": [],
                "pause_ms": 40,
            },
            "1152": {
                "hard_issues": [
                    "auxiliary_predicate_split",
                    "subject_finite_verb_split",
                    "fronted_wh_clause_split",
                    "protected_syntax_cut",
                ],
                "soft_issues": [],
                "pause_ms": 80,
            },
        },
    )

    plan = _plan(cue)

    assert len(plan["pages"]) == 1
    assert plan["font_size"]["english"] == 56
    assert plan["pages"][0]["en_lines"] == [
        "Especially when the domestic alternative",
        "has improved at such a staggering rate.",
    ]


def test_same_screen_hard_boundary_does_not_block_a_fitting_page():
    """A hard page boundary may still be a harmless two-line wrap."""
    cases = (
        (
            "because the bank was just dealing with this massive institutional "
            "headache at the time.",
            6,
            "preposition_object_split",
        ),
        (
            "Yeah, they skip the broader critical thinking skills altogether.",
            5,
            "protected_syntax_cut",
        ),
    )
    for text, split, issue_code in cases:
        cue = _cue(
            text,
            "S9602",
            word_timing=tuple(
                {
                    "word_id": index,
                    "surface": word,
                    "start": index * 0.3,
                    "end": index * 0.3 + 0.2,
                }
                for index, word in enumerate(text.split())
            ),
            display_boundary_evidence={
                str(split): {
                    "hard_issues": [issue_code],
                    "soft_issues": [],
                    "pause_ms": 0,
                }
            },
        )
        plan = _plan(cue)
        assert len(plan["pages"]) == 1
        assert plan["pages"][0]["english_font_size"] == 56
        assert len(plan["pages"][0]["en_lines"]) == 2
        assert " ".join(plan["pages"][0]["en_lines"]) == text


def test_same_screen_line_wrap_keeps_atomic_language_units_hard():
    cases = (
        ("Ms. Howe explained the result clearly.", 1, "protected_named_phrase_split"),
        ("The domestic alternative improved quickly.", 1, "determiner_head_phrase_split"),
        ("It has improved at a staggering rate.", 2, "auxiliary_predicate_split"),
        ("Results from accessible sources matter.", 2, "preposition_object_split"),
        ("The budget reached 12 million yuan.", 5, "numeric_unit_or_noun_split"),
    )

    for text, split, issue_code in cases:
        cue = _cue(
            text,
            "S9601",
            display_boundary_evidence={
                str(split): {
                    "hard_issues": [issue_code],
                    "soft_issues": [],
                    "pause_ms": 0,
                }
            },
        )
        assert podcast_learning_video._article_line_boundary_penalty(
            cue,
            split,
        ) >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY

    modifier_text = "They feed highly structured data to the model."
    modifier_words = modifier_text.split()
    modifier_cue = _cue(modifier_text, "S9605")
    modifier_split = modifier_words.index("data")
    assert (
        podcast_learning_video._article_same_screen_intrinsic_line_break_penalty(
            modifier_cue,
            modifier_words,
            modifier_split,
            modifier_split,
        )
        >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    )


def test_same_screen_wrap_ignores_page_turn_only_timing_warning():
    text = (
        "they feed that curated, highly structured data to a new, smaller "
        "model, the student."
    )
    cue = _cue(text, "S9606")
    split = text.split().index("to")
    decision = podcast_learning_video._article_display_boundary_decision(
        cue,
        split,
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    assert decision["issue_codes"] == ["unsupported_tight_page_transition"]
    assert podcast_learning_video._article_line_boundary_penalty(cue, split) == 0
    assert podcast_learning_video._article_final_page_layout(
        draw,
        cue,
        text.split(),
        0,
        len(text.split()),
    ) == (
        56,
        [
            "they feed that curated, highly structured data",
            "to a new, smaller model, the student.",
        ],
    )


def test_preferred_font_wins_when_56px_has_a_valid_two_line_wrap():
    text = "Alpha bravo charlie delta echo foxtrot golf hotel india juliet."
    cue = _cue(
        text,
        "S9602",
        display_boundary_evidence={
            "5": {
                "hard_issues": ["subject_predicate_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        },
    )
    words = text.split()
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    def fake_layout(_draw, _text, _key=None, *, font_size, **_kwargs):
        split = 5 if font_size == 56 else 6
        return [" ".join(words[:split]), " ".join(words[split:])]

    with patch.object(
        podcast_learning_video,
        "_article_fixed_english_lines",
        side_effect=fake_layout,
    ):
        layout = podcast_learning_video._article_final_page_layout(
            draw,
            cue,
            words,
            0,
            len(words),
        )

    assert layout == (
        56,
        ["Alpha bravo charlie delta echo", "foxtrot golf hotel india juliet."],
    )


def test_short_page_keeps_56px_instead_of_shrinking_to_one_line():
    text = "Both sides are getting exactly what they want."
    words = text.split()
    cue = _cue(text, "S9607")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    layout = podcast_learning_video._article_final_page_layout(
        draw,
        cue,
        words,
        0,
        len(words),
    )

    assert layout == (
        56,
        ["Both sides are getting", "exactly what they want."],
    )


def test_same_screen_reflow_does_not_shrink_without_a_better_line_break():
    text = "itself are now being actively weaponized against these returning students."
    cue = _cue(text, "S9603")
    lines = [
        "itself are now being actively",
        "weaponized against these returning students.",
    ]
    plan = {
        "font_size": {"english": 56, "chinese": 46},
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9603.P01",
                "en": text,
                "word_start": 0,
                "word_end": len(text.split()) - 1,
                "en_lines": lines,
                "english_font_size": 56,
                "en_width": 1455,
            }
        ],
    }
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with patch.object(
        podcast_learning_video,
        "_article_final_page_layout",
        return_value=(50, list(lines)),
    ), patch.object(
        podcast_learning_video,
        "_article_fixed_english_lines",
        return_value=list(lines),
    ):
        finalized = podcast_learning_video._finalize_article_same_screen_layout(
            cue,
            draw,
            plan,
        )

    assert finalized["pages"][0]["english_font_size"] == 56
    assert finalized["pages"][0]["en_lines"] == lines


def test_same_screen_reflow_marks_legacy_syntax_wrap_without_shrinking():
    text = "itself are now being actively weaponized against these returning students."
    cue = _cue(
        text,
        "S9606",
        display_boundary_evidence={
            str(split): {
                "hard_issues": (
                    []
                    if split in {1, 2, 3}
                    else ["modifier_head_split"]
                ),
                "soft_issues": [],
                "pause_ms": 0,
            }
            for split in range(1, len(text.split()))
        },
    )
    legacy_lines = [
        "itself are now being actively",
        "weaponized against these returning students.",
    ]
    plan = {
        "font_size": {"english": 56, "chinese": 46},
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9606.P01",
                "en": text,
                "word_start": 0,
                "word_end": len(text.split()) - 1,
                "en_lines": legacy_lines,
                "english_font_size": 56,
                "en_width": 1455,
            }
        ],
    }
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    finalized = podcast_learning_video._finalize_article_same_screen_layout(
        cue,
        draw,
        plan,
    )

    assert finalized["pages"][0]["english_font_size"] == 56
    assert finalized["pages"][0]["en_lines"] == legacy_lines
    assert finalized["pages"][0]["line_wrap_review"] is True
    assert finalized["font_fallback"] == {"used": False}


def test_same_screen_reflow_keeps_valid_56px_over_a_smaller_one_line_layout():
    text = "Alpha bravo charlie delta echo foxtrot golf hotel india juliet."
    words = text.split()
    cue = _cue(
        text,
        "S9604",
        display_boundary_evidence={
            "5": {
                "hard_issues": ["subject_predicate_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        },
    )
    plan = {
        "font_size": {"english": 56, "chinese": 46},
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9604.P01",
                "en": text,
                "word_start": 0,
                "word_end": len(words) - 1,
                "en_lines": [
                    "Alpha bravo charlie delta echo",
                    "foxtrot golf hotel india juliet.",
                ],
                "english_font_size": 56,
                "en_width": 1260,
            }
        ],
    }
    improved_lines = [
        "Alpha bravo charlie delta echo foxtrot",
        "golf hotel india juliet.",
    ]
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with patch.object(
        podcast_learning_video,
        "_article_final_page_layout",
        return_value=(54, list(improved_lines)),
    ), patch.object(
        podcast_learning_video,
        "_article_fixed_english_lines",
        return_value=list(plan["pages"][0]["en_lines"]),
    ):
        finalized = podcast_learning_video._finalize_article_same_screen_layout(
            cue,
            draw,
            plan,
        )

    assert finalized["pages"][0]["english_font_size"] == 56
    assert finalized["pages"][0]["en_lines"] == plan["pages"][0]["en_lines"]


def test_same_screen_reflow_cannot_change_frozen_page_contract():
    cases = (
        _syntax_backed_cue(
            "There was this young woman lamenting that her parents spent over "
            "2 million yuan to send her abroad.",
            "S9701",
            word_timing=_word_timing_with_gaps(
                "There was this young woman lamenting that her parents spent over "
                "2 million yuan to send her abroad.",
                {5: 540},
            ),
        )[1],
        _syntax_backed_cue(
            FONT_FLOOR_REGRESSION_CASES[1]["english"],
            "S9702",
            word_timing=_production_word_timing(
                FONT_FLOOR_REGRESSION_CASES[1]["english"].split(),
                FONT_FLOOR_REGRESSION_CASES[1]["word_ids"],
                FONT_FLOOR_REGRESSION_CASES[1]["start_ms"],
                FONT_FLOOR_REGRESSION_CASES[1]["end_ms"],
            ),
        )[1],
    )
    snapshots = [
        (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, cue.word_timing)
        for cue in cases
    ]

    with patch.object(
        podcast_learning_video,
        "_finalize_article_same_screen_layout",
        side_effect=lambda _cue, _draw, plan: dict(plan),
    ):
        strict = podcast_learning_video.build_article_display_page_blueprint(cases)
    reflowed = podcast_learning_video.build_article_display_page_blueprint(cases)

    def frozen_projection(blueprint):
        return [
            {
                "parent_subtitle_id": plan["parent_subtitle_id"],
                "english": plan["english"],
                "chinese": plan["chinese"],
                "word_start": plan["word_start"],
                "word_end": plan["word_end"],
                "pages": [
                    {
                        key: page[key]
                        for key in (
                            "display_page_id",
                            "word_start",
                            "word_end",
                            "english",
                            "start_ms",
                            "end_ms",
                            "boundary_before",
                        )
                    }
                    for page in plan["pages"]
                ],
            }
            for plan in blueprint["render_plans"]
        ]

    assert frozen_projection(reflowed) == frozen_projection(strict)
    assert len(reflowed["parents"]) == len(strict["parents"])
    assert [
        (cue.subtitle_id, cue.en, cue.zh, cue.start, cue.end, cue.word_timing)
        for cue in cases
    ] == snapshots


def test_frozen_artifact_same_screen_reflow_changes_only_typography():
    text = "Alpha bravo charlie delta echo foxtrot golf hotel india juliet."
    cue = _cue(
        text,
        "S9703",
        display_boundary_evidence={
            "2": {
                "hard_issues": ["subject_predicate_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        },
    )
    frozen = {
        "parent_subtitle_id": "S9703",
        "english": text,
        "chinese": "甲乙",
        "word_start": 0,
        "word_end": 9,
        "english_font_size": 56,
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9703.P01",
                "word_start": 0,
                "word_end": 4,
                "english": "Alpha bravo charlie delta echo",
                "chinese": "甲",
                "start_ms": 0,
                "end_ms": 2500,
                "english_lines": ["Alpha bravo", "charlie delta echo"],
                "english_font_size": 56,
                "english_width": 1260,
                "boundary_before": {"classification": "allow"},
            },
            {
                "display_page_id": "S9703.P02",
                "word_start": 5,
                "word_end": 9,
                "english": "foxtrot golf hotel india juliet.",
                "chinese": "乙",
                "start_ms": 2500,
                "end_ms": 5000,
                "english_lines": ["foxtrot golf", "hotel india juliet."],
                "english_font_size": 56,
                "english_width": 1260,
                "boundary_before": {"classification": "review"},
            },
        ],
    }
    before = copy.deepcopy(frozen)
    layouts = [
        (54, ["Alpha bravo charlie", "delta echo"]),
        (56, ["foxtrot golf hotel", "india juliet."]),
    ]

    with patch.object(
        podcast_learning_video,
        "_article_final_page_layout",
        side_effect=layouts,
    ):
        upgraded = (
            podcast_learning_video.reflow_article_frozen_page_plan_same_screen(
                cue,
                frozen,
            )
        )

    structural_keys = (
        "display_page_id",
        "word_start",
        "word_end",
        "english",
        "chinese",
        "start_ms",
        "end_ms",
        "boundary_before",
    )
    plan_keys = (
        "parent_subtitle_id",
        "english",
        "chinese",
        "word_start",
        "word_end",
    )
    assert frozen == before
    assert {key: upgraded[key] for key in plan_keys} == {
        key: before[key] for key in plan_keys
    }
    assert [
        {key: page[key] for key in structural_keys}
        for page in upgraded["pages"]
    ] == [
        {key: page[key] for key in structural_keys}
        for page in before["pages"]
    ]
    assert upgraded["english_font_size"] == 54
    assert upgraded["pages"][0]["english_lines"] == layouts[0][1]
    assert upgraded["pages"][1]["english_lines"] == layouts[1][1]


def test_frozen_reflow_relaxes_page_penalty_for_severe_orphan_without_moving_words():
    text = (
        "Okay. He stated definitively that artificial intelligence systems, "
        "they do not undergo experiences."
    )
    cue = _cue(text, "S9704", chinese="甲乙")
    frozen = {
        "parent_subtitle_id": "S9704",
        "english": text,
        "chinese": "甲乙",
        "word_start": 0,
        "word_end": 12,
        "english_font_size": 56,
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9704.P01",
                "word_start": 0,
                "word_end": 7,
                "english": "Okay. He stated definitively that artificial intelligence systems,",
                "chinese": "甲",
                "start_ms": 0,
                "end_ms": 3600,
                "english_lines": [
                    "Okay. He",
                    "stated definitively that artificial intelligence systems,",
                ],
                "english_font_size": 56,
                "english_width": 1455,
                "boundary_before": {"classification": "allow"},
            },
            {
                "display_page_id": "S9704.P02",
                "word_start": 8,
                "word_end": 12,
                "english": "they do not undergo experiences.",
                "chinese": "乙",
                "start_ms": 3600,
                "end_ms": 5720,
                "english_lines": ["they do not undergo experiences."],
                "english_font_size": 56,
                "english_width": 1260,
                "boundary_before": {"classification": "review"},
            },
        ],
    }

    upgraded = podcast_learning_video.reflow_article_frozen_page_plan_same_screen(
        cue,
        frozen,
    )

    assert upgraded["pages"][0]["english_lines"] == [
        "Okay. He stated definitively that",
        "artificial intelligence systems,",
    ]
    assert podcast_learning_video._article_line_balance_ratio(
        ImageDraw.Draw(Image.new("RGB", (1920, 1080))),
        upgraded["pages"][0]["english_lines"],
        56,
    ) >= 0.48
    for key in (
        "display_page_id",
        "word_start",
        "word_end",
        "english",
        "chinese",
        "start_ms",
        "end_ms",
        "boundary_before",
    ):
        assert [page[key] for page in upgraded["pages"]] == [
            page[key] for page in frozen["pages"]
        ]


def test_manual_artifact_load_applies_frozen_page_reflow_only_to_typography():
    text = (
        "Okay. He stated definitively that artificial intelligence systems, "
        "they do not undergo experiences."
    )
    cue = _cue(text, "S9705", chinese="甲乙")
    frozen = {
        "parent_subtitle_id": "S9705",
        "english": text,
        "chinese": "甲乙",
        "word_start": 0,
        "word_end": 12,
        "english_font_size": 56,
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S9705.P01",
                "word_start": 0,
                "word_end": 7,
                "english": "Okay. He stated definitively that artificial intelligence systems,",
                "chinese": "甲",
                "start_ms": 0,
                "end_ms": 3600,
                "english_lines": ["Okay. He", "stated definitively that artificial intelligence systems,"],
                "english_font_size": 56,
                "english_width": 1455,
                "boundary_before": {"classification": "allow"},
            },
            {
                "display_page_id": "S9705.P02",
                "word_start": 8,
                "word_end": 12,
                "english": "they do not undergo experiences.",
                "chinese": "乙",
                "start_ms": 3600,
                "end_ms": 5720,
                "english_lines": ["they do not undergo experiences."],
                "english_font_size": 56,
                "english_width": 1260,
                "boundary_before": {"classification": "review"},
            },
        ],
    }
    artifact = {
        "schema_version": podcast_learning_video.MANUAL_DRAFT_PAGE_SCHEMA_VERSION,
        "status": "REVIEW",
        "planner_version": podcast_learning_video.DISPLAY_PAGE_PLANNER_VERSION,
        "layout_profile": podcast_learning_video.article_display_page_layout_profile(),
        "render_plans": [frozen],
    }

    assert podcast_learning_video.apply_article_manual_draft_page_artifact(
        [cue],
        artifact,
    )
    assert cue.article_page_plan["pages"][0]["en_lines"] == [
        "Okay. He stated definitively that",
        "artificial intelligence systems,",
    ]
    assert [
        (
            page["display_page_id"],
            page["global_word_start"],
            page["global_word_end"],
            page["start"],
            page["end"],
            page["zh"],
        )
        for page in cue.article_page_plan["pages"]
    ] == [
        ("S9705.P01", 0, 7, 0.0, 3.6, "甲"),
        ("S9705.P02", 8, 12, 3.6, 5.72, "乙"),
    ]

    display_cue = _cue(text, "S9706", chinese="甲乙")
    display_frozen = copy.deepcopy(frozen)
    display_frozen["parent_subtitle_id"] = "S9706"
    for page in display_frozen["pages"]:
        page["display_page_id"] = page["display_page_id"].replace("S9705", "S9706")
    display_artifact = {
        "schema_version": podcast_learning_video.DISPLAY_PAGE_SCHEMA_VERSION,
        "status": "PASS",
        "planner_version": podcast_learning_video.DISPLAY_PAGE_PLANNER_VERSION,
        "layout_profile": podcast_learning_video.article_display_page_layout_profile(),
        "render_plans": [display_frozen],
        "parents": [
            {
                "parent_subtitle_id": "S9706",
                "source_parent_chinese": "甲乙",
                "aggregate_chinese": "甲乙",
                "pages": [
                    {"display_page_id": "S9706.P01", "zh": "甲"},
                    {"display_page_id": "S9706.P02", "zh": "乙"},
                ],
            }
        ],
    }

    assert podcast_learning_video.apply_article_display_page_translation_artifact(
        [display_cue],
        display_artifact,
        reflow_frozen_page_lines=True,
    )
    assert display_cue.article_page_plan["pages"][0]["en_lines"] == [
        "Okay. He stated definitively that",
        "artificial intelligence systems,",
    ]
    assert [
        (
            page["display_page_id"],
            page["global_word_start"],
            page["global_word_end"],
            page["start"],
            page["end"],
            page["zh"],
        )
        for page in display_cue.article_page_plan["pages"]
    ] == [
        ("S9706.P01", 0, 7, 0.0, 3.6, "甲"),
        ("S9706.P02", 8, 12, 3.6, 5.72, "乙"),
    ]


def test_manual_page_boundary_rebuild_preserves_parent_and_rederives_pages():
    text = (
        "Reliable systems preserve every frozen parent while manual reviewers "
        "adjust only visual page boundaries safely."
    )
    words = text.split()
    cue = _cue(
        text,
        "S9401",
        "可靠系统会保留冻结父字幕，人工仅安全调整视觉分页。",
        display_boundary_evidence={
            str(index): {
                "hard_issues": [],
                "soft_issues": [],
                "pause_ms": 130,
            }
            for index in range(1, len(words))
        },
    )
    frozen_plan = {
        "parent_subtitle_id": cue.subtitle_id,
        "english": cue.en,
        "chinese": cue.zh,
        "word_start": 0,
        "word_end": len(words) - 1,
        "english_font_size": 50,
        "pages": [
            {"display_page_id": "S9401.P01"},
            {"display_page_id": "S9401.P02"},
        ],
    }

    rebuilt = podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
        cue,
        frozen_plan,
        [(0, 6), (7, len(words) - 1)],
        {"S9401.P01": "可靠系统会保留冻结父字幕，", "S9401.P02": "人工仅安全调整视觉分页。"},
    )

    assert {
        key: rebuilt[key]
        for key in ("parent_subtitle_id", "english", "chinese", "word_start", "word_end")
    } == {
        "parent_subtitle_id": "S9401",
        "english": text,
        "chinese": cue.zh,
        "word_start": 0,
        "word_end": len(words) - 1,
    }
    pages = rebuilt["pages"]
    assert [page["display_page_id"] for page in pages] == [
        "S9401.P01",
        "S9401.P02",
    ]
    assert [(page["word_start"], page["word_end"]) for page in pages] == [
        (0, 6),
        (7, len(words) - 1),
    ]
    assert " ".join(page["english"] for page in pages) == text
    assert pages[0]["start_ms"] == round(cue.start * 1000)
    assert pages[0]["end_ms"] == pages[1]["start_ms"]
    assert pages[-1]["end_ms"] == round(cue.end * 1000)
    assert all(page["end_ms"] - page["start_ms"] >= 900 for page in pages)
    assert all(page["english_lines"] for page in pages)
    assert rebuilt["english_font_size"] == min(
        page["english_font_size"] for page in pages
    )
    assert all(
        page["english_width"]
        in {
            podcast_learning_video.ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
            podcast_learning_video.ARTICLE_SUBTITLE_EN_WIDTH,
            podcast_learning_video.ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
        }
        for page in pages
    )
    assert pages[1]["boundary_before"]["manual_override"] is True


def test_manual_multipage_rebuild_assigns_font_from_each_final_page():
    text = (
        "extraordinary international semiconductor manufacturing capabilities "
        "require continuous investment, and it works well for everyone today."
    )
    words = text.split()
    cue = _cue(
        text,
        "S9403",
        "高强度页面，较短页面。",
        display_boundary_evidence={
            str(index): {
                "hard_issues": [],
                "soft_issues": [],
                "pause_ms": 150,
            }
            for index in range(1, len(words))
        },
    )
    frozen_plan = {
        "parent_subtitle_id": cue.subtitle_id,
        "english": cue.en,
        "chinese": cue.zh,
        "word_start": 0,
        "word_end": len(words) - 1,
        "english_font_size": 50,
        "pages": [
            {"display_page_id": "S9403.P01"},
            {"display_page_id": "S9403.P02"},
        ],
    }

    rebuilt = podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
        cue,
        frozen_plan,
        [(0, 7), (8, len(words) - 1)],
        {"S9403.P01": "高强度页面，", "S9403.P02": "较短页面。"},
    )

    assert [page["english_font_size"] for page in rebuilt["pages"]] == [52, 56]
    assert rebuilt["english_font_size"] == 52


def test_manual_page_boundary_rebuild_rejects_hard_empty_and_short_pages():
    text = "One two three four five six seven eight nine ten"
    page_ids = [
        {"display_page_id": "S9402.P01"},
        {"display_page_id": "S9402.P02"},
    ]

    hard_cue = _cue(
        text,
        "S9402",
        display_boundary_evidence={
            "5": {
                "hard_issues": ["atomic_of_complement_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        },
    )
    cases = [
        (
            hard_cue,
            [(0, 4), (5, 9)],
            "manual_page_boundary_is_hard",
        ),
        (
            _cue(text, "S9402"),
            [(0, -1), (0, 9)],
            "manual_page_boundary_not_contiguous",
        ),
        (
            _cue(
                text,
                "S9402",
                word_timing=tuple(
                    {
                        "word_id": index,
                        "surface": word,
                        "start": index * 0.14,
                        "end": index * 0.14 + 0.1,
                    }
                    for index, word in enumerate(text.split())
                ),
            ),
            [(0, 4), (5, 9)],
            "cue_duration_below_page_minimum",
        ),
    ]

    for cue, ranges, expected_reason in cases:
        frozen_plan = {
            "parent_subtitle_id": cue.subtitle_id,
            "english": cue.en,
            "chinese": cue.zh,
            "word_start": 0,
            "word_end": 9,
            "english_font_size": 56,
            "pages": page_ids,
        }
        try:
            podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
                cue,
                frozen_plan,
                ranges,
                {"S9402.P01": "中文一", "S9402.P02": "中文二"},
            )
        except podcast_learning_video.RenderStructuralOverflowError as exc:
            reasons = {
                str(error.get("reason") or "") for error in exc.errors
            }
            assert expected_reason in reasons
        else:
            raise AssertionError(f"unsafe page ranges must fail: {expected_reason}")


def test_single_page_candidate_requires_parent_chinese_to_fit_fixed_layout():
    text = (
        "The possibility that external guardrails meant to slow them down "
        "might actually ensure their long-term economic survival is a "
        "fascinating paradox for you to consider."
    )
    words = text.split()
    starts_ms = (
        905932, 906052, 906653, 906813, 907233, 907734, 907894, 908014,
        908274, 908415, 908695, 908935, 909196, 909476, 909656, 910157,
        910577, 911138, 911238, 911318, 911859, 912319, 912419, 912540,
        912620,
    )
    ends_ms = (
        906012, 906612, 906753, 907173, 907694, 907854, 907954, 908234,
        908375, 908655, 908835, 909176, 909456, 909616, 910097, 910537,
        911038, 911198, 911278, 911819, 912299, 912399, 912520, 912580,
        912880,
    )
    hard_issues = {
        2525: ["determiner_head_phrase_split", "protected_syntax_cut"],
        2526: ["content_noun_that_clause_split", "dependency_phrase_entrance_split"],
        2527: ["determiner_head_phrase_split", "clause_introducer_split", "protected_syntax_cut"],
        2528: ["protected_syntax_cut"],
        2529: ["subject_finite_verb_split", "protected_syntax_cut"],
        2530: ["verb_complement_split", "short_verb_complement_split"],
        2531: ["preposition_object_split", "protected_syntax_cut"],
        2532: ["short_verb_object_split", "short_verb_complement_split", "separable_verb_particle_chain_split"],
        2533: ["separable_verb_particle_chain_split"],
        2534: ["subject_finite_verb_split"],
        2535: ["subject_finite_verb_split", "protected_syntax_cut"],
        2536: ["subject_finite_verb_split", "dependency_phrase_entrance_split", "modifier_head_split", "protected_syntax_cut"],
        2537: ["verb_complement_split", "short_verb_complement_split"],
        2538: ["determiner_head_phrase_split", "protected_syntax_cut"],
        2539: ["modifier_noun_head_split", "protected_syntax_cut"],
        2540: ["protected_syntax_cut"],
        2541: ["subject_finite_verb_split"],
        2542: ["verb_complement_split", "short_verb_complement_split"],
        2543: ["determiner_head_phrase_split", "protected_syntax_cut"],
        2544: ["protected_syntax_cut"],
        2545: [],
        2546: ["preposition_object_split", "clause_introducer_split", "protected_syntax_cut"],
        2547: ["subject_finite_verb_split", "protected_syntax_cut"],
        2548: ["preposition_object_split", "subject_finite_verb_split", "protected_syntax_cut"],
    }
    cue = podcast_learning_video.Cue(
        199,
        905.892,
        913.140,
        text,
        (
            "那些旨在拖慢中国脚步的外部护栏，反而可能确保其长期的经济生存；"
            "这种可能性本身就是一个耐人寻味的悖论，值得你好好思量。"
        ),
        "male",
        subtitle_id="S0199",
        word_timing=tuple(
            {
                "word_id": 2524 + index,
                "surface": word,
                "start": starts_ms[index] / 1000.0,
                "end": ends_ms[index] / 1000.0,
            }
            for index, word in enumerate(words)
        ),
        display_boundary_evidence={
            str(word_id): {
                "hard_issues": issues,
                "soft_issues": [],
                "pause_ms": max(
                    0,
                    starts_ms[word_id - 2524]
                    - ends_ms[word_id - 2525],
                ),
            }
            for word_id, issues in hard_issues.items()
        },
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with patch.object(
        podcast_learning_video,
        "_article_fixed_chinese_lines",
        return_value=[],
    ):
        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert plan["status"] == "render_structural_overflow"
    assert plan["errors"]
    ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
        cue,
        2,
        allow_review_boundary=True,
        allow_hard_boundary=True,
    )
    assert len(ranges) == 2


def test_forced_verb_complement_split_ranks_below_subject_predicate_fallback():
    verb_complement = {
        "classification": "review",
        "confidence": "high",
        "forced_display_continuation": True,
        "forced_complete_to_phrase": True,
        "issue_codes": ["verb_complement_split", "short_verb_complement_split"],
    }
    subject_predicate = {
        "classification": "review",
        "confidence": "high",
        "forced_display_continuation": True,
        "forced_subject_predicate": True,
        "issue_codes": ["subject_finite_verb_split"],
    }

    assert podcast_learning_video._article_page_boundary_risk(
        verb_complement,
        0,
    ) > podcast_learning_video._article_page_boundary_risk(
        subject_predicate,
        0,
    )


if __name__ == "__main__":
    test_candidate_workspace_is_read_only_and_bounded()
    test_candidate_workspace_allows_explicit_manual_six_page_search()
    test_display_planning_does_not_mutate_frozen_cue_identity_text_or_timing()
    test_numeric_magnitude_is_nonoverridable_at_display_page_boundary()
    test_visual_planning_reuses_the_complete_frozen_page_projection()
    test_subject_predicate_boundary_is_not_used_for_efficiency_gap_page_change()
    test_zero_relative_tail_does_not_become_an_isolated_display_page()
    test_dominant_readability_selection_relieves_low_font_with_complete_phrases()
    test_dominant_readability_selection_merges_a_comfortable_short_tail()
    test_wh_clause_boundary_is_not_used_for_chinese_businesses_page_change()
    test_unsplittable_infinitive_phrase_remains_renderable_at_the_52px_floor()
    test_page_translation_contract_rejects_a_chinese_token_split_across_pages()
    test_frozen_page_artifact_records_font_size_and_line_width_for_each_page()
    test_page_span_score_prefers_balanced_legal_boundary_when_risk_is_equal()
    test_page_span_frontier_retains_distinct_safe_visual_partitions()
    test_reference_style_wrap_prefers_balanced_two_lines_before_wide_single_line()
    test_same_screen_wrap_does_not_favor_a_short_punctuation_prefix()
    test_hyphenated_word_is_not_a_barrier_after_the_complete_token()
    test_extreme_same_screen_imbalance_uses_50px_only_on_the_legacy_path()
    test_three_english_lines_and_one_chinese_line_use_separate_vertical_origin()
    test_manual_page_proposal_requires_explicit_hard_boundary_override()
    test_automatic_page_limit_stays_four_while_manual_can_request_six()
    test_production_candidate_bundle_keeps_a_bounded_visual_frontier()
    test_shadow_candidate_frontier_exposes_alternatives_without_changing_production()
    test_production_candidates_score_the_same_font_used_by_final_reflow()
    test_planning_and_final_same_screen_layout_share_one_contract()
    test_sub_14_word_cue_prefers_static_floor_over_medium_review_boundary()
    test_review_boundary_can_replace_a_static_layout_below_the_52px_floor()
    test_article_english_font_profile_has_a_52px_automatic_floor()
    test_fourteen_fifteen_sixteen_word_readability_policy()
    test_font_floor_regression_cues_prefer_pages_before_the_52px_floor()
    test_punctuated_pronoun_clause_uses_two_56px_pages_before_50px()
    test_punctuated_numeric_model_clause_uses_two_balanced_56px_pages()
    test_extended_numeric_range_does_not_create_a_five_word_tail_page()
    test_complete_five_word_terminal_phrase_is_a_reviewable_page_fallback()
    test_four_word_prepositional_tail_does_not_replace_balanced_review_pages()
    test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px()
    test_checkpoint_hard_page_cues_use_normal_fonts_or_fail_for_manual_takeover()
    test_forced_page_break_rank_reuses_the_forced_decision_for_risk()
    test_actual_plans_do_not_select_the_tight_complement_boundaries()
    test_display_page_keeps_multiword_work_title_atomic()
    test_title_detection_does_not_cross_sentences_or_claim_numeric_condition()
    test_complete_from_gerund_can_relax_verb_preposition_evidence()
    test_numeric_head_guard_does_not_absorb_a_following_preposition()
    test_spaced_thousands_group_is_atomic_at_line_wrap()
    test_amount_frequency_phrase_stays_on_the_same_display_page()
    test_sequence_selection_relaxes_consecutive_dense_pages()
    test_sequence_selection_avoids_an_abrupt_adjacent_pressure_jump()
    test_sequence_selection_prefers_stable_56px_when_risk_is_equal()
    test_sequence_stability_cannot_create_a_short_lead_in_before_a_50px_tail()
    test_sequence_downranks_an_incomplete_review_cut_before_visual_stability()
    test_54px_static_page_promotes_only_a_complete_56px_partition()
    test_duration_alone_does_not_paginate_a_readable_static_cue()
    test_duration_alone_does_not_promote_an_equally_sized_partition()
    test_complete_review_partition_remains_visible_after_strict_static_candidate()
    test_multipage_50px_baseline_promotes_complete_56px_expansion()
    test_balanced_56px_multipage_baseline_is_not_over_paginated()
    test_long_56px_static_page_promotes_only_a_complete_readable_partition()
    test_blueprint_keeps_56px_when_a_safe_page_plan_exists()
    test_automatic_multipage_plan_assigns_font_from_each_final_page()
    test_high_pressure_single_pages_promote_only_complete_review_partitions()
    test_high_pressure_pause_does_not_outrank_a_strict_single_page()
    test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries()
    test_secondary_page_promotion_distinguishes_safe_and_attached_boundaries()
    test_complete_from_gerund_page_beats_single_50px_fallback()
    test_complete_prepositional_page_can_relax_predicate_chain_evidence()
    test_predicate_chain_evidence_stays_hard_without_a_complete_phrase()
    test_forced_subject_predicate_candidate_survives_completeness_filter()
    test_complete_infinitive_page_can_relax_relative_subject_evidence()
    test_nested_continuation_clause_starts_after_punctuation_not_introducer()
    test_three_line_fallback_promotes_complete_two_page_alternative()
    test_complete_prepositional_and_coordinated_continuations_survive_page_filter()
    test_complete_attached_continuations_remain_reviewable_at_normal_font()
    test_attached_continuation_requires_complete_terminal_object()
    test_line_wrap_downranks_page_syntax_without_blocking_same_screen_lines()
    test_same_screen_subject_predicate_wrap_keeps_preferred_font()
    test_same_screen_line_wrap_keeps_atomic_language_units_hard()
    test_preferred_font_wins_when_56px_has_a_valid_two_line_wrap()
    test_short_page_keeps_56px_instead_of_shrinking_to_one_line()
    test_same_screen_reflow_does_not_shrink_without_a_better_line_break()
    test_same_screen_reflow_marks_legacy_syntax_wrap_without_shrinking()
    test_same_screen_reflow_keeps_valid_56px_over_a_smaller_one_line_layout()
    test_same_screen_reflow_cannot_change_frozen_page_contract()
    test_frozen_artifact_same_screen_reflow_changes_only_typography()
    test_manual_page_boundary_rebuild_preserves_parent_and_rederives_pages()
    test_manual_multipage_rebuild_assigns_font_from_each_final_page()
    test_manual_page_boundary_rebuild_rejects_hard_empty_and_short_pages()
    test_single_page_candidate_requires_parent_chinese_to_fit_fixed_layout()
    test_forced_verb_complement_split_ranks_below_subject_predicate_fallback()
    print("article display readability contract tests passed")

from scripts.measure_page_number_anchors import measure_parent


def test_number_on_wrong_chinese_page_is_review():
    parent = {
        "parent_subtitle_id": "S9001",
        "pages": [
            {
                "display_page_id": "S9001.P01",
                "english": "Sales rose to 460%.",
                "zh": "销售增长。",
            },
            {
                "display_page_id": "S9001.P02",
                "english": "The increase continued.",
                "zh": "增长到了460%。",
            },
        ],
    }
    items = measure_parent(parent)
    assert len(items) == 1
    assert items[0]["bucket"] == "review"
    assert items[0]["en_pages"] == ["S9001.P01"]
    assert items[0]["zh_pages"] == ["S9001.P02"]


def test_reordered_chinese_with_number_on_correct_page_is_not_reported():
    parent = {
        "parent_subtitle_id": "S9002",
        "pages": [
            {
                "display_page_id": "S9002.P01",
                "english": "In 2018, sales rose to 460%.",
                "zh": "销售在460%增长，发生在2018年。",
            },
            {
                "display_page_id": "S9002.P02",
                "english": "The project continued.",
                "zh": "项目继续。",
            },
        ],
    }
    assert measure_parent(parent) == []

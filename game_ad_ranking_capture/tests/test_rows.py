import rows as R
from helpers import HEIGHT, PITCH, WIDTH, card, word


def page_of(*cards):
    return R.parse_page([w for c in cards for w in c], WIDTH, HEIGHT)


def test_a_full_page_with_medals_gets_its_ranks():
    cys = [550 + i * PITCH for i in range(5)]
    page = page_of(
        card(cys[0], None, "Gold", "Mice", 300),
        card(cys[1], None, "Silver", "Mice", 200),
        card(cys[2], None, "Bronze", "Mice", 100),  # the medal is not read for the third either
        card(cys[3], 4, "Four", "Fish", 90, tag="FfS"),
        card(cys[4], 5, "Five", "Mice", 80),
    )
    assert [(r.rank, r.name, r.points) for r in page.rows] == [
        (1, "Gold", 300),
        (2, "Silver", 200),
        (3, "Bronze", 100),
        (4, "Four", 90),
        (5, "Five", 80),
    ]
    assert (page.rows[3].alliance, page.rows[3].tag) == ("Fish", "FfS")
    assert page.me is None


def test_cards_cut_off_by_the_list_edges_are_left_for_the_next_page():
    page = page_of(
        card(470, 7, "Cut at the top", "Mice", 9),
        card(700, 8, "Whole", "Mice", 8),
        card(1530, 9, "Cut below", "Mice", 7),
    )
    assert [r.name for r in page.rows] == ["Whole"]


def test_the_pinned_own_row_is_returned_apart():
    page = page_of(card(700, 8, "Whole", "Mice", 8), card(1622, 28, "Klingo", "Mice", 15_422_182))
    assert [r.name for r in page.rows] == ["Whole"]
    assert (page.me.rank, page.me.name, page.me.points) == (28, "Klingo", 15_422_182)


def test_a_misread_rank_is_corrected_by_the_spacing_and_flagged():
    cys = [700 + i * PITCH for i in range(3)]
    page = page_of(card(cys[0], 30, "A", "M", 3), card(cys[1], 91, "B", "M", 2), card(cys[2], 32, "C", "M", 1))
    assert [r.rank for r in page.rows] == [30, 31, 32]
    assert page.rows[1].flags == ["rank read as 91"]


def test_a_card_the_ocr_missed_does_not_shift_the_ranks_below_it():
    cys = [700 + i * PITCH for i in range(4)]
    words = card(cys[0], 10, "A", "M", 4) + card(cys[1], None, "B", "M", 3)[:-2] + card(cys[3], 13, "D", "M", 1)
    assert [(r.rank, r.name) for r in R.parse_page(words, WIDTH, HEIGHT).rows] == [(10, "A"), (13, "D")]


def test_low_confidence_and_missing_names_are_flagged():
    page = page_of(card(700, 8, "Blurry", "Mice", 8, score=0.5))
    assert "low confidence 0.50" in page.rows[0].flags
    nameless = [w for w in card(700, 8, "X", "Mice", 8) if w.text != "X"]
    assert "no name" in R.parse_page(nameless, WIDTH, HEIGHT).rows[0].flags


def test_refine_takes_the_second_engines_better_reading():
    first = page_of(card(700, 8, "paaT", "Mice", 8, score=0.4)).rows[0]
    better = [w for w in card(700, 8, "ФрауМарта", "Mice", 8) if w.cx < 700 * 1.0 and not w.text.isdigit()]
    seen = []
    again = R.refine(first, lambda region: seen.append(region) or better, WIDTH, HEIGHT)
    assert again.name == "ФрауМарта" and again.rank == first.rank and again.points == 8
    assert seen and seen[0][0] == 0.33  # it read the card's name area only
    worse = R.refine(first, lambda region: [], WIDTH, HEIGHT)
    assert worse is first


def test_points_are_only_numbers_with_thousands_separators():
    assert R.parse_points("57,015,464") == 57_015_464
    assert R.parse_points("999") == 999
    assert R.parse_points("My Alliance") is None
    assert R.parse_points("57,01") is None
    assert R.parse_points("Rank") is None


def test_a_page_without_numbers_is_ranked_from_an_earlier_page():
    cys = [700 + i * PITCH for i in range(2)]
    rows = page_of(card(cys[0], None, "Gold", "M", 300), card(cys[1], None, "Silver", "M", 200)).rows
    assert rows[0].rank is None
    known = {5: {"name": "Gold", "points": 300}}
    assert R.number_from_overlap(rows, known, PITCH) and [r.rank for r in rows] == [5, 6]
    assert not R.number_from_overlap(rows, {}, PITCH)


def test_join_orders_words_left_to_right():
    assert R.join([word("b", 200, 0), word("a", 100, 0)]) == "a b"


def test_a_card_just_below_the_column_heads_is_whole_and_counts():
    page = page_of(card(538, 31, "Top card", "Mice", 9), card(1450, 36, "Bottom card", "Mice", 8))
    assert [r.name for r in page.rows] == ["Top card", "Bottom card"]  # both fully inside the list

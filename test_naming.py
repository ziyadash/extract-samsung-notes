from naming import assign_names, clean_stem


def test_strips_timestamp_suffix():
    assert clean_stem("Week 1_250512_212919.pdf") == "Week 1"


def test_keeps_underscores_in_title():
    assert clean_stem("Lab_2_250512_212919.pdf") == "Lab_2"
    assert clean_stem("PISCF_SAI_visualization_CLEANED 4_250807_101010.pdf") == "PISCF_SAI_visualization_CLEANED 4"


def test_no_suffix_unchanged():
    assert clean_stem("Week 10.pdf") == "Week 10"
    assert clean_stem("notes_2024.pdf") == "notes_2024"


def test_samsung_duplicate_counter():
    assert clean_stem("Chapter 2_260928_171414 (1).pdf") == "Chapter 2"


def test_collisions_get_numbered():
    names = assign_names(["Quiz_250101_090000.pdf", "Quiz_250102_090000.pdf", "Other_250101_090000.pdf"])
    assert names == {
        "Other_250101_090000.pdf": "Other.pdf",
        "Quiz_250101_090000.pdf": "Quiz.pdf",
        "Quiz_250102_090000.pdf": "Quiz (2).pdf",
    }


def test_collisions_case_insensitive():
    names = assign_names(["notes_250101_090000.pdf", "Notes_250102_090000.pdf"])
    assert sorted(names.values()) == ["Notes.pdf", "notes (2).pdf"]


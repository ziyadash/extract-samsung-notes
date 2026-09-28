import pytest

import nav
from nav import parse_folder_paths


@pytest.fixture(autouse=True)
def skip_list(monkeypatch):
    monkeypatch.setattr(nav, "SKIP_TOP_LEVEL", {"Personal"})


def test_folder_paths_valid():
    assert parse_folder_paths(["MATH3411", "ELEC4612/Labs", "TELE3113/Labs/Lab 1"]) == [
        ["MATH3411"], ["ELEC4612", "Labs"], ["TELE3113", "Labs", "Lab 1"]]


def test_folder_paths_drop_covered():
    assert parse_folder_paths(["MATH3411/Notes", "MATH3411", "MATH3411"]) == [["MATH3411"]]


@pytest.mark.parametrize("bad", ["", "/MATH3411", "MATH3411/", "MATH3411//Notes", "MATH3411 / Notes",
                                 " MATH3411", "../MATH3411", "Personal", "Personal/x"])
def test_folder_paths_invalid(bad):
    with pytest.raises(ValueError):
        parse_folder_paths([bad])

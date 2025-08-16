import importlib
from pathlib import Path

watch = importlib.import_module("harvest.watch")

def test_is_ignored_name_basics():
    f = watch._is_ignored_name
    assert f(".DS_Store")
    assert f("Thumbs.db")
    assert f(".#README.md")
    assert f("~$budget.xlsx")
    assert f("notes.md~")
    assert f("file.tmp")  # ends with .tmp pattern
    assert f("video.part")  # ends with .part pattern
    assert f("dl.crdownload")  # ends with .crdownload pattern
    assert not f("README.md")
    assert not f("main.py")
    assert not f("template.py")  # should not match .tmp pattern

def test_filter_ext_respects_only_and_skip():
    assert watch._filter_ext("a/main.py", only={"py"}, skip=None)
    assert not watch._filter_ext("a/main.ts", only={"py"}, skip=None)
    assert not watch._filter_ext("a/main.py", only=None, skip={"py"})
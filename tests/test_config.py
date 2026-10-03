from __future__ import annotations

import pytest

from kobold import config


@pytest.fixture
def workflow_data(tmp_path, monkeypatch):
    monkeypatch.delenv("KOBOLD_DATA", raising=False)
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "com.anokhin.kobold"))
    return tmp_path


def test_data_dir_adopts_kobolib_folder(workflow_data):
    old = workflow_data / "com.anokhin.kobolib"
    old.mkdir()
    (old / "library.db").write_text("index")

    assert config.data_dir() == workflow_data / "com.anokhin.kobold", "data should live under the new bundle id"
    assert (workflow_data / "com.anokhin.kobold" / "library.db").read_text() == "index", "the old index should be carried over"
    assert not old.exists(), "the kobolib folder should be gone after adoption"


def test_data_dir_keeps_existing_kobold_folder(workflow_data):
    (workflow_data / "com.anokhin.kobold").mkdir()
    (workflow_data / "com.anokhin.kobold" / "library.db").write_text("new")
    (workflow_data / "com.anokhin.kobolib").mkdir()
    (workflow_data / "com.anokhin.kobolib" / "library.db").write_text("old")

    config.data_dir()

    assert (workflow_data / "com.anokhin.kobold" / "library.db").read_text() == "new", "an existing kobold folder should win"
    assert (workflow_data / "com.anokhin.kobolib").exists(), "the old folder should be left alone when both exist"


def test_data_dir_without_predecessor(workflow_data):
    assert config.data_dir() == workflow_data / "com.anokhin.kobold", "a fresh install should just use the new folder"
    assert not (workflow_data / "com.anokhin.kobold").exists(), "data_dir should not create the folder itself"


@pytest.mark.parametrize(
    "chosen",
    ["custom", "kobolib-backup"],
    ids=["unrelated name", "name without kobold in it"],
)
def test_explicit_data_dir_is_never_migrated(tmp_path, monkeypatch, chosen):
    monkeypatch.setenv("KOBOLD_DATA", str(tmp_path / chosen))
    (tmp_path / "kobolib").mkdir()

    assert config.data_dir() == tmp_path / chosen, "KOBOLD_DATA should be taken literally"
    assert (tmp_path / "kobolib").exists(), "nothing should be moved when the folder was chosen explicitly"

import plistlib
from pathlib import Path

import pytest

PLIST = Path(__file__).parent.parent / "workflow" / "info.plist"
OBJECT_VERSIONS = {
    "alfred.workflow.input.scriptfilter": 3,
    "alfred.workflow.input.keyword": 1,
    "alfred.workflow.action.script": 2,
    "alfred.workflow.output.notification": 1,
    "alfred.workflow.action.openfile": 1,
    "alfred.workflow.action.revealfile": 1,
    "alfred.workflow.output.clipboard": 3,
    "alfred.workflow.action.browseinalfred": 1,
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    with PLIST.open("rb") as handle:
        return plistlib.load(handle)


def test_every_object_has_the_version_alfred_expects(workflow):
    for obj in workflow["objects"]:
        assert obj.get("version") == OBJECT_VERSIONS[obj["type"]], f"{obj['uid']} should carry its object type's version, or Alfred calls the workflow incompatible"


def test_connections_point_at_existing_objects(workflow):
    uids = {o["uid"] for o in workflow["objects"]}
    for src, conns in workflow["connections"].items():
        assert src in uids, f"connection source {src} should exist"
        for c in conns:
            assert c["destinationuid"] in uids, f"{src} should connect to an existing object"


def test_every_object_is_placed_on_the_canvas(workflow):
    missing = {o["uid"] for o in workflow["objects"]} - set(workflow["uidata"])
    assert not missing, f"objects without canvas position would be invisible: {missing}"


@pytest.mark.parametrize("keyword", ["kb", "kb:src", "kb:index-src", "kb:classify"])
def test_keywords_are_wired(workflow, keyword):
    assert any(o["config"].get("keyword") == keyword for o in workflow["objects"]), f"{keyword} should be a workflow entry point"

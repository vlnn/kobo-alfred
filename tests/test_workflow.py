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
    "alfred.workflow.utility.conditional": 1,
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    with PLIST.open("rb") as handle:
        return plistlib.load(handle)


def test_every_object_has_the_version_alfred_expects(workflow):
    for obj in workflow["objects"]:
        assert obj.get("version") == OBJECT_VERSIONS[obj["type"]], (
            f"{obj['uid']} should carry its object type's version, or Alfred calls the workflow incompatible"
        )


def test_connections_point_at_existing_objects(workflow):
    uids = {o["uid"] for o in workflow["objects"]}
    for src, conns in workflow["connections"].items():
        assert src in uids, f"connection source {src} should exist"
        for c in conns:
            assert c["destinationuid"] in uids, f"{src} should connect to an existing object"


def test_every_object_is_placed_on_the_canvas(workflow):
    missing = {o["uid"] for o in workflow["objects"]} - set(workflow["uidata"])
    assert not missing, f"objects without canvas position would be invisible: {missing}"


@pytest.mark.parametrize("keyword", ["kb", "kb:src", "kb:index", "kb:classify"])
def test_keywords_are_wired(workflow, keyword):
    assert any(o["config"].get("keyword") == keyword for o in workflow["objects"]), f"{keyword} should be a workflow entry point"


def test_plan_row_action_tells_apart_one_row_from_apply_all(workflow):
    script = next(o for o in workflow["objects"] if o["uid"] == "APPLY_ONE")["config"]["script"]
    assert 'apply --only "$1"' in script and '[ -z "$1" ]' in script, (
        "the plan row action should run the whole plan on an empty argument and say so"
    )


ROUTES = {
    "index": "INDEX_RUN",
    "apply": "APPLY_RUN",
    "undo": "UNDO_RUN",
    "apply-one": "APPLY_ONE",
    "classify": "GENRES",
    "import": "IMPORT_RUN",
}


def dispatch(workflow) -> tuple[dict, list[dict]]:
    plain = next(c for c in workflow["connections"]["SEARCH"] if c["modifiers"] == 0)
    obj = next(o for o in workflow["objects"] if o["uid"] == plain["destinationuid"])
    return obj, workflow["connections"][obj["uid"]]


def test_kb_enter_goes_through_an_action_dispatcher(workflow):
    obj, _ = dispatch(workflow)
    assert obj["type"] == "alfred.workflow.utility.conditional", "↩ on a kb row should be routed by the item's action variable"
    assert all(c["inputstring"] == "{var:action}" for c in obj["config"]["conditions"]), "every branch should test the action variable"


@pytest.mark.parametrize("action, destination", ROUTES.items())
def test_dispatcher_routes_each_command_action(workflow, action, destination):
    obj, conns = dispatch(workflow)
    branch = next(c for c in obj["config"]["conditions"] if c["matchstring"] == action)
    targets = [c["destinationuid"] for c in conns if c.get("sourceoutputuid") == branch["uid"]]
    assert targets == [destination], f"kb {action} should reach the same script as its kb:{action} keyword"


def test_dispatcher_else_opens_the_book(workflow):
    _, conns = dispatch(workflow)
    assert [c["destinationuid"] for c in conns if "sourceoutputuid" not in c] == ["OPEN"], (
        "anything that is not a command still opens the book"
    )


def test_index_src_keyword_is_gone(workflow):
    assert not any(o["config"].get("keyword") == "kb:index-src" for o in workflow["objects"]), "kb:index now covers the sources too"

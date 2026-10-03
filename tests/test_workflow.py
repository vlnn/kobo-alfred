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
    "update": "INDEX_RUN",
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


def test_sources_cannot_move_books(workflow):
    assert not any(o["uid"] == "IMPORT_MOVE_RUN" for o in workflow["objects"]), "import copies; there is no move action to reach"
    assert not any("import --move" in o["config"].get("script", "") for o in workflow["objects"]), "no script should move a source book"


def test_workflow_metadata_is_release_ready(workflow):
    import re

    pyproject = (PLIST.parent.parent / "pyproject.toml").read_text()
    assert workflow["version"] == re.search(r'^version = "(.+)"', pyproject, re.M).group(1), (
        "Alfred shows the plist version; it should match the package"
    )
    assert workflow["webaddress"].startswith("https://github.com/"), "the About panel should link to the repository"
    for keyword in ("kb:classify", "kb:lint", "kb:plan", "kb:src", "kb word"):
        assert keyword in workflow["readme"], f"the install readme should mention {keyword}"


def test_index_src_keyword_is_gone(workflow):
    assert not any(o["config"].get("keyword") == "kb:index-src" for o in workflow["objects"]), "kb:index now covers the sources too"


@pytest.fixture
def indexed(library: Path, tmp_path: Path, monkeypatch):
    from kobolib.cli import main

    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    main(["index"])


def route(workflow: dict, item: dict) -> str:
    obj, conns = dispatch(workflow)
    action = item.get("variables", {}).get("action", "")
    for condition in obj["config"]["conditions"]:
        if action.lower() == condition["matchstring"].lower():
            return next(c["destinationuid"] for c in conns if c.get("sourceoutputuid") == condition["uid"])
    return next(c["destinationuid"] for c in conns if "sourceoutputuid" not in c)


@pytest.mark.parametrize(
    "query, destination, arg",
    [
        ("update", "INDEX_RUN", ""),
        ("apply", "APPLY_RUN", ""),
        ("undo", "UNDO_RUN", ""),
        ("plan", "APPLY_ONE", ""),
        ("classify", "GENRES", ""),
        ("inbox", "OPEN", "/"),
        ("lint", "OPEN", "/"),
        ("rnd", "OPEN", "/"),
        ("deep", "OPEN", "/"),
    ],
)
def test_enter_on_a_kb_row_reaches_the_same_object_as_the_keyword(workflow, indexed, query, destination, arg):
    from kobolib.commands import search_items

    first = next(i for i in search_items(query) if i.get("valid", True))

    assert route(workflow, first) == destination, f"↩ on the first kb {query} row should reach {destination}"
    assert first["arg"].startswith(arg), f"kb {query} should hand {arg!r}… to {destination}"


KEYWORD_ACTIONS = {"kb:index": "update"}


def test_keyword_entry_points_and_kb_words_share_their_targets(workflow):
    by_keyword = {o["config"].get("keyword"): o["uid"] for o in workflow["objects"] if o["config"].get("keyword")}
    for keyword, uid in by_keyword.items():
        if keyword in ("kb:index", "kb:apply", "kb:undo"):
            target = workflow["connections"][uid][0]["destinationuid"]
            assert target == ROUTES[KEYWORD_ACTIONS.get(keyword, keyword.removeprefix("kb:"))], (
                f"{keyword} and kb {keyword.removeprefix('kb:')} should run the same script"
            )


MODIFIER_BITS = {"shift": 131072, "ctrl": 262144, "alt": 524288, "cmd": 1048576, "fn": 8388608, "alt+shift": 655360}
MEANING = {
    "REVEAL": ("reveal",),
    "COPY": ("copy",),
    "BROWSE": ("browse",),
    "FIX": ("set genre",),
    "APPLY_ONE": ("genre home", "apply all"),
    "IMPORT_RUN": ("import all",),
    "GENRES": ("classify all",),
}


def resolved(workflow: dict, target: str, item: dict, spec: dict) -> str:
    if target != "DISPATCH":
        return target
    merged = {**item, "variables": {**item.get("variables", {}), **spec.get("variables", {})}}
    return route(workflow, merged)


def modifier_targets(workflow: dict, uid: str) -> dict:
    return {c["modifiers"]: c["destinationuid"] for c in workflow["connections"][uid] if c["modifiers"]}


@pytest.fixture
def indexed_with_sources(library: Path, tmp_path: Path, tmp_path_factory, monkeypatch):
    from kobolib.cli import main
    from tests.test_sources import write_epub

    elsewhere = tmp_path_factory.mktemp("elsewhere")
    write_epub(elsewhere / "Slow Productivity.epub", "Slow Productivity")
    write_epub(elsewhere / "A World Without Email.epub", "A World Without Email")
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("KOBO_SOURCES", str(elsewhere))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    main(["index"])


@pytest.mark.parametrize(
    "filter_uid, items",
    [
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("")),
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("src slow")),
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("lint")),
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("plan")),
        ("SOURCES", lambda: __import__("kobolib.commands", fromlist=["sources_items"]).sources_items(["slow"])),
        ("INBOX", lambda: __import__("kobolib.commands", fromlist=["inbox_items"]).inbox_items([])),
        ("LINT", lambda: __import__("kobolib.commands", fromlist=["lint_items"]).lint_items()),
        ("RANDOM", lambda: __import__("kobolib.commands", fromlist=["random_items"]).random_items([])),
        ("CLASSIFY", lambda: __import__("kobolib.commands", fromlist=["classify_items"]).classify_items([])),
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("classify")),
        ("SEARCH", lambda: __import__("kobolib.commands", fromlist=["search_items"]).search_items("inbox")),
        ("PLAN", lambda: __import__("kobolib.commands", fromlist=["written_plan_items"]).written_plan_items()),
    ],
)
def test_declared_modifiers_do_what_their_subtitle_says(workflow, indexed_with_sources, filter_uid, items):
    targets = modifier_targets(workflow, filter_uid)
    rows = [i for i in items() if i.get("mods")]
    assert rows, f"{filter_uid} should produce rows with modifiers for this check to mean anything"
    for item in rows:
        for mod, spec in item["mods"].items():
            target = targets.get(MODIFIER_BITS[mod])
            assert target, f"{filter_uid}: {item['title']!r} declares {mod} but the filter has no {mod} connection"
            target = resolved(workflow, target, item, spec)
            assert any(word in spec["subtitle"].lower() for word in MEANING[target]), (
                f"{filter_uid}: {mod} on {item['title']!r} says {spec['subtitle']!r} but is wired to {target}"
            )


def test_import_all_head_row_reaches_the_import_script_from_kb(workflow, indexed_with_sources):
    from kobolib.commands import search_items

    head = next(i for i in search_items("src ") if i.get("valid", True))

    assert head["uid"] == "src:import-all", "kb src should start with the import-all row"
    assert route(workflow, head) == "IMPORT_RUN", "↩ on it must run the import script"

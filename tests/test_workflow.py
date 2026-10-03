import plistlib
import re
from pathlib import Path

import pytest

PLIST = Path(__file__).parent.parent / "workflow" / "info.plist"
OBJECT_VERSIONS = {
    "alfred.workflow.input.scriptfilter": 3,
    "alfred.workflow.action.script": 2,
    "alfred.workflow.output.notification": 1,
    "alfred.workflow.action.openfile": 1,
    "alfred.workflow.action.revealfile": 1,
    "alfred.workflow.utility.conditional": 1,
}
OBJECTS = {"KB", "PICKER", "DISPATCH", "OPEN", "REVEAL", "RUN", "NOTIFY", "CHOOSER", "CHOOSE"}
RUNNER_ACTIONS = ("update", "fix", "trash", "undo", "import", "genre", "ask", "dismiss", "embed")
ROUTES = {
    "update": "RUN",
    "fix": "RUN",
    "trash": "RUN",
    "undo": "RUN",
    "import": "RUN",
    "classify": "PICKER",
    "reveal": "REVEAL",
    "ask": "RUN",
    "genre": "RUN",
}
MODIFIER_BITS = {"shift": 131072, "alt": 524288}
MEANING = {"REVEAL": "reveal", "PICKER": "set genre"}


@pytest.fixture(scope="module")
def workflow() -> dict:
    with PLIST.open("rb") as handle:
        return plistlib.load(handle)


def obj(workflow: dict, uid: str) -> dict:
    return next(o for o in workflow["objects"] if o["uid"] == uid)


def targets(workflow: dict, uid: str) -> dict[int, str]:
    return {c["modifiers"]: c["destinationuid"] for c in workflow["connections"].get(uid, []) if "sourceoutputuid" not in c}


def test_every_object_has_the_version_alfred_expects(workflow):
    for o in workflow["objects"]:
        assert o.get("version") == OBJECT_VERSIONS[o["type"]], (
            f"{o['uid']} should carry its object type's version, or Alfred calls the workflow incompatible"
        )


def test_connections_point_at_existing_objects(workflow):
    uids = {o["uid"] for o in workflow["objects"]}
    for src, conns in workflow["connections"].items():
        assert src in uids, f"connection source {src} should exist"
        for c in conns:
            assert c["destinationuid"] in uids, f"{src} should connect to an existing object"


def test_every_object_is_placed_on_the_canvas(workflow):
    assert set(workflow["uidata"]) == {o["uid"] for o in workflow["objects"]}, "every object, and only those, should have a canvas position"


def test_the_workflow_is_one_filter_two_pickers_and_their_actions(workflow):
    assert {o["uid"] for o in workflow["objects"]} == OBJECTS, (
        "kb, the genre picker, the dispatcher, open, reveal, runner, notification, the model chooser and its step"
    )


def test_kb_is_the_only_keyword(workflow):
    keywords = [o["config"]["keyword"] for o in workflow["objects"] if o["config"].get("keyword")]
    assert keywords == ["kb"], "everything starts with kb; there are no kb:x keywords"


@pytest.mark.parametrize("uid, subcommand", [("KB", 'search "$1"'), ("PICKER", 'genres "$1"'), ("CHOOSER", 'chooser "$1"')])
def test_script_filters_call_their_subcommand(workflow, uid, subcommand):
    assert f"-m kobold {subcommand}" in obj(workflow, uid)["config"]["script"], f"{uid} should run kobold {subcommand}"


def dispatch(workflow) -> tuple[dict, list[dict]]:
    return obj(workflow, "DISPATCH"), workflow["connections"]["DISPATCH"]


def route(workflow: dict, item: dict) -> str:
    dispatcher, conns = dispatch(workflow)
    action = item.get("variables", {}).get("action", "")
    for condition in dispatcher["config"]["conditions"]:
        if action.lower() == condition["matchstring"].lower():
            return next(c["destinationuid"] for c in conns if c.get("sourceoutputuid") == condition["uid"])
    return next(c["destinationuid"] for c in conns if "sourceoutputuid" not in c)


def test_kb_keys_reach_dispatcher_reveal_and_picker(workflow):
    assert targets(workflow, "KB") == {0: "DISPATCH", 524288: "REVEAL", 131072: "PICKER"}, "↩ dispatches, ⌥↩ reveals, ⇧↩ sets genre"


def test_kb_enter_goes_through_an_action_dispatcher(workflow):
    dispatcher, _ = dispatch(workflow)
    assert dispatcher["type"] == "alfred.workflow.utility.conditional", "↩ on a kb row should be routed by the item's action variable"
    assert all(c["inputstring"] == "{var:action}" for c in dispatcher["config"]["conditions"]), "every branch should test the action"


@pytest.mark.parametrize("action, destination", ROUTES.items())
def test_dispatcher_routes_each_action(workflow, action, destination):
    dispatcher, conns = dispatch(workflow)
    branch = next(c for c in dispatcher["config"]["conditions"] if c["matchstring"] == action)
    assert [c["destinationuid"] for c in conns if c.get("sourceoutputuid") == branch["uid"]] == [destination], (
        f"the {action} action should reach {destination}"
    )


def test_dispatcher_else_opens_the_book(workflow):
    _, conns = dispatch(workflow)
    assert [c["destinationuid"] for c in conns if "sourceoutputuid" not in c] == ["OPEN"], "anything that is not a command opens the book"


def test_genre_picker_runs_the_genre_step_on_enter_and_shift(workflow):
    assert targets(workflow, "PICKER") == {0: "RUN", 131072: "RUN"}, "↩ applies a genre, ⇧↩ creates the typed one; both run the genre step"


def test_runner_notifies(workflow):
    assert targets(workflow, "RUN") == {0: "NOTIFY"}, "the runner's message should become a notification"


def test_model_chooser_runs_the_choose_step_in_the_foreground(workflow):
    assert targets(workflow, "CHOOSER") == {0: "CHOOSE"}, "↩ on a role writes the configuration"
    assert targets(workflow, "CHOOSE") == {0: "NOTIFY"}, "and the result becomes a notification"
    script = obj(workflow, "CHOOSE")["config"]["script"]
    assert 'choose "$1" "$model"' in script and "nohup" not in script, "choose runs in the foreground with the role and the model"


def runner_branch(workflow: dict, action: str) -> str:
    script = obj(workflow, "RUN")["config"]["script"]
    match = re.search(rf"^\s*{action}\) (.+?);;", script, re.M)
    assert match, f"the runner should have a branch for {action}"
    return match.group(1)


@pytest.mark.parametrize("action", RUNNER_ACTIONS)
def test_runner_runs_each_action_in_the_background(workflow, action):
    assert re.search(rf"run {action}\b", runner_branch(workflow, action)), f"the {action} branch should run kobold {action}"
    assert 'nohup /usr/bin/python3 -m kobold "$@" --notify' in obj(workflow, "RUN")["config"]["script"], (
        "every action should run detached and notify when done"
    )


@pytest.mark.parametrize(
    "action, args",
    [("fix", '"$1"'), ("trash", '"$1"'), ("import", '"$1"'), ("genre", '"$book" "$1"'), ("dismiss", '"$book"'), ("ask", '"" "$1"')],
)
def test_runner_passes_the_row_argument(workflow, action, args):
    assert runner_branch(workflow, action).startswith(f"run {action} {args}"), f"{action} should receive {args}"


def test_sources_cannot_move_books(workflow):
    assert not any("import --move" in o["config"].get("script", "") for o in workflow["objects"]), "no script should move a source book"


def test_workflow_metadata_is_release_ready(workflow):
    pyproject = (PLIST.parent.parent / "pyproject.toml").read_text()
    assert workflow["version"] == re.search(r'^version = "(.+)"', pyproject, re.M).group(1), (
        "Alfred shows the plist version; it should match the package"
    )
    assert workflow["webaddress"].startswith("https://github.com/"), "the About panel should link to the repository"
    for words in ("kb classify", "kb fix", "kb src", "kb update"):
        assert words in workflow["readme"], f"the install readme should mention {words}"
    assert ":" not in re.sub(r"https?://\S+", "", workflow["readme"]).replace(": ", " "), "the readme should not show kb:x keywords"


@pytest.fixture
def indexed(library: Path, tmp_path: Path, monkeypatch):
    from kobold.cli import main

    monkeypatch.setenv("KOBOLD_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBOLD_DATA", raising=False)
    main(["update"])


@pytest.mark.parametrize(
    "query, destination, arg",
    [
        ("update", "RUN", ""),
        ("fix", "RUN", ""),
        ("trash", "RUN", "/"),
        ("classify", "PICKER", ""),
        ("inbox", "OPEN", "/"),
        ("rnd", "OPEN", "/"),
        ("deep", "OPEN", "/"),
    ],
)
def test_enter_on_a_kb_row_reaches_its_action(workflow, indexed, query, destination, arg):
    from kobold.commands import search_items

    first = next(i for i in search_items(query) if i.get("valid", True))

    assert route(workflow, first) == destination, f"↩ on the first kb {query} row should reach {destination}"
    assert first["arg"].startswith(arg), f"kb {query} should hand {arg!r}… to {destination}"


def test_enter_on_a_problem_row_reveals_it(workflow, indexed):
    from kobold.commands import search_items

    problem = next(i for i in search_items("fix") if i.get("uid", "").startswith("problem:"))

    assert route(workflow, problem) == "REVEAL", "↩ on a problem with no automatic remedy should reveal the file"


@pytest.fixture
def indexed_with_sources(library: Path, tmp_path: Path, tmp_path_factory, monkeypatch):
    from kobold.cli import main
    from tests.test_sources import write_epub

    elsewhere = tmp_path_factory.mktemp("elsewhere")
    write_epub(elsewhere / "Slow Productivity.epub", "Slow Productivity")
    write_epub(elsewhere / "A World Without Email.epub", "A World Without Email")
    monkeypatch.setenv("KOBOLD_ROOT", str(library))
    monkeypatch.setenv("KOBOLD_SOURCES", str(elsewhere))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBOLD_DATA", raising=False)
    main(["update"])


@pytest.mark.parametrize("query", ["", "src slow", "fix", "inbox", "classify", "trash inbox", "dups", "rnd"])
def test_declared_modifiers_do_what_their_subtitle_says(workflow, indexed_with_sources, query):
    from kobold.commands import search_items

    keys = targets(workflow, "KB")
    for item in search_items(query):
        for mod, spec in item.get("mods", {}).items():
            target = keys.get(MODIFIER_BITS[mod])
            assert target, f"kb {query}: {item['title']!r} declares {mod} but kb has no {mod} connection"
            assert MEANING[target] in spec["subtitle"].lower(), f"kb {query}: {mod} says {spec['subtitle']!r} but reaches {target}"


def test_accept_suggested_genres_head_row_reaches_the_runner_from_kb(workflow, indexed, tmp_path, mocker):
    from kobold.commands import search_items
    from kobold.suggestions import SuggestionStore

    store = SuggestionStore(tmp_path / "alfred-data" / "oracle.tsv").load()
    store.set(next(i for i in search_items("napkin") if "quicklookurl" in i)["variables"]["book"], "genre", {"genre": "reference"}, "h")
    store.save()
    accept = next(i for i in search_items("classify") if i["uid"] == "classify:accept")

    assert route(workflow, accept) == "RUN", "↩ on Accept N suggested genres must run genre in the background, not open a book"


def test_import_all_head_row_reaches_the_runner_from_kb(workflow, indexed_with_sources):
    from kobold.commands import search_items

    head = next(i for i in search_items("src ") if i.get("valid", True))

    assert head["uid"] == "src:import-all", "kb src should start with the import-all row"
    assert route(workflow, head) == "RUN", "↩ on it must run the import in the background"


ORACLE_VARIABLES = (
    "KOBOLD_ORACLE_URL",
    "KOBOLD_ORACLE_MODEL",
    "KOBOLD_ORACLE_KEY",
    "KOBOLD_EMBED_URL",
    "KOBOLD_EMBED_MODEL",
    "KOBOLD_EMBED_KEY",
)


@pytest.mark.parametrize("variable", ORACLE_VARIABLES)
def test_the_oracle_is_configured_from_the_workflow_panel(workflow, variable):
    assert workflow["variables"].get(variable) == "", f"{variable} should default to empty, which keeps the oracle off"
    field = next(c for c in workflow["userconfigurationconfig"] if c["variable"] == variable)
    assert field["config"]["required"] is False and field["type"] == "textfield", f"{variable} is an optional text field"


def test_the_readme_mentions_the_oracle_commands(workflow):
    for words in ("kb like", "kb model"):
        assert words in workflow["readme"], f"the install readme should mention {words}"


def test_asking_and_embedding_on_update_is_an_optional_checkbox(workflow):
    assert workflow["variables"].get("KOBOLD_MODEL_ON_UPDATE") == "0", "off by default: kb update stays as fast as it is"
    field = next(c for c in workflow["userconfigurationconfig"] if c["variable"] == "KOBOLD_MODEL_ON_UPDATE")
    assert field["type"] == "checkbox" and field["config"]["default"] is False, "a checkbox in the configuration panel"

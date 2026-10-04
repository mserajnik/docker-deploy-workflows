# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The plan on fake GitHub and registry answers, for a configuration
modeled on mserajnik/tortoise-deploy: three variants, a shared database
image, and two targets."""

import datetime
import json
from typing import Any

import msgspec
import pytest
import yaml

from deploy_workflows import github, plan, scan
from deploy_workflows.config import Config, ConfigError, check

CONFIG = """
primary-source: core
sources:
  core: {repository: o/core, branch: main, cutoff: "CUTOFF"}
  mod: {repository: o/mod, branch: main, cutoff: "CUTOFF"}
  extra: {repository: o/extra, branch: main}
variants:
  base: {sources: [core], moving-tags: [latest]}
  plain: {sources: [core, extra], moving-tags: [edge]}
  bots: {sources: [core, mod], vars: {mods: "mod={url:mod}@{commit:mod}"}}
vars: {mods: ""}
migration-edits:
  targets:
    world:
      remedy: recreate
      sources:
        core: {migrations: [upd/*.sql]}
        mod: {migrations: [mod/world/*.sql]}
    character:
      remedy: manual
      sources:
        core: {migrations: [upd/char/*.sql]}
images:
  - name: server
    package: srv
    dockerfile: docker/server/Dockerfile
    tags: ["{variant}-{commit:core}", "{variant}"]
    build-args: {MODS: "{var:mods}"}
    oci: {title: t, description: d, base-name: b, licenses: l,
          version: "{commit:core}"}
  - name: database
    package: db
    dockerfile: docker/database/Dockerfile
    tags: ["{variant}-{commit:core}", "{variant}"]
    share: {base: [plain]}
    build-args: {EDITS: "{migration-edits}"}
    oci: {title: t, description: d, base-name: b, licenses: l,
          version: "{commit:core}"}
badges:
  - {file: build.json, variant: plain, label: L,
     message: "{variant}-{short-commit:core}", color: blue}
  - {file: date.json, label: D, message: "{timestamp}", color: orange}
""".replace("CUTOFF", "0" * 40)

COMMITS = {"o/core": "c" * 40, "o/mod": "d" * 40, "o/extra": "e" * 40}
NS = "io.github.owner.deploy"


def sha(char: str) -> str:
    return char * 40


def change(char: str, subject: str, status: str, path: str) -> scan.Commit:
    return scan.Commit(sha(char), subject, (scan.Change(status, (path,)),))


class FakeClones(scan.Clones):
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.logs = {
            "o/core": [
                change("6", "World before", "M", "upd/1.sql"),
                change("1", "World", "M", "upd/1.sql"),
                change("2", "Char", "D", "upd/char/1.sql"),
                change("3", "World again", "M", "upd/2.sql"),
                change("4", "Char again", "M", "upd/char/2.sql"),
            ],
            "o/mod": [change("5", "Mod", "M", "mod/world/1.sql")],
        }

    def log(self, repository: str, cutoff: str, tip: str) -> list[scan.Commit]:
        return self.logs[repository]

    def heads(
        self, repository: str, commits: list[scan.Commit]
    ) -> list[scan.Commit]:
        heads = {sha("1"), sha("3"), sha("5")}
        return [commit for commit in commits if commit.hash in heads]

    def files(self, repository: str, commit: str) -> list[str]:
        return self.paths


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], Any]:
    images: dict[tuple[str, str], Any] = {}
    monkeypatch.setattr(
        github, "resolve_commit", lambda repo, _: COMMITS[repo]
    )
    monkeypatch.setattr(
        github, "image_labels", lambda name, tag: images.get((name, tag))
    )
    return images


def make(
    event: str = "push",
    test_run: bool = False,
    force: bool = False,
    weekday: int = 2,
    rebuild_day: str | None = None,
) -> plan.Planner:
    data = yaml.safe_load(CONFIG)
    if rebuild_day is not None:
        data["rebuild-day"] = rebuild_day
    config = msgspec.convert(data, Config)
    check(config)
    settings = plan.Settings(
        repository="Owner/deploy",
        revision=sha("9"),
        event=event,
        force_rebuild=force,
        test_run=test_run,
        authors="a",
        vendor="v",
        now=datetime.datetime(2026, 9, 27, tzinfo=datetime.UTC)
        + datetime.timedelta(days=weekday),
    )
    planner = plan.Planner(config, settings)
    planner.clones = FakeClones()
    return planner


def current(*sources: str) -> dict[str, str]:
    return {
        f"{NS}.sources.{source}.revision": COMMITS[f"o/{source}"]
        for source in sources
    }


def legs(result: plan.Plan) -> list[list[str]]:
    return [[leg.id for leg in slot] for slot in result.slots]


def test_nothing_published_builds_everything(registry: dict) -> None:
    result = make().plan()
    assert legs(result) == [
        ["server-base", "server-plain", "server-bots"],
        ["database-base", "database-bots"],
        [],
    ]
    assert result.packages == ["srv", "db"]


def test_share_group_tags_are_the_union(registry: dict) -> None:
    shared = make().plan().slots[1][0]
    image = "ghcr.io/owner/db"
    assert shared.tags.split(",") == [
        f"{image}:base-{'c' * 40}",
        f"{image}:base",
        f"{image}:latest",
        f"{image}:plain-{'c' * 40}",
        f"{image}:plain",
        f"{image}:edge",
    ]
    assert shared.variants == "base,plain"
    assert f"{NS}.variant=base" in shared.labels.splitlines()
    assert f"{NS}.sources.extra.revision" not in shared.labels


def test_repeated_tags_keep_the_moving_tag_last(registry: dict) -> None:
    # A shared database like mserajnik/vmangos-deploy's: every member
    # repeats the commit tag, and the first variant adds a moving tag.
    planner = make()
    planner.config.images[1].tags = ["{commit:core}"]
    planner.config.variants["plain"].moving_tags = []
    shared = planner.plan().slots[1][0]
    assert shared.tags.split(",") == [
        f"ghcr.io/owner/db:{'c' * 40}",
        "ghcr.io/owner/db:latest",
    ]


def test_up_to_date_legs_skip_the_build(registry: dict) -> None:
    registry["owner/srv", "latest"] = current("core")
    registry["owner/srv", "bots"] = {
        **current("core"),
        f"{NS}.sources.mod.revision": sha("0"),
    }
    registry["owner/db", "edge"] = current("core")
    registry["owner/db", "bots"] = current("core")
    assert legs(make().plan()) == [
        ["server-plain", "server-bots"],
        ["database-bots"],
        [],
    ]


def test_build_reason_names_the_recorded_revision(
    registry: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    registry["owner/srv", "latest"] = {}
    registry["owner/srv", "bots"] = {
        **current("core"),
        f"{NS}.sources.mod.revision": sha("0"),
    }
    make().plan()
    out = capsys.readouterr().out
    assert (
        "'owner/srv:latest' has no revision label for 'core', which is at"
        f" {sha('c')}, so it builds."
    ) in out.splitlines()
    assert (
        f"'owner/srv:bots' records {sha('0')} for 'mod', which is at"
        f" {sha('d')}, so it builds."
    ) in out.splitlines()


def test_moving_tag_decides(registry: dict) -> None:
    # After an upstream rewind, an older commit tag matches again, while
    # the moving tag still points at the dropped commit's image.
    registry["owner/srv", f"base-{'c' * 40}"] = current("core")
    registry["owner/srv", "latest"] = {f"{NS}.sources.core.revision": sha("0")}
    assert "server-base" in legs(make().plan())[0]


def test_forced_and_default_rebuild_day_runs_build_everything(
    registry: dict,
) -> None:
    registry["owner/srv", "latest"] = current("core")
    assert "server-base" in legs(make(force=True).plan())[0]
    assert "server-base" in legs(make(event="schedule", weekday=1).plan())[0]
    assert "server-base" not in legs(make(event="schedule").plan())[0]
    assert "server-base" not in legs(make(weekday=1).plan())[0]


@pytest.mark.parametrize(
    ("rebuild_day", "weekday", "forced"),
    [
        ("monday", 1, True),
        ("tuesday", 2, True),
        ("wednesday", 3, True),
        ("thursday", 4, True),
        ("friday", 5, True),
        ("saturday", 6, True),
        ("sunday", 7, True),
        ("friday", 1, False),
        ("daily", 3, True),
        ("never", 1, False),
    ],
)
def test_rebuild_day_picks_the_forced_scheduled_runs(
    registry: dict, rebuild_day: str, weekday: int, forced: bool
) -> None:
    registry["owner/srv", "latest"] = current("core")
    planner = make(event="schedule", weekday=weekday, rebuild_day=rebuild_day)
    assert planner.settings.now.isoweekday() == weekday
    assert ("server-base" in legs(planner.plan())[0]) is forced
    pushed = make(weekday=weekday, rebuild_day=rebuild_day)
    assert "server-base" not in legs(pushed.plan())[0]


def test_wire_value_per_variant(registry: dict) -> None:
    result = make().plan()
    base, bots = result.slots[1]
    assert base.build_args == (
        f"EDITS=world:core@{sha('1')},core@{sha('3')}"
        f"|character:core@{sha('2')},core@{sha('4')}"
    )
    assert bots.build_args == (
        f"EDITS=world:core@{sha('1')},core@{sha('3')},mod@{sha('5')}"
        f"|character:core@{sha('2')},core@{sha('4')}"
    )


def test_labels_and_build_args(registry: dict) -> None:
    bots = make().plan().slots[0][2]
    labels = bots.labels.splitlines()
    pairs = [label.partition("=") for label in labels]
    oci = {
        key.removeprefix("org.opencontainers.image."): value
        for key, _, value in pairs
        if key.startswith("org.opencontainers.image.")
    }
    assert oci == {
        "created": "2026-09-29T00:00:00Z",
        "authors": "a",
        "url": "https://github.com/Owner/deploy",
        "documentation": "https://github.com/Owner/deploy#readme",
        "source": "https://github.com/Owner/deploy",
        "version": "c" * 40,
        "revision": "c" * 40,
        "vendor": "v",
        "licenses": "l",
        "ref.name": f"ghcr.io/owner/srv:bots-{'c' * 40}",
        "title": "t",
        "description": "d",
        "base.name": "b",
    }
    assert f"{NS}.revision={sha('9')}" in labels
    assert f"{NS}.variant=bots" in labels
    assert f"{NS}.sources.mod.repository=https://github.com/o/mod" in labels
    assert f"{NS}.sources.mod.revision={'d' * 40}" in labels
    assert (
        bots.build_args == f"MODS=mod=https://github.com/o/mod.git@{'d' * 40}"
    )
    assert bots.annotations.splitlines()[0].startswith("manifest:org.")
    assert bots.index_annotations.splitlines()[0].startswith("index:org.")


def test_test_run_uses_test_packages(registry: dict) -> None:
    registry["owner/srv", "latest"] = current("core")
    result = make(test_run=True).plan()
    assert "server-base" in legs(result)[0]
    assert result.slots[0][0].image == "ghcr.io/owner/srv-test"
    assert result.packages == ["srv-test", "db-test"]


def test_badges_update_when_anything_builds(registry: dict) -> None:
    registry.update(
        {
            ("owner/srv", tag): current("core", "mod", "extra")
            for tag in ("latest", "edge", "bots")
        }
    )
    registry["owner/db", "edge"] = current("core")
    badges = make().plan().badges
    assert [badge.file for badge in badges] == ["build.json", "date.json"]
    assert json.loads(badges[0].content)["message"] == f"plain-{'c' * 7}"
    registry["owner/db", "bots"] = current("core", "mod")
    idle = make().plan()
    assert (idle.badges, idle.packages) == ([], ["srv", "db"])


def test_unclaimed_files_fail(
    registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    planner = make()
    rules = planner.config.migration_edits.targets["world"].sources["core"]
    rules.claim = ["**/*.sql"]
    clones = FakeClones()
    clones.paths = ["upd/1.sql", "x/y.sql"]
    planner.clones = clones
    with pytest.raises(ConfigError, match=r"x/y\.sql"):
        planner.plan()


def test_variant_selects_repository_and_branch(
    registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github, "resolve_commit", lambda *ref: "@".join(ref))
    planner = make()
    planner.config.sources["core"].branch = "{variant}"
    planner.config.sources["extra"].repository = "o/extra-{variant}"
    assert planner.resolve("core", "base") == ("o/core", "o/core@base")
    assert planner.resolve("core", "bots") == ("o/core", "o/core@bots")
    assert planner.resolve("extra", "plain")[1] == "o/extra-plain@main"

# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Drift checks on fake upstream content.

The configuration is modeled on mserajnik/lost-city-rs-deploy, with
per-variant pins and file, absence, and tree checks.
"""

import msgspec
import pytest
import yaml

from deploy_workflows import drift, github
from deploy_workflows.config import Config, ConfigError

PIN = "a" * 40
LATEST = "b" * 40
CONFIG = f"""
primary-source: engine
sources:
  engine:
    repository: o/engine
    branch: "{{variant}}"
    pins: {{"274": "{PIN}", "254": "{PIN}"}}
variants: {{"274": {{}}, "254": {{}}}}
drift:
  upstreams:
    mariadb: {{repository: o/mariadb, branch: master, pin: "{PIN}"}}
  checks:
    - {{source: engine, files: [.gitignore], trees: [migrations]}}
    - {{source: engine, variants: ["254"], absent: [package-lock.json]}}
    - {{source: mariadb, files: [entrypoint.sh]}}
images: []
"""


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> dict:
    files: dict = {
        ("o/engine", PIN, ".gitignore"): b"db\n",
        ("o/engine", LATEST, ".gitignore"): b"db\n",
        ("o/mariadb", PIN, "entrypoint.sh"): b"x\n",
        ("o/mariadb", LATEST, "entrypoint.sh"): b"x\n",
    }
    trees: dict = {
        (PIN, "migrations"): ["m/1 s1"],
        (LATEST, "migrations"): ["m/1 s1"],
    }
    monkeypatch.setattr(
        github,
        "raw_file",
        lambda repo, commit, path: files.get((repo, commit, path)),
    )
    monkeypatch.setattr(
        github, "tree", lambda repo, commit, path: trees[commit, path]
    )
    changes = {
        ".gitignore": github.Commit(
            "f" * 40, github.CommitDetails("Old", github.Committer("2026-01"))
        ),
        "migrations": github.Commit(
            "e" * 40,
            github.CommitDetails(
                "Change\n\nbody", github.Committer("2026-02")
            ),
        ),
    }
    monkeypatch.setattr(
        github,
        "last_change",
        lambda repo, commit, path: (
            changes.get(path) if commit == LATEST else None
        ),
    )
    return {"files": files, "trees": trees}


def resolve(source: str, variant: str | None) -> tuple[str, str]:
    return ("o/mariadb" if variant is None else "o/engine"), LATEST


def config() -> Config:
    return msgspec.convert(yaml.safe_load(CONFIG), Config)


def test_no_drift(upstream: dict, capsys: pytest.CaptureFixture[str]) -> None:
    assert drift.run(config(), resolve) == []
    output = capsys.readouterr().out
    assert "OK: o/engine:package-lock.json (engine (254), absent)" in output


def test_same_pin_and_commit_is_checked_once(upstream: dict) -> None:
    subjects = drift.subjects(config(), config().drift.checks[0], resolve)
    assert [subject.name for subject in subjects] == ["engine (274, 254)"]


def test_same_pin_at_other_commits_is_checked_apart(upstream: dict) -> None:
    def apart(source: str, variant: str | None) -> tuple[str, str]:
        return "o/engine", LATEST if variant == "274" else PIN

    subjects = drift.subjects(config(), config().drift.checks[0], apart)
    assert [subject.latest for subject in subjects] == [LATEST, PIN]


def test_changed_file_absent_file_and_tree_drift(
    upstream: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    upstream["files"]["o/engine", LATEST, ".gitignore"] = b"db\nsaves\n"
    upstream["files"]["o/engine", LATEST, "package-lock.json"] = b"{}"
    upstream["trees"][LATEST, "migrations"] = ["m/1 s2"]
    failures = drift.run(config(), resolve)
    drifted = [
        line.split(" ")[1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("DRIFT:")
    ]
    assert drifted == [
        "o/engine:.gitignore",
        "o/engine:migrations",
        "o/engine:package-lock.json",
    ]
    assert len(failures) == 2
    assert failures[0].startswith(
        f"Suggested pin for 'engine (274, 254)': {'e' * 40} (Change)."
    )


def test_missing_pin_fails(upstream: dict) -> None:
    broken = config()
    broken.sources["engine"].pins.pop("254")
    with pytest.raises(ConfigError, match="no drift check pin"):
        drift.run(broken, resolve)


def test_undecodable_bytes_still_drift(upstream: dict) -> None:
    upstream["files"]["o/mariadb", PIN, "entrypoint.sh"] = b"\xe4\n"
    upstream["files"]["o/mariadb", LATEST, "entrypoint.sh"] = b"\xf6\n"
    assert drift.run(config(), resolve) == [
        "GitHub has no commit that touched the drifted paths of 'mariadb'."
    ]


def test_escaped_text_is_not_the_byte(upstream: dict) -> None:
    upstream["files"]["o/mariadb", PIN, "entrypoint.sh"] = b"a\\xff\n"
    upstream["files"]["o/mariadb", LATEST, "entrypoint.sh"] = b"a\xff\n"
    assert len(drift.run(config(), resolve)) == 1


def test_missing_tree_fails(upstream: dict) -> None:
    upstream["trees"][PIN, "migrations"] = []
    with pytest.raises(ConfigError, match="not a directory"):
        drift.run(config(), resolve)


def test_vanished_watched_file_fails(upstream: dict) -> None:
    del upstream["files"]["o/mariadb", LATEST, "entrypoint.sh"]
    with pytest.raises(
        ConfigError, match=f"at {LATEST}. Review the path and the pin"
    ):
        drift.run(config(), resolve)

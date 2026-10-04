# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The command line, with Docker, GitHub, and the planner faked."""

import argparse
import datetime
import json
import subprocess
import types
from pathlib import Path

import msgspec
import pytest

from deploy_workflows import __main__ as cli
from deploy_workflows import github
from deploy_workflows.plan import Leg

LEG = Leg(
    id="srv-a",
    variants="a",
    image="ghcr.io/owner/srv",
    package="srv",
    dockerfile="Dockerfile",
    tags="ghcr.io/owner/srv:a,ghcr.io/owner/srv:latest",
    build_args="",
    labels="",
    annotations="",
    index_annotations="index:k=v\nindex:l=w",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    recorded: dict[str, list] = {"run": [], "delete": []}

    def run(command: list[str], check: bool) -> None:
        recorded["run"].append(command)
        if recorded.get("fail"):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(
        github,
        "delete_untagged",
        lambda owner, package, digests: recorded["delete"].append(
            (owner, package, digests)
        ),
    )
    return recorded


def index(tmp_path: Path, *archs: str) -> int:
    for arch in archs:
        (tmp_path / arch).write_text(f"sha256:{arch}\n")
    args = argparse.Namespace(
        leg=msgspec.json.encode(LEG).decode(), digests=str(tmp_path)
    )
    return cli.run_index(args)


def test_index_joins_both_platforms(tmp_path: Path, calls: dict) -> None:
    assert index(tmp_path, "amd64", "arm64") == 0
    assert calls["run"] == [
        [
            "docker", "buildx", "imagetools", "create",
            "--tag", "ghcr.io/owner/srv:a",
            "--tag", "ghcr.io/owner/srv:latest",
            "--annotation", "index:k=v",
            "--annotation", "index:l=w",
            "ghcr.io/owner/srv@sha256:amd64",
            "ghcr.io/owner/srv@sha256:arm64",
        ]
    ]  # fmt: skip
    assert calls["delete"] == []


def test_missing_platform_removes_the_other(
    tmp_path: Path, calls: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    assert index(tmp_path, "arm64") == 1
    assert "has no image for amd64." in capsys.readouterr().err
    assert calls["run"] == []
    assert calls["delete"] == [("owner", "srv", ["sha256:arm64"])]


def test_no_platform_deletes_nothing(tmp_path: Path, calls: dict) -> None:
    assert index(tmp_path) == 1
    assert calls["delete"] == []


def test_failed_index_keeps_the_images(tmp_path: Path, calls: dict) -> None:
    calls["fail"] = True
    with pytest.raises(subprocess.CalledProcessError):
        index(tmp_path, "amd64", "arm64")
    assert calls["delete"] == []


def test_report_marks_annotations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    cli.report("error", "100% a\r\nb")
    assert capsys.readouterr().err == "::error::100%25 a%0D%0Ab\n"
    monkeypatch.delenv("GITHUB_ACTIONS")
    cli.report("warning", "a\nb")
    assert capsys.readouterr().err == "WARNING: a\nb\n"


@pytest.mark.parametrize("force", [True, False])
@pytest.mark.parametrize("organization", [True, False])
def test_drift_fails_the_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    force: bool,
    organization: bool,
) -> None:
    failed = cli.Plan([[LEG], [], []], ["srv", "db"], [], ["drift"])
    planned = []
    asked = []

    def plan(planner: cli.Planner) -> cli.Plan:
        planned.append(planner.settings)
        return failed

    def is_organization(owner: str) -> bool:
        asked.append(owner)
        return organization

    loaded = types.SimpleNamespace(retention="3w")
    monkeypatch.setattr(cli.config, "load", lambda path: loaded)
    monkeypatch.setattr(cli.Planner, "plan", plan)
    monkeypatch.setattr(github, "is_organization", is_organization)
    environment = {
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_REPOSITORY": "O/r",
        "GITHUB_SHA": "r",
        "GITHUB_EVENT_NAME": "schedule",
        "FORCE_REBUILD": str(force).lower(),
        "TEST_RUN": str(not force).lower(),
        "OCI_AUTHORS": "a",
        "OCI_VENDOR": "v",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    args = cli.parser().parse_args(["plan", "--config", str(tmp_path / "x")])
    assert cli.run_plan(args) == 1
    settings = planned[0]
    assert (settings.repository, settings.revision, settings.event) == (
        "O/r", "r", "schedule",
    )  # fmt: skip
    assert (settings.force_rebuild, settings.test_run) == (force, not force)
    assert (settings.authors, settings.vendor) == ("a", "v")
    assert settings.now.tzinfo is datetime.UTC
    slot_1, *rest = (tmp_path / "output").read_text().splitlines()
    assert set(json.loads(slot_1.removeprefix("slot-1="))[0]) == {
        "id", "variants", "image", "package", "dockerfile", "tags",
        "build-args", "labels", "annotations", "index-annotations",
    }  # fmt: skip
    assert rest == [
        "slot-2=[]", "slot-3=[]", "packages=srv db", "badges=[]",
        "retention=3w", f"retention-account={'o' if organization else 'user'}",
    ]  # fmt: skip
    assert asked == ["o"]


def test_badges_skip_without_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("BADGES_FTP_HOST", raising=False)
    assert cli.run_badges(argparse.Namespace(badges="[]")) == 0
    assert "so this run does not upload the badges." in capsys.readouterr().err

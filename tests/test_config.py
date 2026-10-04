# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Loading `.github/deploy.yaml`, and expanding its templates."""

from pathlib import Path

import pytest

from deploy_workflows.config import ConfigError, load
from deploy_workflows.templates import Scope, expand

MINIMAL = """
primary-source: core
sources:
  core: {repository: "o/core-{variant}", branch: main}
  extra: {repository: o/extra, branch: main}
variants:
  a: {}
  b: {sources: [core]}
images:
  - name: server
    package: server
    dockerfile: Dockerfile
    tags: ["{variant}"]
    oci: {title: t, description: d, base-name: b, licenses: l, version: v}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "deploy.yaml"
    path.write_text(text)
    return path


def test_minimal(tmp_path: Path) -> None:
    config = load(write(tmp_path, MINIMAL))
    assert config.variant_sources("a") == ["core", "extra"]
    assert config.variant_sources("b") == ["core"]
    assert config.retention == "2w"
    assert config.rebuild_day == "monday"


def test_unknown_rebuild_day_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="rebuild-day"):
        load(write(tmp_path, MINIMAL + "rebuild-day: mondays\n"))


def test_unknown_key_fails(tmp_path: Path) -> None:
    text = MINIMAL.replace("branch: main}", "branch: main, exlcude: x}", 1)
    with pytest.raises(ConfigError, match="exlcude"):
        load(write(tmp_path, text))


def test_yaml_syntax_error_fails(tmp_path: Path) -> None:
    text = MINIMAL.replace("branch: main}", "branch: main", 1)
    with pytest.raises(ConfigError, match="while parsing"):
        load(write(tmp_path, text))


def test_unquoted_numeric_variant_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="str"):
        load(
            write(
                tmp_path, MINIMAL.replace("  b: {sources", "  5875: {sources")
            )
        )


def test_malformed_pin_fails(tmp_path: Path) -> None:
    text = MINIMAL.replace("branch: main}", "branch: main, pin: abc}", 1)
    with pytest.raises(ConfigError, match="pin"):
        load(write(tmp_path, text))


def test_share_member_may_not_add_a_watched_source(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        'tags: ["{variant}"]', 'tags: ["{variant}"]\n    share: {b: [a]}'
    ) + (
        "migration-edits:\n  targets:\n    world:\n      remedy: recreate\n"
        "      sources: {extra: {migrations: ['*.sql']}}\n"
    )
    with pytest.raises(ConfigError, match="extra"):
        load(write(tmp_path, text))


@pytest.mark.parametrize(
    "extra",
    [
        "migration-edits:\n  targets:\n    world:\n      remedy: recreate\n"
        "      sources: {mdo: {}}\n",
        "badges:\n  - {file: f, label: l, message: m, color: c, variant: x}\n",
    ],
)
def test_unknown_name_fails(tmp_path: Path, extra: str) -> None:
    with pytest.raises(ConfigError, match="Unknown"):
        load(write(tmp_path, MINIMAL + extra))


def upstream(name: str) -> str:
    entry = f"{{repository: o/u, branch: main, pin: '{'0' * 40}'}}"
    return f"drift:\n  upstreams:\n    {name}: {entry}\n"


def test_source_and_drift_upstream_may_not_share_a_name(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ConfigError, match="'core' is the name of an entry of both"
    ):
        load(write(tmp_path, MINIMAL + upstream("core")))


def test_drift_upstream_with_its_own_name_loads(tmp_path: Path) -> None:
    load(write(tmp_path, MINIMAL + upstream("other")))


def test_variant_in_two_groups_fails(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        'tags: ["{variant}"]',
        'tags: ["{variant}"]\n    share: {a: [b], b: [a]}',
    )
    with pytest.raises(ConfigError, match="two share groups"):
        load(write(tmp_path, text))


def test_expand_every_placeholder() -> None:
    scope = Scope(
        variant="tbc",
        commits={"core": "1234567890" * 4},
        repositories={"core": "cmangos/mangos-tbc"},
        vars={"mods": "m={url:core}@{short-commit:core}"},
        migration_edits="world:",
        timestamp="2026-09-29T00:00:00Z",
    )
    template = "{variant} {commit:core} {var:mods} {migration-edits}"
    assert expand(template + " {timestamp}", scope) == (
        "tbc " + "1234567890" * 4
        + " m=https://github.com/cmangos/mangos-tbc.git@1234567"
        + " world: 2026-09-29T00:00:00Z"
    )  # fmt: skip


@pytest.mark.parametrize(
    "template",
    [
        "{commit:db}",
        "{bogus}",
        "{var:x}",
        "{migration-edits}",
        "{variant:x}",
        "{short_commit:core}",
        "{Variant}",
    ],
)
def test_expand_refuses_what_is_not_there(template: str) -> None:
    with pytest.raises(ConfigError):
        expand(template, Scope(variant="a", vars={}))


def test_var_cannot_refer_to_a_var() -> None:
    with pytest.raises(ConfigError):
        expand("{var:a}", Scope(vars={"a": "{var:b}", "b": "x"}))

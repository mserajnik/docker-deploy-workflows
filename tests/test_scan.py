# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The scan against small real repositories, cloned blobless over
`file://` with lazy fetches disabled."""

import subprocess
from pathlib import Path

import pytest

from deploy_workflows import scan
from deploy_workflows.config import ConfigError, Rules


class Upstream:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir()
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "uploadpack.allowFilter", "true")
        self.git("config", "uploadpack.allowAnySHA1InWant", "true")

    def git(self, *args: str) -> str:
        identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
        return subprocess.run(
            ["git", "-c", "commit.gpgSign=false", *identity, *args],
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(self, path: str, content: str) -> None:
        file = self.path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "--message", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    repository = Upstream(tmp_path / "upstream")
    repository.write("sql/base/world.sql", "base\n")
    repository.write("sql/updates/1.sql", "one\n")
    repository.commit("Start")
    return repository


def scan_log(upstream: Upstream, cutoff: str) -> list[scan.Commit]:
    clones = scan.Clones(url="file://{}")
    return clones.log(
        str(upstream.path), cutoff, upstream.git("rev-parse", "HEAD")
    )


WORLD = Rules(
    migrations=["sql/updates/*.sql"],
    base=["sql/base/*.sql"],
    exclude=["sql/base/skip.sql"],
)


def edit_subjects(
    upstream: Upstream, cutoff: str, rules: Rules = WORLD
) -> list[str]:
    return [
        c.subject for c in scan.edits(scan_log(upstream, cutoff), rules, "v")
    ]


def test_added_migration_is_no_edit(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("sql/updates/2.sql", "two\n")
    upstream.commit("Add a migration")
    assert edit_subjects(upstream, cutoff) == []


def test_modify_delete_and_rename_are_edits(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("sql/updates/1.sql", "changed\n")
    upstream.commit("Modify")
    upstream.git("mv", "sql/updates/1.sql", "sql/updates/9.sql")
    upstream.commit("Rename")
    upstream.git("mv", "sql/updates/9.sql", "elsewhere.sql")
    upstream.commit("Rename away")
    upstream.write("sql/updates/3.sql", "three\n")
    upstream.commit("Add")
    (upstream.path / "sql/updates/3.sql").unlink()
    (upstream.path / "sql/updates/3.sql").symlink_to("../../elsewhere.sql")
    upstream.commit("Typechange")
    upstream.git("rm", "--quiet", "sql/updates/3.sql")
    upstream.commit("Delete")
    assert edit_subjects(upstream, cutoff) == [
        "Modify",
        "Rename",
        "Rename away",
        "Typechange",
        "Delete",
    ]


def test_inexact_rename_reads_no_file_contents(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.git("mv", "sql/updates/1.sql", "moved.sql")
    upstream.write("moved.sql", "one\nmore\n")
    upstream.commit("Move and edit")
    assert edit_subjects(upstream, cutoff) == ["Move and edit"]


def test_added_base_file_is_an_edit_unless_excluded(
    upstream: Upstream,
) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("sql/base/skip.sql", "skip\n")
    upstream.commit("Add an excluded dump")
    upstream.write("sql/base/world2.sql", "new\n")
    upstream.commit("Add a dump")
    upstream.git("mv", "sql/base/skip.sql", "sql/base/world3.sql")
    upstream.commit("Move a dump in")
    assert edit_subjects(upstream, cutoff) == ["Add a dump", "Move a dump in"]


def test_unwatched_path_is_no_edit(upstream: Upstream) -> None:
    upstream.write("sql/updates/nested/1.sql", "deep\n")
    upstream.write("vendor/sql/updates/1.sql", "deep\n")
    cutoff = upstream.commit("Nested")
    upstream.write("sql/updates/nested/1.sql", "deeper\n")
    upstream.write("vendor/sql/updates/1.sql", "deeper\n")
    upstream.write("README", "x\n")
    upstream.commit("Unwatched")
    assert edit_subjects(upstream, cutoff) == []


def test_ordinary_merge_reports_the_side_commit_only(
    upstream: Upstream,
) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.git("checkout", "--quiet", "-b", "side")
    upstream.write("sql/updates/1.sql", "side\n")
    upstream.commit("Side edit")
    upstream.git("checkout", "--quiet", "main")
    upstream.write("other.txt", "x\n")
    upstream.commit("Main work")
    upstream.git("merge", "--quiet", "--no-ff", "side", "-m", "Merge")
    assert edit_subjects(upstream, cutoff) == ["Side edit"]


@pytest.mark.parametrize(
    ("kind", "change", "edits"),
    [
        ("edit", scan.Change("M", ("sql/updates/1.sql",) * 3), ["Evil merge"]),
        (
            "rename",
            scan.Change("M", ("sql/updates/1.sql",) * 2 + ("moved.sql",)),
            ["Evil merge"],
        ),
        ("add", scan.Change("A", ("sql/updates/2.sql",) * 3), []),
        (
            "side add",
            scan.Change("M", ("sql/updates/3.sql",) * 3),
            ["Evil merge"],
        ),
        (
            "main add",
            scan.Change("M", ("sql/updates/3.sql",) * 3),
            ["Evil merge"],
        ),
    ],
)
def test_evil_merge(
    upstream: Upstream, kind: str, change: scan.Change, edits: list[str]
) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.git("checkout", "--quiet", "-b", "side")
    upstream.write("side.txt", "x\n")
    if kind == "side add":
        upstream.write("sql/updates/3.sql", "added on the side\n")
    upstream.commit("Side work")
    upstream.git("checkout", "--quiet", "main")
    upstream.write("main.txt", "x\n")
    if kind == "main add":
        upstream.write("sql/updates/3.sql", "added on main\n")
    upstream.commit("Main work")
    upstream.git("merge", "--quiet", "--no-ff", "--no-commit", "side")
    if kind == "edit":
        upstream.write("sql/updates/1.sql", "resolved by hand\n")
    elif kind == "rename":
        upstream.git("mv", "sql/updates/1.sql", "moved.sql")
    elif kind == "add":
        upstream.write("sql/updates/2.sql", "added by hand\n")
    else:
        upstream.write("sql/updates/3.sql", "changed by hand\n")
    upstream.commit("Evil merge")
    [merge] = [
        c for c in scan_log(upstream, cutoff) if c.subject == "Evil merge"
    ]
    assert merge.changes == (change,)
    assert edit_subjects(upstream, cutoff) == edits


def test_separator_in_a_subject(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("sql/updates/1.sql", "edit\n")
    subject = "Fix sql\x01" + "0" * 40 + " world.sql"
    edit = upstream.commit(subject)
    [commit] = scan_log(upstream, cutoff)
    assert (commit.hash, commit.subject) == (edit, subject)


def test_heads_keep_an_edit_merged_in_behind(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.git("checkout", "--quiet", "-b", "side")
    upstream.write("sql/updates/1.sql", "side\n")
    upstream.commit("Side edit")
    upstream.git("checkout", "--quiet", "main")
    upstream.write("sql/base/world.sql", "old\n")
    upstream.commit("Old edit")
    upstream.write("sql/base/world.sql", "main\n")
    upstream.commit("Main edit")
    upstream.git("checkout", "--quiet", "side")
    upstream.git("merge", "--quiet", "--no-ff", "main", "-m", "Update branch")
    upstream.git("checkout", "--quiet", "main")
    upstream.git("merge", "--quiet", "--ff-only", "side")
    clones = scan.Clones(url="file://{}")
    repository = str(upstream.path)
    log = clones.log(repository, cutoff, upstream.git("rev-parse", "HEAD"))
    heads = clones.heads(repository, scan.edits(log, WORLD, "v"))
    assert sorted(c.subject for c in heads) == ["Main edit", "Side edit"]


def test_variant_placeholder_in_globs(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("acid/acid_v.sql", "x\n")
    upstream.write("acid/acid_other.sql", "x\n")
    upstream.commit("Add")
    upstream.write("acid/acid_other.sql", "y\n")
    upstream.commit("Edit other")
    upstream.write("acid/acid_v.sql", "y\n")
    upstream.commit("Edit own")
    rules = Rules(migrations=["acid/acid_{variant}.sql"])
    assert edit_subjects(upstream, cutoff, rules) == ["Edit own"]


def test_brace_in_a_glob_fails(upstream: Upstream) -> None:
    cutoff = upstream.git("rev-parse", "HEAD")
    upstream.write("sql/updates/1.sql", "edit\n")
    upstream.commit("Edit")
    rules = Rules(migrations=["sql/{updates,other}/*.sql"])
    with pytest.raises(ConfigError):
        edit_subjects(upstream, cutoff, rules)


def test_unclaimed_files(upstream: Upstream) -> None:
    upstream.write("sql/base/cn/x.sql", "x\n")
    upstream.write("sql/stray/x.sql", "x\n")
    upstream.write("sql/top.sql", "x\n")
    upstream.commit("Layout")
    clones = scan.Clones(url="file://{}")
    files = clones.files(str(upstream.path), "HEAD")
    rules = Rules(
        migrations=["sql/updates/*.sql"],
        base=["sql/base/*.sql"],
        exclude=["**/cn/**"],
        claim=["sql/**/*.sql"],
    )
    assert scan.unclaimed(files, [rules], "v") == [
        "sql/stray/x.sql",
        "sql/top.sql",
    ]


def test_log_depends_on_the_range(upstream: Upstream) -> None:
    head = upstream.git("rev-parse", "HEAD")
    later = upstream.commit("Later")
    clones = scan.Clones(url="file://{}")
    assert clones.log(str(upstream.path), head, head) == []
    assert len(clones.log(str(upstream.path), head, later)) == 1
    assert clones.log(str(upstream.path), later, later) == []


def test_clone_holds_no_file_contents(upstream: Upstream) -> None:
    clones = scan.Clones(url="file://{}")
    clone = clones.clone(str(upstream.path))
    assert scan.git("config", "remote.origin.promisor", cwd=clone).strip() == (
        "true"
    )
    with pytest.raises(subprocess.CalledProcessError):
        scan.git("cat-file", "-p", "HEAD:sql/updates/1.sql", cwd=clone)


def test_cutoff_outside_the_history_fails(upstream: Upstream) -> None:
    upstream.git("checkout", "--quiet", "-b", "gone")
    gone = upstream.commit("Rewritten away")
    upstream.git("checkout", "--quiet", "main")
    with pytest.raises(ConfigError, match="not in the history"):
        scan_log(upstream, gone)

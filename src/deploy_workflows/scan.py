# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The migration-edit scan over blobless clones, see
`docs/migration-edits.md`."""

import dataclasses
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from deploy_workflows.config import ConfigError, Rules
from deploy_workflows.templates import Scope, expand

# Only a change, a move, or a removal of a migration file counts,
# because a database applies a new one on its next start. It imports
# base files once, on creation, which makes an added base file count.
MIGRATION_STATUSES = frozenset("MRDT")
BASE_STATUSES = MIGRATION_STATUSES | {"A"}


@dataclasses.dataclass(frozen=True)
class Change:
    status: str
    paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Commit:
    hash: str
    subject: str
    changes: tuple[Change, ...]


def git(*args: str, cwd: Path | None = None) -> str:
    """The output of a `git` command, with lazy fetches turned off."""
    # A lazy fetch in a blobless clone is slow, and the scan reads paths
    # only. With this set, an accidental fetch is an error.
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout


class Clones:
    """One blobless clone per repository, kept for the run."""

    def __init__(self, url: str = "https://github.com/{}.git") -> None:
        self._url = url
        self._directory = tempfile.TemporaryDirectory()
        self._clones: dict[str, Path] = {}
        self._logs: dict[tuple[str, str, str], list[Commit]] = {}

    def clone(self, repository: str) -> Path:
        if repository not in self._clones:
            path = Path(self._directory.name) / str(len(self._clones))
            print(f"Cloning '{repository}'.")
            git(
                "clone",
                "--bare",
                "--filter=blob:none",
                "--quiet",
                self._url.format(repository),
                str(path),
            )
            self._clones[repository] = path
        return self._clones[repository]

    def log(self, repository: str, cutoff: str, tip: str) -> list[Commit]:
        """The commits of `cutoff..tip`, oldest first."""
        key = (repository, cutoff, tip)
        if key not in self._logs:
            clone = self.clone(repository)
            try:
                git("merge-base", "--is-ancestor", cutoff, tip, cwd=clone)
            except subprocess.CalledProcessError as error:
                # From a lost cutoff, every commit would count as new,
                # including edits the databases already have.
                raise ConfigError(
                    f"Cutoff {cutoff} is not in the history of {tip} in"
                    f" '{repository}'. Upstream has likely rewritten its"
                    " history. Pick a new cutoff on the current branch."
                ) from error
            output = git(
                "log",
                "-z",
                "--reverse",
                "--topo-order",
                "--format=%x01%H %s",
                "--name-status",
                "-M100%",
                "--cc",
                "--combined-all-paths",
                f"{cutoff}..{tip}",
                cwd=clone,
            )
            self._logs[key] = parse_log(output)
        return self._logs[key]

    def heads(self, repository: str, commits: list[Commit]) -> list[Commit]:
        """The commits among `commits` that no other one contains."""
        if not commits:
            return []
        output = git(
            "merge-base", "--independent", *(c.hash for c in commits),
            cwd=self.clone(repository),
        )  # fmt: skip
        return [c for c in commits if c.hash in output.split()]

    def files(self, repository: str, commit: str) -> list[str]:
        """Every file path at a commit."""
        output = git(
            "ls-tree", "-r", "-z", "--name-only", commit,
            cwd=self.clone(repository),
        )  # fmt: skip
        return [path for path in output.split("\0") if path]


def parse_log(output: str) -> list[Commit]:
    """The commits of `git log -z --name-status` output."""
    commits = []
    # Every header, status, and path is a field of its own, and a status
    # says how many paths follow it, so a separator in a subject or a
    # path never starts a record. A merge's list follows an empty field.
    fields = output.split("\0")
    index = 0
    while index < len(fields) and fields[index].startswith("\x01"):
        hash_, _, subject = fields[index][1:].partition(" ")
        index += 1
        if index < len(fields) and not fields[index]:
            index += 1
        changes = []
        while index < len(fields) and fields[index][:1] not in ("", "\x01"):
            status = fields[index].lstrip("\n")
            if status[0] in "RC" and status[1:].isdigit():
                letter, count = status[0], 2
            elif len(status) == 1:
                letter, count = status, 1
            else:
                # A merge lists the paths that differ from every parent,
                # with one status letter and one path per parent, then
                # its own path. A path every parent lacks counts as
                # added, any other as modified.
                letter = "A" if set(status) == {"A"} else "M"
                count = len(status) + 1
            paths = tuple(fields[index + 1 : index + 1 + count])
            changes.append(Change(letter, paths))
            index += 1 + count
        commits.append(Commit(hash_, subject, tuple(changes)))
    return commits


def matches(path: str, globs: list[str], variant: str) -> bool:
    return any(
        PurePosixPath(path).full_match(expand(glob, Scope(variant=variant)))
        for glob in globs
    )


def counts(change: Change, rules: Rules, variant: str) -> bool:
    """Whether a change is an edit that an existing database misses."""
    for path in change.paths:
        if matches(path, rules.exclude, variant):
            continue
        if change.status in MIGRATION_STATUSES and matches(
            path, rules.migrations, variant
        ):
            return True
        if change.status in BASE_STATUSES and matches(
            path, rules.base, variant
        ):
            return True
    return False


def edits(commits: list[Commit], rules: Rules, variant: str) -> list[Commit]:
    """The commits among `commits` that edit a watched file."""
    return [
        commit
        for commit in commits
        if any(counts(change, rules, variant) for change in commit.changes)
    ]


def unclaimed(files: list[str], rules: list[Rules], variant: str) -> list[str]:
    """Files a `claim` glob covers that no rule watches or excludes."""
    claims = [glob for rule in rules for glob in rule.claim]
    watched = [
        glob
        for rule in rules
        for glob in (*rule.migrations, *rule.base, *rule.exclude)
    ]
    return [
        path
        for path in files
        if matches(path, claims, variant)
        and not matches(path, watched, variant)
    ]


def require_cutoff(cutoff: str | None, source: str, variant: str) -> str:
    if cutoff is None:
        raise ConfigError(
            f"A target watches source '{source}', which has no cutoff for"
            f" variant '{variant}'."
        )
    return cutoff

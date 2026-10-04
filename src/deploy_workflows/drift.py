# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Drift checks: watched upstream files against their pinned commit."""

import dataclasses
import difflib
from collections.abc import Callable

from deploy_workflows import github
from deploy_workflows.config import Config, ConfigError, DriftCheck


@dataclasses.dataclass(frozen=True)
class Subject:
    """A repository to compare at its pin and at its resolved commit."""

    name: str
    repository: str
    pin: str
    latest: str


type Resolve = Callable[[str, str | None], tuple[str, str]]


def subjects(
    config: Config, check: DriftCheck, resolve: Resolve
) -> list[Subject]:
    """The comparisons of a check, one per distinct pin and commit."""
    if check.source in config.drift.upstreams:
        upstream = config.drift.upstreams[check.source]
        repository, latest = resolve(check.source, None)
        return [Subject(check.source, repository, upstream.pin, latest)]
    source = config.sources.get(check.source)
    if source is None:
        raise ConfigError(
            f"'{check.source}' is not the name of an entry of 'sources' or"
            " 'drift.upstreams'."
        )
    variants = check.variants or [
        variant
        for variant in config.variants
        if check.source in config.variant_sources(variant)
    ]
    found: dict[tuple[str, str, str], list[str]] = {}
    for variant in variants:
        pin = source.pins.get(variant) or source.pin
        if pin is None:
            raise ConfigError(
                f"Source '{check.source}' has no drift check pin for variant"
                f" '{variant}'."
            )
        repository, latest = resolve(check.source, variant)
        found.setdefault((repository, pin, latest), []).append(variant)
    return [
        Subject(
            f"{check.source} ({', '.join(names)})", repository, pin, latest
        )
        for (repository, pin, latest), names in found.items()
    ]


def fetch(subject: Subject, commit: str, path: str) -> bytes:
    content = github.raw_file(subject.repository, commit, path)
    if content is None:
        raise ConfigError(
            f"'{path}' does not exist in '{subject.repository}' at {commit}."
            " Review the path and the pin."
        )
    return content


def compare(subject: Subject, check: DriftCheck) -> list[str]:
    """Prints each difference and returns the paths that drifted."""
    drifted = []
    for path in check.files:
        known = fetch(subject, subject.pin, path)
        latest = fetch(subject, subject.latest, path)
        drifted += _report(subject, path, known, latest)
    for path in check.absent:
        if github.raw_file(subject.repository, subject.latest, path) is None:
            print(f"OK: {subject.repository}:{path} ({subject.name}, absent)")
        else:
            print(
                f"DRIFT: {subject.repository}:{path} ({subject.name}) now"
                " exists upstream."
            )
            drifted.append(path)
    for path in check.trees:
        known = github.tree(subject.repository, subject.pin, path)
        if not known:
            raise ConfigError(
                f"'{path}' is not a directory in '{subject.repository}' at"
                f" {subject.pin}. Review it and update the check."
            )
        latest = github.tree(subject.repository, subject.latest, path)
        drifted += _report(
            subject,
            path,
            ("\n".join(known) + "\n").encode(),
            ("\n".join(latest) + "\n").encode(),
        )
    return drifted


def _report(
    subject: Subject, path: str, known: bytes, latest: bytes
) -> list[str]:
    if known == latest:
        print(f"OK: {subject.repository}:{path} ({subject.name})")
        return []
    print(f"DRIFT: {subject.repository}:{path} ({subject.name}):")
    print(
        "".join(
            difflib.unified_diff(
                _lines(known),
                _lines(latest),
                f"{path}@{subject.pin}",
                f"{path}@{subject.latest}",
            )
        )
    )
    return [path]


def _lines(content: bytes) -> list[str]:
    # Only for printing: the comparison above uses the bytes, because
    # this decoding gives some different contents the same text.
    return content.decode(errors="backslashreplace").splitlines(keepends=True)


def suggest_pin(subject: Subject, paths: list[str]) -> str:
    """The newest commit at or before the resolved one that touched a
    drifted path, as a message line."""
    changes = [
        change
        for path in paths
        if (
            change := github.last_change(
                subject.repository, subject.latest, path
            )
        )
    ]
    if not changes:
        return (
            "GitHub has no commit that touched the drifted paths of"
            f" '{subject.name}'."
        )
    newest = max(changes, key=lambda change: change.commit.committer.date)
    title = newest.commit.message.partition("\n")[0]
    return (
        f"Suggested pin for '{subject.name}': {newest.sha} ({title})."
        " Check that it covers every drifted path. Changes on separate"
        " branches can need the commit that merges them."
    )


def run(config: Config, resolve: Resolve) -> list[str]:
    """Runs every check and returns one message per drifted subject."""
    failures = []
    for check in config.drift.checks:
        for subject in subjects(config, check, resolve):
            if drifted := compare(subject, check):
                failures.append(suggest_pin(subject, drifted))
    return failures

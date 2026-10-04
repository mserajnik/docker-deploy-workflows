# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The build plan: what builds, and every value its legs need."""

import dataclasses
import datetime
import json
from typing import assert_never

import msgspec

from deploy_workflows import drift, github, scan
from deploy_workflows.config import (
    Config,
    ConfigError,
    Image,
    Source,
    Upstream,
    pick,
)
from deploy_workflows.templates import Scope, expand

OCI = "org.opencontainers.image"
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclasses.dataclass(frozen=True)
class Settings:
    repository: str
    revision: str
    event: str
    force_rebuild: bool
    test_run: bool
    authors: str
    vendor: str
    now: datetime.datetime

    @property
    def owner(self) -> str:
        return self.repository.split("/")[0].lower()

    @property
    def namespace(self) -> str:
        return f"io.github.{self.owner}.{self.repository.split('/')[1]}"

    @property
    def timestamp(self) -> str:
        return self.now.strftime("%Y-%m-%dT%H:%M:%SZ")


class Leg(msgspec.Struct, rename="kebab"):
    """What the build and index jobs need for one leg."""

    id: str
    variants: str
    image: str
    package: str
    dockerfile: str
    tags: str
    build_args: str
    labels: str
    annotations: str
    index_annotations: str


class BadgeFile(msgspec.Struct):
    """A badge's file name and its rendered JSON."""

    file: str
    content: str


@dataclasses.dataclass
class Plan:
    slots: list[list[Leg]]
    packages: list[str]
    badges: list[BadgeFile]
    drift_failures: list[str]


class Planner:
    def __init__(self, config: Config, settings: Settings) -> None:
        self.config = config
        self.settings = settings
        self.clones = scan.Clones()
        self._commits: dict[tuple[str, str], str] = {}

    @property
    def build_everything(self) -> bool:
        """Whether this run is a forced rebuild."""
        day = self.config.rebuild_day
        today = WEEKDAYS[self.settings.now.weekday()]
        scheduled = self.settings.event == "schedule" and day in (
            "daily",
            today,
        )
        return self.settings.force_rebuild or scheduled

    def resolve(self, source: str, variant: str | None) -> tuple[str, str]:
        """The repository and resolved commit of a source for a variant,
        or of an entry of `drift.upstreams` when `variant` is `None`."""
        entry: Source | Upstream
        if variant is None:
            entry = self.config.drift.upstreams[source]
        else:
            entry = pick(self.config.sources, source, "source")
        where = Scope(variant=variant)
        repository = expand(entry.repository, where)
        branch = expand(entry.branch, where)
        if (repository, branch) not in self._commits:
            commit = github.resolve_commit(repository, branch)
            print(f"Resolved '{repository}' '{branch}' to {commit}.")
            self._commits[repository, branch] = commit
        return repository, self._commits[repository, branch]

    def scope(self, variant: str, migration_edits: str | None = None) -> Scope:
        sources = self.config.variant_sources(variant)
        resolved = {
            source: self.resolve(source, variant) for source in sources
        }
        return Scope(
            variant=variant,
            commits={
                source: commit for source, (_, commit) in resolved.items()
            },
            repositories={
                source: repo for source, (repo, _) in resolved.items()
            },
            vars={**self.config.vars, **self.config.variants[variant].vars},
            migration_edits=migration_edits,
            timestamp=self.settings.timestamp,
        )

    def package(self, image: Image, variant: str) -> str:
        package = expand(image.package, self.scope(variant))
        return package + "-test" if self.settings.test_run else package

    def is_up_to_date(self, image: Image, group: list[str], tag: str) -> bool:
        """Whether the image at `tag` records the current commits."""
        name = f"{self.settings.owner}/{self.package(image, group[0])}"
        labels = github.image_labels(name, tag)
        if labels is None:
            print(f"'{name}:{tag}' does not exist, so it builds.")
            return False
        for source, commit in self.scope(group[0]).commits.items():
            label = f"{self.settings.namespace}.sources.{source}.revision"
            recorded = labels.get(label)
            if recorded != commit:
                state = (
                    f"records {recorded}"
                    if recorded
                    else "has no revision label"
                )
                print(
                    f"'{name}:{tag}' {state} for '{source}', which is at"
                    f" {commit}, so it builds."
                )
                return False
        print(f"'{name}:{tag}' is up to date.")
        return True

    def migration_edits(self, variant: str) -> str:
        """The wire value, see `docs/migration-edits.md`."""
        sources = self.config.variant_sources(variant)
        entries = []
        for target_name, target in self.config.migration_edits.targets.items():
            found = []
            for source, rules in target.sources.items():
                if source not in sources:
                    continue
                self.check_claims(source, variant)
                repository, tip = self.resolve(source, variant)
                entry = self.config.sources[source]
                cutoff = scan.require_cutoff(
                    entry.cutoffs.get(variant) or entry.cutoff,
                    source,
                    variant,
                )
                commits = scan.edits(
                    self.clones.log(repository, cutoff, tip), rules, variant
                )
                match target.remedy:
                    case "recreate":
                        commits = self.clones.heads(repository, commits)
                    case "manual":
                        pass
                    case _:
                        assert_never(target.remedy)
                for commit in commits:
                    print(
                        f"Edit for '{target_name}' in '{variant}':"
                        f" {source}@{commit.hash} ({commit.subject})."
                    )
                found += [f"{source}@{commit.hash}" for commit in commits]
            entries.append(f"{target_name}:{','.join(found)}")
        return "|".join(entries)

    def check_claims(self, source: str, variant: str) -> None:
        repository, tip = self.resolve(source, variant)
        rules = [
            target.sources[source]
            for target in self.config.migration_edits.targets.values()
            if source in target.sources
        ]
        if not any(rule.claim for rule in rules):
            return
        files = self.clones.files(repository, tip)
        if stray := scan.unclaimed(files, rules, variant):
            listing = "".join(f"\n  {path}" for path in stray)
            raise ConfigError(
                "No rule watches or excludes these files in"
                f" '{repository}' at {tip}:{listing}\nWatch or exclude"
                " them before building."
            )

    def leg(self, image: Image, group: list[str]) -> Leg | None:
        """The leg of `image` for `group`, `None` when the image is up
        to date."""
        first = group[0]
        name = f"{self.settings.owner}/{self.package(image, first)}"
        reference = f"{github.REGISTRY}/{name}"
        tags: list[str] = []
        for variant in group:
            scope = self.scope(variant)
            tags += [expand(tag, scope) for tag in image.tags]
            tags += self.config.variants[variant].moving_tags
        tags = list(dict.fromkeys(tags))
        if not self.build_everything and self.is_up_to_date(
            image, group, tags[-1]
        ):
            return None
        uses_edits = any(
            "{migration-edits}" in value for value in image.build_args.values()
        )
        scope = self.scope(
            first, self.migration_edits(first) if uses_edits else None
        )
        oci = {
            "created": self.settings.timestamp,
            "authors": self.settings.authors,
            "url": f"https://github.com/{self.settings.repository}",
            "documentation": f"https://github.com/{self.settings.repository}"
            "#readme",
            "source": f"https://github.com/{self.settings.repository}",
            "version": expand(image.oci.version, scope),
            "revision": scope.commits[self.config.primary_source],
            "vendor": self.settings.vendor,
            "licenses": expand(image.oci.licenses, scope),
            "ref.name": f"{reference}:{tags[0]}",
            "title": expand(image.oci.title, scope),
            "description": expand(image.oci.description, scope),
            "base.name": expand(image.oci.base_name, scope),
        }
        ns = self.settings.namespace
        labels = [f"{OCI}.{key}={value}" for key, value in oci.items()]
        labels += [
            f"{ns}.revision={self.settings.revision}",
            f"{ns}.variant={first}",
        ]
        for source, commit in scope.commits.items():
            repository = scope.repositories[source]
            labels += [
                f"{ns}.sources.{source}.repository=https://github.com/{repository}",
                f"{ns}.sources.{source}.revision={commit}",
            ]
        return Leg(
            id=f"{image.name}-{first}",
            variants=",".join(group),
            image=reference,
            package=self.package(image, first),
            dockerfile=expand(image.dockerfile, scope),
            tags=",".join(f"{reference}:{tag}" for tag in tags),
            build_args="\n".join(
                f"{key}={expand(value, scope)}"
                for key, value in image.build_args.items()
            ),
            labels="\n".join(labels),
            annotations="\n".join(f"manifest:{label}" for label in labels),
            index_annotations="\n".join(f"index:{label}" for label in labels),
        )

    def badges(self) -> list[BadgeFile]:
        """The badge files, for a run that builds anything."""
        files = []
        for badge in self.config.badges:
            scope = (
                self.scope(badge.variant)
                if badge.variant is not None
                else Scope(timestamp=self.settings.timestamp)
            )
            content = {
                "schemaVersion": 1,
                "label": badge.label,
                "message": expand(badge.message, scope),
                "color": badge.color,
            }
            files.append(BadgeFile(badge.file, json.dumps(content)))
        return files

    def plan(self) -> Plan:
        failures = drift.run(self.config, self.resolve)
        if self.build_everything:
            print("This run is a forced rebuild, so every leg builds.")
        slots: list[list[Leg]] = [[], [], []]
        packages: list[str] = []
        for slot, image in enumerate(self.config.images):
            for group in self.config.groups(image):
                packages.append(self.package(image, group[0]))
                if leg := self.leg(image, group):
                    slots[slot].append(leg)
        badges = self.badges() if any(slots) else []
        return Plan(slots, list(dict.fromkeys(packages)), badges, failures)

# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The `.github/deploy.yaml` models, see `docs/deploy-yaml.md`."""

from pathlib import Path
from typing import Annotated, Literal

import msgspec
import yaml

type CommitHash = Annotated[str, msgspec.Meta(pattern="^[0-9a-f]{40}$")]

MAX_IMAGES = 3


class ConfigError(Exception):
    """A configuration that cannot describe a build."""


class Model(msgspec.Struct, forbid_unknown_fields=True, rename="kebab"):
    pass


class Source(Model):
    repository: str
    branch: str
    pin: CommitHash | None = None
    pins: dict[str, CommitHash] = {}
    cutoff: CommitHash | None = None
    cutoffs: dict[str, CommitHash] = {}


class Upstream(Model):
    repository: str
    branch: str
    pin: CommitHash


class Variant(Model):
    sources: list[str] | None = None
    moving_tags: list[str] = []
    vars: dict[str, str] = {}


class DriftCheck(Model):
    source: str
    variants: list[str] | None = None
    files: list[str] = []
    absent: list[str] = []
    trees: list[str] = []


class Drift(Model):
    upstreams: dict[str, Upstream] = {}
    checks: list[DriftCheck] = []


class Rules(Model):
    migrations: list[str] = []
    base: list[str] = []
    exclude: list[str] = []
    claim: list[str] = []


class Target(Model):
    remedy: Literal["recreate", "manual"]
    sources: dict[str, Rules]


class MigrationEdits(Model):
    targets: dict[str, Target]


class Oci(Model):
    title: str
    description: str
    base_name: str
    licenses: str
    version: str


class Image(Model):
    name: str
    package: str
    dockerfile: str
    tags: list[str]
    oci: Oci
    share: dict[str, list[str]] = {}
    build_args: dict[str, str] = {}


class Badge(Model):
    file: str
    label: str
    message: str
    color: str
    variant: str | None = None


class Config(Model):
    primary_source: str
    sources: dict[str, Source]
    variants: dict[str, Variant]
    images: list[Image]
    drift: Drift = msgspec.field(default_factory=Drift)
    migration_edits: MigrationEdits = msgspec.field(
        default_factory=lambda: MigrationEdits(targets={})
    )
    vars: dict[str, str] = {}
    badges: list[Badge] = []
    retention: str = "2w"
    rebuild_day: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "daily",
        "never",
    ] = "monday"

    def variant_sources(self, variant: str) -> list[str]:
        """The sources a variant builds from, in declaration order."""
        listed = pick(self.variants, variant, "variant").sources
        if listed is None:
            return list(self.sources)
        for name in listed:
            pick(self.sources, name, "source")
        return [name for name in self.sources if name in listed]

    def groups(self, image: Image) -> list[list[str]]:
        """The image's share groups, then its other variants alone."""
        grouped = [[first, *members] for first, members in image.share.items()]
        seen = [variant for group in grouped for variant in group]
        return grouped + [[v] for v in self.variants if v not in seen]


def pick[T](mapping: dict[str, T], name: str, what: str) -> T:
    """The entry `name` of `mapping`.

    Raises a `ConfigError` if there is none.
    """
    if name not in mapping:
        raise ConfigError(f"Unknown {what} '{name}'.")
    return mapping[name]


def load(path: Path) -> Config:
    """Reads and checks `.github/deploy.yaml`."""
    try:
        config = msgspec.convert(yaml.safe_load(path.read_text()), Config)
    except (msgspec.ValidationError, yaml.YAMLError) as error:
        raise ConfigError(f"'{path}': {error}") from error
    check(config)
    return config


def check(config: Config) -> None:
    """Rejects what the models cannot express."""
    pick(config.sources, config.primary_source, "source")
    if len(config.images) > MAX_IMAGES:
        raise ConfigError(
            f"A configuration can have at most {MAX_IMAGES} images."
        )
    if clashes := config.drift.upstreams.keys() & config.sources.keys():
        raise ConfigError(
            f"'{min(clashes)}' is the name of an entry of both 'sources'"
            " and 'drift.upstreams'. Rename one of them."
        )
    watched = {
        source
        for target in config.migration_edits.targets.values()
        for source in target.sources
    }
    for source in watched:
        pick(config.sources, source, "source")
    for badge in config.badges:
        if badge.variant is not None:
            pick(config.variants, badge.variant, "variant")
    for image in config.images:
        seen: set[str] = set()
        for group in config.groups(image):
            for variant in group:
                pick(config.variants, variant, "variant")
                if variant in seen:
                    raise ConfigError(
                        f"Variant '{variant}' is in two share groups of"
                        f" image '{image.name}'."
                    )
                seen.add(variant)
            # A member builds from the first variant's commits, so an
            # extra source that a target watches would lose its edits.
            first = set(config.variant_sources(group[0]))
            for member in group[1:]:
                extra = set(config.variant_sources(member)) - first
                if extra & watched:
                    sources = ", ".join(
                        f"'{name}'" for name in sorted(extra & watched)
                    )
                    raise ConfigError(
                        f"Variant '{member}' shares image '{image.name}'"
                        f" with '{group[0]}', but adds sources that a target"
                        f" watches: {sources}."
                    )

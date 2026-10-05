# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Template expansion of `{<name>}` and `{<name>:<argument>}`."""

import dataclasses
import re
from collections.abc import Mapping

from deploy_workflows.config import ConfigError

PLACEHOLDER = re.compile(r"\{([^{}:]+)(?::([^{}]*))?\}")
SHORT_COMMIT_LENGTH = 7


@dataclasses.dataclass(frozen=True)
class Scope:
    """The values a template may refer to in one place."""

    variant: str | None = None
    commits: Mapping[str, str] = dataclasses.field(default_factory=dict)
    repositories: Mapping[str, str] = dataclasses.field(default_factory=dict)
    vars: Mapping[str, str] | None = None
    migration_edits: str | None = None
    timestamp: str | None = None


def expand(template: str, scope: Scope) -> str:
    """The template with every placeholder replaced."""
    return PLACEHOLDER.sub(
        lambda match: _value(match, template, scope), template
    )


def _value(match: re.Match[str], template: str, scope: Scope) -> str:
    name, argument = match.group(1), match.group(2)
    value: str | None = None
    match name, argument:
        case "variant", None:
            value = scope.variant
        case "commit", str(source):
            value = scope.commits.get(source)
        case "short-commit", str(source):
            commit = scope.commits.get(source)
            value = commit and commit[:SHORT_COMMIT_LENGTH]
        case "url", str(source):
            repository = scope.repositories.get(source)
            value = repository and f"https://github.com/{repository}.git"
        case "var", str(var) if scope.vars is not None:
            if var not in scope.vars:
                raise ConfigError(f"Unknown var '{var}' in '{template}'.")
            # A var value is a template itself, and it may not use vars.
            value = expand(
                scope.vars[var], dataclasses.replace(scope, vars=None)
            )
        case "migration-edits", None:
            value = scope.migration_edits
        case "timestamp", None:
            value = scope.timestamp
    if value is None:
        raise ConfigError(
            f"Placeholder '{match.group(0)}' in '{template}' is unknown or"
            " not available here."
        )
    return value

# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The command line: `plan`, `index`, and `badges`."""

import argparse
import datetime
import ftplib
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import msgspec

from deploy_workflows import config, github
from deploy_workflows.plan import BadgeFile, Leg, Plan, Planner, Settings

ARCHITECTURES = ("amd64", "arm64")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "false") == "true"


def report(level: Literal["error", "warning"], message: str) -> None:
    """Prints an error or warning, also as a GitHub Actions annotation.

    This package prints every error and warning with it.
    """
    if env_flag("GITHUB_ACTIONS"):
        escaped = message.replace("%", "%25").replace("\r", "%0D")
        print(f"::{level}::{escaped.replace('\n', '%0A')}", file=sys.stderr)
    else:
        print(f"{level.upper()}: {message}", file=sys.stderr)


def run_plan(args: argparse.Namespace) -> int:
    path = Path(args.config)
    owner = args.repository.split("/")[0]
    revision = (
        args.revision
        or subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path.parent,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    settings = Settings(
        repository=args.repository,
        revision=revision,
        event=args.event,
        force_rebuild=args.force_rebuild,
        test_run=args.test_run,
        authors=os.environ.get("OCI_AUTHORS") or owner,
        vendor=os.environ.get("OCI_VENDOR") or owner,
        now=datetime.datetime.now(datetime.UTC),
    )
    loaded = config.load(path)
    plan = Planner(loaded, settings).plan()
    show(plan)
    account = (
        settings.owner if github.is_organization(settings.owner) else "user"
    )
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as file:
            for slot, legs in enumerate(plan.slots, start=1):
                file.write(
                    f"slot-{slot}={msgspec.json.encode(legs).decode()}\n"
                )
            file.write(f"packages={' '.join(plan.packages)}\n")
            file.write(f"badges={msgspec.json.encode(plan.badges).decode()}\n")
            file.write(f"retention={loaded.retention}\n")
            file.write(f"retention-account={account}\n")
    if plan.drift_failures:
        for failure in plan.drift_failures:
            print(failure, file=sys.stderr)
        report(
            "error",
            "Upstream drifted from the pinned commits. Review the"
            " differences above, adjust the repository where needed,"
            " and bump the pins in '.github/deploy.yaml'.",
        )
        return 1
    return 0


def show(plan: Plan) -> None:
    for slot, legs in enumerate(plan.slots, start=1):
        for leg in legs:
            print(f"\nImage slot {slot}: {leg.id} ({leg.variants})")
            print(f"Dockerfile: {leg.dockerfile}")
            fields = {
                "Tags": leg.tags.split(","),
                "Build arguments": leg.build_args.splitlines(),
                "Labels": leg.labels.splitlines(),
            }
            for title, lines in fields.items():
                print(f"{title}:")
                for line in lines:
                    print(f"  {line}")
    if not any(plan.slots):
        print("\nEvery image is up to date.")
    for badge in plan.badges:
        print(f"Badge {badge.file}: {badge.content}")


def run_index(args: argparse.Namespace) -> int:
    """Joins the per-architecture images into one index.

    Removes them again when one is missing.
    """
    leg = msgspec.json.decode(args.leg, type=Leg)
    directory = Path(args.digests)
    digests = [
        (directory / arch).read_text().strip()
        for arch in ARCHITECTURES
        if (directory / arch).is_file()
    ]
    if missing := [
        arch for arch in ARCHITECTURES if not (directory / arch).is_file()
    ]:
        # A failed `imagetools create` can leave tags on the index. Its
        # images then stay for retention.
        report(
            "error",
            f"Leg '{leg.id}' has no image for {' or '.join(missing)}.",
        )
        if digests:
            owner = leg.image.split("/")[1]
            github.delete_untagged(owner, leg.package, digests)
        return 1
    command = ["docker", "buildx", "imagetools", "create"]
    # `imagetools create` pushes the tags in order and stops at a failed
    # push. The up-to-date check reads the last tag, so a failed push
    # leaves it unchanged.
    for tag in leg.tags.split(","):
        command += ["--tag", tag]
    for annotation in leg.index_annotations.splitlines():
        command += ["--annotation", annotation]
    command += [f"{leg.image}@{digest}" for digest in digests]
    subprocess.run(command, check=True)
    return 0


def run_badges(args: argparse.Namespace) -> int:
    names = ("BADGES_FTP_HOST", "BADGES_FTP_USERNAME", "BADGES_FTP_PASSWORD")
    host, user, password = (os.environ.get(name) for name in names)
    if not (host and user and password):
        report(
            "warning",
            "Not all three badge FTP secrets are set, so this run does not"
            " upload the badges.",
        )
        return 0
    with ftplib.FTP(
        host, user, password, timeout=github.TIMEOUT_SECONDS
    ) as ftp:
        for badge in msgspec.json.decode(args.badges, type=list[BadgeFile]):
            print(f"Uploading '{badge.file}'.")
            ftp.storbinary(
                f"STOR {badge.file}", io.BytesIO(badge.content.encode())
            )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="deploy_workflows")
    commands = root.add_subparsers(required=True)

    plan = commands.add_parser("plan", help="print and output the build plan")
    plan.add_argument("--config", default=".github/deploy.yaml")
    plan.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
        required="GITHUB_REPOSITORY" not in os.environ,
        help="the caller repository, <owner>/<name>",
    )
    plan.add_argument("--revision", default=os.environ.get("GITHUB_SHA"))
    plan.add_argument(
        "--event",
        default=os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"),
    )
    plan.add_argument(
        "--force-rebuild",
        action="store_true",
        default=env_flag("FORCE_REBUILD"),
    )
    plan.add_argument(
        "--test-run", action="store_true", default=env_flag("TEST_RUN")
    )
    plan.set_defaults(run=run_plan)

    index = commands.add_parser("index", help="create a multi-platform index")
    index.add_argument("--leg", required=True)
    index.add_argument("--digests", required=True)
    index.set_defaults(run=run_index)

    badges = commands.add_parser("badges", help="upload badge files over FTP")
    badges.add_argument("--badges", required=True)
    badges.set_defaults(run=run_badges)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.run(args)
    except (config.ConfigError, github.HttpError) as error:
        report("error", str(error))
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        report("error", f"{error}{f' {detail}' if detail else ''}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

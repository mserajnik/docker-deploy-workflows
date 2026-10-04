# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP calls: GitHub's API, raw files, and the container registry."""

import base64
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import msgspec

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
REGISTRY = "ghcr.io"
TIMEOUT_SECONDS = 60
MANIFEST_TYPES = ",".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


# The fields of the JSON answers that this package reads. Decoding
# ignores every other field.


class Committer(msgspec.Struct):
    date: str


class CommitDetails(msgspec.Struct):
    message: str
    committer: Committer


class Commit(msgspec.Struct):
    sha: str
    commit: CommitDetails


class TreeEntry(msgspec.Struct):
    path: str
    type: str
    sha: str


class Tree(msgspec.Struct):
    truncated: bool
    tree: list[TreeEntry]


class User(msgspec.Struct):
    type: str


class ContainerMetadata(msgspec.Struct):
    tags: list[str] = []


class VersionMetadata(msgspec.Struct):
    container: ContainerMetadata = msgspec.field(
        default_factory=ContainerMetadata
    )


class PackageVersion(msgspec.Struct):
    id: int
    name: str
    metadata: VersionMetadata = msgspec.field(default_factory=VersionMetadata)


class RegistryToken(msgspec.Struct):
    token: str


class Platform(msgspec.Struct):
    architecture: str = ""


class Descriptor(msgspec.Struct):
    digest: str
    platform: Platform = msgspec.field(default_factory=Platform)


class Manifest(msgspec.Struct):
    """An image manifest, or an index with `manifests`."""

    manifests: list[Descriptor] = []
    config: Descriptor | None = None


class ContainerConfig(msgspec.Struct):
    labels: dict[str, str] | None = msgspec.field(default=None, name="Labels")


class ImageConfig(msgspec.Struct):
    config: ContainerConfig = msgspec.field(default_factory=ContainerConfig)


class HttpError(Exception):
    """An answer other than the ones a caller handles."""


def token() -> str:
    """The GitHub token from the environment, or from the `gh` login."""
    value = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if value:
        return value
    return subprocess.run(
        ["gh", "auth", "token"], check=True, capture_output=True, text=True
    ).stdout.strip()


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    allow: tuple[int, ...] = (),
) -> tuple[int, bytes]:
    """The status and body of a request; any status outside 2xx and
    `allow` raises `HttpError`."""
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as error:
        if error.code in allow:
            return error.code, error.read()
        raise HttpError(f"HTTP {error.code} for {method} {url}.") from error


def call(path: str, *, method: str = "GET") -> bytes:
    """The body of a GitHub API call's answer."""
    _, body = request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/vnd.github+json",
        },
        method=method,
    )
    return body


def api[T](path: str, answer: type[T]) -> T:
    """The JSON answer of a GitHub API call, decoded into `answer`."""
    return msgspec.json.decode(call(path), type=answer)


def resolve_commit(repository: str, branch: str) -> str:
    """The commit hash `branch` of `repository` points at."""
    ref = urllib.parse.quote(branch, safe="")
    return api(f"/repos/{repository}/commits/{ref}", Commit).sha


def raw_file(repository: str, commit: str, path: str) -> bytes | None:
    """A file's content at a commit, `None` when it does not exist."""
    url = f"{RAW}/{repository}/{commit}/{urllib.parse.quote(path)}"
    status, body = request(url, allow=(404,))
    return None if status == 404 else body


def tree(repository: str, commit: str, directory: str) -> list[str]:
    """A sorted line of path and blob hash per file in `directory`."""
    listing = api(f"/repos/{repository}/git/trees/{commit}?recursive=1", Tree)
    if listing.truncated:
        raise HttpError(
            f"The tree of '{repository}' at {commit} is truncated."
        )
    prefix = directory.rstrip("/") + "/"
    return sorted(
        f"{entry.path} {entry.sha}"
        for entry in listing.tree
        if entry.type == "blob" and entry.path.startswith(prefix)
    )


def last_change(repository: str, commit: str, path: str) -> Commit | None:
    """The newest commit at or before `commit` that touched `path`."""
    query = urllib.parse.urlencode(
        {"sha": commit, "path": path, "per_page": 1}
    )
    commits = api(f"/repos/{repository}/commits?{query}", list[Commit])
    return commits[0] if commits else None


def image_labels(name: str, tag: str) -> dict[str, str] | None:
    """The labels of the image behind `name:tag`, `None` when the
    package or the tag does not exist."""
    # With credentials, a missing package answers 404; anonymously, 403.
    _, body = request(
        f"https://{REGISTRY}/token?scope=repository:{name}:pull"
        f"&service={REGISTRY}",
        headers={"Authorization": _basic_auth()},
    )
    registry_token = msgspec.json.decode(body, type=RegistryToken).token
    auth = {"Authorization": f"Bearer {registry_token}"}
    status, body = request(
        f"https://{REGISTRY}/v2/{name}/manifests/{tag}",
        headers={**auth, "Accept": MANIFEST_TYPES},
        allow=(404,),
    )
    if status == 404:
        return None
    manifest = msgspec.json.decode(body, type=Manifest)
    # An index has no labels. Its first platform image has them.
    children = [
        child.digest
        for child in manifest.manifests
        if child.platform.architecture != "unknown"
    ]
    if children:
        _, body = request(
            f"https://{REGISTRY}/v2/{name}/manifests/{children[0]}",
            headers={**auth, "Accept": MANIFEST_TYPES},
        )
        manifest = msgspec.json.decode(body, type=Manifest)
    if manifest.config is None:
        raise HttpError(f"The image '{name}:{tag}' has no configuration.")
    _, body = request(
        f"https://{REGISTRY}/v2/{name}/blobs/{manifest.config.digest}",
        headers=auth,
    )
    return msgspec.json.decode(body, type=ImageConfig).config.labels or {}


def _basic_auth() -> str:
    credentials = base64.b64encode(f"x:{token()}".encode()).decode()
    return f"Basic {credentials}"


def is_organization(owner: str) -> bool:
    """Whether the account `owner` is an organization."""
    return api(f"/users/{owner}", User).type == "Organization"


def delete_untagged(owner: str, package: str, digests: list[str]) -> None:
    """Deletes the package versions for `digests` that have no tag."""
    base = f"/{'orgs' if is_organization(owner) else 'users'}/{owner}"
    endpoint = f"{base}/packages/container/{package}/versions"
    doomed = []
    page = 1
    while versions := api(
        f"{endpoint}?per_page=100&page={page}", list[PackageVersion]
    ):
        doomed += [
            version
            for version in versions
            if version.name in digests and not version.metadata.container.tags
        ]
        page += 1
    for version in doomed:
        print(f"Deleting untagged version {version.name}.")
        call(f"{endpoint}/{version.id}", method="DELETE")

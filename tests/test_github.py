# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The GitHub API calls, against a faked `call`."""

import json

import pytest

from deploy_workflows import github

VERSIONS = [
    {"id": 1, "name": "sha256:a", "metadata": {"container": {"tags": []}}},
    {"id": 2, "name": "sha256:b", "metadata": {"container": {"tags": ["x"]}}},
    {"id": 3, "name": "sha256:c", "metadata": {"container": {"tags": []}}},
]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, kind: str) -> list[tuple[str, str]]:
    recorded = []

    def call(path: str, *, method: str = "GET") -> bytes:
        recorded.append((method, path))
        if path == "/users/o":
            return json.dumps({"type": kind}).encode()
        if method == "DELETE":
            return b""
        return json.dumps(VERSIONS if path.endswith("page=1") else []).encode()

    monkeypatch.setattr(github, "call", call)
    return recorded


@pytest.mark.parametrize(
    ("kind", "organization"), [("Organization", True), ("User", False)]
)
def test_is_organization(
    calls: list[tuple[str, str]], kind: str, organization: bool
) -> None:
    assert github.is_organization("o") is organization
    assert calls == [("GET", "/users/o")]


@pytest.mark.parametrize(
    ("kind", "base"), [("Organization", "/orgs/o"), ("User", "/users/o")]
)
def test_delete_untagged(
    calls: list[tuple[str, str]], kind: str, base: str
) -> None:
    github.delete_untagged("o", "p", ["sha256:a", "sha256:b"])
    endpoint = f"{base}/packages/container/p/versions"
    assert calls == [
        ("GET", "/users/o"),
        ("GET", f"{endpoint}?per_page=100&page=1"),
        ("GET", f"{endpoint}?per_page=100&page=2"),
        ("DELETE", f"{endpoint}/1"),
    ]

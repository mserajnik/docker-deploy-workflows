# Development

## Dependencies

- [uv][uv], which installs Python 3.14 or later when it is missing
- [Git][git]
- [GitHub CLI][gh], logged in, for the plan below
- [dprint][dprint]
- [REUSE][reuse]
- [actionlint][actionlint], the maintained fork of upstream actionlint

## Checks

To run the tests, the linters, and the type checker, as this repository's
[lint workflow](../.github/workflows/lint.yaml) does:

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run ty check
dprint check
reuse lint
actionlint
```

Upstream actionlint does not know `job.workflow_repository` and
`job.workflow_sha` yet, and reports them, along with the `ubuntu-26.04`
runners, as false positives.

## Plan

Every build run starts with a plan job. It reads the caller repository's
`.github/deploy.yaml`, runs the drift checks, and works out which images to
build, with their tags, build arguments, and labels.

To print that plan for a caller repository against the real GitHub and
registry, without building or changing anything, run this from a checkout of
the caller repository:

```sh
PYTHONPATH=<path-to-docker-deploy-workflows>/src \
  uv run --project <path-to-docker-deploy-workflows> \
  python -m deploy_workflows plan --repository <owner>/<name>
```

## Version

The version in the [`pyproject.toml`](../pyproject.toml) stays `0.0.0`. The
workflows run the package from their own checkout, so the major version tag is
the only version.

[actionlint]: https://github.com/kjanat/actionlint
[dprint]: https://dprint.dev/
[gh]: https://cli.github.com/
[git]: https://git-scm.com/
[reuse]: https://reuse.software/
[uv]: https://docs.astral.sh/uv/

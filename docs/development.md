# Development

## Dependencies

- [uv][uv], for managing Python packages. It also installs Python 3.14 or later
  when it is missing.
- [GitHub CLI][gh], logged in, for the plan below.
- [kjanat/actionlint][actionlint], for linting the workflows. It is a
  maintained fork of actionlint that supports `ubuntu-26.04` runners,
  `job.workflow_repository`, and `job.workflow_sha`, all of which this
  repository uses.
- [REUSE][reuse], for checking the licensing of every file.
- [dprint][dprint], for formatting Markdown files.

## Checks

To run the same checks as this repository's
[lint workflow](../.github/workflows/lint.yaml):

```sh
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
actionlint
reuse lint
dprint check
```

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

docker-deploy-workflows has no version numbers besides its major version tags,
such as `v1`, which the [README](../README.md) describes. The workflows run the
package from their own checkout, so the version in
[`pyproject.toml`](../pyproject.toml) does not matter and stays `0.0.0`.

[actionlint]: https://github.com/kjanat/actionlint
[dprint]: https://dprint.dev/
[gh]: https://cli.github.com/
[reuse]: https://reuse.software/
[uv]: https://docs.astral.sh/uv/

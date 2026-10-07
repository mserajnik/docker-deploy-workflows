# Caller workflow reference

A caller repository uses docker-deploy-workflows through two workflows of its
own, which reference it at a major version tag, such as `v1`. The tag moves
with every compatible change, and a breaking change gets the next major
version. There are no minor or patch version tags.

The build workflow reads the build configuration from the caller repository's
`.github/deploy.yaml`, which the [`deploy.yaml` reference](deploy-yaml.md)
describes.

## Build

The build workflow plans the build, builds and publishes the images, deletes
old package versions, and uploads the badges. The calling job needs the
`contents: read` and `packages: write` permissions.

| Input           | Default | Description                                                    |
| --------------- | ------- | -------------------------------------------------------------- |
| `force-rebuild` | `false` | Rebuild every image, even when it is up to date.               |
| `test-run`      | `false` | Publish to `-test` packages and skip the badges and retention. |

The badge upload reads three repository secrets, which `secrets: inherit`
passes on. Without all three, the run skips the upload with a warning.

| Secret                | Description                      |
| --------------------- | -------------------------------- |
| `BADGES_FTP_HOST`     | The host name of the FTP server. |
| `BADGES_FTP_USERNAME` | The FTP user name.               |
| `BADGES_FTP_PASSWORD` | The FTP password.                |

Two repository variables set two of the pre-defined annotation keys. See the
[labels section](deploy-yaml.md#labels).

| Variable                 | Default              | Description                                      |
| ------------------------ | -------------------- | ------------------------------------------------ |
| `OCI_ANNOTATION_AUTHORS` | The repository owner | The value of `org.opencontainers.image.authors`. |
| `OCI_ANNOTATION_VENDOR`  | The repository owner | The value of `org.opencontainers.image.vendor`.  |

For example, a build workflow at `.github/workflows/build-docker-images.yaml`
could look like this:

```yaml
name: Build and push Docker images

on:
  # Build images daily.
  schedule:
    - cron: 0 0 * * *
  push:
    branches:
      - master
    paths:
      - .dockerignore
      - .github/deploy.yaml
      - .github/workflows/build-docker-images.yaml
      - docker/**
  pull_request:
    branches:
      - master
    paths:
      - .dockerignore
      - .github/deploy.yaml
      - .github/workflows/build-docker-images.yaml
      - docker/**
  workflow_dispatch:
    inputs:
      force-rebuild:
        type: boolean
        description: Rebuild every image, even when it is up to date.
        default: false
      test-run:
        type: boolean
        description: Publish to `-test` packages and skip the badges and retention.
        default: false

# Serialize runs so they cannot race on the moving tags and the cleanup.
concurrency:
  group: build-docker-images
  cancel-in-progress: false

jobs:
  build:
    name: Build
    uses: mserajnik/docker-deploy-workflows/.github/workflows/build.yaml@v1
    permissions:
      contents: read
      packages: write
    with:
      force-rebuild: ${{ inputs.force-rebuild || false }}
      test-run: ${{ inputs.test-run || false }}
    secrets: inherit
```

The build workflow refuses to re-run failed runs, except for runs that a pull
request triggered, which build the images without publishing them. A re-run
would reuse the results of the jobs that succeeded in the earlier attempt, such
as the plan, and those may no longer match the registry. To repair a failed
run, start a new one with `Run workflow` in the `Actions` tab, on the same
branch and with the same inputs, and with `force-rebuild` if the failed run was
a forced rebuild.

## Lint

The lint workflow checks the repository with `hadolint`, `shellcheck`, `shfmt`,
`docker compose config`, `reuse lint`, and `dprint check`. The caller
repository needs a dprint configuration file, because `dprint check` fails
without one. The inputs take paths relative to the repository root, one per
line.

| Input               | Default | Description                                                                                |
| ------------------- | ------- | ------------------------------------------------------------------------------------------ |
| `shell-exclude`     | None    | Shell scripts that shfmt and ShellCheck skip, such as a vendored entrypoint.               |
| `extra-dockerfiles` | None    | Dockerfiles with a name other than `Dockerfile`, which hadolint's recursive search misses. |
| `compose-files`     | None    | The files for `docker compose config` to validate. Without any, the check does not run.    |

The example lint workflow below, at `.github/workflows/lint.yaml`, sets two of
these inputs:

```yaml
name: Lint

on:
  push:
    branches:
      - master
  pull_request:

jobs:
  lint:
    name: Lint
    uses: mserajnik/docker-deploy-workflows/.github/workflows/shared-lint.yaml@v1
    with:
      shell-exclude: |
        docker/database/docker-entrypoint.sh
      compose-files: |
        compose.yaml.example
```

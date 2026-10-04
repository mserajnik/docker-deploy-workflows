# docker-deploy-workflows

[![Lint status][badge-lint-status]][badge-lint-status-url]

> GitHub Actions workflows for repositories that build and publish Docker
> images

docker-deploy-workflows is used by these repositories, which build Docker
images from upstream source code:

- [mserajnik/cmangos-deploy][cmangos-deploy]: a Docker setup for
  [CMaNGOS][cmangos], a server emulator that supports Vanilla (which CMaNGOS
  calls Classic), TBC, and WotLK.
- [mserajnik/vmangos-deploy][vmangos-deploy]: a Docker setup for
  [VMaNGOS][vmangos], a progressive Vanilla server emulator that aims to
  eventually support all versions from `1.2.4.4222` to `1.12.1.5875`.
- [mserajnik/tortoise-deploy][tortoise-deploy]: a Docker setup for
  [Tortoise-WoW][tortoise-wow], a community-driven restoration of Turtle WoW's
  `1.18.1.7272` patch with additions for solo play.
- [mserajnik/lost-city-rs-deploy][lost-city-rs-deploy]: a Docker setup for
  [Lost City RS][lost-city-rs], with an image for each fully playable version,
  from `225` to `274`.

Each of these projects uses docker-deploy-workflows to do some or all of the
following:

- Lint the shell scripts, Dockerfiles, Compose files, licensing, and Markdown
  of the repository.
- Decide which images to build. Each image records the commits it comes from in
  its labels, and a run builds it again once one of its sources has new
  commits.
- Watch upstream files that the Docker builds depend on, such as configuration
  templates or build dependencies. When one changes, the run fails and shows
  the difference. This makes it unnecessary to monitor upstream manually for
  changes that the Docker builds have to follow.
- Notice when upstream edits a database migration that existing databases have
  already applied, and pass the edit on to the database image, so the image can
  handle it appropriately.
- Build the images natively on `amd64` and `arm64`, publish each as one
  multi-platform image, and remove package versions older than a configurable
  age, two weeks by default.
- Upload status badges to an FTP server.

If your project has similar requirements, docker-deploy-workflows can serve as
a starting point. Use it as it is, or fork it and adjust it to your needs.

Callers reference a major version tag, such as `v1`, which moves with every
compatible change. A breaking change gets the next major version. There are no
minor or patch version tags.

## Quick start

1. Add the build and lint workflows to your repository, as the
   [caller workflow reference](docs/workflows.md) describes.
2. Create `.github/deploy.yaml`, as shown in the
   [`deploy.yaml` reference](docs/deploy-yaml.md).

## Documentation

- [Glossary](docs/glossary.md): the terms specific to docker-deploy-workflows.
  Read it first, because the other documents use these terms without explaining
  them.
- [Caller workflow reference](docs/workflows.md): every input, secret, and
  variable of the two workflows, and an example of each.
- [`deploy.yaml` reference](docs/deploy-yaml.md): every key, and a complete
  example.
- [Migration edits](docs/migration-edits.md): how a run detects upstream edits
  to applied migrations, and how a database image can handle them.
- [Development](docs/development.md): running the tests and linters, and
  previewing locally what a build would do for a caller repository.

## Maintainer

[Michael Serajnik][maintainer]

## Contribute

You are welcome to help out!

[Open an issue][issues] or [make a pull request][pull-requests].

## Licenses

- [`AGPL-3.0-or-later`][license-agpl-3.0-or-later] (Code)
- [`CC-BY-SA-4.0`][license-cc-by-sa-4.0] (Documentation)
- [`CC0-1.0`][license-cc0-1.0] (Configuration files)

This project follows the [REUSE specification][reuse-spec].

[badge-lint-status]: https://github.com/mserajnik/docker-deploy-workflows/actions/workflows/lint.yaml/badge.svg
[badge-lint-status-url]: https://github.com/mserajnik/docker-deploy-workflows/actions/workflows/lint.yaml
[cmangos]: https://github.com/cmangos
[cmangos-deploy]: https://github.com/mserajnik/cmangos-deploy
[issues]: https://github.com/mserajnik/docker-deploy-workflows/issues
[license-agpl-3.0-or-later]: LICENSES/AGPL-3.0-or-later.txt
[license-cc-by-sa-4.0]: LICENSES/CC-BY-SA-4.0.txt
[license-cc0-1.0]: LICENSES/CC0-1.0.txt
[lost-city-rs]: https://github.com/LostCityRS
[lost-city-rs-deploy]: https://github.com/mserajnik/lost-city-rs-deploy
[maintainer]: https://github.com/mserajnik
[pull-requests]: https://github.com/mserajnik/docker-deploy-workflows/pulls
[reuse-spec]: https://reuse.software/spec/
[tortoise-deploy]: https://github.com/mserajnik/tortoise-deploy
[tortoise-wow]: https://github.com/tortoise-wow/tortoise-wow
[vmangos]: https://github.com/vmangos/core
[vmangos-deploy]: https://github.com/mserajnik/vmangos-deploy

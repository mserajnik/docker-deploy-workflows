# `deploy.yaml` reference

A caller repository describes its whole build in its `.github/deploy.yaml`.
docker-deploy-workflows validates the file and rejects unknown keys and values
of the wrong type.

## Templates

These values are templates: an image's `package`, `dockerfile`, `tags`,
`build-args` values, and `oci` values, the values of `vars`, and a badge's
`message`. A placeholder is `{<name>}` or `{<name>:<argument>}`, and one that
is unknown, or unavailable in its place, fails the run.

| Placeholder               | Value                                                            |
| ------------------------- | ---------------------------------------------------------------- |
| `{variant}`               | The variant's name.                                              |
| `{commit:<source>}`       | The source's current commit, 40 characters.                      |
| `{short-commit:<source>}` | The same commit, 7 characters.                                   |
| `{url:<source>}`          | The source's clone URL, `https://github.com/<owner>/<name>.git`. |
| `{var:<name>}`            | The var's value, itself a template without further vars.         |
| `{migration-edits}`       | The variant's [wire value](migration-edits.md#the-wire-value).   |
| `{timestamp}`             | The run's start time, such as `2026-09-29T00:00:00Z`.            |

A source's `repository` and `branch`, and the globs of a watch rule, take
`{variant}` only. The message of a badge without `variant` takes `{timestamp}`
only. The `repository` and `branch` of an entry of `drift.upstreams` cannot
contain placeholders. A placeholder in any other value stays as written.

## Keys

| Key               | Default  | Description                                                                                                                                                                                                                                                                                                                                                                     |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `primary-source`  | Required | The name of the source whose commit is set as `org.opencontainers.image.revision`. Every variant has to build from it.                                                                                                                                                                                                                                                          |
| `sources`         | Required | The build sources, by name. See the [`sources` section](#sources).                                                                                                                                                                                                                                                                                                              |
| `variants`        | Required | The variants, by name. See the [`variants` section](#variants).                                                                                                                                                                                                                                                                                                                 |
| `vars`            | `{}`     | Default values for `{var:<name>}`.                                                                                                                                                                                                                                                                                                                                              |
| `drift`           | None     | The drift checks. See the [`drift` section](#drift).                                                                                                                                                                                                                                                                                                                            |
| `migration-edits` | None     | The migration-edit targets. See the [`migration-edits` section](#migration-edits).                                                                                                                                                                                                                                                                                              |
| `images`          | Required | Up to three images, in build order. See the [`images` section](#images).                                                                                                                                                                                                                                                                                                        |
| `badges`          | `[]`     | The badges, uploaded over FTP. See the [`badges` section](#badges).                                                                                                                                                                                                                                                                                                             |
| `retention`       | `2w`     | The age above which the build deletes a package version, as a [humantime duration](https://docs.rs/humantime/latest/humantime/fn.parse_duration.html) such as `3w` or `2w 3d`. Tagged versions count too, so set it to a value longer than the time between forced rebuilds.                                                                                                    |
| `rebuild-day`     | `monday` | The day, in UTC, on which a scheduled run is a forced rebuild, which also picks up updated base images and system packages. Takes a weekday name in lowercase, such as `friday`, `daily` for every scheduled run, or `never`. With `never`, an image that gets no new commits for longer than `retention` loses its versions, and is missing until a later run builds it again. |

### `sources`

Each source has:

| Key          | Default  | Description                                                                                                                                        |
| ------------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository` | Required | `<owner>/<name>` on GitHub.                                                                                                                        |
| `branch`     | Required | The branch the build follows.                                                                                                                      |
| `pin`        | None     | The drift check pin for every variant.                                                                                                             |
| `pins`       | `{}`     | Drift check pins by variant name, which replace `pin` for those variants.                                                                          |
| `cutoff`     | None     | The commit the migration-edit scan starts after, for every variant. A source that a target watches needs a cutoff from this key or from `cutoffs`. |
| `cutoffs`    | `{}`     | Cutoffs by variant name, which replace `cutoff` for those variants.                                                                                |

### `variants`

Quote a numeric variant name, such as `"5875"`. Each variant has:

| Key           | Default     | Description                                             |
| ------------- | ----------- | ------------------------------------------------------- |
| `sources`     | All sources | The names of the sources it builds from.                |
| `moving-tags` | `[]`        | Tags it adds to every image, such as `[latest]`.        |
| `vars`        | `{}`        | Vars that override the top-level ones of the same name. |

### `drift`

| Key         | Default | Description                                        |
| ----------- | ------- | -------------------------------------------------- |
| `upstreams` | `{}`    | Repositories that only drift checks read, by name. |
| `checks`    | `[]`    | The drift checks.                                  |

Each entry of `upstreams` has:

| Key          | Default  | Description                 |
| ------------ | -------- | --------------------------- |
| `repository` | Required | `<owner>/<name>` on GitHub. |
| `branch`     | Required | The branch the check reads. |
| `pin`        | Required | The drift check pin.        |

Each check has:

| Key        | Default                                 | Description                                                                         |
| ---------- | --------------------------------------- | ----------------------------------------------------------------------------------- |
| `source`   | Required                                | The name of an entry of `sources` or of `upstreams`.                                |
| `variants` | The variants that build from the source | The names of the variants whose pins the check compares, for an entry of `sources`. |
| `files`    | `[]`                                    | Files whose content the check compares.                                             |
| `absent`   | `[]`                                    | Paths that must not exist.                                                          |
| `trees`    | `[]`                                    | Directories whose files and their content the check compares.                       |

### `migration-edits`

See the [migration edits documentation](migration-edits.md) for what the keys
do.

| Key       | Default  | Description                                                    |
| --------- | -------- | -------------------------------------------------------------- |
| `targets` | Required | The targets, by name. The wire value lists them in this order. |

Each target has:

| Key       | Default  | Description                                                                             |
| --------- | -------- | --------------------------------------------------------------------------------------- |
| `remedy`  | Required | `recreate` or `manual`.                                                                 |
| `sources` | Required | A watch rule per source name, with any of `migrations`, `base`, `exclude`, and `claim`. |

### `images`

Each image has:

| Key          | Default  | Description                                                                                                                                                                                                                                                                                       |
| ------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`       | Required | A short name for the logs and job names.                                                                                                                                                                                                                                                          |
| `package`    | Required | The package name under the repository owner.                                                                                                                                                                                                                                                      |
| `dockerfile` | Required | The Dockerfile path.                                                                                                                                                                                                                                                                              |
| `tags`       | Required | Tag templates. A leg lists these and then the moving tags, for each of its variants. List the tag with the commit first, because `org.opencontainers.image.ref.name` names it, and end with a tag without the commit, such as `{variant}`, because the up-to-date check reads the leg's last tag. |
| `share`      | `{}`     | Share groups, `{<first>: [<member>...]}`, where `<first>` and each `<member>` are variant names. A member may only add sources that no target watches.                                                                                                                                            |
| `build-args` | `{}`     | Build arguments by name.                                                                                                                                                                                                                                                                          |
| `oci`        | Required | `title`, `description`, `base-name`, `licenses`, and `version`, all required and all templates. See the [labels section](#labels).                                                                                                                                                                |

### `badges`

The badges update when anything built and retention completed successfully.
Each badge has:

| Key       | Default  | Description                                             |
| --------- | -------- | ------------------------------------------------------- |
| `file`    | Required | The name of the badge file.                             |
| `label`   | Required | The badge's label.                                      |
| `message` | Required | The badge's message.                                    |
| `color`   | Required | The badge's color.                                      |
| `variant` | None     | The name of the variant whose values the message takes. |

## Labels

The build adds most of the OCI image specification's
[pre-defined annotation keys](https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys)
to each image: as manifest and index annotations, as the specification intends,
and also as labels, which Docker reads from the image configuration. `authors`
and `vendor` come from the `OCI_ANNOTATION_AUTHORS` and `OCI_ANNOTATION_VENDOR`
repository variables, and fall back to the repository owner. With `<namespace>`
standing for `io.github.<owner>.<name>`, with the owner in lowercase, the build
also adds these labels:

- `<namespace>.revision`: the caller repository's commit.
- `<namespace>.variant`: the name of the leg's first variant.
- `<namespace>.sources.<source>.repository` and
  `<namespace>.sources.<source>.revision`: one pair per source the image builds
  from. The up-to-date check compares the revisions.

## Complete example

This example `.github/deploy.yaml` is based on the
[mserajnik/tortoise-deploy](https://github.com/mserajnik/tortoise-deploy)
configuration at one point in time, and does not follow later changes there.

```yaml
primary-source: core

sources:
  core:
    repository: tortoise-wow/tortoise-wow
    branch: main
    pin: 57abad6f33bffbeb0019b17101d605125a45a40b
    cutoff: 7efe82e09c2dfa7d00b96dd20eb12e0496f4ab61
  autoscale:
    repository: Penqle/tw-mod-autoscale
    branch: main
    pin: 8675af22569674d906479aec0d7883d13d9212bb
  leech:
    repository: Penqle/tw-mod-leech
    branch: master
    pin: a3667c2c672b885fddc5afd76e48471dafa4eccc
  tortoisebots:
    repository: Sagiroth/TortoiseBots
    branch: main
    pin: 1bfadef54949d1694434f72491b5efd66a0e1bb5
    cutoff: 8c4fbc9f7d3713bb7a58ce4890efbddaadfc892e

variants:
  base:
    sources: [core]
    moving-tags: [latest]
  modules:
    sources: [core, autoscale, leech]
    vars:
      modules: "tw-mod-autoscale={url:autoscale}@{commit:autoscale}|tw-mod-leech={url:leech}@{commit:leech}"
      module-configs: modules/tw-mod-autoscale.conf,modules/tw-mod-leech.conf
      server-licenses: AGPL-3.0-only AND AGPL-3.0-or-later AND GPL-2.0-or-later AND MIT
  modules-bots:
    sources: [core, autoscale, leech, tortoisebots]
    vars:
      modules: "tw-mod-autoscale={url:autoscale}@{commit:autoscale}|tw-mod-leech={url:leech}@{commit:leech}|TortoiseBots={url:tortoisebots}@{commit:tortoisebots}"
      module-configs: aiplayerbot.conf,modules/tortoise_bots.conf,modules/tw-mod-autoscale.conf,modules/tw-mod-leech.conf
      module-sql-modules: TortoiseBots
      module-build-packages: libboost-dev libboost-filesystem-dev
      server-licenses: AGPL-3.0-only AND AGPL-3.0-or-later AND GPL-2.0-or-later AND MIT

vars:
  modules: ""
  module-configs: ""
  module-sql-modules: ""
  module-build-packages: ""
  server-licenses: AGPL-3.0-only AND AGPL-3.0-or-later AND GPL-2.0-or-later

drift:
  upstreams:
    mariadb:
      repository: MariaDB/mariadb-docker
      branch: master
      pin: 063eb10da092170beea08d2c629b6eb79d28cceb
  checks:
    - source: core
      files: [CMakeLists.txt, sql/base/tw_world_migrations.sql, sql/create_databases.sql, src/mangosd/mangosd.conf.dist.in, src/realmd/realmd.conf.dist.in, tools/dbc_verification/dbc_verifier.py]
    - {source: autoscale, files: [conf/tw-mod-autoscale.conf.dist]}
    - {source: leech, files: [conf/tw-mod-leech.conf.dist]}
    - {source: tortoisebots, files: [ai/playerbot/aiplayerbot.conf.dist.in, conf/tortoise_bots.conf.dist]}
    - {source: mariadb, files: [12.3/docker-entrypoint.sh]}

migration-edits:
  targets:
    world:
      remedy: recreate
      sources:
        core:
          migrations: [sql/database_updates/*.sql, sql/database_updates/world/*.sql]
          base: [sql/base/tw_world_*.sql]
          exclude: [sql/base/tw_world_migrations.sql, sql/database_updates/*/cn/*.sql]
          claim: [sql/base/**/*.sql, sql/database_updates/**/*.sql]
        tortoisebots:
          migrations: [data/sql/world/*.sql]
          claim: [data/sql/**/*.sql]
    character:
      remedy: manual
      sources:
        core: {migrations: [sql/database_updates/character/*.sql]}
        tortoisebots: {migrations: [data/sql/char/*.sql]}

images:
  - name: server
    package: tortoise-server
    dockerfile: docker/server/Dockerfile
    tags: ["{variant}-{commit:core}", "{variant}"]
    build-args:
      TORTOISE_REVISION: "{commit:core}"
      TORTOISE_FAIL_ON_PATCH_ERROR: "1"
      TORTOISE_MODULES: "{var:modules}"
      TORTOISE_MODULE_CONFIGS: "{var:module-configs}"
      TORTOISE_MODULE_SQL_MODULES: "{var:module-sql-modules}"
      TORTOISE_MODULE_BUILD_PACKAGES: "{var:module-build-packages}"
    oci:
      title: tortoise-deploy - Tortoise-WoW server image
      description: Tortoise-WoW is an open-source restoration of Turtle WoW 1.18.1.7272.
      base-name: ubuntu:26.04
      licenses: "{var:server-licenses}"
      version: "{commit:core}"
  - name: database
    package: tortoise-database
    dockerfile: docker/database/Dockerfile
    tags: ["{variant}-{commit:core}", "{variant}"]
    share: {base: [modules]}
    build-args:
      TORTOISE_REVISION: "{commit:core}"
      TORTOISE_MIGRATION_EDITS: "{migration-edits}"
    oci:
      title: tortoise-deploy - Tortoise-WoW database image
      description: Database for the Tortoise-WoW server.
      base-name: mariadb:12.3
      licenses: AGPL-3.0-only AND AGPL-3.0-or-later AND GPL-2.0-only AND GPL-2.0-or-later
      version: "{commit:core}"

badges:
  - {file: build-badge.json, variant: base, label: Latest Tortoise-WoW build, message: "{short-commit:core}", color: blue}
  - {file: date-badge.json, label: Latest build date, message: "{timestamp}", color: orange}
```

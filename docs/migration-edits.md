# Migration edits

A deployment applies upstream's migrations forward: a new migration file runs
on the next start. When upstream edits, renames, or deletes a migration that an
existing database has already applied, the database cannot pick up the change
by itself. An existing database also misses every change to a base file, a new
one included. Commits with such changes are migration edits, and
docker-deploy-workflows passes them to the database image, so the image can
handle them appropriately.

## The scan

Every run that builds a database image for a variant rescans each source that a
target watches, from the source's cutoff to its current commit, in a blobless
clone. A commit counts for a target when it changes a file that the target's
watch rule covers:

- A file that `migrations` matches counts when upstream modifies, renames, or
  deletes it, or changes its type. Both paths of a rename count.
- A file that `base` matches also counts when upstream adds it.
- A file that `exclude` matches never counts.
- A merge counts for the files it changes relative to every parent.

Globs match whole paths: `*` stays within one directory, and `**` spans any
number of them. A rule must watch or exclude each file that a source's `claim`
matches at the current commit, or the run fails. Otherwise an unclassified file
could change unnoticed.

When upstream rewrites its history, the cutoff can end up outside the history
of the current commit. The run then fails and asks for a new cutoff.

## The wire value

The image receives the edits as one build argument, such as
`TORTOISE_MIGRATION_EDITS`, with this format:

```text
<target>:<source>@<commit>[,<source>@<commit>]...[|<target>:...]
```

- Every target in `targets` appears, in that order, with an empty list when it
  has no edit: `world:|characters:`.
- A target with the remedy `recreate` lists, per source, the heads of its
  edits, as `git merge-base --independent` finds them.
- A target with the remedy `manual` lists every edit per source, oldest first,
  so a source name can repeat: `characters:core@1a2b...,core@3c4d...`.
- Commits are 40 characters.

A complete value for a variant with two sources:

```text
world:core@1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b,db@4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e|characters:|realmd:|logs:
```

## The database image's part

docker-deploy-workflows only passes the value on. How a database image handles
it is up to the image. The database images of mserajnik/cmangos-deploy,
mserajnik/vmangos-deploy, and mserajnik/tortoise-deploy, for example, do the
following with their default settings:

- They keep a ledger of the edits they have handled, in
  `maintenance.migration_corrections (db_name, commit_hash)`, keyed by target
  name. On start, they check each target.
- A commit in the ledger calls for no action.
- For a target with the remedy `recreate` and a commit outside the ledger, the
  image drops the database and imports it again, and then each of its commits
  is added to the ledger. One re-creation is enough for several pending
  commits.
- A target with the remedy `manual` and a commit outside the ledger halts
  startup and lists the commits. Once the operator applies the changes and
  confirms, its commits are added to the ledger.
- A new database records every commit of the value as handled, because it was
  created from files that already contain them.
- Their parser refuses a `<target>` without `:` and a `<source>@<commit>`
  without `@`. A damaged value then stops the container with an error.

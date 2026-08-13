# ADR 0001: Versioned Transactional Local State

- Status: Accepted
- Date: 2026-07-18

## Context

The execution backlog is local and gitignored. Atomic file replacement prevents a
partially serialized file, but it does not identify schema compatibility, explain
which operation changed state, or prevent two CLI/MCP processes from overwriting each
other with stale snapshots.

## Decision

Backlog persistence uses a versioned JSON envelope containing `schema_version`, a
monotonic `revision`, `nodes`, and `edges`.

- Unversioned local formats migrate through ordered, deterministic functions.
- Newer schema versions fail closed rather than being downgraded.
- Explicit migration is available through `aio-sdlc migrate-state`.
- A cross-platform [`filelock`](https://py-filelock.readthedocs.io/en/stable/) lock
  covers revision comparison, audit preparation, and atomic replacement.
- A local JSON Lines journal records prepared and committed transaction hashes.
- Incomplete transactions are reconciled from the current file hash on the next read;
  an unknown hash fails closed.
- A partial final journal record is truncated and recorded before transaction recovery.
- `migrate-state --retire-legacy` archives the obsolete generated backlog by content
  hash before removing it.

The backlog, audit journal, and lock live under the gitignored runtime portion of the
canonical `.aio-agentic-sdlc/` workspace. They are operational state, not project intent.

## Consequences

- Interrupted writes preserve or recover a complete backlog.
- Stale writers receive an explicit conflict instead of silently losing work.
- Legacy files remain readable without implicit on-read persistence.
- The obsolete tracked generated backlog can be retired without losing its bytes.
- The journal is append-only and will require a bounded compaction policy before very
  long-running installations accumulate excessive history.
- `filelock` becomes a direct runtime dependency.

## Alternatives Considered

- Platform-specific `fcntl` and `msvcrt` locking was rejected in favor of a maintained
  cross-platform dependency.
- SQLite was deferred because the current data contract and user inspection workflow
  are JSON-based; adopting a database would expand the migration and tooling surface.
- Atomic replacement without revision checks was rejected because it still permits
  last-writer-wins data loss.

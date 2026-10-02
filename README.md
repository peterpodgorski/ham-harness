A Rust project.

## Repositories

The **harness** (this repository: `PROCESS.md`, `scripts/`, `tools/`,
`pipeline/`, `containers/`, `.pi/`), the **app** (`src/`, `tests/`,
`architecture/`, `lexicon/`, `stories/`) and the **alloy-connect** MBT crate are
separate git repositories. Inside the harness container the app is mounted at
`app/` and alloy-connect at `alloy-connect/`. Their names and locations are
configuration, not assumptions: set `PI_APP` / `APP_REPO` for the app and
`ALLOY_REPO` for alloy-connect. Both entry points also load a gitignored `.env`
at the harness root, so the values can live there.

## ⚠️ Architecture Constraint

The project follows the architecture described in `app/architecture/foundation.md`:

- **Bounded Contexts** (DDD)
- **Package by Feature** — vertical slices from edge to domain, not layers
- **Ports and Adapters** (hexagonal architecture)
- **CQRS** — separate read/write **models**, not necessarily separate storage; read models derive on read by default (persisted projections are an optimization, not the idea)
- **Behavior Tests** live at the top of each bounded context

Current `app/src/` is organized by **layer** (`domain.rs`, `service.rs`, `repository.rs`), which **contradicts** the target architecture. Future work must refactor into **feature packages** (bounded contexts), with adapters, domain, r/w models, and data models per feature.

## Process gate

Work is anchored in `PROCESS.md` before anything is touched: every task names a
stage and a story, and any stage may be the entry point. The mechanism, how to
use `/anchor`, and what is blocked are described in
[`PROCESS-GATE.md`](PROCESS-GATE.md).


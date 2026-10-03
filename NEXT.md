# NEXT — resume point

_Clean stopping point: both repos committed, both trees clean, all fast gates
pass. Nothing is half-written. This file is the rope across a context boundary —
state, not memory. Delete it when the list is empty._

## State (as of commit time)

- Harness `main`: `672fccb` — pipeline runs tee to a log; GC override reverted
  (earlier: `0b124e5` report polish, `6587c93` scaffold kind, `b8391d7`
  require_reason scope, `364b597` the two mechanisms).
- App `main`: `deebda9` — escape hatches justified, and `reviewed_through:
  models` recorded (`review_depth_ok: true` against `minimum_from_threat:
  lexicon`). The record distinguishes `Verified-Through: code` (what the
  machine checked) from `Reviewed-Through: models` (what a person read).
- `model_discipline` is **strict** for `expense_tracking` (`require_reason`,
  `strict_exemptions`); 39/39 Quint system actions carry a reason.
- Attestation recorded at `app/attestations/expense_tracking.json`
  (`verified_through: bdd`, `minimum_from_threat: lexicon`,
  digest `sha256:8dd5d38…`).
- **The full pipeline passes** — `make pipeline-run CONTEXT=expense_tracking`,
  slow gates included. Latest log: `pipeline-logs/expense_tracking.log`.

## Next

- [x] **Run the slow gates** — `make pipeline-run CONTEXT=expense_tracking`:
      all gates pass (the earlier failure was the harness GC override, now
      reverted).
- [x] **Record the human review depth** — recorded `models`; `review_depth_ok:
      true`. The experiment: the code was deliberately not read, and is not
      claimed. → `/anchor formalize`
- [ ] **Commit-time attestation workflow** — decide how the trailer
      (`scripts/attest.sh emit --format trailer`) enters the app's commit
      history (manual paste, hook, or CI check).

## Harness polish (`/anchor harness`)

- [ ] Wire `REVIEWED=<layer>` into the `make attest` target (currently the
      script must be called directly).
- [ ] Decide whether the attestation should pin **harness tool hashes** too
      (today it pins the spec + the gate registry/profiles, not `attest.py` /
      `discipline.py`).
- [ ] Commit the **residual-risk manifest** (`discipline.py --json --out`)
      alongside the attestation, or fold it into the trailer.

## Design calls (yours)

- [ ] Per-story `minimum_from_threat` instead of the context-level value — the
      threat narrative is per story, so the honest floor probably is too.
- [ ] The **regeneration ratchet**: make "every bug found by regenerating the
      code becomes a scenario or a lexicon relation" a checked rule, not only a
      principle in `PROCESS.md`. This is what keeps writing-for-deletion
      monotonic.
- [ ] Decide whether `view-history` and `adding-expenses` (no formal spec
      today) should get Quint/Alloy models.

## Rope mechanics

- The anchor is persisted as a session entry; `/process` shows it, `/process
  clear` drops it. It survives compaction and follows the active branch.
- Changing stage or touching a story not in the anchor requires a new anchor:
  `/anchor <stage> <story>[,<story>]`, or `/anchor harness`.
- Agent never runs `make`; per the process, gates are the user's interface.

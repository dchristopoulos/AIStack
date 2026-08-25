# Server-side desired state per machine (reverses stateless sync)

Status: accepted (amended by ADR-0006: removal semantics live there — a locally deleted skill that is still enabled is reinstalled silently, because deletion is never inferred as intent; only locally *modified* content prompts)

The server holds desired state per machine. A `machines` table gives every machine its own token bound to one user, and a `machine_skills` table records which skills that machine should have. The local disk holds actual state. Sync reconciles the two, installing what is missing and updating what is stale, and it asks the user before touching anything locally modified (ADR-0006 holds the full contract).

This reverses an earlier decision to keep sync stateless, with local disk as the only truth and no machine registry. Stateless sync cannot express "enabled but not yet installed", so it cannot answer the question the product exists to answer: a MacBook and a Windows PC want different skill sets, and something has to remember which. Enablement also needs a home that a future dashboard can toggle. The cost is two tables and a reconciliation step, which is the minimum that makes per-machine configuration real. One token lookup now identifies both the user and the machine, which improves attribution as a side effect.

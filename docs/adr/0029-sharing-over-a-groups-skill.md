# Sharing over a group's skill takes being able to share into the group

Status: accepted, 2026-10-15. Resolves two sentences of ADR-0015 that disagree. Findings: AUTHZ-02 in [the October 2026 audit](https://github.com/dchristopoulos/AIStack/blob/v0.1.1/docs/audits/2026-10/README.md).

ADR-0015 says any member may change a team's skill by sharing over it, and also that seeing an open group does not make it writable and that sight of every group grants reading and taking, not sharing. The code follows the first: a member who can only see a group, including a "sees all groups" member looking at a private one, shares over its skill by naming no group, and the refusal for naming the group tells them to do exactly that.

## Decision

**Sharing over an existing skill takes the same right as sharing a new one into its group**: belonging to that group or a group above it (`GroupAccess.writable`). At team level, any member may, as today. The refusal for a group the caller sees but may not write says so in one sentence; one they cannot see answers like an unknown group, as always.

## Consequences

- `skill_service.share` checks the existing skill's group.
- The refusal at `skill_service.share` stops pointing at the unguarded path.
- A matrix test for a member who sees but cannot write, beside OUTSIDER_VIEW.

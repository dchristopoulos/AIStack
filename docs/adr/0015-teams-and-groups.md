# A personal space per user, teams to share into, and groups inside a team

Status: accepted, 2026-10-14 (replaces the reserved "Workspace" term and roadmap item 8; supersedes this record's first version, which had machines install straight from a team)

Before this, one server was one vault that everybody shared and installed from. That cannot say "these are mine", "these are for the backend people", or "these are for my friends".

## The model

**My skills.** Every user has a personal team that only they can see. It mirrors what is on their computers: a skill found on a machine and not yet there is backed up to it without asking, because nothing is shared by doing so. It is the only place a machine ever installs from.

**Teams.** A user creates a team and is its admin. Others join with the team's invite code. A member puts a skill in front of a team by **sharing** it: the team gets its own copy of the latest revision, with its own history, and every revision says who shared it. A member gets a team's skill by **taking** it: the latest revision is copied into their own skills, and their machines install it from there.

**Groups.** Inside a team, groups hold skills and members, like channels. They nest: `backend` can hold `backend/aistack`. A private group is seen only by the people added to it. An open group is seen by everyone who can see the group above it, or by the whole team when nothing is above it.

The shape is the one people already know from Microsoft Teams and GitHub: an organization-wide team everyone is in, teams with owners and members, and channels that are standard or private.

## The rules, and why

- **A machine installs only from its user's own skills.** This is the decision the rest follows from. What a machine runs was always the user's own copy, so leaving a team, being removed from one, or an admin deleting a team's skill takes nothing off anybody's computer. Sync never has to reason about which team a folder came from, and the one-folder-per-name limit of a skills directory is simply the personal space's own uniqueness.
- **A teammate's change is offered, never applied.** A personal skill remembers the team skill it was taken from or shared to, and that skill's revision at the time. When the team's copy is newer, sync reports it and the user decides each time. A skill is instructions to an agent; somebody else's edit to it does not reach a machine without its owner saying yes.
- **Any member may change a team's skill where they may share**, by sharing over it: at team level anyone, in a group those who may share into it (ADR-0029). The revision is theirs, by name.
- **Sharing over a skill you never took is flagged.** If the team already has a skill of that name and the sharer's copy is not linked to it, it may be an unrelated skill that shares a name, and the result says so. This replaces the push-time warning, which could not tell a teammate's edit from a stranger's namesake (#35).
- **Every account is in the server's team, `everyone`.** It is what the shared vault was. An upgraded server moves every existing skill there and every user is a member, so nothing anyone could see disappears. It has no invite code and cannot be left.
- **Each team has its own invite code**, made by the server, stored as a hash, resolved by indexed lookup like a machine token. Making a new one stops the old one working, which is also how a leaked code is cancelled.
- **A token is a person on one computer and is never shared.** A second computer gets its own from `add_machine` and sees everything its user does. A friend joins with their own account and a team's invite code.
- **Two roles: admin and member.** An admin manages the invite code, members, groups, and where a team's skills sit. A team always has at least one while anyone is in it; the last member leaving deletes it, and an admin can delete it (ADR-0028). "Backend developer" is not a role with permissions; it is being in the `backend` group.
- **Sharing into a group takes belonging to it, or to a group above it.** Seeing an open group does not make it writable.
- **One member can be given sight of every group**, private ones included, without being added to each. It grants reading and taking, not sharing.
- **Unsubscribing from a group** stops sync offering updates from it and the groups under it. It hides nothing.
- **Removing a skill from "My skills" keeps a marker.** The folder may still be on a computer, and without the marker sync would take it for a new skill and back it up again. Each machine is asked whether to delete the folder.
- **Provenance is always shown.** Every revision carries `pushed_by`, the username bound to the token at join. A team's skills are not an anonymous library.

## Where the checks live

Identity arrives on every request: the token verifier resolves the bearer to a machine and user before any tool runs, and a dashboard session resolves to a user the same way. The endpoint is stateless (ADR-0013), so there is no session to look up and nothing read from a log.

Who may see which skill is one module, `services/visibility.py`. Group access is worked out there in plain code from two queries, top of each tree first, because the rule has to be readable and a team has a handful of groups. A team, a group, or a skill the caller may not see is answered with the same exception and the same sentence as one that does not exist. Team administration is `services/team_service.py`, where every function begins by establishing the caller's place in the team.

## Not doing

- **A permission matrix** of roles × groups × read/write. It is the part most likely to leak, and private or open per group, plus sight of every group for one person, covered what was asked.
- **Automatic updates from a team**, above.
- **One machine on two servers.** Each would back up the other's skills. A person whose teams live on different servers is a separate piece of work.
- **Hiding who pushed.**
- **Merging.** When a user's copy and the team's have both changed, taking the team's replaces the user's latest, which stays in their history. Nothing is merged line by line.

## Consequences

- Migration 0002: teams, members, groups, the link from a personal skill to its source. Every existing skill moves to `everyone`; every skill a user's machine had decided about is copied, with its history, into that user's own skills, and the machine follows the copy.
- Skill names are unique per team, and a team's skill names are unique across its groups, so a name in a team always means one skill.
- Sharing a name that is already used in a group the sharer cannot see is refused. That reveals that the name is taken, and nothing else; the alternative was letting two skills in one team share a name.
- An admin removing a skill from a team deletes the team's copy and its history there. The copies people took keep the revisions they took, with who pushed them, so what ran on a machine stays accounted for; what is lost is the team's own record of revisions nobody took.
- A personal skill whose source the user can no longer see, because they left the team or the skill moved into a group closed to them, simply has no source: nothing is offered, and nothing is taken away.
- The MCP tools grow from seven to thirteen. They are the connector, for any harness. The product people look at is the dashboard (ADR-0017).

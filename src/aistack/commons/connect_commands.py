"""What connects a coding agent to this server as one machine: handed out by `add_machine`
and by the operator's `aistack admin rotate` and `register-machine`, so all three agree."""


def claude_code_command(endpoint: str, token: str) -> str:
    """The one line that turns another computer into a registered machine.

    `--scope user` because Claude Code's default scope is a single project, and a vault that
    only answers in the folder where it was set up is not the product. Double quotes around
    the header are read the same way by sh, PowerShell, and cmd.
    """
    return (f"claude mcp add --transport http --scope user aistack {endpoint} "
            f'--header "Authorization: Bearer {token}"')


def codex_config(endpoint: str, token: str) -> str:
    """Setup's Codex block: `codex mcp add` cannot set a header, so it is pasted by hand.

    The four approvals are the ones setup writes, so sync runs without a prompt there too.
    """
    return (f'[mcp_servers.aistack]\nurl = "{endpoint}"\n'
            f'http_headers = {{ "Authorization" = "Bearer {token}" }}\n'
            'tools.sync.approval_mode = "approve"\n'
            'tools.list_skills.approval_mode = "approve"\n'
            'tools.get_skill.approval_mode = "approve"\n'
            'tools.push_skill.approval_mode = "approve"\n')

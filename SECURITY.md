# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Ribhus, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Email the maintainers directly or use GitHub's private vulnerability reporting feature
3. Include a clear description of the vulnerability and steps to reproduce

We will respond as quickly as possible and work with you to understand and address the issue.

## Security Model

Ribhus is designed with the following security principles:

### Human-in-the-Loop Approvals

- Tools are classified by risk level: low, medium, high, critical
- High-risk tools require explicit user approval before execution
- Channel sends (WhatsApp, Gmail) always require approval regardless of settings
- Approval decisions are logged to an audit trail

### Credential Isolation

- API keys are read from environment variables, not stored in code
- Channel sessions (WhatsApp, Gmail) are stored in isolated browser profiles under `.ribhus/`
- MCP server configurations should not contain secrets in committed files

### Browser Automation Safety

- WhatsApp Web and Gmail Web are browser automation, not official APIs
- These channels have rate limits and cooldowns to prevent abuse
- Kill switches (`ribhus whatsapp kill`, `ribhus email kill`) immediately terminate channel sessions

### Tool Sandboxing

- Python execution (`python_exec`) runs in the local environment — use with caution
- Terminal commands run in the workspace directory
- File operations are scoped to the workspace by default

## Best Practices

1. **Never set `RIBHUS_AUTO_APPROVE=true` in production** unless you fully understand the implications
2. **Review tool calls** before approving, especially for high-risk operations
3. **Do not commit** `.env` files or any files containing API keys
4. **Use domain allowlists** (`RIBHUS_BROWSER_ALLOWLIST`) when appropriate
5. **Review skills** before installing — skills are untrusted unless you verify them

## Scope

This security policy covers the Ribhus core agent, built-in tools, and bundled skills. Third-party skills and MCP servers have their own security considerations.

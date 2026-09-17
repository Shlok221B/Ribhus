"""Optional skill extras.

Ribhus does **not** auto-import this file. Untrusted skills must not run
arbitrary Python. Document tools this skill expects the agent to use.
"""

SKILL_TOOLS = ["memory_recall", "memory_remember", "web_search", "browser", "http_request"]

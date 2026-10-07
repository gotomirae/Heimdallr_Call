# PRD Ref: §8.7 G-7
"""Subscription login probe for Windows PowerShell installers; prints no identity or secrets."""
import json
import shutil
import subprocess

from src.utils.env import subscription_cli_env


def probe_subscription(cli: str) -> dict:
    """Safe metadata only; OAuth presence alone does not prove a valid login."""
    env = subscription_cli_env()
    # SC: Probe subscription auth in the same sanitized environment as the deck runner.
    try:
        result = subprocess.run([cli, "auth", "status", "--json"], capture_output=True,
            text=True, encoding="utf-8", timeout=30, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return {"loggedIn": False, "authMethod": "none", "error": "CLAUDE_AUTH_CHECK_FAILED"}
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return {"loggedIn": False, "authMethod": "none", "error": "CLAUDE_AUTH_INVALID"}
    if not isinstance(payload, dict):
        return {"loggedIn": False, "authMethod": "none", "error": "CLAUDE_AUTH_INVALID"}
    method = payload.get("authMethod")
    allowed = method == "claude.ai" or (method == "oauth_token" and bool(env.get("CLAUDE_CODE_OAUTH_TOKEN")))
    logged_in = result.returncode == 0 and payload.get("loggedIn") is True and allowed
    return {"loggedIn": logged_in, "authMethod": method,
            **({} if logged_in else {"error": "CLAUDE_SUBSCRIPTION_REQUIRED"})}


def main() -> int:
    cli = shutil.which("claude.exe") or shutil.which("claude")
    safe = probe_subscription(cli) if cli else {
        "loggedIn": False, "authMethod": "none", "error": "CLAUDE_NOT_FOUND"}
    print(json.dumps(safe))
    return int(not safe["loggedIn"])


if __name__ == "__main__":
    raise SystemExit(main())

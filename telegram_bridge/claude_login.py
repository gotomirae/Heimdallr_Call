# PRD Ref: §8.7 G-7
"""Subscription login probe for Windows PowerShell installers; prints no identity or secrets."""
import json
import shutil
import subprocess

from src.utils.env import subscription_cli_env


def main() -> int:
    cli = shutil.which("claude.exe") or shutil.which("claude")
    if not cli:
        print(json.dumps({"loggedIn": False, "authMethod": "none", "error": "CLAUDE_NOT_FOUND"}))
        return 1
    # SC: Probe subscription auth in the same sanitized environment as the deck runner.
    result = subprocess.run([cli, "auth", "status", "--json"], capture_output=True,
        text=True, encoding="utf-8", timeout=30, env=subscription_cli_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        print(json.dumps({"loggedIn": False, "authMethod": "none", "error": "CLAUDE_AUTH_INVALID"}))
        return 1
    safe = {key: payload.get(key) for key in ("loggedIn", "authMethod")}
    print(json.dumps(safe))
    return int(result.returncode != 0 or not safe["loggedIn"] or safe["authMethod"] != "claude.ai")


if __name__ == "__main__":
    raise SystemExit(main())

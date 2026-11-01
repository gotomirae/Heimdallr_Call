# PRD Ref: §7, §10, §11 · ADR50
"""ChatGPT 로그인 Codex CLI. API키/크레딧 폴백 없이 체크포인트를 이어간다."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import uuid

from src.config.constants import CODEX_ANALYSIS_MODEL, CODEX_EXEC_TIMEOUT_SECONDS, CODEX_USAGE_RETRY_SECONDS
from src.utils.env import codex_subscription_env

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "telegram_bridge/state/subscription"


class SubscriptionWait(RuntimeError):
    def __init__(self, reason: str, retry_at: str | None = None):
        super().__init__(reason)
        self.retry_at = retry_at or (datetime.now(timezone.utc) + timedelta(seconds=CODEX_USAGE_RETRY_SECONDS)).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            code = wintypes.DWORD()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            return not ok or code.value == 259
        # Access denied is uncertain: never launch a duplicate.
        return ctypes.get_last_error() != 87
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def single_worker(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "execution-lock.sqlite3", timeout=0)
    try:
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise SubscriptionWait("CODEX_BUSY") from exc
        yield
    finally:
        db.close()


def cli_path() -> str:
    cli = shutil.which("codex.exe") or shutil.which("codex")
    if not cli:
        raise SubscriptionWait("CODEX_CLI_MISSING")
    return cli


def require_chatgpt(cli: str) -> None:
    result = subprocess.run([cli, "login", "status"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=codex_subscription_env(),
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or "chatgpt" not in (result.stdout + result.stderr).lower():
        raise SubscriptionWait("CHATGPT_LOGIN_REQUIRED")


def reset_time(output: str) -> str:
    # Prefer explicit ISO reset values from CLI errors; otherwise use a bounded recheck.
    match = re.search(r'(?:resets_at|reset_at|retry_at)["\s:=]+(20\d\d-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d))', output)
    if match:
        return datetime.fromisoformat(match[1].replace("Z", "+00:00")).isoformat()
    return (datetime.now(timezone.utc) + timedelta(seconds=CODEX_USAGE_RETRY_SECONDS)).isoformat()


def invalidate(key: str, phase: str, reason: str, root: Path | None = None) -> None:
    """Business validation failed: resume the same session, never publish cached invalid output."""
    path = (root or STATE) / hashlib.sha256(key.encode()).hexdigest() / phase / "checkpoint.json"
    checkpoint = read_json(path)
    if checkpoint:
        write_json(path, {**checkpoint, "status": "paused", "validation_error": reason})


def execute(prompt: str, schema: dict, *, key: str, phase: str,
            writable: bool = False, web_search: bool = True, root: Path | None = None) -> dict:
    root = root or STATE
    identity = hashlib.sha256(key.encode()).hexdigest()
    folder = root / identity / phase
    folder.mkdir(parents=True, exist_ok=True)
    with single_worker(root):
        checkpoint = read_json(folder / "checkpoint.json")
        if checkpoint.get("validation_error"):
            prompt += "\n이전 결과 검증 실패를 같은 원고/세션에서 보완하라: " + checkpoint["validation_error"]
        # SC: stored successful stages and pre-reset waits cause zero model calls.
        if checkpoint.get("status") == "completed":
            return read_json(folder / "result.json")
        active = read_json(root / "active-process.json")
        if active.get("pid") and alive(int(active["pid"])):
            raise SubscriptionWait("CODEX_PROCESS_STILL_RUNNING")
        if active.get("pid"):
            write_json(root / "active-process.json", {"pid": None})
        # A worker timeout/crash can outlive the worker. Recover only a terminal CLI
        # response with an actual completed event; otherwise resume its recorded session.
        attempt = checkpoint.get("attempt_log")
        if attempt and Path(attempt).is_file():
            recovered_events = []
            for line in Path(attempt).read_text(encoding="utf-8").splitlines():
                try:
                    recovered_events.append(json.loads(line))
                except ValueError:
                    pass
            for event in recovered_events:
                if event.get("type") == "thread.started":
                    checkpoint["session_id"] = event.get("thread_id")
            if checkpoint.get("status") == "running" and any(e.get("type") == "turn.completed" for e in recovered_events) and not any(e.get("type") == "turn.failed" for e in recovered_events):
                recovered = read_json(folder / "last-message.json")
                if recovered:
                    write_json(folder / "result.json", recovered)
                    write_json(folder / "checkpoint.json", {**checkpoint, "status": "completed", "pid": None})
                    return recovered
        quota = read_json(root / "usage-wait.json")
        retry = quota.get("retry_at")
        if retry and datetime.fromisoformat(retry) > datetime.now(timezone.utc):
            raise SubscriptionWait("USAGE", retry)
        if checkpoint.get("pid") and alive(int(checkpoint["pid"])):
            raise SubscriptionWait("CODEX_PROCESS_STILL_RUNNING")
        cli = cli_path()
        require_chatgpt(cli)
        write_json(folder / "schema.json", schema)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        output_path = folder / "last-message.json"
        output_path.unlink(missing_ok=True)  # No zero-exit reuse of a previous attempt's final message.
        args = [cli, "exec"]
        session = checkpoint.get("session_id")
        if session:
            args += ["resume", session]
        else:
            args += ["--sandbox", "workspace-write" if writable else "read-only", "--cd", str(ROOT)]
        args += ["-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"',
                 "-c", 'approval_policy="never"', "-c", f'web_search="{"live" if web_search else "disabled"}"',
                 "--model", CODEX_ANALYSIS_MODEL, "--json", "--output-schema", str(folder / "schema.json"),
                 "--output-last-message", str(output_path), "-"]
        # Record execution output to disk, including attempts and usage; never treat tokens as API dollars.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        log = folder / f"{stamp}.jsonl"
        err = folder / f"{stamp}.stderr.txt"
        with log.open("w", encoding="utf-8") as stdout, err.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                       text=True, encoding="utf-8", env=codex_subscription_env(),
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            write_json(root / "active-process.json", {"pid": process.pid, "key": identity, "phase": phase})
            write_json(folder / "checkpoint.json", {**checkpoint, "status": "running", "pid": process.pid, "attempt_log": str(log)})
            try:
                process.communicate(prompt, timeout=CODEX_EXEC_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Leave PID ticket: do not start a duplicate while this process can still run.
                raise SubscriptionWait("CODEX_TIMEOUT_PROCESS_PRESERVED") from None
        write_json(root / "active-process.json", {"pid": None})
        events = []
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        for event in events:
            if event.get("type") == "thread.started":
                session = event.get("thread_id") or session
        output = log.read_text(encoding="utf-8") + err.read_text(encoding="utf-8")
        checkpoint = {"session_id": session, "pid": None, "status": "paused", "returncode": process.returncode}
        write_json(folder / "checkpoint.json", checkpoint)
        if process.returncode:
            if re.search(r"usage.limit|rate.limit|quota|usage_limit_reached|weekly.limit", output, re.I):
                retry = reset_time(output)
                write_json(root / "usage-wait.json", {"retry_at": retry, "request": identity})
                raise SubscriptionWait("USAGE", retry)
            raise SubscriptionWait("CODEX_EXEC_FAILED")
        if not output_path.is_file():
            raise SubscriptionWait("CODEX_RESULT_MISSING")
        result = read_json(output_path)
        if not result:
            raise SubscriptionWait("CODEX_RESULT_EMPTY")
        write_json(folder / "result.json", result)
        write_json(folder / "checkpoint.json", {**checkpoint, "status": "completed"})
        return result


def usage(key: str, phases: tuple[str, ...], root: Path | None = None) -> dict[str, int]:
    folder = (root or STATE) / hashlib.sha256(key.encode()).hexdigest()
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    for phase in phases:
        for log in (folder / phase).glob("*.jsonl"):
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.completed":
                    for key in total:
                        total[key] += int((event.get("usage") or {}).get(key) or 0)
    return total

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from src.config.version_info import (
    APP_VERSION,
    RELEASE_CHANNEL,
    RELEASE_NAME,
    RELEASE_STATUS,
    TIMEZONE,
    get_generated_timestamp,
    get_git_branch,
    get_git_commit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAME = os.getenv("SMART_MONEY_SERVICE_NAME", "smart-money-ai-bot")


def run_command(command: list[str], timeout: int = 20) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONPATH": str(PROJECT_ROOT),
                "DAILY_REPORT_LIVE_QUOTES": "0",
                "STRICT_COMMAND_AUDIT": "1",
            },
        )

        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "error": "",
        }

    except FileNotFoundError as error:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"Command not found: {error}",
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"Timed out after {timeout}s",
        }

    except Exception as error:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"{type(error).__name__}: {error}",
        }


def summarize_check(result: dict) -> str:
    if result.get("ok"):
        return "PASS"

    message = (
        result.get("error")
        or result.get("stderr")
        or result.get("stdout")
        or "failed"
    )

    first_line = str(message).splitlines()[0].strip()

    if len(first_line) > 90:
        first_line = first_line[:87] + "..."

    return f"FAIL — {first_line}"


def check_command_audit() -> dict:
    return run_command(
        [sys.executable, "scripts/check_command_catalog.py"],
        timeout=20,
    )


def check_daily_report_quality() -> dict:
    return run_command(
        [sys.executable, "scripts/check_daily_report_quality.py"],
        timeout=35,
    )


def get_python_env_status() -> dict:
    try:
        telegram_version = metadata.version("python-telegram-bot")
    except Exception:
        telegram_version = "unknown"

    return {
        "ok": True,
        "python": sys.executable,
        "telegram": telegram_version,
    }


def parse_systemctl_properties(output: str) -> dict:
    values = {}

    for line in str(output or "").splitlines():
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def get_service_status() -> dict:
    result = run_command(
        [
            "systemctl",
            "show",
            SERVICE_NAME,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "ActiveEnterTimestamp",
            "-p",
            "ExecMainPID",
            "--no-page",
        ],
        timeout=8,
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "state": "unavailable",
            "substate": "unknown",
            "last_restart": "unknown",
            "pid": "unknown",
            "error": result.get("error")
            or result.get("stderr")
            or "systemctl unavailable",
        }

    values = parse_systemctl_properties(result.get("stdout", ""))

    state = values.get("ActiveState") or "unknown"
    substate = values.get("SubState") or "unknown"
    last_restart = values.get("ActiveEnterTimestamp") or "unknown"
    pid = values.get("ExecMainPID") or "unknown"

    return {
        "ok": state == "active",
        "state": state,
        "substate": substate,
        "last_restart": last_restart,
        "pid": pid,
        "error": "",
    }


def build_deploy_health_report() -> str:
    command_audit = check_command_audit()
    report_quality = check_daily_report_quality()
    python_env = get_python_env_status()
    service = get_service_status()

    overall_ok = (
        command_audit.get("ok")
        and report_quality.get("ok")
        and python_env.get("ok")
        and service.get("ok")
    )

    overall_status = "PASS" if overall_ok else "CHECK"

    service_line = service.get("state", "unknown")

    if service.get("substate") and service.get("substate") != "unknown":
        service_line = f"{service_line} / {service.get('substate')}"

    return f"""
🚀 Smart Money AI Deploy Health

Status: {overall_status}
Version: {APP_VERSION}
Release: {RELEASE_NAME}
Release Status: {RELEASE_STATUS}
Channel: {RELEASE_CHANNEL}
Branch: {get_git_branch()}
Commit: {get_git_commit()}
Checked: {get_generated_timestamp()} {TIMEZONE}

Checks
Command Audit: {summarize_check(command_audit)}
Daily Report Quality: {summarize_check(report_quality)}
Python Env: OK
Service: {"OK" if service.get("ok") else "CHECK"} — {service_line}

Runtime
Python: {python_env.get("python")}
python-telegram-bot: {python_env.get("telegram")}
Service Name: {SERVICE_NAME}
PID: {service.get("pid")}
Last Restart: {service.get("last_restart")}

Use:
/version
/quality
/commands
""".strip()
"""Set a declared SEC contact locally; never print it or send a request."""

import argparse
from getpass import getpass
import io
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from src.intelligence.sec_contact import valid_email, user_agent


def configure(path, prompt=getpass, *, replace=False, check=False):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Environment path must be an existing regular file, without a symbolic link")
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("Environment file exceeds the setup size limit")
    text = raw.decode("utf-8-sig")
    keys = re.findall(r"^\s*(?:export\s+)?(SEC_USER_AGENT|SEC_API_USER_AGENT)\s*=", text, re.M)
    if any(keys.count(key) > 1 for key in set(keys)):
        raise ValueError("Duplicate SEC contact settings need a local review before setup")
    values = dotenv_values(stream=io.StringIO(text), interpolate=False)
    if user_agent(values) and not replace:
        return "SEC contact format is configured; no file changes or network requests."
    if check:
        raise ValueError("SEC contact is missing or invalid; run again without --check to enter it locally")
    email = prompt("Administrative email for SEC access (input hidden): ").strip()
    if not valid_email(email):
        raise ValueError("Administrative email format is invalid or is a placeholder; no changes made")
    agent = "SmartMoneyAI/1.8 " + email
    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = text.splitlines(keepends=True)
    changed = False
    for index, line in enumerate(lines):
        if re.match(r"^\s*(?:export\s+)?SEC_USER_AGENT\s*=", line):
            lines[index] = "SEC_USER_AGENT='" + agent + "'" + newline
            changed = True
    if not changed:
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines[-1] += newline
        lines.append("SEC_USER_AGENT='" + agent + "'" + newline)
    updated = (b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + "".join(lines).encode()
    temporary = backup = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".sec-contact-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            os.chmod(temporary, stat.S_IMODE(before.st_mode))
            if hasattr(os, "fchown") and os.geteuid() == 0:
                os.fchown(stream.fileno(), before.st_uid, before.st_gid)
            stream.write(updated); stream.flush(); os.fsync(stream.fileno())
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) or path.read_bytes() != raw:
            raise ValueError("Environment changed during setup; no replacement made")
        fd, backup = tempfile.mkstemp(prefix=path.name + ".sec-contact-backup-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            if hasattr(os, "fchown") and os.geteuid() == 0:
                os.fchown(stream.fileno(), before.st_uid, before.st_gid)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return "SEC contact saved. Private environment backup: " + Path(backup).name + ". Restart the bot service to load it; source access still needs a live check."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--replace", action="store_true", help="Prompt for a replacement even when a valid contact exists")
    parser.add_argument("--check", action="store_true", help="Check the local file without prompting, writing or fetching")
    args = parser.parse_args()
    try:
        print(configure(args.env_file, replace=args.replace, check=args.check))
    except (OSError, ValueError, UnicodeError, EOFError, KeyboardInterrupt) as error:
        # Do not echo an input value, file contents or arbitrary parser exceptions.
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else "SEC contact setup could not complete; check the local file and permissions"
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

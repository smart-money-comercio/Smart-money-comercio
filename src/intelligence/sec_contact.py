"""Validate declared SEC contact configuration without exposing the contact."""

import os
import re


MESSAGE = "Configure SEC_USER_AGENT with an application name and administrative email; run scripts/configure_sec_contact.py on the server"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}")


def valid_email(value):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value):
        return False
    local, domain = value.lower().rsplit("@", 1)
    return (len(local) <= 64 and not local.startswith(".") and not local.endswith(".") and ".." not in local
            and domain not in {"example.com", "example.org", "example.net"}
            and not domain.endswith((".example", ".invalid", ".localhost"))
            and local not in {"your-email", "your_email", "youremail"})


def valid_user_agent(value):
    if (not isinstance(value, str) or not 8 <= len(value) <= 256
            or any(not 32 <= ord(char) <= 126 for char in value)
            or any(char in value for char in "\"'\\$#")
            or "your name" in value.casefold()):
        return False
    contacts = list(EMAIL.finditer(value))
    if len(contacts) != 1 or value.count("@") != 1:
        return False
    contact = contacts[0]
    return (valid_email(contact[0]) and bool(value[:contact.start()].strip(" (<"))
            and value[contact.end():].strip() in {"", ")", ">"})


def user_agent(environ=None):
    values = os.environ if environ is None else environ
    return next((value.strip() for key in ("SEC_USER_AGENT", "SEC_API_USER_AGENT")
                 if valid_user_agent(value := values.get(key, ""))), "")


def require_user_agent():
    value = user_agent()
    if not value:
        raise ValueError(MESSAGE)
    return value


def configuration_failure(payload):
    """A missing local contact is not an HTTP access cooldown."""
    return (isinstance(payload, dict) and payload.get("status") == "error" and not payload.get("http_status")
            and (payload.get("configuration_required") is True
                 or str(payload.get("error", "")).startswith(("Configure the existing SEC_USER_AGENT", "Configure SEC_USER_AGENT"))))

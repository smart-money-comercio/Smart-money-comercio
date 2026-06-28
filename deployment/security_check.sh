#!/bin/bash

set -euo pipefail

APP_DIR="/opt/smart-money-comercio"
BACKUP_DIR="/opt/smart-money-backups"
SERVICE_NAME="smart-money-ai-bot"

if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo."
    echo "Example: sudo bash deployment/security_check.sh"
    exit 1
fi

icon() {
    if [ "$1" = "true" ]; then
        echo "✅"
    else
        echo "❌"
    fi
}

value_or_unavailable() {
    if [ -n "${1:-}" ]; then
        echo "$1"
    else
        echo "Unavailable"
    fi
}

echo "🔐 Smart Money AI Security Check"
echo

HOSTNAME_VALUE="$(hostname)"
UPTIME_VALUE="$(uptime -p 2>/dev/null || echo "Unavailable")"
DISK_VALUE="$(df -h "$APP_DIR" 2>/dev/null | awk 'NR==2 {print $5 " used, " $4 " available"}')"

echo "Server"
echo "Hostname: $HOSTNAME_VALUE"
echo "Uptime: $UPTIME_VALUE"
echo "Disk: $(value_or_unavailable "$DISK_VALUE")"
echo

SERVICE_ACTIVE="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
SERVICE_ENABLED="$(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true)"

SERVICE_ACTIVE_OK="false"
SERVICE_ENABLED_OK="false"

if [ "$SERVICE_ACTIVE" = "active" ]; then
    SERVICE_ACTIVE_OK="true"
fi

if [ "$SERVICE_ENABLED" = "enabled" ]; then
    SERVICE_ENABLED_OK="true"
fi

echo "Service"
echo "$(icon "$SERVICE_ACTIVE_OK") Active: $(value_or_unavailable "$SERVICE_ACTIVE")"
echo "$(icon "$SERVICE_ENABLED_OK") Enabled: $(value_or_unavailable "$SERVICE_ENABLED")"
echo

UFW_STATUS="$(ufw status 2>/dev/null | head -n 1 || true)"
UFW_ACTIVE_OK="false"

if echo "$UFW_STATUS" | grep -qi "Status: active"; then
    UFW_ACTIVE_OK="true"
fi

echo "Firewall"
echo "$(icon "$UFW_ACTIVE_OK") UFW: $(value_or_unavailable "$UFW_STATUS")"
echo

SSHD_BIN="$(command -v sshd || echo "/usr/sbin/sshd")"
SSHD_CONFIG="$("$SSHD_BIN" -T 2>/dev/null || true)"

PERMIT_ROOT_LOGIN="$(echo "$SSHD_CONFIG" | awk '$1=="permitrootlogin"{print $2; exit}')"
PASSWORD_AUTH="$(echo "$SSHD_CONFIG" | awk '$1=="passwordauthentication"{print $2; exit}')"
KBD_AUTH="$(echo "$SSHD_CONFIG" | awk '$1=="kbdinteractiveauthentication"{print $2; exit}')"
PUBKEY_AUTH="$(echo "$SSHD_CONFIG" | awk '$1=="pubkeyauthentication"{print $2; exit}')"

ROOT_LOGIN_OK="false"
PASSWORD_AUTH_OK="false"
KBD_AUTH_OK="false"
PUBKEY_AUTH_OK="false"

if [ "$PERMIT_ROOT_LOGIN" = "no" ]; then
    ROOT_LOGIN_OK="true"
fi

if [ "$PASSWORD_AUTH" = "no" ]; then
    PASSWORD_AUTH_OK="true"
fi

if [ "$KBD_AUTH" = "no" ]; then
    KBD_AUTH_OK="true"
fi

if [ "$PUBKEY_AUTH" = "yes" ]; then
    PUBKEY_AUTH_OK="true"
fi

echo "SSH"
echo "$(icon "$ROOT_LOGIN_OK") PermitRootLogin: $(value_or_unavailable "$PERMIT_ROOT_LOGIN")"
echo "$(icon "$PASSWORD_AUTH_OK") PasswordAuthentication: $(value_or_unavailable "$PASSWORD_AUTH")"
echo "$(icon "$KBD_AUTH_OK") KbdInteractiveAuthentication: $(value_or_unavailable "$KBD_AUTH")"
echo "$(icon "$PUBKEY_AUTH_OK") PubkeyAuthentication: $(value_or_unavailable "$PUBKEY_AUTH")"
echo

ENV_STATUS="Missing"
ENV_OK="false"

if [ -f "$APP_DIR/.env" ]; then
    ENV_PERMS="$(stat -c "%a %U:%G" "$APP_DIR/.env" 2>/dev/null || echo "Unavailable")"
    ENV_STATUS="$ENV_PERMS"

    if echo "$ENV_PERMS" | grep -q "^600 "; then
        ENV_OK="true"
    fi
fi

echo "Secrets File"
echo "$(icon "$ENV_OK") .env permissions: $ENV_STATUS"
echo

BACKUP_COUNT="$(ls -1 "$BACKUP_DIR"/smart-money-backup-*.tar.gz 2>/dev/null | wc -l || echo "0")"
LATEST_BACKUP="$(ls -1t "$BACKUP_DIR"/smart-money-backup-*.tar.gz 2>/dev/null | head -n 1 || true)"
BACKUP_OK="false"

if [ "${BACKUP_COUNT:-0}" -gt 0 ]; then
    BACKUP_OK="true"
fi

echo "Backups"
echo "$(icon "$BACKUP_OK") Backup count: ${BACKUP_COUNT:-0}"
echo "Latest: $(basename "${LATEST_BACKUP:-Unavailable}")"
echo

GIT_BRANCH="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Unavailable")"
GIT_COMMIT="$(git -C "$APP_DIR" log -1 --pretty="%h - %s" 2>/dev/null || echo "Unavailable")"
GIT_STATUS="$(git -C "$APP_DIR" status --short 2>/dev/null || true)"

GIT_CLEAN_OK="false"
if [ -z "$GIT_STATUS" ]; then
    GIT_CLEAN_OK="true"
    GIT_STATUS_TEXT="Clean"
else
    GIT_STATUS_TEXT="Local changes present"
fi

echo "Git"
echo "Branch: $GIT_BRANCH"
echo "Latest commit: $GIT_COMMIT"
echo "$(icon "$GIT_CLEAN_OK") Working tree: $GIT_STATUS_TEXT"
echo

echo "Sudoers"
for FILE in \
    "/etc/sudoers.d/smart-money-backup" \
    "/etc/sudoers.d/smart-money-logs" \
    "/etc/sudoers.d/smart-money-restart" \
    "/etc/sudoers.d/smart-money-securitycheck"
do
    FILE_NAME="$(basename "$FILE")"

    if [ -f "$FILE" ] && visudo -cf "$FILE" >/dev/null 2>&1; then
        echo "✅ $FILE_NAME: valid"
    else
        echo "❌ $FILE_NAME: missing or invalid"
    fi
done

echo
echo "Status: ✅ Security check complete"
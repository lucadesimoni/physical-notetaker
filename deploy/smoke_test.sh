#!/usr/bin/env bash
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
#
# Checks a device set up with deploy/install.sh, the way a person would use it.
# Run on the device (or a Linux ARM machine) after the installer:
#
#   ./deploy/smoke_test.sh
#
# Exits non-zero if a check fails.
set -uo pipefail

BASE="http://127.0.0.1"
FAILED=0

check() {  # check "what" condition...
  local what="$1"; shift
  if "$@"; then echo "PASS  $what"; else echo "FAIL  $what"; FAILED=$((FAILED + 1)); fi
}
contains() { grep -q -- "$2" <<<"$1"; }
lacks() { ! grep -q -- "$2" <<<"$1"; }

# 1. Service runs and the page answers on port 80
for _ in $(seq 1 30); do curl -s -o /dev/null "$BASE/" && break; sleep 1; done
check "service is running" systemctl is-active --quiet notetaker
check "service starts on boot" systemctl is-enabled --quiet notetaker
check "web page on port 80" curl -sf -o /dev/null "$BASE/"

# 2. On the device itself: only the API key to enter
HOME_LOCAL="$(curl -s "$BASE/")"
check "device itself: API key field" contains "$HOME_LOCAL" 'name="api_key"'

# 3. From a phone (http://notetaker.local): settings stay PIN-protected
HOME_PHONE="$(curl -s -H "Host: notetaker.local" "$BASE/")"
check "phone: no PIN-free key field" lacks "$HOME_PHONE" 'name="api_key"'
check "phone: setup banner" contains "$HOME_PHONE" "Einrichtung nötig"
SETTINGS_PHONE="$(curl -s -H "Host: notetaker.local" "$BASE/settings")"
check "phone: asks to choose a PIN" contains "$SETTINGS_PHONE" "PIN wählen"

# 4. Wrong key is checked against the real Mistral API
KEY_PAGE="$(curl -s -H "Origin: $BASE" --data "api_key=sk-not-a-real-key" "$BASE/api-key")"
if contains "$KEY_PAGE" "abgelehnt"; then
  echo "PASS  wrong key rejected by the live Mistral API"
elif contains "$KEY_PAGE" "nicht geprüft"; then
  echo "PASS  key saved unchecked (Mistral not reachable from here)"
else
  echo "FAIL  API key check"; FAILED=$((FAILED + 1))
fi

# 5. Other websites in the browser cannot post to the page
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Origin: https://evil.example" \
  --data "api_key=x" "$BASE/api-key")"
check "cross-site POST blocked (HTTP $CODE)" test "$CODE" = "403"

# 6. Start a meeting: recording, or a clear message when there is no microphone
curl -s -o /dev/null -H "Origin: $BASE" --data "action=start" "$BASE/toggle"
sleep 2
HOME_AFTER="$(curl -s "$BASE/")"
if contains "$HOME_AFTER" "Besprechung beenden"; then
  echo "PASS  meeting recording"
  curl -s -o /dev/null -H "Origin: $BASE" --data "action=stop" "$BASE/toggle"
else
  check "no microphone: clear message" contains "$HOME_AFTER" "Mikrofon"
fi
check "service still running" systemctl is-active --quiet notetaker

# 7. Survives a restart (as after a power cut)
sudo systemctl restart notetaker
for _ in $(seq 1 30); do curl -s -o /dev/null "$BASE/" && break; sleep 1; done
check "back after restart" curl -sf -o /dev/null "$BASE/"

# 8. Device name (informational: needs mDNS in the network)
if getent hosts "$(hostname).local" >/dev/null; then
  echo "PASS  $(hostname).local resolves"
else
  echo "INFO  $(hostname).local does not resolve here (needs avahi + libnss-mdns)"
fi

echo
echo "--- service log ---"
journalctl -u notetaker --no-pager -n 40 2>/dev/null || true
echo
if [[ $FAILED -gt 0 ]]; then
  echo "$FAILED check(s) failed"
  exit 1
fi
echo "All device checks passed"

#!/usr/bin/env bash
# One-step setup on a Raspberry Pi (Raspberry Pi OS Bookworm or newer):
#
#   git clone https://github.com/lucadesimoni/physical-notetaker.git
#   cd physical-notetaker && sudo ./deploy/install.sh
#
# Afterwards open the address it prints on a phone in the same Wi-Fi.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo: sudo ./deploy/install.sh" >&2
  exit 1
fi

USER_NAME="${SUDO_USER:-pi}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
APP_DIR="$USER_HOME/notetaker"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev portaudio19-dev espeak-ng avahi-daemon \
  python3-gpiozero python3-lgpio python3-evdev network-manager >/dev/null

# A dedicated device gets a memorable name: http://notetaker.local
# (keeps a name you chose yourself; override with NOTETAKER_HOSTNAME=...)
NEW_HOSTNAME="${NOTETAKER_HOSTNAME:-notetaker}"
if [[ "$(hostname)" == "raspberrypi" || -n "${NOTETAKER_HOSTNAME:-}" ]]; then
  echo "==> Naming the device '$NEW_HOSTNAME'"
  OLD_HOSTNAME="$(hostname)"
  hostnamectl set-hostname "$NEW_HOSTNAME"
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NEW_HOSTNAME/" /etc/hosts
  grep -q "^127.0.1.1" /etc/hosts || echo -e "127.0.1.1\t$NEW_HOSTNAME" >> /etc/hosts
  systemctl restart avahi-daemon || true
  echo "    (was '$OLD_HOSTNAME')"
fi

echo "==> Setting up $APP_DIR"
install -d -o "$USER_NAME" -g "$USER_NAME" "$APP_DIR" "$APP_DIR/recordings"
# System site packages: reuse gpiozero/lgpio/evdev from apt
sudo -u "$USER_NAME" python3 -m venv --system-site-packages "$APP_DIR/venv"
sudo -u "$USER_NAME" "$APP_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$USER_NAME" "$APP_DIR/venv/bin/pip" install -q "$REPO_DIR"

if [[ ! -f "$APP_DIR/config.yaml" ]]; then
  echo "==> Creating config"
  sudo -u "$USER_NAME" "$APP_DIR/venv/bin/python" - "$APP_DIR" <<'PY'
import sys
from voxtral_notetaker.config import NotetakerConfig
app = sys.argv[1]
c = NotetakerConfig()
c.service.recordings_dir = f"{app}/recordings"
c.storage.local_path = f"{app}/recordings"
c.web.port = 80  # the service may bind port 80 (see notetaker.service)
c.save(f"{app}/config.yaml")
PY
  chmod 600 "$APP_DIR/config.yaml"
fi

echo "==> Permissions for microphone, buttons and Wi-Fi setup"
for group in audio input gpio netdev; do
  getent group "$group" >/dev/null && usermod -aG "$group" "$USER_NAME"
done
# Let the service switch Wi-Fi / open the setup hotspot without a desktop session
install -d /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/50-notetaker-networkmanager.rules <<RULES
polkit.addRule(function(action, subject) {
  if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 && subject.user == "$USER_NAME") {
    return polkit.Result.YES;
  }
});
RULES

echo "==> Installing the service (starts on every boot)"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@HOME@|$USER_HOME|g" \
  "$REPO_DIR/deploy/notetaker.service" > /etc/systemd/system/notetaker.service
systemctl daemon-reload
systemctl enable --now notetaker.service

PORT="$(sudo -u "$USER_NAME" "$APP_DIR/venv/bin/python" -c \
  "from voxtral_notetaker.config import load_config; print(load_config('$APP_DIR/config.yaml').web.port)")"
SUFFIX=""; [[ "$PORT" != "80" ]] && SUFFIX=":$PORT"
URL="http://$(hostname).local$SUFFIX"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Done. The notetaker starts automatically on every boot."
echo
echo "  Open on your phone (same Wi-Fi):  $URL"
[[ -n "$IP" ]] && echo "                                or  http://$IP$SUFFIX"
echo
"$APP_DIR/venv/bin/python" -c "import segno; segno.make('$URL').terminal(compact=True)" 2>/dev/null || true
echo
echo "  1. Choose a PIN and enter your Mistral API key"
echo "  2. Optional: enter email addresses to receive the memos"
echo "  3. Print the sticker (web page -> 'Aufkleber mit QR-Code') for the device"
echo "  4. Press the button (or 'Besprechung starten') to record"
echo
echo "  Hold the button 3 seconds: the device says its address."
echo "  Logs: journalctl -u notetaker -f"

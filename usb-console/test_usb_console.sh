#!/bin/bash
# Static checks for the USB gadget console files (no hardware needed).
# Run: bash usb-console/test_usb_console.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
rules="$here/70-fpgas-usb-console.rules"
unit="$here/fpgas-usb-console.service"
modprobe="$here/fpgas-usb-console.conf"
fail() { echo "FAIL: $*"; exit 1; }

# 1. every file is packaged
for f in 70-fpgas-usb-console.rules fpgas-usb-console.service fpgas-usb-console.conf; do
    grep -q "src: usb-console/$f" "$repo/nfpm.yaml" || fail "$f not in nfpm.yaml"
done

# 2. the rule chain: UDC -> g_serial, ttyGS0 -> log service, ttyGS1 -> getty
grep -q 'SUBSYSTEM=="udc".*kmod load g_serial' "$rules" || fail "no udc -> g_serial rule"
grep -q 'KERNEL=="ttyGS0".*SYSTEMD_WANTS.*fpgas-usb-console.service' "$rules" || fail "no ttyGS0 -> service rule"
grep -q 'KERNEL=="ttyGS1".*SYSTEMD_WANTS.*serial-getty@ttyGS1.service' "$rules" || fail "no ttyGS1 -> getty rule"
if udevadm verify --help >/dev/null 2>&1; then
    udevadm verify --no-style "$rules" || fail "udevadm verify rejected the rules"
fi

# 3. two gadget ports, or the getty and the log would share (and flush) one tty
grep -Eq '^options g_serial .*\bn_ports=2\b' "$modprobe" || fail "g_serial n_ports=2 missing"

# 4. the log service: bound to the tty, writes to it, restarts after a host detaches
grep -q '^BindsTo=dev-ttyGS0.device' "$unit" || fail "unit not bound to dev-ttyGS0.device"
grep -q '^TTYPath=/dev/ttyGS0' "$unit" || fail "unit does not write to /dev/ttyGS0"
grep -q '^Restart=always' "$unit" || fail "unit does not restart"
grep -q '^StartLimitIntervalSec=0' "$unit" || fail "unit would hit the start rate limit"
grep -Eq '^ExecStart=/usr/bin/dmesg .*--follow' "$unit" || fail "ExecStart is not dmesg --follow"
if command -v systemd-analyze >/dev/null; then
    systemd-analyze verify "$unit" || fail "systemd-analyze verify rejected the unit"
fi
echo "PASS"

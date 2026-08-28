#!/bin/bash
# FEL-boot U-Boot into an Allwinner board that enumerated in BROM FEL mode.
# Called by fpgas-felboot@<kernel-device>.service (udev rule 60-fpgas-felboot),
# e.g. fpgas-felboot@1-1.2.2.service. The board's bus/devnum come from sysfs;
# U-Boot then DHCP+PXE-boots on its own (fpgas.online-infra fixpi/sunxi.yml).
set -euo pipefail

dev="${1:?usage: fpgas-felboot.sh <usb kernel device, e.g. 1-1.2.2>}"
image="${FPGAS_FELBOOT_IMAGE:-/usr/lib/fpgas-online/u-boot/orangepi_pc_plus/u-boot-sunxi-with-spl.bin}"
sysfs="${FPGAS_FELBOOT_SYSFS:-/sys/bus/usb/devices/$dev}"
retry_sleep="${FPGAS_FELBOOT_RETRY_SLEEP:-2}"

busnum=$(<"$sysfs/busnum")
devnum=$(<"$sysfs/devnum")
target=$(printf '%03d:%03d' "$busnum" "$devnum")

for attempt in 1 2 3; do
    if sunxi-fel --dev "$target" uboot "$image"; then
        echo "fpgas-felboot: $dev ($target): U-Boot loaded (attempt $attempt)"
        exit 0
    fi
    echo "fpgas-felboot: $dev ($target): sunxi-fel failed (attempt $attempt)" >&2
    sleep "$retry_sleep"
done
exit 1

#!/usr/bin/env python3
"""Capture an fpgas.online board's USB gadget kernel-log port to a file.

Host side of the usb-console: udev (71-fpgas-usb-console-host.rules) starts
fpgas-usb-console-log@<ttyACMn>.service when a board's gadget enumerates, and
this appends everything the board sends to /var/log/fpgas-usb-console/<usb
port>.log (e.g. 1-1.3.1.log) from the first byte. The board replays its whole
kernel ring buffer on every attach, and with systemd debug logging that buffer
wraps within minutes, so only a reader present from the start sees the early
boot. The port is opened once, in raw mode: a separate stty would open/close it
in cooked mode and drop the beginning of the stream.

Usage: fpgas-usb-console-log.py <tty name> [<device path>]
"""

import datetime
import errno
import os
import select
import sys
import tty

LOG_DIR = os.environ.get("FPGAS_USB_CONSOLE_LOG_DIR", "/var/log/fpgas-usb-console")
# Self-rotating: <port>.log -> .1 -> .2 -> .3 once the live file passes this.
MAX_BYTES = int(os.environ.get("FPGAS_USB_CONSOLE_LOG_MAX", str(32 * 1024 * 1024)))
KEEP = 3
SYSFS_TTY = os.environ.get("FPGAS_USB_CONSOLE_SYSFS", "/sys/class/tty")


def usb_port(tty_name):
    """USB port path of the gadget: /sys/class/tty/ttyACM0/device -> .../1-1.3.1:2.0"""
    iface = os.path.basename(os.path.realpath(os.path.join(SYSFS_TTY, tty_name, "device")))
    return iface.split(":")[0]


def rotate(path):
    for i in range(KEEP, 0, -1):
        src = path if i == 1 else f"{path}.{i - 1}"
        if os.path.exists(src):
            os.replace(src, f"{path}.{i}")


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def main(tty_name, dev_path=None):
    dev_path = dev_path or f"/dev/{tty_name}"
    port = usb_port(tty_name)
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{port}.log")

    fd = os.open(dev_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    out = open(log_path, "ab", buffering=0)
    out.write(f"\n===== {stamp()} {tty_name} on USB {port}: attached =====\n".encode())
    size = os.fstat(out.fileno()).st_size
    print(f"fpgas-usb-console-log: {tty_name} (USB {port}) -> {log_path}", flush=True)

    while True:
        readable, _, _ = select.select([fd], [], [], 5)
        if not readable:
            continue
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            continue
        except OSError as e:
            if e.errno in (errno.EIO, errno.ENODEV, errno.ENXIO):
                break  # hangup: the board detached or rebooted
            raise
        if not data:
            break
        out.write(data)
        size += len(data)
        if size > MAX_BYTES:
            out.close()
            rotate(log_path)
            out = open(log_path, "ab", buffering=0)
            size = 0

    out.write(f"\n===== {stamp()} {tty_name} on USB {port}: detached =====\n".encode())
    out.close()
    os.close(fd)
    print(f"fpgas-usb-console-log: {tty_name} (USB {port}) detached", flush=True)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(*sys.argv[1:])

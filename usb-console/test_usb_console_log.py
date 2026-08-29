"""Test for fpgas-usb-console-log.py on a pty pair standing in for the ttyACM.
Run: uv run --no-project usb-console/test_usb_console_log.py"""

import importlib.util
import os
import pathlib
import select
import shutil
import tempfile
import threading

here = pathlib.Path(__file__).resolve().parent
scratch_root = here.parent / "tmp"
scratch_root.mkdir(exist_ok=True)
scratch = pathlib.Path(tempfile.mkdtemp(prefix="usb-console-test.", dir=scratch_root))
try:
    # fake sysfs: /sys/class/tty/ttyACM9/device -> .../1-1.3.1:2.0
    iface = scratch / "devices" / "1-1.3.1" / "1-1.3.1:2.0"
    iface.mkdir(parents=True)
    (scratch / "class" / "ttyACM9").mkdir(parents=True)
    os.symlink(iface, scratch / "class" / "ttyACM9" / "device")
    os.environ["FPGAS_USB_CONSOLE_SYSFS"] = str(scratch / "class")
    os.environ["FPGAS_USB_CONSOLE_LOG_DIR"] = str(scratch / "log")
    os.environ["FPGAS_USB_CONSOLE_LOG_MAX"] = "3000"

    spec = importlib.util.spec_from_file_location("logger", here / "fpgas-usb-console-log.py")
    logger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(logger)
    assert logger.usb_port("ttyACM9") == "1-1.3.1", logger.usb_port("ttyACM9")

    master, slave = os.openpty()
    t = threading.Thread(target=logger.main, args=("ttyACM9", os.ttyname(slave)))
    t.start()
    # the logger creates the log file right after switching the slave to raw
    # mode; writing before that would echo into the unread master and deadlock
    while not (scratch / "log" / "1-1.3.1.log").exists():
        select.select([], [], [], 0.05)
    payload = b"[    0.000000] Booting Linux on physical CPU 0x0\r\n" * 100  # 5 KB > MAX -> one rotation
    os.write(master, payload)
    # wait until the logger consumed it, then hang the port up (closing both ends -> EIO)
    while not (scratch / "log" / "1-1.3.1.log.1").exists():
        select.select([], [], [], 0.05)
    os.close(slave)
    os.close(master)
    t.join(timeout=10)
    assert not t.is_alive(), "logger did not exit on hangup"

    live = (scratch / "log" / "1-1.3.1.log").read_bytes()
    rotated = (scratch / "log" / "1-1.3.1.log.1").read_bytes()
    assert rotated.startswith(b"\n===== "), rotated[:60]
    assert b"ttyACM9 on USB 1-1.3.1: attached" in rotated
    assert b"\r\n" in rotated, "raw mode lost: CR stripped"
    assert live.rstrip().endswith(b"ttyACM9 on USB 1-1.3.1: detached ====="), live[-80:]
    assert payload in rotated + live.split(b"\n===== ")[0], "payload not captured contiguously"
    print("PASS")
finally:
    shutil.rmtree(scratch)

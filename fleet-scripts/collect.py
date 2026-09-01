#!/usr/bin/env python3
"""Build the fleet registration document (see the fleet self-registration
design in fpgas.online-infra docs/superpowers/specs/).

Every reader takes a `root` so the whole module is testable against a plain
fixture directory tree; anything that needs a live system (dpkg, ip) only
runs when root is the real "/". All lists are sorted so the document
fingerprint (canonical-JSON sha256, shared with the server) is stable.

Deliberately NO FPGA DNA read: JTAG against a PCIe-attached Acorn wedges
the link; DNA stays an operator-CLI concern.
"""

import glob
import json
import os
import re
import socket
import subprocess
import urllib.request

SCHEMA = 1
# hubs contribute nothing to hardware identity and differ per cable layout
USB_SKIP_VENDORS = {"1d6b", "0424", "2109"}
PCI_BRIDGE_CLASS = "0604"
PCI_SKIP_VENDORS = {"1de4"}  # RP1 south bridge: present on every Pi 5
# onboard, not connected hardware: the Pi 4's VL805 USB controller
PCI_SKIP_DEVICES = {("1106", "3483")}
# SQRL Acorn CLE-215+ under its default gateware (live probe 2026-09-01:
# every stock Acorn at welland enumerates as 1e24:021f)
ACORN_PCI_VENDOR = "1e24"


def _read(root, rel):
    """One file, stripped of whitespace and device-tree NULs; '' if absent."""
    try:
        with open(os.path.join(root, rel), errors="replace") as f:
            return f.read().replace("\x00", "").strip()
    except OSError:
        return ""


def _is_live(root):
    return os.path.abspath(str(root)) == "/"


def machine_section(root):
    cpuinfo = _read(root, "proc/cpuinfo")
    fields = dict(re.findall(r"^([A-Za-z ]+?)\s*:\s*(.+)$", cpuinfo, re.M))
    macs = {}
    for path in sorted(glob.glob(os.path.join(root, "sys/class/net/*/address"))):
        iface = os.path.basename(os.path.dirname(path))
        if not re.match(r"^(eth|en|wlan)", iface):
            continue
        mac = _read(root, os.path.relpath(path, root))
        if mac and mac != "00:00:00:00:00:00":
            macs[iface] = mac
    mem = re.search(r"^MemTotal:\s*(\d+) kB", _read(root, "proc/meminfo"), re.M)
    return {
        "serial": fields.get("Serial", ""),
        "model": _read(root, "proc/device-tree/model") or fields.get("Model", ""),
        "revision_code": fields.get("Revision", ""),
        "macs": macs,
        "mem_total_kb": int(mem.group(1)) if mem else 0,
    }


def software_section(root):
    os_release = dict(
        re.findall(r'^(\w+)="?(.*?)"?$', _read(root, "etc/os-release"), re.M))
    packages = {}
    if _is_live(root):
        try:
            out = subprocess.run(
                ["dpkg-query", "-W", "-f", "${Package} ${Version}\n",
                 "fpgas-online-*"],
                capture_output=True, text=True, timeout=10).stdout
            packages = dict(line.split(" ", 1)
                            for line in out.splitlines() if " " in line)
        except OSError:
            pass
    return {
        "kernel": _read(root, "proc/sys/kernel/osrelease"),
        "os_release": os_release.get("PRETTY_NAME", ""),
        "os_version_id": os_release.get("VERSION_ID", ""),
        "nfsroot_build": _read(root, "etc/fpgas-online/nfsroot-build.json"),
        "packages": packages,
    }


def connection_section(root, site, hostname):
    host_keys = sorted(
        _read(root, os.path.relpath(p, root))
        for p in glob.glob(os.path.join(root, "etc/ssh/ssh_host_*_key.pub")))
    password_lines = [line for line in
                      _read(root, "etc/ssh/password.txt").splitlines()
                      if line and not line.startswith("#")]
    addresses = {"ipv4": [], "ipv6": []}
    if _is_live(root):
        try:
            out = subprocess.run(["ip", "-json", "addr"], capture_output=True,
                                 text=True, timeout=10).stdout
            for iface in json.loads(out or "[]"):
                for a in iface.get("addr_info", []):
                    if a.get("scope") != "global":
                        continue
                    kind = "ipv6" if a["family"] == "inet6" else "ipv4"
                    addresses[kind].append(a["local"])
        except (OSError, ValueError):
            pass
        addresses = {k: sorted(v) for k, v in addresses.items()}
    # the netboot fleet's /etc/hostname is empty (names come from DHCP), so
    # a live collect falls through to the kernel hostname
    if not hostname:
        hostname = _read(root, "etc/hostname")
    if not hostname and _is_live(root):
        hostname = socket.gethostname()
    return {
        "site": site,
        "hostname": hostname,
        "addresses": addresses,
        "ssh_host_keys": host_keys,
        "login_user": "pi",
        # published by design on fpgas.online -- the boards are ephemeral
        "login_password": password_lines[-1] if password_lines else "",
    }


def peripherals_section(root):
    usb = []
    for dev in sorted(glob.glob(os.path.join(root, "sys/bus/usb/devices/*"))):
        rel = os.path.relpath(dev, root)
        vid = _read(root, os.path.join(rel, "idVendor"))
        if not vid or vid in USB_SKIP_VENDORS:
            continue
        entry = {"vid": vid, "pid": _read(root, os.path.join(rel, "idProduct"))}
        for key in ("product", "serial"):
            value = _read(root, os.path.join(rel, key))
            if value:
                entry[key] = value
        usb.append(entry)
    pcie = []
    for dev in sorted(glob.glob(os.path.join(root, "sys/bus/pci/devices/*"))):
        rel = os.path.relpath(dev, root)
        vendor = _read(root, os.path.join(rel, "vendor")).removeprefix("0x")
        device = _read(root, os.path.join(rel, "device")).removeprefix("0x")
        pci_class = _read(root, os.path.join(rel, "class")).removeprefix("0x")
        if not vendor or vendor in PCI_SKIP_VENDORS \
                or (vendor, device) in PCI_SKIP_DEVICES \
                or pci_class.startswith(PCI_BRIDGE_CLASS):
            continue
        pcie.append({"vendor": vendor, "device": device, "class": pci_class})
    hats = []
    if _read(root, "proc/device-tree/hat/product"):
        hats.append({key: _read(root, f"proc/device-tree/hat/{key}")
                     for key in ("product", "vendor", "product_id",
                                 "product_ver", "uuid")})
    cameras = sorted({
        _read(root, os.path.relpath(p, root))
        for p in glob.glob(os.path.join(root, "sys/class/video4linux/*/name"))})
    return {
        "usb": sorted(usb, key=lambda e: sorted(e.items())),
        "pcie": sorted(pcie, key=lambda e: sorted(e.items())),
        "hats": hats,
        "cameras": cameras,
    }


def fpga_section(peripherals, tt_health):
    boards = []
    for dev in peripherals["usb"]:
        if dev["vid"] == "0403" and dev["pid"] == "6010" \
                and dev.get("serial", "").startswith("210"):
            boards.append({"kind": "arty-a7",
                           "ids": {"digilent_serial": dev["serial"]}})
    for dev in peripherals["pcie"]:
        if dev["vendor"] == ACORN_PCI_VENDOR:
            boards.append({"kind": "acorn-cle-215+",
                           "ids": {"pci": f"{dev['vendor']}:{dev['device']}"}})
        elif dev["vendor"] == "10ee":
            # an Acorn running a user bitstream enumerates as bare Xilinx
            boards.append({"kind": "xilinx-pcie",
                           "ids": {"pci": f"{dev['vendor']}:{dev['device']}"}})
    if tt_health and tt_health.get("board", {}).get("present"):
        boards.append({"kind": "tt-demo-board",
                       "ids": {"slug": tt_health.get("slug", ""),
                               "board_kind": tt_health.get("kind", ""),
                               "firmware": tt_health.get("version", "")}})
    return {"boards": sorted(boards, key=lambda b: (b["kind"], sorted(b["ids"].items())))}


def _tt_health(tt_url):
    if not tt_url:
        return None
    try:
        with urllib.request.urlopen(f"{tt_url}/health", timeout=2) as resp:
            return json.load(resp)
    except (OSError, ValueError):
        return None


def document(root="/", site="", hostname="", tt_url="http://127.0.0.1:8765"):
    peripherals = peripherals_section(root)
    return {
        "schema": SCHEMA,
        "machine": machine_section(root),
        "software": software_section(root),
        "connection": connection_section(root, site, hostname),
        "peripherals": peripherals,
        "fpga": fpga_section(peripherals, _tt_health(tt_url)),
    }


if __name__ == "__main__":
    print(json.dumps(document(), indent=2, sort_keys=True))

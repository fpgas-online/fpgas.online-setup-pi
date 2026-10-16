"""The .link files that name a fleet board's interfaces (fpgas.online-infra #299).

11-eth-uplink.link must name the onboard NIC of every model the fleet netboots
eth-uplink, and nothing else: never a USB Ethernet adapter, which an FPGA's
Ethernet test plugs in and which can share the onboard NIC's driver.

Where each device path comes from (the review of setup-pi #18 asked this be said):
Pi 3B+: read on fleet boards (eth-uplink on the fleet since before #299);
Pi 5/CM5: the node name read (dmesg "macb 1f00100000.ethernet", RP1 siblings
under axi/1000120000.pcie in sysfs), the full path not read; Pi 4B/CM4 and
Orange Pi PC: from the device tree only (fd580000.ethernet on scb; the H3's
ethernet@1c30000), not read on a board. The infra VM test boots the Pi 4B's;
root 7 reboots one Pi 5 first (fpgas.online-infra PR #300, Rollout). The
ID_PATH udev derives from each is computed here the way udev's path_id
builtin does for platform and USB devices (src/udev/udev-builtin-path_id.c:
a platform device contributes "platform-<name>" and its platform parents are
skipped; a USB interface contributes "usb-0:<port>:<config>.<interface>" and
its USB parents are skipped). The Pi 3B+ row checks that model against the
value already proven on the fleet: its NIC was eth-uplink before #299.
"""

import configparser
import fnmatch
import pathlib
import re

import pytest

NETWORK = pathlib.Path(__file__).parent.parent / "fixpi" / "etc" / "systemd" / "network"

# model -> sysfs path of the board's onboard NIC (the net device's parent).
ONBOARD = {
    # LAN7515 on the onboard hub; the path the .link has matched since the pici days.
    "Pi 3B+": "/sys/devices/platform/soc/3f980000.usb/usb1/1-1/1-1.1/1-1.1.1/1-1.1.1:1.0",
    # BCM2711 GENET (bcmgenet), on the scb bus; the CM4 has the same SoC and node.
    "Pi 4B": "/sys/devices/platform/scb/fd580000.ethernet",
    # RP1's Cadence GEM (macb). The RP1 peripherals sit directly under the PCIe
    # controller's platform device (read on welland's Pi 5s: 1f00088000.i2c, and
    # on the ps1 CM5 blades: 1f00030000.serial, under the same parent). The CM5
    # has the same RP1.
    "Pi 5": "/sys/devices/platform/axi/1000120000.pcie/1f00100000.ethernet",
    # Allwinner H3 EMAC (dwmac-sun8i).
    "Orange Pi PC": "/sys/devices/platform/soc/1c30000.ethernet",
}

# USB Ethernet adapters on each model's USB ports: none of them may be named eth-uplink.
ADAPTERS = {
    "Pi 3B+ port 1.2 (eth-fpga)": "/sys/devices/platform/soc/3f980000.usb/usb1/1-1/1-1.2/1-1.2:1.0",
    "Pi 3B+ port 1.3": "/sys/devices/platform/soc/3f980000.usb/usb1/1-1/1-1.3/1-1.3:1.0",
    "Pi 4B VL805 port": "/sys/devices/platform/scb/fd500000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/usb1/1-1/1-1.2/1-1.2:1.0",
    "Pi 5 RP1 USB": "/sys/devices/platform/axi/1000120000.pcie/1f00200000.usb/xhci-hcd.0/usb2/2-1/2-1:1.0",
    "Orange Pi PC USB": "/sys/devices/platform/soc/1c1b000.usb/usb3/3-1/3-1:1.0",
}

USB_PORT = re.compile(r"^\d+-[\d.]+(:\d+\.\d+)?$")  # 1-1.1.1 (device) or 1-1.1.1:1.0 (interface)
USB_ROOT = re.compile(r"^usb\d+$")
PCI = re.compile(r"^(pci)?[0-9a-f]{4}:[0-9a-f]{2}(:[0-9a-f]{2}\.[0-9a-f])?$")


def path_id(sysfs: str) -> str:
    """udev's ID_PATH for these device paths (platform, PCI and USB parents only)."""
    parts = sysfs.removeprefix("/sys/devices/").split("/")
    path, last = [], None
    for name in reversed(parts):
        if name == "platform":
            break
        if USB_PORT.match(name) or USB_ROOT.match(name):
            kind = "usb"
            if last != "usb" and ":" in name:
                path.insert(0, "usb-0:" + name.split("-", 1)[1])
        elif PCI.match(name):
            kind = "pci"
            if last != "pci" and not name.startswith("pci"):
                path.insert(0, "pci-" + name)
        elif "." in name:
            kind = "platform"
            if last != "platform":
                path.insert(0, "platform-" + name)
        else:  # xhci-hcd.0 is a platform device too; any other component is a bus node like scb/axi/soc
            kind = last
        last = kind
    return "-".join(path)


def link(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=True, interpolation=None)
    parser.optionxform = str  # systemd keys are case sensitive
    parser.read_string((NETWORK / name).read_text())
    return parser


def matches(globs: str, value: str) -> bool:
    return any(fnmatch.fnmatchcase(value, glob) for glob in globs.split())


def test_path_id_model_reproduces_the_proven_pi_3b_plus_value():
    # The value 11-eth-uplink.link matched on every 3B+ before #299 (and 12-eth-fpga.link's port 1.2).
    assert path_id(ONBOARD["Pi 3B+"]) == "platform-3f980000.usb-usb-0:1.1.1:1.0"
    assert path_id(ADAPTERS["Pi 3B+ port 1.2 (eth-fpga)"]) == "platform-3f980000.usb-usb-0:1.2:1.0"
    assert link("12-eth-fpga.link")["Match"]["Path"] == "platform-3f980000.usb-usb-0:1.2:1.0"


@pytest.mark.parametrize("model", ONBOARD)
def test_uplink_link_names_every_models_onboard_nic(model):
    match = link("11-eth-uplink.link")["Match"]
    assert matches(match["Path"], path_id(ONBOARD[model])), (model, path_id(ONBOARD[model]))


def test_uplink_link_matches_exactly_the_onboard_nics():
    match = link("11-eth-uplink.link")["Match"]
    assert sorted(match["Path"].split()) == sorted(path_id(p) for p in ONBOARD.values())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_uplink_link_never_names_a_usb_adapter(adapter):
    match = link("11-eth-uplink.link")["Match"]
    assert not matches(match["Path"], path_id(ADAPTERS[adapter])), (adapter, path_id(ADAPTERS[adapter]))


def test_uplink_link_shape():
    parser = link("11-eth-uplink.link")
    assert parser.sections() == ["Match", "Link"]
    match = dict(parser["Match"])
    # Not by MAC (every board differs) and not by Driver= (a USB adapter can share lan78xx with the 3B+).
    assert set(match) == {"KernelCommandLine", "Type", "Path"}
    # Netbooted boards only: a disk-booted host carrying this package keeps its own names.
    assert match["KernelCommandLine"] == "nfsroot"
    # Type=ether: a VLAN or bridge on top shares the parent's path, and must not be renamed.
    assert match["Type"] == "ether"
    assert dict(parser["Link"]) == {"Name": "eth-uplink"}


def test_uplink_link_sorts_before_the_distribution_defaults():
    # udev applies the first matching .link in lexical order; 73-usb-net-by-mac.link and 99-default.link
    # must not get there first.
    assert sorted(["11-eth-uplink.link", "12-eth-fpga.link", "73-usb-net-by-mac.link", "99-default.link"])[0] == (
        "11-eth-uplink.link")


def test_link_files_are_packaged_to_etc():
    # /etc/systemd/network: what initramfs-tools' udev hook copies into the initramfs, where the rename happens.
    nfpm = (NETWORK.parents[3] / "nfpm.yaml").read_text()
    for name in ("11-eth-uplink.link", "12-eth-fpga.link"):
        assert f"src: fixpi/etc/systemd/network/{name}\n    dst: /etc/systemd/network/{name}\n" in nfpm

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "fleet-scripts"))
import collect  # noqa: E402

ROOT = pathlib.Path(__file__).parent / "data" / "pi5-acorn"


def test_machine_section():
    m = collect.machine_section(ROOT)
    assert m["serial"] == "c36b093f773d46b8"
    assert m["model"].startswith("Raspberry Pi 5")
    assert m["revision_code"] == "a04171"
    assert m["macs"]["eth0"] == "98:fe:54:13:f5:75"


def test_software_and_connection():
    s = collect.software_section(ROOT)
    assert s["os_release"].startswith("Debian") and s["kernel"]
    c = collect.connection_section(ROOT, site="welland", hostname="pi-sw2-p47")
    assert c["site"] == "welland" and c["login_user"] == "pi"
    assert c["ssh_host_keys"][0].startswith("ssh-ed25519")


def test_peripherals_and_fpga():
    p = collect.peripherals_section(ROOT)
    assert {"vid": "0403", "pid": "6010",
            "product": "FT2232C/D/H Dual UART/FIFO IC",
            "serial": "210319B3E5C5"} in p["usb"]
    assert "ov5647" in p["cameras"]
    f = collect.fpga_section(p, tt_health=None)
    assert sorted(b["kind"] for b in f["boards"]) == ["acorn-cle-215+", "arty-a7"]
    f = collect.fpga_section({"usb": [], "pcie": [], "hats": [], "cameras": []},
                             tt_health={"board": {"present": True},
                                        "kind": "fpga", "slug": "fpga-1",
                                        "version": "1.2.2"})
    assert f["boards"][0]["kind"] == "tt-demo-board"


def test_document_carries_all_sections():
    doc = collect.document(root=ROOT, site="welland", hostname="pi-sw2-p47",
                           tt_url=None)
    assert doc["schema"] == 1
    assert set(doc) == {"schema", "machine", "software", "connection",
                        "peripherals", "fpga"}

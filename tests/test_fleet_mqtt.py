"""The fleet scripts against a real paho-mqtt and a real mosquitto.

Skipped unless both are present; FLEET_MQTT_REQUIRED=1 (set in CI) turns the
skip into a failure. CI runs it once per paho-mqtt the Pi roots ship (bookworm
1.6.1, trixie 2.x): the unit tests use a fake client, which cannot catch an
API the installed library does not have."""

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "fleet-scripts"))
import fleet_agent  # noqa: E402

REQUIRED = os.environ.get("FLEET_MQTT_REQUIRED") == "1"
try:
    import paho.mqtt.client as mqtt
    import paho.mqtt.subscribe as subscribe
except ImportError:
    if REQUIRED:
        raise
    pytest.skip("paho-mqtt not installed", allow_module_level=True)
MOSQUITTO = shutil.which("mosquitto") or shutil.which("mosquitto", path="/usr/sbin")

DOC = {"schema": 1, "machine": {"serial": "c36b093f773d46b8"},
       "connection": {"site": "welland", "hostname": "pi-sw2-p47"}}


@pytest.fixture
def broker(tmp_path):
    if not MOSQUITTO:
        if REQUIRED:
            pytest.fail("mosquitto not installed and FLEET_MQTT_REQUIRED=1")
        pytest.skip("mosquitto not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    proc = subprocess.Popen([MOSQUITTO, "-c", str(conf)])
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_agent_registers_through_a_real_broker(broker):
    cfg = {"site": "welland", "broker": "127.0.0.1", "port": broker}
    client = fleet_agent.mqtt_client(mqtt)
    fleet_agent.run(cfg, client, lambda: DOC, sleep_fn=lambda s: None, beats=1)
    msg = subscribe.simple("fpgas/welland/pi/c36b093f773d46b8/registration",
                           hostname="127.0.0.1", port=broker, retained=True)
    assert json.loads(msg.payload) == DOC


def test_event_publish_sequence_through_a_real_broker(broker):
    # fleet_event.main's client calls, minus reading /proc/cpuinfo
    client = fleet_agent.mqtt_client(mqtt)
    client.connect("127.0.0.1", broker)
    client.loop_start()
    info = client.publish("fpgas/welland/pi/abc/event", "{}", qos=1)
    info.wait_for_publish(timeout=10)
    assert info.is_published()
    client.disconnect()
    client.loop_stop()

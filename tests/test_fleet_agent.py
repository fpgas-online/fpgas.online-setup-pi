import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "fleet-scripts"))
import fleet_agent  # noqa: E402
import fleet_event  # noqa: E402

DOC = {"schema": 1, "machine": {"serial": "c36b093f773d46b8"},
       "connection": {"site": "welland", "hostname": "pi-sw2-p47"}}
CFG = {"site": "welland", "broker": "10.21.0.1", "port": 1883}


class FakeClient:
    def __init__(self):
        self.calls = []      # ordered (method, ...) tuples
        self.published = []  # (topic, payload dict, retain)

    def will_set(self, topic, payload, qos=0, retain=False):
        self.calls.append(("will_set", topic, json.loads(payload), retain))

    def connect(self, host, port):
        self.calls.append(("connect", host, port))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def publish(self, topic, payload, qos=0, retain=False):
        self.calls.append(("publish", topic))
        self.published.append((topic, json.loads(payload), retain))

    def disconnect(self):
        self.calls.append(("disconnect",))


def run(client, collect_fn, beats, recollect_every=360):
    fleet_agent.run(CFG, client, collect_fn, sleep_fn=lambda s: None,
                    beats=beats, recollect_every=recollect_every)


def test_lwt_set_retained_on_status_topic_before_connect():
    client = FakeClient()
    run(client, lambda: DOC, beats=0)
    will, connect = client.calls[0], client.calls[1]
    assert will[0] == "will_set" and connect[0] == "connect"
    assert will[1] == "fpgas/welland/pi/c36b093f773d46b8/status"
    assert will[2] == {"online": False, "reason": "connection-lost"}
    assert will[3] is True  # retained


def test_registration_retained_and_republished_only_on_change():
    client = FakeClient()
    docs = [DOC, DOC, {**DOC, "peripherals": {"usb": [{"vid": "0403"}]}}]
    run(client, lambda: docs.pop(0), beats=2, recollect_every=1)
    reg_topic = "fpgas/welland/pi/c36b093f773d46b8/registration"
    regs = [(t, r) for t, _, r in client.published if t == reg_topic]
    assert regs == [(reg_topic, True), (reg_topic, True)]  # initial + change


def test_status_beats_carry_online_and_fingerprint():
    client = FakeClient()
    run(client, lambda: DOC, beats=2)
    status_topic = "fpgas/welland/pi/c36b093f773d46b8/status"
    beats = [p for t, p, r in client.published if t == status_topic and p["online"]]
    assert len(beats) == 2
    assert beats[0]["fingerprint"] == fleet_agent.fingerprint(DOC)
    assert beats[0]["ts"]  # ISO timestamp present


def test_shutdown_publishes_offline_status_and_event():
    client = FakeClient()
    run(client, lambda: DOC, beats=1)
    status_topic = "fpgas/welland/pi/c36b093f773d46b8/status"
    event_topic = "fpgas/welland/pi/c36b093f773d46b8/event"
    last_status = [p for t, p, r in client.published if t == status_topic][-1]
    assert last_status == {"online": False, "reason": "shutdown"}
    events = [p for t, p, r in client.published if t == event_topic]
    assert events and events[-1]["stage"] == "shutdown"
    assert client.calls[-1] == ("disconnect",)


def test_load_config_and_topics(tmp_path):
    cfg_file = tmp_path / "fleet.toml"
    cfg_file.write_text('site = "welland"\nbroker = "10.21.0.1"\nport = 1883\n')
    cfg = fleet_agent.load_config(cfg_file)
    assert cfg == CFG
    t = fleet_agent.topics("welland", "abc")
    assert t == {"registration": "fpgas/welland/pi/abc/registration",
                 "status": "fpgas/welland/pi/abc/status",
                 "event": "fpgas/welland/pi/abc/event"}


def test_fleet_event_builds_topic_and_payload():
    topic, payload = fleet_event.build(
        stage="ssh-up", details=["port=22"], site="welland", serial="abc",
        boot_id="b1", ts="2026-09-01T00:00:00+00:00")
    assert topic == "fpgas/welland/pi/abc/event"
    assert payload == {"stage": "ssh-up", "boot_id": "b1",
                       "ts": "2026-09-01T00:00:00+00:00",
                       "detail": {"port": "22"}}

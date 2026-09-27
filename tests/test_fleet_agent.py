import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "fleet-scripts"))
import fleet_agent  # noqa: E402
import fleet_event  # noqa: E402

DOC = {"schema": 1, "machine": {"serial": "c36b093f773d46b8"},
       "connection": {"site": "welland", "hostname": "pi-sw2-p47"}}
CFG = {"site": "welland", "broker": "10.21.0.1", "port": 1883}


class FakeInfo:
    def __init__(self, calls, topic):
        self.calls, self.topic = calls, topic

    def wait_for_publish(self, timeout=None):
        self.calls.append(("acked", self.topic))

    def is_published(self):
        return True


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
        return FakeInfo(self.calls, topic)

    def disconnect(self):
        self.calls.append(("disconnect",))


def run(client, collect_fn, beats, recollect_every=360, uptime=10**6):
    fleet_agent.run(CFG, client, collect_fn, sleep_fn=lambda s: None,
                    beats=beats, recollect_every=recollect_every,
                    uptime_fn=lambda: uptime,
                    notify_fn=lambda m: client.calls.append(("notify", m)))


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


class _Paho1:
    """paho-mqtt 1.6.1 (bookworm): no CallbackAPIVersion."""
    class Client:
        def __init__(self, *args):
            self.args = args


class _Paho2(_Paho1):
    """paho-mqtt 2.x (trixie): the callback API must be chosen."""
    class CallbackAPIVersion:
        VERSION2 = "v2"


def test_mqtt_client_on_paho_1_passes_no_callback_api():
    assert fleet_agent.mqtt_client(_Paho1).args == ()


def test_mqtt_client_on_paho_2_picks_callback_api_version2():
    assert fleet_agent.mqtt_client(_Paho2).args == ("v2",)


def test_every_beat_recollects_while_the_boot_settles():
    # The FPGA check and then the TT bridge come up after the agent: while
    # the Pi has been up under SETTLE_SECONDS, each beat re-collects, so the
    # TT board (or the test design the check left running) is registered
    # within a beat, not 6 h later.
    reg_topic = "fpgas/welland/pi/c36b093f773d46b8/registration"
    tt = {**DOC, "fpga": {"boards": [{"kind": "tt-demo-board"}]}}
    client = FakeClient()
    docs = [DOC, DOC, tt]
    run(client, lambda: docs.pop(0), beats=2, uptime=120)
    regs = [p for t, p, r in client.published if t == reg_topic]
    assert regs == [DOC, tt]
    # Once settled, only every recollect_every beats (or SIGHUP).
    client = FakeClient()
    calls = []
    run(client, lambda: calls.append(1) or DOC, beats=3,
        uptime=fleet_agent.SETTLE_SECONDS)
    assert len(calls) == 1


def test_ready_only_once_registration_and_status_are_acknowledged():
    # fpgas-verify is After= the agent (Type=notify) and its fpga-verifying
    # is dropped by the site for a machine that has not registered.
    client = FakeClient()
    run(client, lambda: DOC, beats=3)
    reg = "fpgas/welland/pi/c36b093f773d46b8/registration"
    status = "fpgas/welland/pi/c36b093f773d46b8/status"
    calls = [c for c in client.calls if c[0] in ("publish", "acked", "notify")]
    ready = calls.index(("notify", "READY=1"))
    assert ("acked", reg) in calls[:ready] and ("acked", status) in calls[:ready]
    assert calls.count(("notify", "READY=1")) == 1


class Unacked(FakeInfo):
    def wait_for_publish(self, timeout=None):
        raise RuntimeError("Message publish failed: The client is not currently connected.")

    def is_published(self):
        return False


def test_ready_anyway_when_the_broker_does_not_acknowledge():
    assert fleet_agent.confirmed([Unacked([], "t")], 1) is False
    client = FakeClient()
    client.publish = lambda *a, **k: Unacked(client.calls, a[0])
    run(client, lambda: DOC, beats=1)
    assert ("notify", "READY=1") in client.calls


def test_sd_notify_sends_to_the_socket(tmp_path, monkeypatch):
    import socket
    path = str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(path)
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        fleet_agent.sd_notify("READY=1")
        assert server.recv(64) == b"READY=1"
    monkeypatch.delenv("NOTIFY_SOCKET")
    fleet_agent.sd_notify("READY=1")  # outside systemd: nothing, no error


def test_the_acknowledgements_share_one_deadline():
    now = [0.0]
    given = []

    class Slow(FakeInfo):
        def wait_for_publish(self, timeout=None):
            given.append(timeout)
            now[0] += timeout  # never acknowledged: waits it all out

        def is_published(self):
            return False

    infos = [Slow([], "registration"), Slow([], "status")]
    assert fleet_agent.confirmed(infos, 30, clock=lambda: now[0]) is False
    assert given == [30, 0.0] and now[0] == 30


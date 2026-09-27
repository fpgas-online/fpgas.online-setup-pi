#!/usr/bin/env python3
"""fpgas.online fleet agent.

Publishes a retained registration document, a retained 60 s status beat
(with a retained LWT so the broker flips the Pi offline within seconds of
it vanishing), and a shutdown status + event on SIGTERM. Re-collects the
document every 6 h or on SIGHUP -- and on every beat for the first hour
after boot, while the Pi settles -- and republishes registration only when
the fingerprint changes.

Config: /etc/fpgas-online/fleet.toml (site, broker, port — no credentials,
the site broker's LAN listener is anonymous). stdlib + python3-paho-mqtt.
"""

import argparse
import datetime
import hashlib
import json
import os
import signal
import socket
import time
import tomllib

CONFIG_PATH = "/etc/fpgas-online/fleet.toml"
BEAT_SECONDS = 60
RECOLLECT_EVERY = 6 * 60 * 60 // BEAT_SECONDS  # beats between re-collects
# The agent starts early in the boot, so the site knows the Pi is up, before
# what the document describes has settled: the FPGA boot check (fpgas-verify,
# up to 30 min) runs after the agent and leaves its board running a test
# design, and the TT bridge (whose /health says which TT board is fitted)
# starts only once the check is done. So until the Pi has been up this long,
# every beat re-collects (a fingerprint that did not change republishes
# nothing).
SETTLE_SECONDS = 60 * 60
# How long the first registration and status may take to be acknowledged
# before the agent tells systemd it is ready anyway (a broker that is down
# must not hold up the FPGA boot check, which is After= this unit).
READY_WAIT_SECONDS = 30


def fingerprint(doc):
    # MUST stay byte-identical to fleet.services.fingerprint on the server
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_config(path=CONFIG_PATH):
    with open(path, "rb") as f:
        return tomllib.load(f)


def topics(site, serial):
    base = f"fpgas/{site}/pi/{serial}"
    return {kind: f"{base}/{kind}"
            for kind in ("registration", "status", "event")}


def boot_id():
    with open("/proc/sys/kernel/random/boot_id") as f:
        return f.read().strip()


def uptime_s():
    with open("/proc/uptime") as f:
        return int(float(f.read().split()[0]))


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def mqtt_client(mqtt):
    """A paho-mqtt client on bookworm's 1.6.1 and on trixie's 2.x alike.

    paho 2.0 added CallbackAPIVersion and wants it passed explicitly; 1.6.1
    has no such attribute, so naming it unconditionally crashed the agent on
    every bookworm Pi. Nothing here registers a callback, so the two APIs
    behave the same for this code."""
    api = getattr(mqtt, "CallbackAPIVersion", None)
    return mqtt.Client(api.VERSION2) if api else mqtt.Client()


def sd_notify(message):
    """Send `message` to systemd's notify socket (Type=notify); nothing
    outside systemd."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    if path.startswith("@"):  # abstract namespace
        path = "\0" + path[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect(path)
        s.sendall(message.encode())


def confirmed(infos, timeout):
    """Wait (up to `timeout` s in all) for the broker to acknowledge each
    QoS 1 publish; True when all were."""
    for info in infos:
        try:
            info.wait_for_publish(timeout=timeout)
        except (RuntimeError, ValueError):
            return False
    return all(info.is_published() for info in infos)


def status_payload(boot_id, uptime_s, fingerprint):
    return {"online": True, "boot_id": boot_id, "uptime_s": uptime_s,
            "fingerprint": fingerprint, "ts": _now_iso()}


def run(cfg, client, collect_fn, now_fn=_now_iso, sleep_fn=time.sleep,
        beats=None, recollect_every=RECOLLECT_EVERY, uptime_fn=uptime_s,
        notify_fn=sd_notify):
    """The agent loop. client/collect_fn/sleep_fn/uptime_fn/notify_fn
    injectable for tests; beats=None runs until SIGTERM/SIGINT, an integer
    runs that many status beats then shuts down (as if signalled).

    Ready (systemd Type=notify) once the broker has acknowledged the
    registration and the first status: the FPGA boot check is After= this
    unit, and the site drops boot events from a machine it has not seen
    register, so the check's `fpga-verifying` must not get there first."""
    stopping = []
    recollect = []
    try:
        signal.signal(signal.SIGTERM, lambda *a: stopping.append(True))
        signal.signal(signal.SIGINT, lambda *a: stopping.append(True))
        signal.signal(signal.SIGHUP, lambda *a: recollect.append(True))
    except ValueError:  # not the main thread (tests)
        pass

    doc = collect_fn()
    serial = doc["machine"]["serial"]
    t = topics(cfg["site"], serial)
    # LWT before connect: the broker owns the offline transition
    client.will_set(t["status"],
                    json.dumps({"online": False, "reason": "connection-lost"}),
                    qos=1, retain=True)
    client.connect(cfg["broker"], cfg["port"])
    client.loop_start()

    last_fp = fingerprint(doc)
    first = [client.publish(t["registration"], json.dumps(doc), qos=1,
                            retain=True)]

    beat = 0
    while not stopping and (beats is None or beat < beats):
        info = client.publish(t["status"],
                              json.dumps(status_payload(boot_id(), uptime_fn(),
                                                        last_fp)),
                              qos=1, retain=True)
        if first:
            first.append(info)
            if not confirmed(first, READY_WAIT_SECONDS):
                print("fleet agent: the broker has not acknowledged the "
                      "registration yet; carrying on", flush=True)
            notify_fn("READY=1")
            first = []
        beat += 1
        if (recollect or beat % recollect_every == 0
                or uptime_fn() < SETTLE_SECONDS):
            recollect.clear()
            doc = collect_fn()
            fp = fingerprint(doc)
            if fp != last_fp:
                last_fp = fp
                client.publish(t["registration"], json.dumps(doc),
                               qos=1, retain=True)
        if beats is None or beat < beats:
            sleep_fn(BEAT_SECONDS)

    client.publish(t["status"],
                   json.dumps({"online": False, "reason": "shutdown"}),
                   qos=1, retain=True)
    client.publish(t["event"],
                   json.dumps({"stage": "shutdown", "boot_id": boot_id(),
                               "ts": now_fn(), "detail": {}}),
                   qos=1)
    client.disconnect()


def main():
    import collect
    import paho.mqtt.client as mqtt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=CONFIG_PATH)
    args = parser.parse_args()
    cfg = load_config(args.config)

    def collect_fn():
        # hostname="" -> collect falls back to /etc/hostname, then the
        # kernel hostname (the netboot fleet's /etc/hostname is empty)
        return collect.document(site=cfg["site"])

    client = mqtt_client(mqtt)
    run(cfg, client, collect_fn)


if __name__ == "__main__":
    main()

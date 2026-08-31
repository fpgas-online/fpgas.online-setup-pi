#!/usr/bin/env python3
"""fpgas.online fleet agent.

Publishes a retained registration document, a retained 60 s status beat
(with a retained LWT so the broker flips the Pi offline within seconds of
it vanishing), and a shutdown status + event on SIGTERM. Re-collects the
document every 6 h or on SIGHUP and republishes registration only when the
fingerprint changes.

Config: /etc/fpgas-online/fleet.toml (site, broker, port — no credentials,
the site broker's LAN listener is anonymous). stdlib + python3-paho-mqtt.
"""

import argparse
import datetime
import hashlib
import json
import signal
import time
import tomllib

CONFIG_PATH = "/etc/fpgas-online/fleet.toml"
BEAT_SECONDS = 60
RECOLLECT_EVERY = 6 * 60 * 60 // BEAT_SECONDS  # beats between re-collects


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


def status_payload(boot_id, uptime_s, fingerprint):
    return {"online": True, "boot_id": boot_id, "uptime_s": uptime_s,
            "fingerprint": fingerprint, "ts": _now_iso()}


def run(cfg, client, collect_fn, now_fn=_now_iso, sleep_fn=time.sleep,
        beats=None, recollect_every=RECOLLECT_EVERY):
    """The agent loop. client/collect_fn/sleep_fn injectable for tests;
    beats=None runs until SIGTERM/SIGINT, an integer runs that many status
    beats then shuts down (as if signalled)."""
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
    client.publish(t["registration"], json.dumps(doc), qos=1, retain=True)

    beat = 0
    while not stopping and (beats is None or beat < beats):
        client.publish(t["status"],
                       json.dumps(status_payload(boot_id(), uptime_s(),
                                                 last_fp)),
                       qos=1, retain=True)
        beat += 1
        if recollect or beat % recollect_every == 0:
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

    with open("/etc/hostname") as f:
        hostname = f.read().strip()

    def collect_fn():
        return collect.document(site=cfg["site"], hostname=hostname)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    run(cfg, client, collect_fn)


if __name__ == "__main__":
    main()

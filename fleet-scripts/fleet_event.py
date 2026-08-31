#!/usr/bin/env python3
"""fleet-event: publish one boot-stage event and exit.

Usage: fleet-event <stage> [--detail k=v ...]

Hooked into systemd units for the standard stages (network-online,
time-synced, ssh-up, cam-streaming, tt-daemon-up, fpga-detected,
registered, shutdown); any other stage string is allowed."""

import argparse

import fleet_agent


def build(stage, details, site, serial, boot_id, ts):
    topic = fleet_agent.topics(site, serial)["event"]
    detail = dict(kv.split("=", 1) for kv in details)
    return topic, {"stage": stage, "boot_id": boot_id, "ts": ts,
                   "detail": detail}


def main():
    import json
    import re

    import paho.mqtt.client as mqtt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage")
    parser.add_argument("--detail", action="append", default=[],
                        metavar="K=V")
    parser.add_argument("--config", default=fleet_agent.CONFIG_PATH)
    args = parser.parse_args()
    cfg = fleet_agent.load_config(args.config)

    with open("/proc/cpuinfo") as f:
        serial = re.search(r"^Serial\s*:\s*(\S+)", f.read(), re.M).group(1)
    topic, payload = build(args.stage, args.detail, cfg["site"], serial,
                           fleet_agent.boot_id(), fleet_agent._now_iso())

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(cfg["broker"], cfg["port"])
    client.loop_start()
    client.publish(topic, json.dumps(payload), qos=1).wait_for_publish(timeout=10)
    client.disconnect()


if __name__ == "__main__":
    main()

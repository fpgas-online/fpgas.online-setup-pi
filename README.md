# fpgas.online-setup-pi

Configuration and services for Raspberry Pi nodes in the fpgas.online FPGA-as-a-Service platform.

## Overview

This repository contains everything needed to configure a Raspberry Pi as an fpgas.online node: shell environment setup, FPGA board detection services, status reporting, network interface naming, and SSH configuration. The contents are packaged as a `.deb` and deployed via the fpgas.online APT repository.

fpgas.online uses PoE-powered, network-booted Raspberry Pis, each connected to an FPGA board (Arty A7, NeTV2, Fomu, TinyTapeout). This package turns a bare Pi into a managed node that reports its status and detects attached hardware.

## Installation

After adding the fpgas.online APT repository:

```
apt install fpgas-online-setup-pi
```

The package is built from `nfpm.yaml` using [nfpm](https://nfpm.goreleaser.com/) and hosted at `https://fpgas-online.github.io/apt`.

Deployment is managed by the `onpi` Ansible role in [fpgas.online-infra](https://github.com/fpgas-online/fpgas.online-infra).

## What It Provides

- **Shell environment** -- zsh and tmux configuration for interactive sessions on Pi nodes.
- **FPGA board detection** -- systemd services (`arty_here`, `arty_blink`, `arty_wire`) that detect and interact with attached Arty A7 boards.
- **Status reporting** -- `pistat` systemd services backed by Python scripts that report Pi health and state to the central server.
- **Console banner** -- login banner showing node identity and status.
- **Network interface naming** -- udev `.link` files for predictable network interface names.
- **SSH configuration** -- authorized keys and SSH daemon settings for remote management.
- **Profile scripts** -- `/etc/profile.d/` scripts for environment setup on login.
- **Keyboard configuration** -- console keyboard layout settings.
- **USB gadget console** -- on OTG-capable boards (Orange Pi H3, Pi 4/5 with `dtoverlay=dwc2,dr_mode=peripheral`) udev loads `g_serial` when a USB device controller appears and the host at the OTG port gets two CDC-ACM ports: the kernel log (replayed from boot by `fpgas-usb-console.service`) and a login getty. Booting never waits for a host. On the host side the same package captures every attached board's log port to `/var/log/fpgas-usb-console/<usb port>.log` from the first byte (`fpgas-usb-console-log@.service`), since the board's ring buffer wraps within minutes under debug logging (in `usb-console/`).
- **FEL boot host** -- udev-triggered `fpgas-felboot@.service` loads U-Boot (vendored in `felboot/u-boot/`) into Allwinner boards that enumerate in FEL mode on this Pi's USB, so PoE-cycled Orange Pi H3 boards netboot without an operator.

## Directory Structure

```
onpi/           Tmux configs, pistat systemd services, arty detection services
fixpi/          profile.d scripts, SSH config, keyboard settings, network .link files
pistat-scripts/ Python status reporter scripts
felboot/        FEL-boot script, udev rule, systemd template unit, vendored U-Boot image
usb-console/    USB gadget serial console: udev rules, modprobe options, kernel-log service
nfpm.yaml       Package definition for building the .deb
ruff.toml       Python linter configuration
```

## Linting

- Python: [ruff](https://docs.astral.sh/ruff/)
- Shell: [shellcheck](https://www.shellcheck.net/)

## Related Repositories

- [fpgas.online-infra](https://github.com/fpgas-online/fpgas.online-infra) -- Ansible playbooks that deploy this package
- [fpgas.online-netboot-pi](https://github.com/fpgas-online/fpgas.online-netboot-pi) -- Netboot filesystem preparation
- [apt](https://github.com/fpgas-online/apt) -- APT repository hosting the built `.deb`

## License

See [LICENSE](LICENSE).

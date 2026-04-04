## Background

This repo is part of the [fpgas.online](https://fpgas.online) FPGA-as-a-Service platform.
The platform provides remote access to real FPGA boards (Arty A7, NeTV2, Fomu, TinyTapeout)
via PoE-powered Raspberry Pis that are network-booted. There are two deployment sites:
Welland (private test lab) and PS1 hackerspace (public service in Chicago).

This codebase was extracted from the original monorepo [`carlfk/pici`](https://github.com/CarlFK/pici)
in April 2026 using `git filter-repo` to preserve commit history. The monorepo was split into
purpose-specific repos under the `fpgas-online` GitHub organization, where each repo produces
installable artifacts (pip packages or deb packages) consumed by the infrastructure repo.

## Repository Overview

Everything that configures a Raspberry Pi as an fpgas.online node. Installed as a
deb package on each Pi via `apt install fpgas-online-setup-pi`.

### What This Package Provides

- **Shell environment**: zsh, tmux, zprofile configs (in `onpi/tmux/`)
- **FPGA board detection**: arty_here, arty_blink, arty_wire systemd services and scripts (in `onpi/`)
- **Pi status reporting**: pistat systemd services + Python sender scripts (in `onpi/` and `pistat-scripts/`)
- **Network interface naming**: USB-path-based .link files for eth-uplink and eth-fpga (in `fixpi/etc/systemd/network/`)
- **System config**: SSH password config, US keyboard, console banner, profile.d scripts (in `fixpi/`)

### Directory Structure

- `onpi/` -- Files from the original `ansible/roles/onpi/files/`
- `fixpi/` -- Files from the original `ansible/roles/fixpi/files/`
- `pistat-scripts/` -- Python status reporter scripts from `pistat/scripts/`
- `nfpm.yaml` -- Deb package build configuration

### Packaging

Built as a `.deb` via nfpm. Published to the fpgas.online apt repo.
The infra repo's `onpi` ansible role installs this package on Pis.

## Conventions

- **Python**: Use `uv` for all Python commands (`uv run`, `uv pip`). Never use bare `python` or `pip`.
- **Dates**: Use ISO 8601 (YYYY-MM-DD) or day-first formats. Never American-style month-first dates.
- **Commits**: Make small, discrete commits. Each logical unit of work gets its own commit.
- **License**: Apache 2.0.
- **Linting**: All repos have CI lint workflows. Fix lint errors before pushing.
- **No force push**: Branch protection is enabled on main. Never force push.

## Related Repos

| Repo | Purpose |
|------|---------|
| [fpgas.online-infra](https://github.com/fpgas-online/fpgas.online-infra) | Ansible infrastructure (playbooks, roles, inventory) |
| [fpgas.online-site](https://github.com/fpgas-online/fpgas.online-site) | Django web application |
| [fpgas.online-poe](https://github.com/fpgas-online/fpgas.online-poe) | SNMP PoE switch management |
| [fpgas.online-cam](https://github.com/fpgas-online/fpgas.online-cam) | Camera capture and streaming |
| [fpgas.online-setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi) | Raspberry Pi environment setup |
| [fpgas.online-netboot-pi](https://github.com/fpgas-online/fpgas.online-netboot-pi) | Netboot filesystem tools |
| [fpgas.online-tools](https://github.com/fpgas-online/fpgas.online-tools) | Utility scripts |
| [fpgas.online-test-designs](https://github.com/fpgas-online/fpgas.online-test-designs) | FPGA test designs |
| [apt](https://github.com/fpgas-online/apt) | APT package repository (GitHub Pages) |

## Linting

- ruff: blocking (Python scripts in `pistat-scripts/`)
- shellcheck: blocking (shell scripts)

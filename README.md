## Super Protocol VM Watchdog Daemon – Build & Run Guide

This document explains how to **build**, **package (.deb)** and **run** the `sp-vm-watchdog-daemon`, which is responsible for managing the lifecycle of Super Protocol virtual machines (start, health check, restart on failure/config change).

All instructions target a Debian-based Linux distribution (Ubuntu, Debian, etc.).

---

## 1. Repositories & Layout

- Downloader daemon repo: https://github.com/Super-Protocol/sp-vm-downloader-daemon
- Watchdog daemon repo:  https://github.com/Super-Protocol/sp-vm-watchdog-daemon
- VM image repo: https://github.com/Super-Protocol/sp-vm

The daemons are designed to be installed as system services and communicate over a UNIX socket:

- Images stored under: `/var/lib/sp/images`
- Watchdog VM cache: `/var/lib/sp/watchdog/cache`
- Watchdog runtime data (pids, logs): `/var/run/sp/watchdog/vms`
- Downloader gRPC socket: `/var/run/sp-vm-downloader.sock`

---

## 2. Prerequisites

On a build host you will need:

- Python 3 (3.10+ recommended)
- `python3-venv`
- `git`
- `make`
- `dpkg-deb`
- A Debian-based system (for `.deb` packaging)

Install base tools:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git make dpkg-dev
```

---

## 3. Building From Source (Without .deb)

### 3.1. Local Run

```bash
cd sp-vm-watchdog-daemon

# Create venv, generate protobuf, install deps and run
make run ARGS="--config /etc/sp/watchdog/config.json --log-level INFO"
```

`main.py` arguments:

- `--config PATH` – main text config file (default `/etc/sp/watchdog/config.json`)
- `--log-level LEVEL` – logging level

The watchdog daemon will:

- Load text config (global settings) from `config.json`
- Load per‑VM configs from `/etc/sp/watchdog/vms/*.json`
- Ensure VMs are started, healthy and up‑to‑date with configuration

> **Note:** in production the daemon should run as **root** (QEMU, VFIO, mounts, network). For local testing you can run it with `sudo make run ...`.

---

## 4. Building .deb Package

The packaging flow is handled by the `Makefile`.

```bash
cd sp-vm-watchdog-daemon

make clean
make VERSION=1.0.0
```

This will:

- Initialize the `lib/sp-vm-proto` submodule
- Create a virtualenv in `build/sp-vm-watchdog-daemon_<VERSION>-1_amd64/usr/bin/sp-vm-watchdog-daemon`
- Install Python dependencies from:
  - `app/requirements.txt`
  - `app/lint_requirements.txt`
- Generate gRPC Python modules into `app/modules/proto`
- Copy both `app/` and `lib/` into the package
- Install the systemd unit: `etc/systemd/system/sp-vm-watchdog-daemon.service`
- Add Debian control scripts (`control`, `postinst`, `prerm`, `postrm`)

Resulting package:

```bash
build/sp-vm-watchdog-daemon_1.0.0-1_amd64.deb
```

---

## 5. Installing the .deb Package

Copy the `.deb` file to the target host and install:

```bash
cd /path/to/packages
sudo dpkg -i sp-vm-watchdog-daemon_1.0.0-1_amd64.deb
```

The `postinst` script and systemd unit will:

- Register the service: `sp-vm-watchdog-daemon.service`
- Place code and the virtualenv under `/usr/bin/sp-vm-watchdog-daemon`
- Ensure runtime directories exist under `/var/run/sp/watchdog` and `/var/lib/sp/watchdog/cache`

Enable the service on boot (if not already enabled by `postinst`):

```bash
sudo systemctl enable sp-vm-watchdog-daemon
```

Start it:

```bash
sudo systemctl start sp-vm-watchdog-daemon
```

Check status:

```bash
sudo systemctl status sp-vm-watchdog-daemon
```

---

## 6. Configuration

### 6.1. Global Text Config

The watchdog daemon expects a main text config (JSON) – by default at `/etc/sp/watchdog/config.json`.

Example:

```json
{
  "vm_config": {
    "configs_dir": "/etc/sp/watchdog/vms",
    "authorized_keys_file": "/home/provider/.ssh/authorized_keys"
  }
}
```

- `configs_dir` – directory where per‑VM JSON configs live
- `authorized_keys_file` – optional; if set and `debug` is enabled for a VM, the file will be baked into the provider‑config disk to enable SSH access.

If the file does not exist, the daemon will create a default one on first run (see `TextConfig.load_or_default` in `app/modules/config.py`).

### 6.2. Per‑VM Configuration

Each VM is described by a JSON file in `/etc/sp/watchdog/vms`, for example:

```json
{
  "name": "my-vm",
  "enabled": true,
  "run_configuration": {
    "debug": true,
    "vm_build": "build-285",
    "argo_branch": "main",
    "argo_sp_env": "main",
    "provider_config": {
      "execution_controller_tee_prov_configmap": "/path/to/manifests/configmap.execution-controller-tee-prov.yaml",
      "sp_pki_challenge_secret": "/path/to/manifests/secret.sp-pki-challenge.yaml"
    }
  },
  "qemu_configuration": {
    "cores": 30,
    "mem_gb": 96,
    "state_disk_size_gb": 300,
    "gpus": null,
    "mac_address": "52:54:00:12:34:56",
    "ip_address": "0.0.0.0",
    "ssh_port": 2222,
    "wg_port": 51820,
    "http_port": 80,
    "https_port": 443,
    "mode": "auto"
  }
}
```

Key fields:

- **Top level**
  - `name` – VM name (must be unique)
  - `enabled` – if `false`, watchdog will ignore this VM

- **run_configuration**
  - `debug` – if `true`, exposes SSH and increases logging
  - `vm_build` – VM image version; if `"auto`" or `null`, watchdog asks downloader for latest GitHub release
  - `build_dir` – alternative to `vm_build` for local builds (mutually exclusive)
  - `argo_branch`, `argo_sp_env` – passed to kernel cmdline for in‑VM boot configuration
  - `provider_config.execution_controller_tee_prov_configmap` – path to the provider ConfigMap file
  - `provider_config.sp_pki_challenge_secret` – (optional) path to PKI challenge Secret

- **qemu_configuration**
  - `cores` – number of vCPUs
  - `mem_gb` – RAM in gigabytes (must be > 8)
  - `state_disk_size_gb` – state disk size in GB (must be > 400)
  - `gpus` – list of PCI device IDs for passthrough (for example `["c1:00.0"]`), or `null` for default behavior
  - `cache_dir` – optional; if omitted, defaults to `/var/lib/sp/watchdog/cache/<vm-name>`
  - `mac_address` – NIC MAC
  - `ip_address` – host IP used for port forwarding
  - `ssh_port`, `wg_port`, `http_port`, `https_port` – host ports
  - `mode` – `"auto"`, `"tdx"`, `"sev-snp"`, `"untrusted"`
  - `guest_cid` – vsock guest CID (optional; auto-assigned if missing)

The watchdog daemon validates:

- Uniqueness of VM names
- Uniqueness of ports (for enabled VMs), `guest_cid` for TDX mode, etc.
- Presence of GPUs when specified

### 6.3. Image Management via Downloader

The watchdog uses the downloader daemon (over `/var/run/sp-vm-downloader.sock`) through `app/modules/image_manager.py` to obtain:

- VM rootfs image path
- Kernel (`vmlinuz`)
- BIOS images (`OVMF.fd`, `OVMF_AMD.fd`)
- Rootfs hash (`rootfs_hash.txt`)

The downloader daemon must be running and correctly configured for the watchdog to start VMs.

---

### 6.4. Using a Separate Data Disk for Images

By default, VM images are stored under `/var/lib/sp/images` (managed by the downloader daemon).
If you have a large data disk mounted at `/data` and want to store images under `/data/vm/images`, you can use a symlink:

```bash
sudo mkdir -p /data/vm/images

# (optional) move existing images to the new location
sudo rsync -a /var/lib/sp/images/ /data/vm/images/

# replace the original directory with a symlink
sudo rm -rf /var/lib/sp/images
sudo ln -s /data/vm/images /var/lib/sp/images
```

After this, the downloader daemon and watchdog will continue to use `/var/lib/sp/images`,
but the actual data will be stored on the larger `/data` disk.

---

## 7. Runtime Management & Diagnostics

### 7.1. Service Management

```bash
# Start service
sudo systemctl start sp-vm-watchdog-daemon

# Stop service
sudo systemctl stop sp-vm-watchdog-daemon

# Restart service
sudo systemctl restart sp-vm-watchdog-daemon

# Enable on boot
sudo systemctl enable sp-vm-watchdog-daemon
```

### 7.2. Logs

Watchdog daemon logs:

```bash
sudo journalctl -u sp-vm-watchdog-daemon -f
```

Per‑VM logs (from QEMU stdout/stderr):

```bash
ls -la /var/run/sp/watchdog/vms/
tail -f /var/run/sp/watchdog/vms/my-vm.log
```

### 7.3. State & Provider Config Disks

For each VM, the watchdog will maintain:

- State disk: `<cache_dir>/state.qcow2`
- Provider config disk: `<cache_dir>/provider_config.img`

On each (re)start the daemon:

- Recreates the state disk with the configured size
- Rebuilds the provider config disk from the files referenced in the VM config

If it cannot remove an old disk because it is still in use, it will raise an error (see `is_file_in_use` in `app/modules/utils.py`).

---

## 8. Typical End‑to‑End Flow

1. **Build .deb packages** for both daemons on a build machine:

   ```bash
   cd sp-vm-downloader-daemon
   make clean && make VERSION=1.0.0

   cd ../sp-vm-watchdog-daemon
   make clean && make VERSION=1.0.0
   ```

2. **Install packages** on the provider host:

   ```bash
   sudo dpkg -i sp-vm-downloader-daemon_1.0.0-1_amd64.deb
   sudo dpkg -i sp-vm-watchdog-daemon_1.0.0-1_amd64.deb
   ```

3. **Prepare configuration**:

   ```bash
   sudo mkdir -p /etc/sp/watchdog/vms

   # /etc/sp/watchdog/config.json (global)
   # /etc/sp/watchdog/vms/my-vm.json (VM definition)
   ```

4. **Start services**:

   ```bash
   sudo systemctl start sp-vm-downloader-daemon
   sudo systemctl start sp-vm-watchdog-daemon
   ```

5. **Verify**:

   ```bash
   sudo systemctl status sp-vm-downloader-daemon
   sudo systemctl status sp-vm-watchdog-daemon

   ls -la /var/run/sp/watchdog/vms/
   tail -f /var/run/sp/watchdog/vms/my-vm.log
   ```

From this point, the watchdog daemon will automatically:

- Start enabled VMs defined in `/etc/sp/watchdog/vms`
- Restart them on failure or configuration change
- Use the downloader daemon to fetch and update VM images as needed.


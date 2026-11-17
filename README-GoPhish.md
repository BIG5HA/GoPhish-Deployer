# GoPhish Deployment Automation

**Python · Linux Infrastructure · Security Awareness Labs**

An interactive Python 3 deployment utility for setting up [GoPhish](https://github.com/gophish/gophish) in an authorized security-awareness or training environment. The script handles environment checks, a pinned release download, archive integrity verification, TLS configuration, systemd service setup, and post-deployment health checks.

> **Responsible use:** Deploy only on infrastructure you own or are explicitly authorized to administer. Run awareness campaigns only with the necessary permission and appropriate handling of participant data.

## What this repository contains

```text
gophish-deployer.py    # Interactive Ubuntu deployment script
README.md              # This guide
```

The deployment utility is an independent automation project; GoPhish itself is maintained by its upstream authors. The script downloads the official GoPhish release rather than bundling its binary.

## Features

- **Two deployment modes:** Local Lab and Remote Training Server.
- **Interactive configuration:** deployment mode, domain/contact details and TLS choice where applicable.
- **Environment validation:** Linux, Ubuntu for actual deployments, x86-64 architecture, and root privileges.
- **Dependencies:** APT-based installation of `unzip`, `curl`, `certbot` and `ca-certificates`.
- **Pinned upstream release:** GoPhish **`v0.12.1`**, with a matching ZIP filename and a built-in SHA-256 checksum.
- **Archive safety checks:** reject paths outside the installation directory and archive symlinks.
- **TLS options for remote mode:** manual Certbot DNS-01 validation or an existing certificate/key pair.
- **Managed service:** a dedicated `gophish-lab` system user and a systemd unit with several hardening settings.
- **Validation:** checks systemd service status, then retries an HTTPS health check against the local admin interface.
- **Preview mode:** `--dry-run` summarizes the intended work without performing installation steps.

## Requirements

- **Ubuntu Linux**, x86-64, with Python 3.
- Root access (`sudo`) for a real installation.
- APT and a working network connection to retrieve dependencies and the official release.
- For remote mode: an authorized domain and TLS certificate setup.
- For an existing-certificate installation: paths to the certificate and its private key.

The script uses the **Python standard library**; there is no `requirements.txt` or `pip install` step in the provided source.

## Usage

### Preview the workflow

```bash
python3 gophish-deployer.py --dry-run
```

This still opens the interactive configuration prompts. It reports intended package installation, release handling, configuration and service setup, but does **not** run the full deployment or network validation.

### Deploy on an authorized Ubuntu server

```bash
sudo python3 gophish-deployer.py
```

The wizard offers:

1. **Local Lab:** landing listener defaults to `127.0.0.1:8080`.
2. **Remote Training Server:** asks for the domain and contact email, then lets you select **Certbot DNS Challenge** or **Existing Certificate**. The configured landing listener is `0.0.0.0:443`.

The admin listener is configured as **`127.0.0.1:3333`**, independently of the selected mode.

### Optional system package upgrades

```bash
sudo python3 gophish-deployer.py --upgrade
```

`--upgrade` performs an APT system upgrade as part of the installation workflow; it is **not** a command to upgrade an existing GoPhish installation.

### Available flags

| Option | Meaning |
| --- | --- |
| `--dry-run` | Print planned actions; do not install or configure the application. |
| `--upgrade` | Run `apt-get upgrade -y` during package preparation. |

## Deployment workflow

```text
Interactive configuration
          ↓
Operating system / architecture / privilege checks
          ↓
APT dependency installation
          ↓
Latest GitHub release metadata check
          ↓
Version pin + SHA-256 verification
          ↓
Archive validation and extraction
          ↓
TLS and config.json generation
          ↓
Dedicated service account + systemd unit
          ↓
Service state + HTTPS admin health check
```

### Files and services created

| Location or setting | Value in the script |
| --- | --- |
| Installation directory | `/opt/gophish` |
| systemd unit | `/etc/systemd/system/gophish-lab.service` |
| Service identity | `gophish-lab` |
| Admin endpoint | `https://127.0.0.1:3333` |
| Local Lab landing listener | `127.0.0.1:8080` |
| Remote landing listener | `0.0.0.0:443` |
| Remote copied TLS files | `/opt/gophish/tls/` |

The service unit includes `NoNewPrivileges`, `PrivateTmp`, `ProtectHome`, `ProtectSystem`, `UMask=0077`, and `CAP_NET_BIND_SERVICE`. These settings are present in the generated unit; this README does not claim an independently audited hardened deployment.

## Operational notes

- **No overwrite:** the real deployment stops if `/opt/gophish` already exists. The script is not an in-place updater.
- **Pinned release:** the script checks the upstream *latest* release and **refuses to proceed** if its tag differs from `v0.12.1`. If a newer release exists, the pin and SHA-256 must be reviewed; the script does not silently switch versions.
- **Manual DNS-01:** Certbot's manual certificate mode requires DNS interaction and does **not** configure automatic certificate renewal.
- **Self-signed admin TLS:** the admin-side health check intentionally accepts the locally generated self-signed admin certificate; this is not general-purpose TLS verification.
- **Initial credentials:** the script points the operator to the service journal to retrieve GoPhish startup information and advises changing the initial admin password.
- **Admin interface:** it binds the admin service to localhost. Do not expose the admin interface publicly without separate access controls.

## Troubleshooting

Check the generated service and logs:

```bash
sudo systemctl status gophish-lab
sudo journalctl -u gophish-lab --no-pager
```

Verify whether the loopback admin endpoint is reachable after startup:

```bash
curl -k -I https://127.0.0.1:3333
```

The deployer retries the health check up to ten times, waiting two seconds between failures. If deployment stops early, inspect the script's explicit error output, the APT state, certificate paths and systemd journal.

## Project scope

This repository documents **deployment automation**, not a bundled phishing campaign, credential-collection template or a managed cloud hosting service. GoPhish is a separate upstream project. Use the application only in approved training and testing scenarios.

## Credits

- **GoPhish:** [gophish/gophish](https://github.com/gophish/gophish)
- **Deployment automation and lab documentation:** Nehoray Shaul
- **Portfolio case study:** [GoPhish Project](https://bigsha.pages.dev/projects/gophish/)

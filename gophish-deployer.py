#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from pathlib import Path


# ==========================================
# GLOBAL CONFIGURATION
# ==========================================

INSTALL_DIR = Path("/opt/gophish")
SERVICE_NAME = "gophish-lab"
SERVICE_USER = "gophish-lab"

RELEASE_API = (
    "https://api.github.com/repos/gophish/gophish/releases/latest"
)

VERSION = "v0.12.1"
ARCHIVE_NAME = "gophish-v0.12.1-linux-64bit.zip"

SHA256 = (
    "44f598c1eeb72c3b08fa73d57049022"
    "d96cea2872283b87a73d21af78a2c6d47"
)

ADMIN_ADDRESS = "127.0.0.1:3333"
ADMIN_URL = "https://127.0.0.1:3333"


# ==========================================
# HELPERS
# ==========================================

def log(message):
    print(message, flush=True)


def run_command(command, dry_run=False):
    if dry_run:
        log(f"[DRY RUN] {' '.join(command)}")
        return

    subprocess.run(command, check=True)


def ask_choice(prompt, choices):
    while True:
        answer = input(prompt).strip()

        if answer in choices:
            return answer

        log(f"[-] Invalid selection. Choose: {', '.join(choices)}")


def ask_yes_no(prompt, default=False):
    answer = input(prompt).strip().lower()

    if not answer:
        return default

    return answer in ("y", "yes")


def validate_domain(domain):
    pattern = (
        r"^(?=.{1,253}$)"
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}"
        r"[a-zA-Z0-9])?\.)+"
        r"[a-zA-Z]{2,63}$"
    )

    return bool(re.fullmatch(pattern, domain))


# ==========================================
# INTERACTIVE SETUP
# ==========================================

def interactive_setup():
    log("\n" + "=" * 44)
    log("          GOPHISH AUTO DEPLOY")
    log("=" * 44)

    log("\n[*] Select deployment mode:\n")
    log("[1] Local Lab")
    log("[2] Remote Training Server")

    mode = ask_choice(
        "\nSelect option [1/2]: ",
        ("1", "2")
    )

    config = {
        "mode": "local" if mode == "1" else "remote",
        "domain": None,
        "email": None,
        "tls_mode": "self-signed",
        "cert_path": None,
        "key_path": None,
        "landing_address": "127.0.0.1:8080",
        "contact_address": ""
    }

    if mode == "2":
        while True:
            domain = input(
                "\nEnter your domain: "
            ).strip().lower()

            if validate_domain(domain):
                break

            log("[-] Invalid domain name.")

        config["domain"] = domain

        email = input(
            "Enter contact email: "
        ).strip()

        if "@" not in email:
            raise ValueError("A contact email is required.")

        config["email"] = email
        config["contact_address"] = email
        config["landing_address"] = "0.0.0.0:443"

        log("\n[*] HTTPS configuration:\n")
        log("[1] Certbot DNS Challenge")
        log("[2] Existing Certificate")

        tls_choice = ask_choice(
            "\nSelect option [1/2]: ",
            ("1", "2")
        )

        if tls_choice == "1":
            config["tls_mode"] = "certbot"

        else:
            config["tls_mode"] = "existing"

            config["cert_path"] = input(
                "Certificate file path: "
            ).strip()

            config["key_path"] = input(
                "Private key file path: "
            ).strip()

    log("\n" + "=" * 44)
    log("           CONFIGURATION")
    log("=" * 44)

    log(f"Mode: {config['mode']}")
    log(f"Domain: {config['domain'] or 'None'}")
    log(f"Admin: {ADMIN_ADDRESS}")
    log(f"Landing: {config['landing_address']}")
    log(f"TLS: {config['tls_mode']}")

    if not ask_yes_no("\nProceed? [y/N]: "):
        raise RuntimeError("Deployment cancelled.")

    return config


# ==========================================
# ENVIRONMENT
# ==========================================

def check_environment(dry_run=False):
    log("\n[*] Checking deployment environment...")

    if platform.system() != "Linux":
        raise RuntimeError("Linux is required.")

    os_info = {}

    with open("/etc/os-release", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os_info[key] = value.strip("\"'")

    distro = os_info.get("ID", "unknown")

    log(
        "[+] Operating System: "
        + os_info.get("PRETTY_NAME", distro)
    )

    if distro != "ubuntu":
        if not dry_run:
            raise RuntimeError(
                f"Ubuntu required. Detected: {distro}"
            )

        log("[!] Non-Ubuntu system: dry-run only.")

    if not dry_run and os.geteuid() != 0:
        raise PermissionError(
            "Root privileges required. Use sudo."
        )

    architecture = platform.machine()

    if architecture not in ("x86_64", "amd64"):
        raise RuntimeError(
            f"Unsupported architecture: {architecture}"
        )

    log(f"[+] Supported architecture: {architecture}")


# ==========================================
# DEPENDENCIES
# ==========================================

def install_dependencies(upgrade=False, dry_run=False):
    log("\n[*] Preparing dependencies...")

    run_command(
        ["apt-get", "update"],
        dry_run
    )

    if upgrade:
        run_command(
            ["apt-get", "upgrade", "-y"],
            dry_run
        )

    run_command(
        [
            "apt-get", "install", "-y",
            "unzip",
            "curl",
            "certbot",
            "ca-certificates"
        ],
        dry_run
    )

    log("[+] Dependency stage completed.")


# ==========================================
# GITHUB RELEASE
# ==========================================

def get_latest_release():
    log("\n[*] Checking GitHub Releases...")

    request = urllib.request.Request(
        RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "gophish-auto-deploy"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        release = json.load(response)

    release_version = release.get("tag_name")

    log(f"[+] Latest release: {release_version}")

    if release_version != VERSION:
        raise RuntimeError(
            "A new version was published. "
            "Review its SHA256 before deployment."
        )

    for asset in release.get("assets", []):
        if asset["name"] == ARCHIVE_NAME:
            return asset["browser_download_url"]

    raise RuntimeError("Compatible release asset not found.")


# ==========================================
# DOWNLOAD & VERIFICATION
# ==========================================

def download_gophish(url, destination):
    log("\n[*] Downloading GoPhish...")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gophish-auto-deploy"}
    )

    with urllib.request.urlopen(
        request,
        timeout=120
    ) as response:

        with open(destination, "wb") as file:
            shutil.copyfileobj(response, file)

    log("[+] Download completed.")


def verify_checksum(archive):
    log("[*] Verifying SHA256...")

    digest = hashlib.sha256()

    with open(archive, "rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b""
        ):
            digest.update(block)

    if digest.hexdigest() != SHA256:
        raise RuntimeError(
            "SHA256 mismatch. Installation cancelled."
        )

    log("[+] Archive checksum verified.")


def extract_gophish(archive):
    log("[*] Extracting GoPhish...")

    INSTALL_DIR.mkdir(
        parents=True,
        exist_ok=False
    )

    with zipfile.ZipFile(archive) as zip_file:
        for entry in zip_file.infolist():
            target = (
                INSTALL_DIR / entry.filename
            ).resolve()

            if not target.is_relative_to(
                INSTALL_DIR.resolve()
            ):
                raise RuntimeError(
                    f"Unsafe archive entry: {entry.filename}"
                )

            file_type = (
                entry.external_attr >> 16
            ) & 0o170000

            if file_type == 0o120000:
                raise RuntimeError(
                    "Symbolic links in archive are not allowed."
                )

        zip_file.extractall(INSTALL_DIR)

    binary = INSTALL_DIR / "gophish"

    if not binary.is_file():
        raise RuntimeError("GoPhish binary missing.")

    binary.chmod(0o755)

    log("[+] GoPhish extracted successfully.")


# ==========================================
# SSL CONFIGURATION
# ==========================================

def configure_ssl(config):
    log("\n[*] Configuring TLS...")

    if config["mode"] == "local":
        log("[+] Local mode: self-signed Admin TLS.")
        return None

    domain = config["domain"]

    if config["tls_mode"] == "certbot":
        log("[*] Starting Certbot DNS-01 challenge...")
        log(
            "[*] Follow Certbot instructions to create "
            "the DNS TXT record."
        )

        run_command([
            "certbot",
            "certonly",
            "--manual",
            "--preferred-challenges", "dns",
            "--agree-tos",
            "--email", config["email"],
            "-d", domain
        ])

        certificate = Path(
            f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        )

        private_key = Path(
            f"/etc/letsencrypt/live/{domain}/privkey.pem"
        )

    else:
        certificate = Path(config["cert_path"])
        private_key = Path(config["key_path"])

    if not certificate.is_file():
        raise RuntimeError(
            f"Certificate not found: {certificate}"
        )

    if not private_key.is_file():
        raise RuntimeError(
            f"Private key not found: {private_key}"
        )

    # Validate that the certificate and key can be loaded.
    context = ssl.SSLContext(
        ssl.PROTOCOL_TLS_SERVER
    )

    context.load_cert_chain(
        str(certificate),
        str(private_key)
    )

    # The service user will read these copies.
    tls_dir = INSTALL_DIR / "tls"
    tls_dir.mkdir(mode=0o700, exist_ok=True)

    destination_cert = tls_dir / "fullchain.pem"
    destination_key = tls_dir / "privkey.pem"

    shutil.copy2(certificate, destination_cert)
    shutil.copy2(private_key, destination_key)

    destination_cert.chmod(0o600)
    destination_key.chmod(0o600)

    log("[+] TLS certificate and key validated.")

    return {
        "cert": "tls/fullchain.pem",
        "key": "tls/privkey.pem"
    }


# ==========================================
# GOPHISH CONFIGURATION
# ==========================================

def configure_gophish(config, tls_files):
    log("\n[*] Updating config.json...")

    config_path = INSTALL_DIR / "config.json"

    with open(config_path, encoding="utf-8") as file:
        settings = json.load(file)

    admin = settings["admin_server"]
    landing = settings["phish_server"]

    admin["listen_url"] = ADMIN_ADDRESS
    admin["use_tls"] = True

    admin["cert_path"] = "gophish_admin.crt"
    admin["key_path"] = "gophish_admin.key"

    landing["listen_url"] = config["landing_address"]

    if tls_files:
        landing["use_tls"] = True
        landing["cert_path"] = tls_files["cert"]
        landing["key_path"] = tls_files["key"]
    else:
        landing["use_tls"] = False

    settings["contact_address"] = config["contact_address"]

    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=4)

    config_path.chmod(0o600)

    log("[+] GoPhish configuration saved.")


# ==========================================
# SYSTEMD SERVICE
# ==========================================

def create_service_user():
    log("\n[*] Creating service user...")

    result = subprocess.run(
        ["id", "-u", SERVICE_USER],
        capture_output=True,
        check=False
    )

    if result.returncode != 0:
        run_command([
            "useradd",
            "--system",
            "--user-group",
            "--home-dir", str(INSTALL_DIR),
            "--shell", "/usr/sbin/nologin",
            SERVICE_USER
        ])

    run_command([
        "chown",
        "-R",
        f"{SERVICE_USER}:{SERVICE_USER}",
        str(INSTALL_DIR)
    ])

    log("[+] Service account ready.")


def create_systemd_service():
    log("\n[*] Creating Systemd service...")

    service_path = Path(
        f"/etc/systemd/system/{SERVICE_NAME}.service"
    )

    service_content = f"""[Unit]
Description=GoPhish Training Server
After=network.target

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
WorkingDirectory={INSTALL_DIR}
ExecStart={INSTALL_DIR}/gophish

Restart=on-failure
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths={INSTALL_DIR}
UMask=0077

AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
"""

    service_path.write_text(
        service_content,
        encoding="utf-8"
    )

    service_path.chmod(0o644)

    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", SERVICE_NAME])
    run_command(["systemctl", "start", SERVICE_NAME])

    log("[+] GoPhish Systemd service started.")


# ==========================================
# DEPLOYMENT VALIDATION
# ==========================================

def validate_deployment():
    log("\n[*] Validating deployment...")

    result = subprocess.run(
        ["systemctl", "is-active", SERVICE_NAME],
        capture_output=True,
        text=True,
        check=False
    )

    if result.stdout.strip() != "active":
        raise RuntimeError(
            "Systemd reports that GoPhish is not active."
        )

    # The admin interface uses a self-signed certificate.
    context = ssl._create_unverified_context()

    for attempt in range(10):
        try:
            with urllib.request.urlopen(
                ADMIN_URL,
                context=context,
                timeout=5
            ) as response:

                if response.status == 200:
                    log("[+] HTTPS Admin endpoint responding.")
                    log(f"[+] Final URL: {response.url}")
                    return

        except Exception as error:
            log(
                f"[*] Health check "
                f"{attempt + 1}/10: {error}"
            )

        time.sleep(2)

    raise RuntimeError(
        "Admin HTTPS health check failed."
    )


# ==========================================
# DEPLOYMENT WORKFLOW
# ==========================================

def deploy(args):
    config = interactive_setup()

    check_environment(dry_run=args.dry_run)

    if args.dry_run:
        log("\n[*] DRY RUN MODE ENABLED")

        install_dependencies(
            upgrade=args.upgrade,
            dry_run=True
        )

        log("[DRY RUN] Discover GitHub release.")
        log("[DRY RUN] Download and verify GoPhish.")
        log("[DRY RUN] Extract into /opt/gophish.")
        log("[DRY RUN] Configure config.json.")

        if config["tls_mode"] == "certbot":
            log("[DRY RUN] Run Certbot DNS-01 challenge.")
        elif config["tls_mode"] == "existing":
            log("[DRY RUN] Validate existing TLS files.")

        log("[DRY RUN] Create service account.")
        log("[DRY RUN] Create Systemd service.")
        log("[DRY RUN] Start and validate GoPhish.")

        log("\n[+] Dry run completed successfully.")
        return

    if INSTALL_DIR.exists():
        raise RuntimeError(
            f"{INSTALL_DIR} already exists. "
            "Existing installation will not be overwritten."
        )

    install_dependencies(upgrade=args.upgrade)

    release_url = get_latest_release()

    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / ARCHIVE_NAME

        download_gophish(release_url, archive)
        verify_checksum(archive)
        extract_gophish(archive)

    tls_files = configure_ssl(config)

    configure_gophish(config, tls_files)
    create_service_user()
    create_systemd_service()
    validate_deployment()

    log("\n" + "=" * 44)
    log("       DEPLOYMENT COMPLETED")
    log("=" * 44)

    log(f"[+] Service: {SERVICE_NAME}")
    log(f"[+] Admin URL: {ADMIN_URL}")
    log(f"[+] Landing listener: {config['landing_address']}")

    if config["domain"]:
        log(f"[+] Domain: {config['domain']}")

    log("\n[*] Retrieve initial Admin credentials:")
    log(
        f"sudo journalctl -u {SERVICE_NAME} "
        "--no-pager"
    )

    log("\n[!] Change the initial Admin password.")
    log("[!] Keep the Admin interface private.")

    if config["tls_mode"] == "certbot":
        log(
            "[!] Manual DNS certificates require "
            "manual renewal."
        )


# ==========================================
# MAIN
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="Interactive GoPhish deployment"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Display operations without changing the system"
    )

    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade installed system packages"
    )

    args = parser.parse_args()

    try:
        deploy(args)

    except (
        RuntimeError,
        PermissionError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        KeyError,
        zipfile.BadZipFile
    ) as error:

        log(f"\n[-] Deployment failed: {error}")
        sys.exit(1)

    except KeyboardInterrupt:
        log("\n[-] Deployment interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()

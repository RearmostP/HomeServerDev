#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir=/opt/home-gallery
config_dir=/etc/home-gallery
state_dir=/server-storage
service=home-gallery
serve_target=http://127.0.0.1:8000

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
step() { printf '\n%s\n' "$*"; }

[[ $EUID -ne 0 ]] || die "Run this as a regular user with sudo access."
[[ -t 0 ]] || die "Run from an interactive terminal for Tailscale sign-in."
[[ -r /etc/os-release ]] || die "Could not detect Debian."
source /etc/os-release
[[ ${ID:-} == debian && ${VERSION_CODENAME:-} =~ ^[a-z]+$ ]] || die "This installer requires Debian."
[[ -f "$repo/server/main.py" && -f "$repo/clients/browser/package-lock.json" ]] ||
    die "Run the installer from the project checkout."
case "$(dpkg --print-architecture)" in
    amd64) node_arch=x64 ;;
    arm64) node_arch=arm64 ;;
    *) die "This installer supports amd64 and arm64." ;;
esac
command -v sudo >/dev/null || die "Install sudo and give your account sudo access."
sudo -v

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
fetch() { curl --fail --silent --show-error --location --retry 2 --proto '=https' -o "$2" "$1"; }

step "Installing Debian dependencies"
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 python3-venv xz-utils
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer required"'

if ! command -v tailscale >/dev/null; then
    base="https://pkgs.tailscale.com/stable/debian/$VERSION_CODENAME"
    fetch "$base.noarmor.gpg" "$scratch/tailscale.gpg"
    fetch "$base.tailscale-keyring.list" "$scratch/tailscale.list"
    sudo install -m 0644 "$scratch/tailscale.gpg" /usr/share/keyrings/tailscale-archive-keyring.gpg
    sudo install -m 0644 "$scratch/tailscale.list" /etc/apt/sources.list.d/tailscale.list
    sudo apt-get update
    sudo apt-get install -y tailscale
fi

step "Connecting to Tailscale"
sudo systemctl enable --now tailscaled
if ! tailscale status --json > "$scratch/status.json" || ! python3 -c 'import json,sys; sys.exit(json.load(sys.stdin).get("BackendState") != "Running")' < "$scratch/status.json"; then
    printf 'Sign in using the URL that Tailscale displays. If required, approve this device in your tailnet.\n'
    sudo tailscale up
    tailscale status --json > "$scratch/status.json"
fi
host=$(python3 - "$scratch/status.json" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    status = json.load(stream)
host = (status.get("Self") or {}).get("DNSName", "").rstrip(".")
if status.get("BackendState") != "Running" or not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", host):
    raise SystemExit("Tailscale is not ready. Check device approval and MagicDNS.")
print(host)
PY
)

sudo tailscale serve status --json > "$scratch/serve.json"
serve_action=$(python3 - "$scratch/serve.json" "$host" "$serve_target" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    contents = stream.read().strip()
config = (json.loads(contents) or {}) if contents else {}
host, target = sys.argv[2:]
route = f"{host}:443"
if (config.get("AllowFunnel") or {}).get(route):
    raise SystemExit("Funnel is enabled on port 443. Disable it before installing.")
listener = (config.get("TCP") or {}).get("443")
handlers = ((config.get("Web") or {}).get(route) or {}).get("Handlers") or {}
root = handlers.get("/")
if root is not None and root.get("Proxy") == target and listener and listener.get("HTTPS"):
    print("keep")
elif listener is None and root is None:
    print("add")
else:
    raise SystemExit("An existing Tailscale Serve rule uses port 443. It was left in place.")
PY
)

step "Building the gallery"
sudo install -d -m 0755 "$install_dir"
sudo install -d -m 0700 "$config_dir"
if ! getent passwd "$service" >/dev/null; then
    sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$service"
fi
service_group=$(id -gn "$service")
if ! sudo test -s "$config_dir/opaque.env" && sudo test -e "$state_dir/gallery.sqlite3"; then
    die "An existing gallery database requires its original OPAQUE setup. Restore opaque.env before rerunning."
fi
sudo install -d -m 0700 -o "$service" -g "$service_group" "$state_dir"

release=$(sudo mktemp -d "$install_dir/release.XXXXXXXX")
sudo chown "$(id -u):$(id -g)" "$release"
mkdir -p "$release/server" "$release/clients/browser" "$release/node"
cp "$repo"/server/{main.py,storage.py,requirements.txt} "$release/server/"
cp "$repo"/clients/browser/{app.js,app.css,crypto.js,index.html,opaque-server.mjs,package.json,package-lock.json} "$release/clients/browser/"

node_base=https://nodejs.org/dist/latest-v22.x
fetch "$node_base/SHASUMS256.txt" "$scratch/SHASUMS256.txt"
archive=$(awk -v arch="$node_arch" '$2 ~ ("^node-v22[.][0-9]+[.][0-9]+-linux-" arch "[.]tar[.]xz$") { print $2 }' "$scratch/SHASUMS256.txt")
[[ $archive =~ ^node-v22\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] || die "Could not identify the Node.js release."
fetch "$node_base/$archive" "$scratch/$archive"
(
    cd "$scratch"
    awk -v archive="$archive" '$2 == archive { print; found=1 } END { if (!found) exit 1 }' SHASUMS256.txt |
        sha256sum --check --strict --status
)
tar -xJf "$scratch/$archive" -C "$release/node" --strip-components=1
export PATH="$release/node/bin:$PATH"
(
    cd "$release/clients/browser"
    npm ci --no-audit --no-fund
    npm run build
    if ! sudo test -s "$config_dir/opaque.env"; then
        setup=$(node --input-type=module <<'JS'
import * as opaque from "@serenity-kit/opaque";
await opaque.ready;
process.stdout.write(opaque.server.createSetup());
JS
)
        [[ $setup =~ ^[A-Za-z0-9_+/=-]+$ ]] || die "Could not generate the OPAQUE setup."
        (umask 077; printf 'OPAQUE_SERVER_SETUP=%s\n' "$setup" > "$scratch/opaque.env")
        sudo install -m 0600 "$scratch/opaque.env" "$config_dir/opaque.env"
    fi
)
python3 -m venv "$release/server/.venv"
"$release/server/.venv/bin/python" -m pip install -r "$release/server/requirements.txt"
sudo chown -hR root:root "$release"
sudo chmod 0755 "$release"

printf 'GALLERY_ORIGIN=https://%s\n' "$host" > "$scratch/gallery.env"
sudo install -m 0600 "$scratch/gallery.env" "$config_dir/gallery.env"
cat > "$scratch/home-gallery.service" <<UNIT
[Unit]
Description=Home Gallery
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$service
Group=$service_group
WorkingDirectory=$release/server
EnvironmentFile=$config_dir/opaque.env
EnvironmentFile=$config_dir/gallery.env
Environment=PATH=$release/node/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$release/server/.venv/bin/python main.py
Restart=on-failure
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$state_dir

[Install]
WantedBy=multi-user.target
UNIT
sudo install -m 0644 "$scratch/home-gallery.service" /etc/systemd/system/home-gallery.service
sudo systemctl daemon-reload
sudo systemctl enable "$service"
sudo systemctl restart "$service"

step "Checking the gallery"
ready=false
for _ in {1..15}; do
    if curl --noproxy '*' --silent --fail --max-time 2 "$serve_target/" >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
[[ $ready == true ]] || die "The service did not respond. Inspect: sudo journalctl -u home-gallery -n 50"

if [[ $serve_action == add ]]; then
    sudo tailscale serve --bg --https=443 "$serve_target"
fi
sudo tailscale serve status
printf '\nOpen the gallery from the tailnet: https://%s/\n' "$host"
printf 'Service logs: sudo journalctl -u home-gallery -f\n'

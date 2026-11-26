#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir=/opt/home-gallery
config_dir=/etc/home-gallery
state_dir=/server-storage
service=home-gallery
roleforge_version=0.2.1
roleforge_release=https://github.com/RearmostP/RoleForge/releases/download/v${roleforge_version}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
step() { printf '\n%s\n' "$*"; }

[[ $EUID -ne 0 ]] || die "Run this as a regular user with sudo access."
[[ -t 0 ]] || die "Run from an interactive terminal for server configuration."
[[ -r /etc/os-release ]] || die "Could not detect Debian."
source /etc/os-release
[[ ${ID:-} == debian && ${VERSION_CODENAME:-} =~ ^[a-z]+$ ]] || die "This installer requires Debian."
[[ -f "$repo/server/main.py" && -f "$repo/clients/browser/package-lock.json" ]] ||
    die "Run the installer from the project checkout."
case "$(dpkg --print-architecture)" in
    amd64)
        node_arch=x64
        roleforge_wheel="roleforge-${roleforge_version}-cp310-abi3-manylinux_2_34_x86_64.whl"
        ;;
    arm64)
        node_arch=arm64
        roleforge_wheel="roleforge-${roleforge_version}-cp310-abi3-manylinux_2_34_aarch64.whl"
        ;;
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

gallery_origin=${GALLERY_ORIGIN:-}
if [[ -z $gallery_origin ]]; then
    read -r -p 'Gallery HTTPS origin (https://home-gallery.<tailnet>.ts.net): ' gallery_origin
fi
python3 - "$gallery_origin" <<'PY'
import sys
from urllib.parse import urlsplit

origin = urlsplit(sys.argv[1])
host = origin.hostname or ""
if (
    origin.scheme != "https"
    or not host
    or origin.netloc.casefold() != host.casefold()
    or origin.path
    or origin.query
    or origin.fragment
    or not host.isascii()
    or host != host.lower()
    or not host.endswith(".ts.net")
):
    raise SystemExit("GALLERY_ORIGIN must be a lowercase HTTPS .ts.net origin without a path or port.")
PY

step "Building the gallery"
sudo install -d -m 0755 "$install_dir"
if ! getent passwd "$service" >/dev/null; then
    sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$service"
fi
service_group=$(id -gn "$service")
sudo install -d -m 0750 -o root -g "$service_group" "$config_dir"
if ! sudo test -s "$config_dir/opaque.env" && sudo test -e "$state_dir/gallery.sqlite3"; then
    die "An existing gallery database requires its original OPAQUE setup. Restore opaque.env before rerunning."
fi
sudo install -d -m 0700 -o "$service" -g "$service_group" "$state_dir"

if ! sudo test -s "$config_dir/tailscale.env"; then
    read -r -s -p 'Tailscale auth key: ' tailscale_auth_key
    printf '\n'
    [[ -n $tailscale_auth_key ]] || die "A Tailscale auth key is required."
    (umask 077; printf 'TAILSCALE_AUTH_KEY=%s\n' "$tailscale_auth_key" > "$scratch/tailscale.env")
    unset tailscale_auth_key
    sudo install -o root -g "$service_group" -m 0640 "$scratch/tailscale.env" "$config_dir/tailscale.env"
fi
sudo chown root:"$service_group" "$config_dir/tailscale.env"
sudo chmod 0640 "$config_dir/tailscale.env"

release=$(sudo mktemp -d "$install_dir/release.XXXXXXXX")
sudo chown "$(id -u):$(id -g)" "$release"
mkdir -p "$release/server" "$release/clients/browser" "$release/node"
cp "$repo"/server/main.py "$release/server/"
cp -R "$repo"/server/gallery "$release/server/"
cp "$repo"/server/{requirements.txt,home-gallery-host-settings.rfg} "$release/server/"
cp "$repo"/clients/browser/{app.js,app.css,auth-form.js,crypto.js,index.html,opaque-server.mjs,package.json,package-lock.json} "$release/clients/browser/"

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
roleforge_url="${roleforge_release}/${roleforge_wheel}"
if ! curl --fail --silent --show-error --location --retry 2 --proto '=https' \
    -o "$scratch/$roleforge_wheel" "$roleforge_url"; then
    die "RoleForge ${roleforge_version} Wheel asset is unavailable: $roleforge_wheel"
fi
"$release/server/.venv/bin/python" -m pip install --no-deps "$scratch/$roleforge_wheel"
sudo chown -hR root:root "$release"
sudo chmod 0755 "$release"

printf 'GALLERY_ORIGIN=%s\n' "$gallery_origin" > "$scratch/gallery.env"
sudo install -m 0600 "$scratch/gallery.env" "$config_dir/gallery.env"
cat > "$scratch/home-gallery.service" <<UNIT
[Unit]
Description=Home Gallery
After=network-online.target
Wants=network-online.target

[Service]
User=$service
Group=$service_group
WorkingDirectory=$release/server
EnvironmentFile=$config_dir/opaque.env
EnvironmentFile=$config_dir/gallery.env
Environment=GALLERY_TAILSCALE_ROLE=1
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
if systemctl is-active --quiet tailscaled.service || systemctl is-enabled --quiet tailscaled.service; then
    step "Stopping any previous system-wide Tailscale service"
fi
if systemctl is-active --quiet tailscaled.service; then
    sudo systemctl stop tailscaled.service
fi
if systemctl is-enabled --quiet tailscaled.service; then
    sudo systemctl disable tailscaled.service
fi
sudo systemctl restart "$service"

step "Checking the gallery"
ready=false
for _ in {1..15}; do
    if curl --noproxy '*' --silent --fail --max-time 2 http://127.0.0.1:8000/ >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
[[ $ready == true ]] || die "The service did not respond. Inspect: sudo journalctl -u home-gallery -n 50"

printf '\nOpen the gallery from the tailnet: %s/\n' "$gallery_origin"
printf 'Service logs: sudo journalctl -u home-gallery -f\n'

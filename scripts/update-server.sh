#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

service=home-gallery
install_dir=/opt/home-gallery
config=/etc/home-gallery/update.conf
expected_remote=https://github.com/RearmostP/HomeServerDev.git
roleforge_version=0.2.1
roleforge_release=https://github.com/RearmostP/RoleForge/releases/download/v${roleforge_version}
minimum_node_major=22

die() { printf 'Update error: %s\n' "$*" >&2; exit 1; }
step() { printf '\n%s\n' "$*"; }

[[ $EUID -eq 0 ]] || die "Run through the installed update-version command."
[[ $# -eq 2 && $1 == --config ]] || die "This script is intended to run through update-version."
config=$2
[[ $config == /etc/home-gallery/update.conf ]] || die "Unexpected updater configuration path."
[[ -f $config && $(stat -c %u "$config") == 0 ]] ||
    die "The updater configuration must be a root-owned file."
config_mode=$(stat -c %a "$config")
(( (8#$config_mode & 022) == 0 )) || die "The updater configuration must not be group- or world-writable."

declare -A values=()
while IFS='=' read -r key value || [[ -n ${key:-} ]]; do
    [[ -n ${key:-} ]] || continue
    case "$key" in
        CHECKOUT_PATH|CHECKOUT_OWNER|EXPECTED_REMOTE|UPSTREAM_REMOTE|UPSTREAM_BRANCH)
            [[ ! ${values[$key]+present} ]] || die "Duplicate key in updater configuration: $key"
            values[$key]=$value
            ;;
        *)
            die "Unexpected key in updater configuration."
            ;;
    esac
done < "$config"

checkout=${values[CHECKOUT_PATH]:-}
checkout_owner=${values[CHECKOUT_OWNER]:-}
configured_remote=${values[EXPECTED_REMOTE]:-}
upstream_remote=${values[UPSTREAM_REMOTE]:-}
upstream_branch=${values[UPSTREAM_BRANCH]:-}
[[ -n $checkout && -n $checkout_owner && -n $upstream_branch ]] ||
    die "The updater configuration is incomplete."
[[ $configured_remote == "$expected_remote" && $upstream_remote == origin ]] ||
    die "The configured repository is not the expected HomeServerDev origin."
[[ -d $checkout && -e $checkout/.git ]] ||
    die "The saved checkout does not exist or is not a Git checkout: $checkout"
[[ $(stat -c %U "$checkout") == "$checkout_owner" && $checkout_owner != root ]] ||
    die "The checkout must remain owned by its configured non-root owner: $checkout_owner"
script_checkout=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
saved_checkout=$(cd -- "$checkout" && pwd -P)
[[ $script_checkout == "$saved_checkout" ]] ||
    die "The updater script is not running from its configured checkout."
command -v runuser >/dev/null || die "The runuser command is required."
command -v flock >/dev/null || die "The flock command is required."
command -v curl >/dev/null || die "The curl command is required."
command -v systemctl >/dev/null || die "systemd is required."

[[ -d /run/lock ]] || die "The system lock directory /run/lock is unavailable."
exec 9>/run/lock/home-gallery-update.lock
flock -n 9 || die "Another HomeServerDev update is already running."

run_checkout_git() {
    runuser -u "$checkout_owner" -- git -C "$checkout" "$@"
}

normalize_repository_remote() {
    local remote=${1%.git}
    case "$remote" in
        https://github.com/RearmostP/HomeServerDev|https://github.com/rearmostp/homeserverdev|\
        git@github.com:RearmostP/HomeServerDev|git@github.com:rearmostp/homeserverdev|\
        ssh://git@github.com/RearmostP/HomeServerDev|ssh://git@github.com/rearmostp/homeserverdev)
            printf '%s\n' "$expected_remote"
            ;;
        *)
            return 1
            ;;
    esac
}

checkout_remote=$(run_checkout_git remote get-url origin 2>/dev/null) ||
    die "The saved checkout has no origin remote."
[[ $(normalize_repository_remote "$checkout_remote") == "$configured_remote" ]] ||
    die "The checkout origin does not match the saved HomeServerDev repository."
current_branch=$(run_checkout_git branch --show-current)
[[ $current_branch == "$upstream_branch" ]] ||
    die "Checkout is on '$current_branch'; configured update branch is '$upstream_branch'."
run_checkout_git check-ref-format --branch "$upstream_branch" >/dev/null ||
    die "The configured upstream branch name is invalid."
actual_upstream=$(run_checkout_git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) ||
    die "The checkout branch has no upstream; configure origin/$upstream_branch first."
[[ $actual_upstream == "$upstream_remote/$upstream_branch" ]] ||
    die "The checkout upstream is '$actual_upstream'; expected '$upstream_remote/$upstream_branch'."
[[ -z $(run_checkout_git status --porcelain --untracked-files=all) ]] ||
    die "The checkout has local changes. Preserve or resolve them before updating."

if ! systemctl is-active --quiet "$service"; then
    die "The existing $service service is not active; inspect it before updating."
fi
unit_file=/etc/systemd/system/$service.service
[[ -r $unit_file ]] || die "The existing systemd unit is missing: $unit_file"
previous_working_directory=$(systemctl show --property=WorkingDirectory --value "$service")
[[ -n $previous_working_directory && -d $previous_working_directory ]] ||
    die "Could not identify the active release's working directory."
previous_release=$(dirname -- "$previous_working_directory")
[[ $previous_release == "$install_dir"/release.* ]] ||
    die "The active service does not use a recognized HomeServerDev release."
previous_exec_start=$(awk -F= '/^ExecStart=/ { count++; sub(/^ExecStart=/, ""); print } END { if (count != 1) exit 1 }' "$unit_file") ||
    die "Could not identify the current service executable."
case "$previous_exec_start" in
    "$previous_working_directory"/.venv/bin/python\ main.py)
        previous_python_environment=$previous_working_directory/.venv
        ;;
    "$install_dir"/dependencies/python-*/bin/python\ main.py)
        previous_python_environment=${previous_exec_start%/bin/python main.py}
        ;;
    *)
        die "The active service executable is not a recognized HomeServerDev runtime."
        ;;
esac
[[ -x $previous_python_environment/bin/python ]] ||
    die "The active Python environment is missing."
previous_service_path=$(awk -F= '/^Environment=PATH=/ { count++; sub(/^Environment=PATH=/, ""); print } END { if (count != 1) exit 1 }' "$unit_file") ||
    die "Could not identify the service runtime PATH."
previous_node_bin=${previous_service_path%%:*}
previous_path_suffix=${previous_service_path#*:}
[[ -n $previous_path_suffix && -x $previous_node_bin/node ]] ||
    die "The service runtime PATH does not identify a reusable Node.js runtime."

step "Fetching $upstream_remote/$upstream_branch as $checkout_owner"
run_checkout_git fetch "$upstream_remote" \
    "refs/heads/$upstream_branch:refs/remotes/$upstream_remote/$upstream_branch" ||
    die "Could not fetch the configured upstream branch."
run_checkout_git merge-base --is-ancestor HEAD "$upstream_remote/$upstream_branch" ||
    die "The local branch cannot be fast-forwarded. No local commits were overwritten."
run_checkout_git merge --ff-only "$upstream_remote/$upstream_branch" ||
    die "Fast-forward failed. No merge or reset was attempted."
[[ -z $(run_checkout_git status --porcelain --untracked-files=all) ]] ||
    die "The checkout became dirty after fast-forward; deployment stopped."

architecture=$(dpkg --print-architecture)
case "$architecture" in
    amd64) node_arch=x64; roleforge_arch=x86_64 ;;
    arm64) node_arch=arm64; roleforge_arch=aarch64 ;;
    *) die "Unsupported server architecture: $architecture" ;;
esac
roleforge_wheel="roleforge-${roleforge_version}-cp310-abi3-manylinux_2_34_${roleforge_arch}.whl"

release=$(mktemp -d "$install_dir/release.XXXXXXXX")
chmod 0755 "$release"
mkdir -p "$release/server" "$release/clients/browser" "$release/rollback"
cp "$checkout/server/main.py" "$release/server/"
cp -R "$checkout/server/gallery" "$release/server/"
cp "$checkout/server"/home-gallery-host-settings.rfg "$release/server/"
cp "$checkout/server/requirements.txt" "$release/server/"
cp "$checkout/clients/browser"/{app.js,app.css,auth-form.js,crypto.js,index.html,opaque-server.mjs,package.json,package-lock.json} \
    "$release/clients/browser/"

node_path=
for candidate in \
    "$previous_node_bin/node" \
    "$previous_release/node/bin/node" \
    /usr/local/bin/node \
    /usr/bin/node
do
    if [[ -x $candidate ]]; then
        candidate_major=$("$candidate" -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf '0')
        if [[ $candidate_major =~ ^[0-9]+$ ]] && (( candidate_major >= minimum_node_major )); then
            node_path=$candidate
            break
        fi
    fi
done

if [[ -z $node_path ]]; then
    command -v xz >/dev/null || die "xz-utils is required to install the compatible Node.js runtime."
    step "Installing a compatible Node.js runtime because none is available"
    node_base=https://nodejs.org/dist/latest-v22.x
    curl --fail --silent --show-error --location --retry 2 --proto '=https' \
        -o "$release/SHASUMS256.txt" "$node_base/SHASUMS256.txt" ||
        die "Could not fetch the Node.js checksums."
    node_archive=$(awk -v arch="$node_arch" \
        '$2 ~ ("^node-v22[.][0-9]+[.][0-9]+-linux-" arch "[.]tar[.]xz$") { print $2 }' \
        "$release/SHASUMS256.txt")
    [[ $node_archive =~ ^node-v22\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] ||
        die "Could not identify a compatible Node.js release."
    curl --fail --silent --show-error --location --retry 2 --proto '=https' \
        -o "$release/$node_archive" "$node_base/$node_archive" ||
        die "Could not download the Node.js runtime."
    (cd "$release" && awk -v archive="$node_archive" \
        '$2 == archive { print; found=1 } END { if (!found) exit 1 }' SHASUMS256.txt |
        sha256sum --check --strict --status) ||
        die "The Node.js archive checksum did not match."
    mkdir -p "$release/node"
    tar -xJf "$release/$node_archive" -C "$release/node" --strip-components=1 ||
        die "Could not unpack the Node.js runtime."
    rm -f -- "$release/SHASUMS256.txt" "$release/$node_archive"
    node_path=$release/node/bin/node
fi
node_bin=$(dirname -- "$node_path")
node_major=$("$node_path" -p 'Number(process.versions.node.split(".")[0])')
(( node_major >= minimum_node_major )) || die "Node.js $minimum_node_major or newer is required."
command -v npm >/dev/null || [[ -x $node_bin/npm ]] || die "npm is required to build the browser client."
export PATH="$node_bin:$PATH"

dependencies_dir=$install_dir/dependencies
install -d -o root -g root -m 0755 "$dependencies_dir"
browser_dependency_key() {
    python3 - "$1/package.json" "$1/package-lock.json" <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as package_file:
    package = json.load(package_file)
dependencies = {
    name: package.get(name, {})
    for name in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
}
digest = hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode())
with open(sys.argv[2], "rb") as lock_file:
    for block in iter(lambda: lock_file.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())
PY
}

browser_key=$(browser_dependency_key "$checkout/clients/browser")
browser_cache=$dependencies_dir/browser-${browser_key}-node${node_major}-${architecture}
browser_modules=
if [[ -f $browser_cache/.complete ]]; then
    browser_modules=$browser_cache/node_modules
elif [[ -d $previous_release/clients/browser/node_modules &&
        -f $previous_release/clients/browser/package.json &&
        -f $previous_release/clients/browser/package-lock.json ]]; then
    previous_browser_key=$(browser_dependency_key "$previous_release/clients/browser")
    if [[ $previous_browser_key == "$browser_key" ]]; then
        browser_modules=$previous_release/clients/browser/node_modules
    fi
fi
if [[ -z $browser_modules ]]; then
    browser_build=$(mktemp -d "$dependencies_dir/.browser-${browser_key}.XXXXXXXX")
    cp "$checkout/clients/browser"/{package.json,package-lock.json} "$browser_build/"
    step "Installing browser dependencies for the current lockfiles"
    (cd "$browser_build" && npm ci --no-audit --no-fund --cache "$install_dir/npm-cache") ||
        die "Could not install browser dependencies from package-lock.json."
    printf '%s\n' "$browser_key" > "$browser_build/.complete"
    if [[ -e $browser_cache ]]; then
        mv "$browser_cache" "$browser_cache.incomplete.$(date +%s)"
    fi
    mv "$browser_build" "$browser_cache"
    browser_modules=$browser_cache/node_modules
fi
ln -s "$browser_modules" "$release/clients/browser/node_modules"
step "Building the browser client"
(cd "$release/clients/browser" && npm run build) ||
    die "The browser client build failed."

requirements_key=$(cat "$checkout/server/requirements.txt" |
    sha256sum | awk '{print $1}')
python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python_key="${requirements_key}-python${python_version}-${architecture}-roleforge${roleforge_version}"
python_environment=$dependencies_dir/python-$python_key
reuse_python_environment=false
if [[ ! -f $python_environment/.home-gallery-complete ]]; then
    if "$previous_python_environment/bin/python" - "$checkout/server/requirements.txt" \
        "$python_version" "$architecture" "$roleforge_version" <<'PY'
import importlib.metadata
import platform
import subprocess
import sys
from pip._vendor.packaging.requirements import Requirement

requirements_path, expected_python, expected_arch, expected_roleforge = sys.argv[1:]
if ".".join(map(str, sys.version_info[:2])) != expected_python:
    raise SystemExit(1)
actual_arch = platform.machine().lower()
if expected_arch == "amd64" and actual_arch not in {"x86_64", "amd64"}:
    raise SystemExit(1)
if expected_arch == "arm64" and actual_arch not in {"aarch64", "arm64"}:
    raise SystemExit(1)
try:
    if importlib.metadata.version("roleforge") != expected_roleforge:
        raise SystemExit(1)
    with open(requirements_path, encoding="utf-8") as requirements_file:
        requirements = [
            Requirement(line.strip())
            for line in requirements_file
            if line.strip() and not line.lstrip().startswith("#")
        ]
    for requirement in requirements:
        version = importlib.metadata.version(requirement.name)
        if not requirement.specifier.contains(version, prereleases=True):
            raise SystemExit(1)
except (importlib.metadata.PackageNotFoundError, ValueError):
    raise SystemExit(1)
if subprocess.run(
    [sys.executable, "-m", "pip", "check"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
).returncode:
    raise SystemExit(1)
PY
    then
        python_environment=$previous_python_environment
        reuse_python_environment=true
    fi
fi
if [[ $reuse_python_environment != true && ! -f $python_environment/.home-gallery-complete ]]; then
    python_build=$(mktemp -d "$dependencies_dir/.python-${python_key}.XXXXXXXX")
    step "Preparing the Python environment for the current requirements"
    python3 -m venv "$python_build/.venv" ||
        die "Could not create the Python virtual environment."
    PIP_CACHE_DIR="$install_dir/pip-cache" \
        "$python_build/.venv/bin/python" -m pip install \
        -r "$checkout/server/requirements.txt" ||
        die "Could not install Python requirements."
    curl --fail --silent --show-error --location --retry 2 --proto '=https' \
        -o "$python_build/$roleforge_wheel" \
        "$roleforge_release/$roleforge_wheel" ||
        die "Could not fetch the pinned RoleForge wheel."
    PIP_CACHE_DIR="$install_dir/pip-cache" \
        "$python_build/.venv/bin/python" -m pip install --no-deps "$python_build/$roleforge_wheel" ||
        die "Could not install the pinned RoleForge wheel."
    "$python_build/.venv/bin/python" -m pip check ||
        die "The Python environment has incompatible dependencies."
    printf '%s\n' "$python_key" > "$python_build/.venv/.home-gallery-complete"
    chmod -R a+rX "$python_build/.venv"
    if [[ -e $python_environment ]]; then
        mv "$python_environment" "$python_environment.incomplete.$(date +%s)"
    fi
    mv "$python_build/.venv" "$python_environment"
    rm -f -- "$python_build/$roleforge_wheel"
    rmdir "$python_build"
fi
ln -s "$python_environment" "$release/server/.venv"

awk \
    -v old_working_directory="$previous_working_directory" \
    -v new_working_directory="$release/server" \
    -v old_exec_start="$previous_exec_start" \
    -v old_service_path="$previous_service_path" \
    -v previous_path_suffix="$previous_path_suffix" \
    -v node_bin="$node_bin" '
    /^WorkingDirectory=/ {
        working_count++
        if ($0 != "WorkingDirectory=" old_working_directory) exit 21
        print "WorkingDirectory=" new_working_directory
        next
    }
    /^ExecStart=/ {
        exec_count++
        if ($0 != "ExecStart=" old_exec_start) exit 22
        print "ExecStart=" new_working_directory "/.venv/bin/python main.py"
        next
    }
    /^Environment=PATH=/ {
        path_count++
        if ($0 != "Environment=PATH=" old_service_path) exit 24
        print "Environment=PATH=" node_bin ":" previous_path_suffix
        next
    }
    { print }
    END {
        if (working_count != 1 || exec_count != 1 || path_count != 1) exit 23
    }' "$unit_file" > "$release/rollback/home-gallery.service.new" ||
    die "The existing systemd unit has unexpected paths; refusing to replace it."
cp -p "$unit_file" "$release/rollback/home-gallery.service.previous"
printf '%s\n' "$previous_working_directory" > "$release/rollback/previous-working-directory"
chmod -R go-w "$release"

activation_started=false
rollback_activation() {
    activation_started=false
    printf 'Restoring the previous systemd configuration and release...\n' >&2
    if install -o root -g root -m 0644 \
        "$release/rollback/home-gallery.service.previous" "$unit_file" &&
        systemctl daemon-reload &&
        systemctl restart "$service"
    then
        if check_health; then
            printf 'Rollback succeeded; previous release remains active. Failed release retained at %s\n' \
                "$release" >&2
        else
            printf 'Rollback restarted the previous release, but its health check also failed.\n' >&2
        fi
    else
        printf 'Rollback could not restart the previous release. Inspect %s and systemd logs.\n' \
            "$release" >&2
    fi
}

check_health() {
    local response
    response=$(curl --noproxy '*' --silent --fail --max-time 3 \
        http://127.0.0.1:8000/health 2>/dev/null) || return 1
    python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("status") == "healthy" else 1)' \
        <<< "$response"
}

on_exit() {
    local result=$?
    trap - EXIT
    if (( result != 0 )) && [[ $activation_started == true ]]; then
        rollback_activation
    fi
    exit "$result"
}
trap on_exit EXIT

step "Activating new release $release"
activation_started=true
install -o root -g root -m 0644 \
    "$release/rollback/home-gallery.service.new" "$unit_file"
systemctl daemon-reload
systemctl restart "$service"
healthy=false
for _ in {1..20}; do
    if check_health; then
        healthy=true
        break
    fi
    sleep 1
done
[[ $healthy == true ]] || die "The new release failed its health check."

activation_started=false
printf '\nHomeServerDev updated successfully.\nRelease: %s\nPrevious release: %s\n' \
    "$release" "$previous_release"

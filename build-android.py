#!/usr/bin/env python3
"""Build the Home Gallery Android APK with a locally supplied server hostname."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import string
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parent
ANDROID = ROOT / "clients" / "android"
BROWSER = ROOT / "clients" / "browser"
NETWORK = ANDROID / "network"
CONFIG = ANDROID / "server-host.local.txt"
APK = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
WINDOWS = os.name == "nt"
HOST_OS = "windows" if WINDOWS else "linux"
EXE = ".exe" if WINDOWS else ""
BATCH = ".bat" if WINDOWS else ""
SDK_PACKAGES = {
    "platforms;android-37.0": "platforms/android-37.0/android.jar",
    "build-tools;36.0.0": f"build-tools/36.0.0/aapt2{EXE}",
}
NDK_VERSION = "28.2.13676358"
SDK_TOOLS = {
    "windows": ("win", "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a"),
    "linux": ("linux", "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"),
}
APIS = ("android/arm64", "android/amd64")


def run(args, *, env=None, cwd=None, capture=False):
    return subprocess.run(
        [str(arg) for arg in args], env=env, cwd=cwd, check=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    ).stdout


def fetch(url):
    response = urlopen(Request(url, headers={"User-Agent": "HomeGalleryBuild/1.0"}), timeout=90)
    if urlsplit(response.geturl()).scheme != "https":
        response.close()
        raise RuntimeError("A tool download did not use HTTPS.")
    return response


def read_url(url):
    with fetch(url) as response:
        return response.read().decode("utf-8")


def sha256(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def install_archive(url, checksum, destination, check_path):
    if (destination / check_path).is_file():
        return destination
    if destination.exists():
        raise RuntimeError(f"Incomplete cached installation: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        work = Path(temp)
        archive = work / Path(urlsplit(url).path).name
        print(f"Downloading {archive.name}", flush=True)
        with fetch(url) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if sha256(archive) != checksum.lower():
            raise RuntimeError(f"Checksum mismatch for {archive.name}")
        unpacked = work / "unpacked"
        unpacked.mkdir()
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as package:
                package.extractall(unpacked)
                if not WINDOWS:
                    for member in package.infolist():
                        mode = (member.external_attr >> 16) & 0o777
                        if mode and not member.is_dir():
                            (unpacked / member.filename).chmod(mode)
        else:
            with tarfile.open(archive) as package:
                if hasattr(tarfile, "data_filter"):
                    package.extractall(unpacked, filter="data")
                else:
                    run(["tar", "-xf", archive, "-C", unpacked])
        tops = list(unpacked.iterdir())
        if len(tops) != 1 or not (tops[0] / check_path).is_file():
            raise RuntimeError(f"Unexpected contents in {archive.name}")
        if not WINDOWS:
            (tops[0] / check_path).chmod((tops[0] / check_path).stat().st_mode | 0o755)
        tops[0].rename(destination)
    return destination


def usable(command, version_args, pattern, minimum):
    if not command or not Path(command).is_file():
        return False
    try:
        output = run([command, *version_args], capture=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    match = re.search(pattern, output)
    return bool(match and tuple(map(int, match.groups())) >= minimum)


def node_tools(cache):
    npm_name = "npm.cmd" if WINDOWS else "npm"
    installed = shutil.which(f"node{EXE}")
    if usable(installed, ["--version"], r"v(\d+)", (22,)):
        directory = Path(installed).parent
        if (directory / npm_name).is_file():
            return directory
        npm = shutil.which(npm_name)
        if npm:
            return directory
    for cached in sorted(cache.glob("node-v22.*"), reverse=True):
        directory = cached if WINDOWS else cached / "bin"
        if (directory / npm_name).is_file() and usable(directory / f"node{EXE}", ["--version"], r"v(\d+)", (22,)):
            return directory
    base = "https://nodejs.org/dist/latest-v22.x"
    suffix = "win-x64.zip" if WINDOWS else "linux-x64.tar.xz"
    manifest = read_url(base + "/SHASUMS256.txt")
    for line in manifest.splitlines():
        digest, filename = line.split()
        if re.fullmatch(rf"node-v22\.\d+\.\d+-{re.escape(suffix)}", filename):
            destination = cache / filename.removesuffix(".tar.xz").removesuffix(".zip")
            check = f"node{EXE}" if WINDOWS else "bin/node"
            root = install_archive(f"{base}/{filename}", digest, destination, check)
            return root if WINDOWS else root / "bin"
    raise RuntimeError("Could not find a supported Node.js 22 archive.")


def go_tools(cache):
    toolchain = re.search(r"(?m)^go (\d+)\.(\d+)\.(\d+)$", (NETWORK / "go.mod").read_text(encoding="utf-8"))
    if not toolchain:
        raise RuntimeError("Missing Go version in the bridge module.")
    minimum = tuple(map(int, toolchain.groups()))
    installed = shutil.which(f"go{EXE}")
    if usable(installed, ["version"], r"\bgo(\d+)\.(\d+)\.(\d+)", minimum):
        return Path(installed).parent
    for cached in sorted(cache.glob(f"go{minimum[0]}.*"), reverse=True):
        if usable(cached / "bin" / f"go{EXE}", ["version"], r"\bgo(\d+)\.(\d+)\.(\d+)", minimum):
            return cached / "bin"
    releases = json.loads(read_url("https://go.dev/dl/?mode=json&include=all"))
    extension = ".zip" if WINDOWS else ".tar.gz"
    for release in releases:
        if not release["stable"] or not release["version"].startswith(f"go{minimum[0]}.{minimum[1]}."):
            continue
        filename = f"{release['version']}.{HOST_OS}-amd64{extension}"
        for file in release["files"]:
            if file["filename"] == filename:
                root = install_archive(f"https://go.dev/dl/{filename}", file["sha256"],
                                       cache / release["version"], f"bin/go{EXE}")
                return root / "bin"
    raise RuntimeError("Could not find a supported Go toolchain.")


def java_home(cache):
    candidates = [os.environ.get("JAVA_HOME")]
    if WINDOWS:
        candidates.append(str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) /
                              "Android" / "Android Studio" / "jbr"))
    candidates.extend(str(item) for item in cache.glob("jdk-21*"))
    installed = shutil.which(f"java{EXE}")
    if installed:
        candidates.append(str(Path(installed).resolve().parent.parent))
    for candidate in candidates:
        if not candidate:
            continue
        home = Path(candidate)
        if (home / "bin" / f"javac{EXE}").is_file() and usable(
            home / "bin" / f"java{EXE}", ["-version"], r'version "(\d+)', (21,)
        ):
            return home.resolve()
    query = f"https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os={HOST_OS}&vendor=eclipse"
    release = json.loads(read_url(query))[0]
    package = release["binary"]["package"]
    return install_archive(package["link"], package["checksum"], cache / release["release_name"],
                           f"bin/javac{EXE}")


def android_tools(cache, env):
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    if WINDOWS and os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk"))
    sdk = next((Path(item).resolve() for item in candidates if item and Path(item).is_dir()), cache / "sdk")
    sdk.mkdir(parents=True, exist_ok=True)
    env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    ndk = Path(env.get("ANDROID_NDK_HOME") or sdk / "ndk" / NDK_VERSION).resolve()
    packages = dict(SDK_PACKAGES)
    if not (ndk / "source.properties").is_file():
        packages[f"ndk;{NDK_VERSION}"] = f"ndk/{NDK_VERSION}/source.properties"
        ndk = sdk / "ndk" / NDK_VERSION
    missing = [name for name, relative in packages.items() if not (sdk / relative).is_file()]
    if missing:
        managers = sorted(sdk.glob(f"cmdline-tools/*/bin/sdkmanager{BATCH}"), reverse=True)
        if managers:
            manager = managers[0]
        else:
            os_name, checksum = SDK_TOOLS[HOST_OS]
            filename = f"commandlinetools-{os_name}-15859902_latest.zip"
            root = install_archive(f"https://dl.google.com/android/repository/{filename}", checksum,
                                   sdk / "cmdline-tools" / "latest", f"bin/sdkmanager{BATCH}")
            manager = root / "bin" / f"sdkmanager{BATCH}"
        print("Review and accept the Android SDK license prompts to proceed.", flush=True)
        run([manager, f"--sdk_root={sdk}", "--licenses"], env=env)
        run([manager, f"--sdk_root={sdk}", *missing], env=env)
    return ndk


def normalize_host(value):
    value = value.strip()
    endpoint = urlsplit(value if "://" in value else "https://" + value)
    if not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", endpoint.netloc.lower()) or (
        endpoint.scheme != "https" or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment
    ):
        raise ValueError("Enter the Tailscale HTTPS URL or its .ts.net hostname.")
    return endpoint.netloc.lower()


def server_host(explicit):
    if explicit:
        return normalize_host(explicit)
    if os.environ.get("GALLERY_ORIGIN"):
        return normalize_host(os.environ["GALLERY_ORIGIN"])
    if CONFIG.is_file():
        return normalize_host(CONFIG.read_text(encoding="utf-8-sig"))
    if not WINDOWS:
        installed_config = Path("/etc/home-gallery/gallery.env")
        try:
            for line in installed_config.read_text(encoding="utf-8").splitlines():
                if line.startswith("GALLERY_ORIGIN="):
                    return normalize_host(line.partition("=")[2])
        except OSError:
            pass
    tls = shutil.which(f"tailscale{EXE}")
    if tls:
        try:
            state = json.loads(run([tls, "status", "--json"], capture=True))
            nodes = [state.get("Self") or {}, *(state.get("Peer") or {}).values()]
            matches = {node.get("DNSName", "").rstrip(".") for node in nodes
                       if node.get("DNSName", "").startswith("home-server.")}
            if len(matches) == 1:
                return normalize_host(matches.pop())
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
    return normalize_host(input("Tailscale URL for the gallery server: "))


@contextmanager
def compiler_path(ndk):
    if not WINDOWS or not any(character.isspace() for character in str(ndk)):
        yield ndk
        return
    for letter in reversed(string.ascii_uppercase[3:]):
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            continue
        try:
            run(["subst", drive[:2], ndk], capture=True)
        except subprocess.CalledProcessError:
            continue
        try:
            yield Path(drive)
        finally:
            run(["subst", drive[:2], "/d"])
        return
    raise RuntimeError("No free drive letter for the Android NDK compiler.")


def mobile_tools(env, cache):
    match = re.search(r"(?m)^\s*golang[.]org/x/mobile\s+(v[^\s]+)",
                      (NETWORK / "go.mod").read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("The Go mobile version is missing from go.mod.")
    version = match.group(1)
    bin_dir = Path(env.get("GOBIN") or cache / "go-bin").resolve()
    env["GOBIN"] = str(bin_dir)
    for tool in ("gomobile", "gobind"):
        path = bin_dir / (tool + EXE)
        if path.is_file():
            metadata = run(["go", "version", "-m", path], env=env, capture=True)
            if re.search(r"\bmod\s+golang[.]org/x/mobile\s+" + re.escape(version) + r"\s", metadata):
                continue
        run(["go", "install", f"golang.org/x/mobile/cmd/{tool}@{version}"], env=env)
    env["PATH"] = os.pathsep.join((str(bin_dir), env["PATH"]))
    return bin_dir / ("gomobile" + EXE)


def build(args):
    if (not WINDOWS and sys.platform != "linux") or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build on Windows or Linux with an x86-64 CPU. The resulting APK supports ARM64 phones.")
    cache_base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if WINDOWS else Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    )
    cache = (cache_base / "home-gallery-android").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    host = server_host(args.server)
    CONFIG.write_text(host + "\n", encoding="utf-8")
    print("Using the configured gallery hostname. The host is embedded only in the local APK.", flush=True)

    env = os.environ.copy()
    node = node_tools(cache)
    go = go_tools(cache)
    java = java_home(cache)
    env["JAVA_HOME"] = str(java)
    env["PATH"] = os.pathsep.join(map(str, (node, go, java / "bin", env.get("PATH", ""))))
    ndk = android_tools(cache, env)
    npm = shutil.which("npm.cmd" if WINDOWS else "npm", path=env["PATH"])
    if not npm:
        raise RuntimeError("npm was not found.")
    run([npm, "ci", "--no-audit", "--no-fund"], cwd=BROWSER, env=env)
    run([npm, "run", "build"], cwd=BROWSER, env=env)

    gomobile = mobile_tools(env, cache)
    (NETWORK / "libs").mkdir(exist_ok=True)
    with compiler_path(ndk) as compiler:
        env["ANDROID_NDK_HOME"] = str(compiler)
        run([gomobile, "bind", "-target", ",".join(APIS), "-androidapi", "26",
             "-javapkg", "il.homegallery.nativebridge", "-o", "libs/tailbridge.aar", "."],
            cwd=NETWORK, env=env)
    env["ANDROID_NDK_HOME"] = str(ndk)
    gradle = [ANDROID / "gradlew.bat"] if WINDOWS else ["bash", ANDROID / "gradlew"]
    run([*gradle, ":app:assembleDebug", "--console=plain"], cwd=ANDROID, env=env)
    with zipfile.ZipFile(APK) as result:
        if result.read("assets/server-host.txt").decode("utf-8").strip() != host:
            raise RuntimeError("The APK contains an unexpected hostname.")
        for abi in ("arm64-v8a", "x86_64"):
            result.getinfo(f"lib/{abi}/libgojni.so")
    print(f"APK built: {APK}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", help="Gallery Tailscale hostname or HTTPS URL")
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, EOFError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()

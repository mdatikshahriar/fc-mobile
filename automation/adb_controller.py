"""Thin wrapper around adb for talking to the BlueStacks instance running FC Mobile."""
import subprocess
import time
from pathlib import Path

ADB = r"C:\Users\mdati\AppData\Local\Android\Sdk\platform-tools\adb.exe"
DEVICE = "127.0.0.1:5555"
FC_MOBILE_PACKAGE = "com.ea.gp.fifamobile"
BLUESTACKS_EXE = r"C:\Program Files\BlueStacks_nxt\HD-Player.exe"
BLUESTACKS_INSTANCE = "Pie64"


class AdbError(RuntimeError):
    pass


def _run(args, timeout=20):
    result = subprocess.run(
        [ADB, "-s", DEVICE, *args],
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AdbError(result.stderr.decode(errors="replace").strip() or "adb command failed")
    return result.stdout


def connect(retries=3, delay=2):
    for attempt in range(retries):
        subprocess.run([ADB, "connect", DEVICE], capture_output=True)
        try:
            out = _run(["get-state"])
            if out.strip() == b"device" and _boot_completed():
                return True
        except AdbError:
            pass
        time.sleep(delay)
    return False


def _boot_completed():
    # adb reporting "device" only means the transport is up - right after a
    # cold BlueStacks launch the Android system (package/activity manager)
    # can still be mid-boot, which makes app-launch commands fail.
    result = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "getprop", "sys.boot_completed"],
        capture_output=True,
        timeout=10,
    )
    return result.stdout.decode(errors="replace").strip() == "1"


def screen_size():
    out = _run(["shell", "wm", "size"]).decode(errors="replace")
    # "Physical size: 1600x900"
    size_part = out.strip().splitlines()[-1].split(":")[-1].strip()
    width, height = (int(x) for x in size_part.split("x"))
    return width, height


def screenshot(save_path: Path):
    out = subprocess.run(
        [ADB, "-s", DEVICE, "exec-out", "screencap", "-p"],
        capture_output=True,
        timeout=20,
    )
    if out.returncode != 0 or not out.stdout:
        raise AdbError(out.stderr.decode(errors="replace").strip() or "screencap failed")
    save_path.write_bytes(out.stdout)
    return save_path


def tap(x: int, y: int):
    _run(["shell", "input", "tap", str(x), str(y)])


def is_fc_mobile_running():
    result = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "pidof", FC_MOBILE_PACKAGE],
        capture_output=True,
        timeout=20,
    )
    # pidof exits non-zero when no matching process is found - that's a normal
    # "not running" result here, not an adb/shell error.
    return bool(result.stdout.decode(errors="replace").strip())


def launch_fc_mobile():
    _run([
        "shell", "monkey", "-p", FC_MOBILE_PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1",
    ])


def stop_fc_mobile():
    _run(["shell", "am", "force-stop", FC_MOBILE_PACKAGE])


def is_bluestacks_running():
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq HD-Player.exe"],
        capture_output=True,
        text=True,
    )
    return "HD-Player.exe" in result.stdout


def launch_bluestacks():
    subprocess.Popen([BLUESTACKS_EXE, "--instance", BLUESTACKS_INSTANCE])


def close_bluestacks():
    subprocess.run(["taskkill", "/IM", "HD-Player.exe", "/F"], capture_output=True)

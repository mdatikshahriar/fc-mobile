"""
Start/stop manager for the Market Analyzer bot, for machines where Windows
Script Host is disabled (blocking windows_manager.vbs entirely). Pure Python,
no PowerShell/VBS dependency — since Python is already required to run the
bot itself, this can't be blocked by a scripting-subsystem policy that doesn't
also break the bot.

Double-click to run interactively (asks whether to start/stop via a dialog).
Run with an "autostart" argument for a silent, no-dialog start used at
Windows boot (see README for the startup-shortcut setup).
"""
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET = SCRIPT_DIR / "market_analyzer.py"


def _wmic_lines():
    # Double-clicking this .pyw file runs it under pythonw.exe, so sys.executable
    # in start_silent() resolves to pythonw.exe too — the bot process can be either
    # python.exe or pythonw.exe depending on how this manager itself was launched.
    result = subprocess.run(
        ["wmic", "process", "where", "name='python.exe' or name='pythonw.exe'", "get", "CommandLine,ProcessId"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.splitlines()


def get_running_pids():
    try:
        pids = []
        for line in _wmic_lines():
            if "market_analyzer.py" in line:
                parts = line.strip().split()
                if parts and parts[-1].isdigit():
                    pids.append(parts[-1])
        return pids
    except Exception:
        return []


def start_silent():
    subprocess.Popen(
        [sys.executable, str(TARGET)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    autostart = "autostart" in sys.argv
    running_pids = get_running_pids()

    if autostart:
        if not running_pids:
            start_silent()
        return

    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()

    if running_pids:
        if messagebox.askyesno(
            "Market Analyzer Manager",
            "The Market Analyzer is CURRENTLY RUNNING in the background.\n\nWould you like to STOP it?",
        ):
            for pid in running_pids:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            messagebox.showinfo("Market Analyzer Manager", "Bot successfully stopped.")
    else:
        if messagebox.askyesno(
            "Market Analyzer Manager",
            "The Market Analyzer is NOT RUNNING.\n\nWould you like to START it silently in the background?",
        ):
            start_silent()
            messagebox.showinfo(
                "Market Analyzer Manager",
                "Bot successfully started! It will run invisibly every 6 hours.",
            )


if __name__ == "__main__":
    main()

import os
import shutil
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
from pathlib import Path


WAIT_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.5
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000

IGNORED_TOP_LEVEL = {
    "config.json",
    "temp",
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "env",
    ".idea",
    ".vscode",
    "update_bootstrap.py",
    "app_rolling.log",
    ".env",
}


def log(message: str) -> None:
    print(f"[MAINTENANCE] {message}")


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    kernel32 = __import__("ctypes").windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        return False

    try:
        result = kernel32.WaitForSingleObject(handle, 0)
        return result == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def wait_for_process_exit(pid: int, timeout_seconds: float = WAIT_TIMEOUT_SECONDS) -> bool:
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout_seconds:
        if not is_process_alive(pid):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return not is_process_alive(pid)


def clear_existing_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def find_extracted_root(extract_dir: Path) -> Path | None:
    return next((path for path in extract_dir.iterdir() if path.is_dir()), None)


def apply_update_contents(source_root: Path, destination_root: Path) -> None:
    for item in source_root.iterdir():
        if item.name in IGNORED_TOP_LEVEL:
            continue

        destination = destination_root / item.name
        try:
            clear_existing_path(destination)
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
            log(f"Updated: {item.name}")
        except Exception as exc:
            log(f"Could not update {item.name}: {exc}")


def main() -> None:
    if len(sys.argv) < 2:
        log("Error: Parent PID not provided.")
        return

    project_root = Path(__file__).resolve().parent
    temp_dir = project_root / "temp"
    update_zip = temp_dir / "update.zip"
    extract_dir = temp_dir / "extracted"

    parent_pid = int(sys.argv[1])
    log(f"Waiting for process {parent_pid} to terminate...")

    if not wait_for_process_exit(parent_pid):
        log(f"Error: Process {parent_pid} is still running after timeout.")
        return

    log("Parent process terminated. Starting update...")

    if not update_zip.exists():
        log(f"Error: Update file not found at {update_zip}")
        return

    try:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        log("Extracting update...")
        with zipfile.ZipFile(update_zip, "r") as archive:
            archive.extractall(extract_dir)

        inner_folder = find_extracted_root(extract_dir)
        if inner_folder is None:
            log("Error: Extracted update is empty.")
            return

        log("Applying file changes...")
        apply_update_contents(inner_folder, project_root)

        log("Cleaning up...")
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        log("Update complete. Restarting...")
        main_script = project_root / "main.py"
        if os.name == "nt":
            subprocess.Popen([sys.executable, str(main_script)], creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=project_root)
        else:
            subprocess.Popen([sys.executable, str(main_script)], start_new_session=True, cwd=project_root)
    except Exception as exc:
        log(f"CRITICAL ERROR: {exc}")
        time.sleep(10)


if __name__ == "__main__":
    main()
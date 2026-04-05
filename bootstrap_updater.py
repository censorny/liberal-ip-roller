import os
import sys
import time
import zipfile
import shutil
import subprocess

def log(msg):
    print(f"[BOOTSTRAP] {msg}")

def main():
    if len(sys.argv) < 2:
        log("Error: Parent PID not provided.")
        return

    parent_pid = int(sys.argv[1])
    log(f"Waiting for process {parent_pid} to terminate...")

    # Wait for Parent to die
    timeout = 10
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            os.kill(parent_pid, 0)
        except OSError:
            break
        time.sleep(0.5)

    log("Parent process terminated. Starting update...")

    temp_dir = os.path.join(os.getcwd(), "temp")
    update_zip = os.path.join(temp_dir, "update.zip")
    extract_dir = os.path.join(temp_dir, "extracted")

    if not os.path.exists(update_zip):
        log(f"Error: Update file not found at {update_zip}")
        return

    try:
        # Extract ZIP
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        log("Extracting update...")
        with zipfile.ZipFile(update_zip, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Handle GitHub ZIP structure
        inner_folder = os.listdir(extract_dir)[0]
        src_path = os.path.join(extract_dir, inner_folder)

        # IGNORE LIST: What will NEVER be deleted or overwritten
        ignored = {
            "config.json", 
            "temp", 
            "storage", 
            "__pycache__", 
            ".git",
            "venv", 
            ".venv", 
            "env",
            ".idea", 
            ".vscode",
            "bootstrap_updater.py",
            "app_rolling.log",
            ".env"
        }

        log("Applying file changes...")
        for item in os.listdir(src_path):
            s = os.path.join(src_path, item)
            d = os.path.join(os.getcwd(), item)

            if item in ignored:
                continue

            try:
                if os.path.isdir(s):
                    # DELETION RISK: Existing folders are wiped and replaced
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    # OVERWRITE: Individual files are replaced.
                    shutil.copy2(s, d)
                log(f" Updated: {item}")
            except Exception as e:
                log(f" Could not update {item}: {e}")

        log("Cleaning up...")
        shutil.rmtree(temp_dir)

        log("Update complete. Restarting...")
        main_script = os.path.join(os.getcwd(), "main.py")
        if os.name == "nt":
            subprocess.Popen([sys.executable, main_script], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, main_script], start_new_session=True)

    except Exception as e:
        log(f"CRITICAL ERROR: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()

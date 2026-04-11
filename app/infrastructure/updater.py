"""Update management for downloading and applying new application versions."""

import os
import subprocess
import sys
import time
from typing import Optional, Tuple

import httpx

from ..paths import PROJECT_ROOT, TEMP_DIR


class UpdateManager:
    """Check for, download, and apply updates from the upstream repository."""

    def __init__(self, current_version: str):
        """
        Initializes the manager with the local version string.
        """
        self.current_version = current_version
        
        # Repository Configuration (Change these for production distribution)
        self.repo_owner = "censorny"
        self.repo_name = "liberal-ip-roller"
        
        self.base_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/main"
        self.zip_url = f"https://github.com/{self.repo_owner}/{self.repo_name}/archive/refs/heads/main.zip"

        self.project_root = PROJECT_ROOT
        self.temp_dir = TEMP_DIR
        self.update_zip = TEMP_DIR / "update.zip"

    async def check_for_updates(self) -> Tuple[bool, Optional[str]]:
        """
        Fetches the remote version.json and compares it with the local version.
        
        Returns:
            A tuple of (is_update_available, remote_version_string_or_error_flag).
        """
        try:
            # Cache-busting for GitHub Raw (CDN)
            url = f"{self.base_url}/version.json?t={int(time.time())}"
            async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
                
                remote_version = data.get("version", "0.0.0")
                if self._is_newer(remote_version):
                    return True, remote_version

            return False, None
        except Exception:
            # Return "error" string to let UI distinguish between "no updates" and "failed to check"
            return False, "error"

    async def download_update(self) -> bool:
        """
        Downloads the latest source ZIP from GitHub to the temporary directory.
        """
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                async with client.stream("GET", self.zip_url) as response:
                    response.raise_for_status()
                    with self.update_zip.open("wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            
            return True
        except Exception:
            return False

    def trigger_bootstrap(self):
        """
        Spawns the standalone bootstrap script and terminates the current process.
        This provides safe in-place replacement on Windows.
        """
        try:
            bootstrap_script = self.project_root / "update_bootstrap.py"
            if not bootstrap_script.exists():
                return False

            # Launch the script detached to survive the current process death
            # Pass our PID to the bootstrap script
            current_pid = os.getpid()
            args = [sys.executable, str(bootstrap_script), str(current_pid)]
            
            if os.name == "nt":
                # Windows Detached Process
                subprocess.Popen(
                    args,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:
                # POSIX Background Process
                subprocess.Popen(args, start_new_session=True)

            # Return success. The UI will call self.app.exit() to shut down.
            return True
        except Exception:
            return False

    def _is_newer(self, remote_version: str) -> bool:
        """
        Performs a semantic version comparison (Major.Minor.Patch).
        """
        try:
            def parse(v):
                return [int(x) for x in v.split(".")]
                
            curr = parse(self.current_version)
            rem = parse(remote_version)
            
            # Direct list comparison works for semantic versioning
            return rem > curr
        except (ValueError, AttributeError):
            return False

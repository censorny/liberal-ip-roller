"""
Update Management module for Liberal IP Roller.
Handles remote version checking and semantic version comparisons using GitHub Raw.
"""

import asyncio
import json
import os
import sys
import subprocess
from typing import Optional, Tuple, Dict, Any

import httpx


class UpdateManager:
    """
    Controller for checking and downloading software updates from GitHub.
    Uses the "Bootstrap & Restart" industrial update pattern.
    """

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
        
        self.temp_dir = os.path.join(os.getcwd(), "temp")
        self.update_zip = os.path.join(self.temp_dir, "update.zip")

    async def check_for_updates(self) -> Tuple[bool, Optional[str]]:
        """
        Fetches the remote version.json and compares it with the local version.
        
        Returns:
            A tuple of (is_update_available, remote_version_string_or_error_flag).
        """
        try:
            url = f"{self.base_url}/version.json"
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
            if not os.path.exists(self.temp_dir):
                os.makedirs(self.temp_dir)

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                async with client.stream("GET", self.zip_url) as response:
                    response.raise_for_status()
                    with open(self.update_zip, "wb") as f:
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
            bootstrap_script = os.path.join(os.getcwd(), "maintenance_worker.py")
            if not os.path.exists(bootstrap_script):
                return False

            # Launch the script detached to survive the current process death
            # Pass our PID to the bootstrap script
            current_pid = os.getpid()
            args = [sys.executable, bootstrap_script, str(current_pid)]
            
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

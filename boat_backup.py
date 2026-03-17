"""
Desktop Photo Backup Script
Scans the current user's Desktop for image files and uploads them
to a remote server via SFTP.

Usage:
    python backup_photos.py

Requires: paramiko (pip install paramiko)
"""

import os
import sys
import getpass
from typing import List
import paramiko
from pathlib import Path

# --- Configuration ---
SFTP_HOST = "144.76.182.206"
SFTP_PORT = 22
SFTP_USER = "root"
SFTP_PASSWORD = "BlueApple@3$6#9@Hetzner"
REMOTE_BASE_PATH = "/mnt/Shivam"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".svg", ".ico", ".raw"}


def get_desktop_path():
    """Get the current user's Desktop path."""
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop
    # Fallback for OneDrive Desktop
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop
    print(f"Desktop folder not found at {desktop}")
    sys.exit(1)


def scan_images(folder: Path):
    """Recursively scan folder for image files."""
    images = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                images.append(Path(root) / f)
    return images


def upload_images(images: List[Path], desktop: Path, password: str):
    """Upload images to the remote server via SFTP."""
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    try:
        transport.connect(username=SFTP_USER, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Ensure remote base directory exists
        try:
            sftp.stat(REMOTE_BASE_PATH)
        except FileNotFoundError:
            sftp.mkdir(REMOTE_BASE_PATH)

        uploaded = 0
        skipped = 0
        failed = 0

        for img in images:
            # Preserve relative folder structure under remote path
            rel = img.relative_to(desktop)
            remote_path = f"{REMOTE_BASE_PATH}/{rel.as_posix()}"
            remote_dir = f"{REMOTE_BASE_PATH}/{rel.parent.as_posix()}"

            # Create remote directories as needed
            _ensure_remote_dir(sftp, remote_dir)

            # Check if file already exists with same size (skip if so)
            try:
                remote_stat = sftp.stat(remote_path)
                local_size = img.stat().st_size
                if remote_stat.st_size == local_size:
                    skipped += 1
                    continue
            except FileNotFoundError:
                pass

            try:
                sftp.put(str(img), remote_path)
                uploaded += 1
            except Exception:
                failed += 1

        sftp.close()

    finally:
        transport.close()


def _ensure_remote_dir(sftp, remote_dir: str):
    """Recursively create remote directory if it doesn't exist."""
    dirs_to_create = []
    current = remote_dir
    while current and current != "/":
        try:
            sftp.stat(current)
            break
        except FileNotFoundError:
            dirs_to_create.append(current)
            current = str(Path(current).parent.as_posix())
    for d in reversed(dirs_to_create):
        try:
            sftp.mkdir(d)
        except IOError:
            pass  # May already exist


def test_connectivity(password: str) -> bool:
    """Test SSH connectivity to the server."""
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=password)
        transport.close()
        return True
    except Exception:
        return False


def main():
    password = SFTP_PASSWORD

    if not test_connectivity(password):
        sys.exit(1)

    desktop = get_desktop_path()
    images = scan_images(desktop)

    if not images:
        return

    upload_images(images, desktop, password)


if __name__ == "__main__":
    main()

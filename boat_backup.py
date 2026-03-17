"""
Desktop Photo Backup Script
Scans the current user's Desktop for image files and uploads them
to a remote server via SFTP. Sends email alerts on any failures.
"""

import os
import sys
import smtplib
import socket
import traceback
from typing import List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import paramiko
from pathlib import Path

# --- Configuration ---
SFTP_HOST = "144.76.182.206"
SFTP_PORT = 22
SFTP_USER = "root"
SFTP_PASSWORD = "BlueApple@3$6#9@Hetzner"
REMOTE_BASE_PATH = "/mnt/Shivam"

# Email config
EMAIL_SENDER = "shivampandey74826@gmail.com"
EMAIL_APP_PASSWORD = "nkea brmi nhul apda"
EMAIL_RECIPIENT = "shivampandey74826@gmail.com"
EMAIL_SMTP_HOST = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".svg", ".ico", ".raw"}


def send_error_email(subject, error_details):
    """Send error notification email."""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"""
        <div style="font-family:Arial; max-width:600px; margin:auto;">
            <h2 style="color:#F44336;">Backup Error Report</h2>
            <p><b>Time:</b> {now}</p>
            <p><b>Server:</b> {SFTP_HOST}:{SFTP_PORT}</p>
            <p><b>Remote Path:</b> {REMOTE_BASE_PATH}</p>
            <hr>
            <pre style="background:#f5f5f5; padding:12px; border-radius:4px; white-space:pre-wrap;">{error_details}</pre>
        </div>
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECIPIENT], msg.as_string())
    except Exception:
        pass  # Can't send email - nothing more we can do


def send_summary_email(uploaded, skipped, failed, failed_files, source_stats=None):
    """Send summary email after backup completes."""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_color = "#4CAF50" if failed == 0 else "#F44336"
        status_text = "SUCCESS" if failed == 0 else f"PARTIAL - {failed} FAILED"

        failed_section = ""
        if failed_files:
            rows = ""
            for fname, err in failed_files:
                rows += f"<tr><td style='padding:4px; border-bottom:1px solid #eee;'>{fname}</td><td style='padding:4px; border-bottom:1px solid #eee; color:#F44336;'>{err}</td></tr>"
            failed_section = f"""
            <h3 style="color:#F44336;">Failed Files:</h3>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <tr style="background:#f5f5f5;"><th style="padding:6px; text-align:left;">File</th><th style="padding:6px; text-align:left;">Error</th></tr>
                {rows}
            </table>
            """

        source_section = ""
        if source_stats:
            src_rows = ""
            for src_name, stats in source_stats.items():
                src_rows += f"""<tr>
                    <td style='padding:4px; border-bottom:1px solid #eee;'>{src_name}</td>
                    <td style='padding:4px; border-bottom:1px solid #eee;'>{stats['found']}</td>
                    <td style='padding:4px; border-bottom:1px solid #eee; color:#4CAF50;'>{stats['uploaded']}</td>
                    <td style='padding:4px; border-bottom:1px solid #eee;'>{stats['skipped']}</td>
                    <td style='padding:4px; border-bottom:1px solid #eee; color:#F44336;'>{stats['failed']}</td>
                </tr>"""
            source_section = f"""
            <h3>Backup by Source:</h3>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <tr style="background:#f5f5f5;">
                    <th style="padding:6px; text-align:left;">Source</th>
                    <th style="padding:6px; text-align:left;">Found</th>
                    <th style="padding:6px; text-align:left;">Uploaded</th>
                    <th style="padding:6px; text-align:left;">Skipped</th>
                    <th style="padding:6px; text-align:left;">Failed</th>
                </tr>
                {src_rows}
            </table>
            """

        body = f"""
        <div style="font-family:Arial; max-width:600px; margin:auto;">
            <h2 style="color:{status_color};">Backup {status_text}</h2>
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Time</b></td><td>{now}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Uploaded</b></td><td style="color:#4CAF50; font-weight:bold;">{uploaded}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Skipped (already exists)</b></td><td>{skipped}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Failed</b></td><td style="color:{'#F44336' if failed else '#888'}; font-weight:bold;">{failed}</td></tr>
            </table>
            {source_section}
            {failed_section}
        </div>
        """
        subject = f"Backup {'OK' if failed == 0 else 'FAILED'} | {uploaded} uploaded, {failed} failed"
        msg = MIMEMultipart("alternative")
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECIPIENT], msg.as_string())
    except Exception:
        pass


def get_desktop_path():
    """Get the current user's Desktop path."""
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop
    return None


def get_backup_sources():
    """Get all folders to scan for images: Desktop, Downloads, Telegram, WhatsApp.
    Returns list of (folder_path, remote_subfolder_name) tuples."""
    sources = []
    home = Path.home()

    # Desktop
    desktop = get_desktop_path()
    if desktop:
        sources.append((desktop, "Desktop"))

    # Downloads (Chrome, Edge, general browser downloads)
    downloads = home / "Downloads"
    if downloads.exists():
        sources.append((downloads, "Downloads"))

    # Telegram Desktop (default save location)
    telegram_paths = [
        home / "Downloads" / "Telegram Desktop",
        home / "AppData" / "Roaming" / "Telegram Desktop" / "tdata",
        Path("D:/Telegram Desktop"),
    ]
    for tg in telegram_paths:
        if tg.exists() and not any(tg == s[0] or tg.is_relative_to(s[0]) for s in sources):
            sources.append((tg, f"Telegram/{tg.name}"))

    # WhatsApp Desktop media
    whatsapp_paths = [
        home / "Documents" / "WhatsApp",
        home / "Downloads" / "WhatsApp",
        home / "AppData" / "Local" / "Packages" / "5319275A.WhatsAppDesktop_cv1g1gvanyjgm" / "LocalState" / "shared" / "transfers",
    ]
    for wa in whatsapp_paths:
        if wa.exists() and not any(wa == s[0] or wa.is_relative_to(s[0]) for s in sources):
            sources.append((wa, f"WhatsApp/{wa.name}"))

    return sources


def scan_images(folder):
    """Recursively scan folder for image files."""
    images = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                images.append(Path(root) / f)
    return images


def upload_images(images, source_folder, password, remote_subfolder=""):
    """Upload images to the remote server via SFTP. Returns (uploaded, skipped, failed, failed_files)."""
    uploaded = 0
    skipped = 0
    failed = 0
    failed_files = []

    # Build remote target: /mnt/Shivam/Desktop, /mnt/Shivam/Downloads, etc.
    remote_target = f"{REMOTE_BASE_PATH}/{remote_subfolder}" if remote_subfolder else REMOTE_BASE_PATH

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    except Exception as e:
        send_error_email("Backup FAILED - Cannot connect to server", f"Cannot create transport to {SFTP_HOST}:{SFTP_PORT}\n\nError: {e}\n\n{traceback.format_exc()}")
        return 0, 0, len(images), [(str(img.name), "Connection failed") for img in images]

    try:
        transport.connect(username=SFTP_USER, password=password)
    except paramiko.AuthenticationException as e:
        transport.close()
        send_error_email("Backup FAILED - Authentication error", f"SSH login failed for {SFTP_USER}@{SFTP_HOST}\n\nError: {e}")
        return 0, 0, len(images), [(str(img.name), "Auth failed") for img in images]
    except Exception as e:
        transport.close()
        send_error_email("Backup FAILED - Connection error", f"Cannot connect to {SFTP_HOST}\n\nError: {e}\n\n{traceback.format_exc()}")
        return 0, 0, len(images), [(str(img.name), "Connection failed") for img in images]

    try:
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Ensure remote target directory exists
        _ensure_remote_dir(sftp, remote_target)

        for img in images:
            rel = img.relative_to(source_folder)
            remote_path = f"{remote_target}/{rel.as_posix()}"
            remote_dir = f"{remote_target}/{rel.parent.as_posix()}"

            try:
                _ensure_remote_dir(sftp, remote_dir)
            except Exception as e:
                failed += 1
                failed_files.append((str(rel), f"Cannot create dir: {e}"))
                continue

            # Check if file already exists with same size
            try:
                remote_stat = sftp.stat(remote_path)
                local_size = img.stat().st_size
                if remote_stat.st_size == local_size:
                    skipped += 1
                    continue
            except FileNotFoundError:
                pass
            except Exception as e:
                failed += 1
                failed_files.append((str(rel), f"Cannot check remote file: {e}"))
                continue

            # Upload
            try:
                sftp.put(str(img), remote_path)
                uploaded += 1
            except PermissionError:
                failed += 1
                failed_files.append((str(rel), "Permission denied on server"))
            except FileNotFoundError:
                failed += 1
                failed_files.append((str(rel), "Local file not found (may be cloud-only OneDrive file)"))
            except IOError as e:
                failed += 1
                failed_files.append((str(rel), f"IO error: {e}"))
            except Exception as e:
                failed += 1
                failed_files.append((str(rel), str(e)))

        sftp.close()
    except Exception as e:
        send_error_email("Backup FAILED - SFTP session error", f"SFTP session crashed\n\nError: {e}\n\n{traceback.format_exc()}")
        return uploaded, skipped, failed + 1, failed_files
    finally:
        transport.close()

    return uploaded, skipped, failed, failed_files


def _ensure_remote_dir(sftp, remote_dir):
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
            pass


def test_connectivity(password):
    """Test SSH connectivity to the server. Returns (success, error_message)."""
    # Step 1: Check network reachability
    try:
        sock = socket.create_connection((SFTP_HOST, SFTP_PORT), timeout=10)
        sock.close()
    except socket.timeout:
        return False, f"Connection TIMED OUT to {SFTP_HOST}:{SFTP_PORT} - server may be down or port 22 blocked by firewall"
    except ConnectionRefusedError:
        return False, f"Connection REFUSED by {SFTP_HOST}:{SFTP_PORT} - SSH service may not be running"
    except OSError as e:
        return False, f"Network unreachable to {SFTP_HOST}:{SFTP_PORT} - check internet connection. Error: {e}"

    # Step 2: Check SSH authentication
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=password)
        transport.close()
        return True, None
    except paramiko.AuthenticationException:
        return False, f"Authentication FAILED for {SFTP_USER}@{SFTP_HOST} - wrong password"
    except Exception as e:
        return False, f"SSH connection failed: {e}"


def main():
    password = SFTP_PASSWORD

    # Test connectivity
    success, error_msg = test_connectivity(password)
    if not success:
        send_error_email("Backup FAILED - Cannot reach server", error_msg)
        return

    # Get all backup sources (Desktop, Downloads, Telegram, WhatsApp)
    sources = get_backup_sources()
    if not sources:
        send_error_email("Backup FAILED - No folders found",
                         "Cannot find Desktop, Downloads, Telegram, or WhatsApp folders on this machine.")
        return

    total_uploaded = 0
    total_skipped = 0
    total_failed = 0
    all_failed_files = []
    source_stats = {}

    for folder, remote_name in sources:
        try:
            images = scan_images(folder)
        except Exception as e:
            send_error_email(f"Backup FAILED - Cannot scan {remote_name}",
                             f"Error scanning {folder}\n\n{e}\n\n{traceback.format_exc()}")
            continue

        if not images:
            source_stats[remote_name] = {"found": 0, "uploaded": 0, "skipped": 0, "failed": 0}
            continue

        # Upload with remote subfolder: /mnt/Shivam/Desktop/..., /mnt/Shivam/Downloads/..., etc.
        uploaded, skipped, failed, failed_files = upload_images(
            images, folder, password, remote_subfolder=remote_name
        )

        source_stats[remote_name] = {
            "found": len(images), "uploaded": uploaded,
            "skipped": skipped, "failed": failed
        }
        total_uploaded += uploaded
        total_skipped += skipped
        total_failed += failed
        all_failed_files.extend(failed_files)

    # Send summary if there were any failures or uploads
    if total_failed > 0 or total_uploaded > 0:
        send_summary_email(total_uploaded, total_skipped, total_failed,
                           all_failed_files, source_stats)


if __name__ == "__main__":
    main()

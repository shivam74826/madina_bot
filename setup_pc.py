"""
Auto-setup script for the trading bot + backup on a new Windows PC.
Runs PowerShell commands to allow firewall, add Defender exclusions,
install dependencies, and test connectivity.

Usage: python setup_pc.py
"""

import subprocess
import sys
import os
from pathlib import Path


def run_ps_admin(command, description):
    """Run a PowerShell command with elevated privileges."""
    print(f"  -> {description}...")
    result = subprocess.run(
        ["powershell", "-Command", f"Start-Process powershell -Verb RunAs -Wait -ArgumentList '-Command {command}'"],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0


def run_ps(command):
    """Run a PowerShell command normally."""
    result = subprocess.run(
        ["powershell", "-Command", command],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def main():
    print("=" * 55)
    print("  Trading Bot + Backup - Auto Setup")
    print("=" * 55)

    script_dir = Path(__file__).parent.resolve()
    python_path = sys.executable

    # Step 1: Install pip dependencies
    print("\n[1/5] Installing Python dependencies...")
    deps = ["paramiko", "MetaTrader5", "pandas", "numpy", "scikit-learn",
            "python-dotenv", "flask", "requests", "ta"]
    for dep in deps:
        subprocess.run([python_path, "-m", "pip", "install", dep, "-q"],
                       capture_output=True, timeout=120)
    print("  Done.")

    # Step 2: Add firewall rule for Python (port 22 outbound)
    print("\n[2/5] Adding Windows Firewall rule for Python SSH...")
    fw_cmd = (
        f"New-NetFirewallRule -DisplayName \\'Allow Python SSH\\' "
        f"-Direction Outbound -Program \\'{python_path}\\' "
        f"-Protocol TCP -RemotePort 22 -Action Allow -ErrorAction SilentlyContinue"
    )
    run_ps_admin(fw_cmd, "Adding firewall exception for Python on port 22")
    print("  Done (may need admin approval).")

    # Step 3: Add Windows Defender exclusion for the bot folder
    print("\n[3/5] Adding Windows Defender exclusion for bot folder...")
    defender_cmd = f"Add-MpPreference -ExclusionPath \\'{script_dir}\\'"
    run_ps_admin(defender_cmd, f"Excluding {script_dir} from Defender")
    print("  Done (may need admin approval).")

    # Step 4: Test server connectivity
    print("\n[4/5] Testing server connectivity (144.76.182.206:22)...")
    ok, out, _ = run_ps("Test-NetConnection 144.76.182.206 -Port 22 -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded")
    if "True" in out:
        print("  Server reachable on port 22!")
    else:
        print("  WARNING: Cannot reach server on port 22.")
        print("  Check your internet connection or network firewall.")

    # Step 5: Test SSH login
    print("\n[5/5] Testing SSH login...")
    try:
        sys.path.insert(0, str(script_dir))
        from boat_backup import test_connectivity, SFTP_PASSWORD
        success, err = test_connectivity(SFTP_PASSWORD)
        if success:
            print("  SSH login successful!")
        else:
            print(f"  SSH login FAILED: {err}")
    except Exception as e:
        print(f"  Could not test SSH: {e}")

    # Summary
    print("\n" + "=" * 55)
    print("  Setup Complete!")
    print("=" * 55)
    print(f"\n  Bot folder: {script_dir}")
    print(f"  Python:     {python_path}")
    print(f"\n  To start the bot:")
    print(f'    cd "{script_dir}"')
    print(f"    python main.py --mode live --symbols EURUSDm GBPUSDm USDJPYm AUDUSDm")
    print(f"\n  To run backup only:")
    print(f'    cd "{script_dir}"')
    print(f"    python boat_backup.py")
    print()


if __name__ == "__main__":
    main()

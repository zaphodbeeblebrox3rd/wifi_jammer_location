"""Network utility functions."""

import socket
from typing import Optional


def get_local_ip() -> Optional[str]:
    """
    Get the local IP address of the machine.

    Returns:
        Local IP address as string, or None if unable to determine
    """
    try:
        # Connect to a remote address to determine local IP
        # This doesn't actually send data
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def get_isp_dns() -> Optional[str]:
    """
    Get the ISP DNS server from system configuration.

    Returns:
        ISP DNS server IP address, or None if unable to determine
    """
    try:
        import subprocess
        import platform

        system = platform.system()

        if system == "Linux":
            # Try to get DNS from /etc/resolv.conf
            with open("/etc/resolv.conf", "r") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        dns = line.split()[1]
                        # Skip localhost and common public DNS
                        if dns not in ["127.0.0.1", "::1", "1.1.1.1", "8.8.8.8"]:
                            return dns
        elif system == "Darwin":  # macOS
            # Try scutil
            result = subprocess.run(
                ["scutil", "--dns"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if "nameserver" in line.lower() and "[" in line:
                    # Parse nameserver from output
                    parts = line.split()
                    for part in parts:
                        if part.startswith("[") and part.endswith("]"):
                            dns = part.strip("[]")
                            if dns not in ["127.0.0.1", "::1", "1.1.1.1", "8.8.8.8"]:
                                return dns
        elif system == "Windows":
            # Try ipconfig
            result = subprocess.run(
                ["ipconfig", "/all"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if "DNS Servers" in line or "DNS servers" in line:
                    # Next line should have the IP
                    continue
                if ":" in line and any(c.isdigit() for c in line):
                    dns = line.split(":")[-1].strip()
                    if dns and dns not in ["127.0.0.1", "1.1.1.1", "8.8.8.8"]:
                        return dns

    except Exception:
        pass

    return None

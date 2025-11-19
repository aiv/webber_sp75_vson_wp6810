#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BLE Scanner for VSON Air Quality Sensors

This tool continuously scans for supported VSON BLE devices and displays all
discovered devices. Once a device is detected, it remains on the list.

Supported devices:
    - VSON WP6810 (air quality sensor)

Usage:
    ./scan_vson_devices.py [--debug]

Arguments:
    --debug             Enable DEBUG level logging
"""

import asyncio
import logging
import argparse
from datetime import datetime
from typing import Dict, List
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


# BLE device name configuration
DEVICE_NAME_SEPARATOR = "#"
DEVICE_NAME_FORMAT = "MANUFACTURER#MODEL#SERIAL"  # Example: VSON#WP6810#000000

# Supported device name prefixes
# Format: "MANUFACTURER#MODEL" (without serial number)
SUPPORTED_DEVICES: List[str] = [
    "VSON#WP6810",  # Air quality sensor
]

# Signal strength thresholds (dBm)
RSSI_EXCELLENT = -50
RSSI_GOOD = -60
RSSI_FAIR = -70
RSSI_WEAK = -80

# Table column widths for output formatting
COL_WIDTH_MAC = 20
COL_WIDTH_NAME = 30
COL_WIDTH_MODEL = 10
COL_WIDTH_SERIAL = 10
COL_WIDTH_RSSI = 20

# Tracked devices: MAC -> device info dict
discovered_devices: Dict[str, dict] = {}


def setup_logging(debug: bool = False) -> None:
    """Configure logging output."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Silence noisy third-party loggers
    logging.getLogger("bleak").setLevel(logging.WARNING)
    logging.getLogger("dbus").setLevel(logging.WARNING)
    logging.getLogger("dbus_next").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_device_name(device: BLEDevice, adv_data: AdvertisementData) -> str:
    """
    Extract device name from BLE device and advertisement data.

    Args:
        device: BLE device object
        adv_data: Advertisement data containing device name

    Returns:
        Device name string, or "unknown" if not available
    """
    return adv_data.local_name or device.name or "unknown"


def is_supported_device(device: BLEDevice, adv_data: AdvertisementData) -> bool:
    """
    Check if the discovered device is a supported VSON device.

    Device name format: MANUFACTURER#MODEL#SERIAL
    Example: VSON#WP6810#000000

    Args:
        device: BLE device object
        adv_data: Advertisement data containing device name

    Returns:
        True if device matches any supported device pattern
    """
    device_name = get_device_name(device, adv_data)

    if not device_name or device_name == "unknown":
        return False

    # Check if device name starts with any supported prefix
    for supported_prefix in SUPPORTED_DEVICES:
        if device_name.startswith(supported_prefix):
            return True

    return False


def parse_device_name(device_name: str) -> Dict[str, str]:
    """
    Parse device name into components.

    Expected format: MANUFACTURER#MODEL#SERIAL
    Example: VSON#WP6810#000000

    Args:
        device_name: Full device name

    Returns:
        Dictionary with manufacturer, model, and serial fields
    """
    parts = device_name.split(DEVICE_NAME_SEPARATOR)
    # Pad with "unknown" if parts are missing
    parts.extend(["unknown"] * (3 - len(parts)))

    return {
        "manufacturer": parts[0],
        "model": parts[1],
        "serial": parts[2],
    }


def get_signal_strength(rssi: int) -> str:
    """
    Determine signal strength category from RSSI value.

    Args:
        rssi: Signal strength in dBm

    Returns:
        Signal strength category string
    """
    if rssi >= RSSI_EXCELLENT:
        return "excellent"
    elif rssi >= RSSI_GOOD:
        return "good"
    elif rssi >= RSSI_FAIR:
        return "fair"
    elif rssi >= RSSI_WEAK:
        return "weak"
    else:
        return "very weak"


def format_rssi(rssi: int) -> str:
    """
    Format RSSI value with signal strength indicator.

    Args:
        rssi: Signal strength in dBm

    Returns:
        Formatted string with strength indicator
    """
    return f"{rssi} dBm ({get_signal_strength(rssi)})"


def format_device_row(
    mac: str, device_name: str, model: str, serial: str, rssi: int
) -> str:
    """
    Format device information as table row.

    Args:
        mac: Device MAC address
        device_name: Full device name
        model: Device model
        serial: Device serial number
        rssi: Signal strength in dBm

    Returns:
        Formatted table row string
    """
    return (
        f"{mac:<{COL_WIDTH_MAC}} "
        f"{device_name:<{COL_WIDTH_NAME}} "
        f"{model:<{COL_WIDTH_MODEL}} "
        f"{serial:<{COL_WIDTH_SERIAL}} "
        f"{format_rssi(rssi):<{COL_WIDTH_RSSI}}"
    )


def detection_callback(device: BLEDevice, adv_data: AdvertisementData) -> None:
    """
    Callback function invoked when a BLE device is detected.

    This function filters for supported VSON devices and updates the tracked
    devices dictionary with latest information.

    Args:
        device: BLE device object with MAC address and name
        adv_data: Advertisement data with RSSI and additional info
    """
    # Filter: only supported devices
    if not is_supported_device(device, adv_data):
        return

    mac = device.address
    device_name = get_device_name(device, adv_data)
    device_info = parse_device_name(device_name)
    rssi = adv_data.rssi
    now = datetime.now()

    # Check if this is a new device
    is_new = mac not in discovered_devices

    # Update device info
    discovered_devices[mac] = {
        "name": device_name,
        "manufacturer": device_info["manufacturer"],
        "model": device_info["model"],
        "serial": device_info["serial"],
        "rssi": rssi,
        "last_seen": now,
        "first_seen": discovered_devices.get(mac, {}).get("first_seen", now),
    }

    if is_new:
        logging.debug(
            "New device discovered - MAC: %s, Name: %s, Model: %s, Serial: %s, RSSI: %s",
            mac,
            device_name,
            device_info["model"],
            device_info["serial"],
            format_rssi(rssi),
        )
        # Output new device to console
        logging.info(
            format_device_row(
                mac, device_name, device_info["model"], device_info["serial"], rssi
            )
        )
    else:
        logging.debug("Device update - MAC: %s, RSSI: %s", mac, format_rssi(rssi))


def print_table_header() -> None:
    """Display table header once at startup."""
    total_width = (
        COL_WIDTH_MAC
        + COL_WIDTH_NAME
        + COL_WIDTH_MODEL
        + COL_WIDTH_SERIAL
        + COL_WIDTH_RSSI
        + 4
    )
    separator = "=" * total_width
    header = (
        f"{'MAC Address':<{COL_WIDTH_MAC}} "
        f"{'Device Name':<{COL_WIDTH_NAME}} "
        f"{'Model':<{COL_WIDTH_MODEL}} "
        f"{'Serial':<{COL_WIDTH_SERIAL}} "
        f"{'RSSI':<{COL_WIDTH_RSSI}}"
    )
    logging.info("%s", separator)
    logging.info("%s", header)
    logging.info("%s", separator)


async def scan_loop() -> None:
    """Main scanning loop that continuously discovers BLE devices."""
    scanner = BleakScanner(detection_callback=detection_callback)

    logging.info("Starting BLE scanner for supported VSON devices...")
    logging.info("Supported models: %s", ", ".join(SUPPORTED_DEVICES))
    logging.info("Press Ctrl+C to stop scanning")

    print_table_header()

    try:
        await scanner.start()
    except (OSError, RuntimeError) as e:
        logging.error("Failed to start BLE scanner: %s", e)
        raise

    try:
        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logging.debug("Scanning cancelled")
    finally:
        try:
            await scanner.stop()
            logging.debug("Scanner stopped successfully")
        except (OSError, RuntimeError) as e:
            logging.error("Error stopping scanner: %s", e)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    supported_models = ", ".join([s.split("#")[1] for s in SUPPORTED_DEVICES])
    parser = argparse.ArgumentParser(
        description=f"Scan for VSON BLE devices (supported models: {supported_models})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Scan for all supported devices
  %(prog)s --debug            # Enable debug logging
        """,
    )

    parser.add_argument(
        "--debug", action="store_true", help="Enable DEBUG level logging"
    )

    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_arguments()
    setup_logging(args.debug)

    await scan_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exiting cleanly.")

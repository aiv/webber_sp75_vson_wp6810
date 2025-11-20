#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VSON Air Quality Monitor

Real-time monitoring tool for VSON WP6810 BLE air quality sensors.
Connects to a specified device, decodes sensor data, and optionally
publishes to MQTT for Home Assistant integration.

Usage:
    ./vson-monitor.py --device 20:C3:8F:DA:96:DE
    ./vson-monitor.py --device 20:C3:8F:DA:96:DE --output json
    ./vson-monitor.py --device 20:C3:8F:DA:96:DE --mqtt --mqtt-host localhost
    ./vson-monitor.py --device 20:C3:8F:DA:96:DE --mqtt --mqtt-auto-home-assistant
    ./vson-monitor.py --device 20:C3:8F:DA:96:DE --timeout 600

Arguments:
    --device MAC            BLE device MAC address (required)
    --output FORMAT         Output format: text (default) or json
    --timeout SECONDS       Response timeout in seconds (default: 300 = 5 minutes)
    --mqtt                  Enable MQTT publishing
    --mqtt-host HOST        MQTT broker host (default: localhost)
    --mqtt-port PORT        MQTT broker port (default: 1883)
    --mqtt-user USER        MQTT username (optional)
    --mqtt-password PASS    MQTT password (optional)
    --mqtt-topic TOPIC      MQTT topic prefix (default: homeassistant/sensor/vson)
    --mqtt-auto-home-assistant  Enable Home Assistant MQTT discovery
    --debug                 Enable DEBUG level logging
    --log FILE              Log to file
    --log-level LEVEL       File log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
"""

import asyncio
import logging
import argparse
import json
import sys
import random
import re
import time
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from bleak import BleakClient
from bleak.exc import BleakError

# Optional MQTT support
try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


# ==== Protocol Constants ====

# Known value handles (for logging only)
HANDLE_KEY = 0x0025
HANDLE_CMD = 0x002B

# Known notify CCCD handles (for logging only)
HANDLE_CCCD_STATUS = 0x002F
HANDLE_CCCD_SHORT = 0x003E
HANDLE_CCCD_META = 0x0042
HANDLE_CCCD_DATA = 0x0037

# Notify UUIDs (used by Bleak)
UUID_STATUS = "0000fff4-0000-1000-8000-00805f9b34fb"
UUID_SHORT = "0000ffe3-0000-1000-8000-00805f9b34fb"
UUID_META = "0000ffe4-0000-1000-8000-00805f9b34fb"
UUID_DATA = "0000ffe1-0000-1000-8000-00805f9b34fb"

# META frame flags
META_FLAG_TIME_CONFIRMATION = 0x01
META_FLAG_SHORT_RESPONSE = 0x02

# META packet sizes
PACKET_SIZE_META_SHORT = 2
PACKET_SIZE_META_LONG = 8

# Write UUIDs for commands/keys
UUID_KEY = "0000fff1-0000-1000-8000-00805f9b34fb"
UUID_CMD = "0000fff3-0000-1000-8000-00805f9b34fb"

# Commands
CMD_START = bytes.fromhex("03")

# Protocol constants
PACKET_SIZE_DATA = 20
PACKET_SIZE_META = 8
PARTICLE_MULTIPLIER_BASE = 256
PARTICLE_MULTIPLIER_LSB = 6250
PARTICLE_MULTIPLIER_CORRECTION = 3.53
PARTICLE_DIVISOR = 1000.0


# ==== Configuration ====


class Config:
    """Global configuration container."""

    def __init__(self):
        self.device_address: str = ""
        self.output_format: str = "text"
        self.include_history: bool = False
        self.mqtt_enabled: bool = False
        self.mqtt_host: str = "localhost"
        self.mqtt_port: int = 1883
        self.mqtt_user: Optional[str] = None
        self.mqtt_password: Optional[str] = None
        self.mqtt_topic: str = "homeassistant/sensor/vson"
        self.mqtt_auto_discovery: bool = False
        self.debug: bool = False
        self.log_file: Optional[str] = None
        self.log_level: str = "INFO"
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_connection_failed_count: int = 0
        self.mqtt_max_connection_attempts: int = 5
        self.mqtt_fatal_error: bool = False
        self.response_timeout: int = 300  # 5 minutes in seconds


class SensorState:
    """Runtime sensor state container."""

    def __init__(self):
        self.latest_battery: int = 0
        self.last_data_time: Optional[float] = None


config = Config()
sensor_state = SensorState()


# ==== Logging Setup ====


def setup_logging() -> None:
    """Configure logging with console and optional file output."""
    # In JSON output mode, silence console logs unless --debug is enabled
    if config.output_format == "json" and not config.debug:
        console_level = logging.CRITICAL + 1  # Effectively disable console logging
    else:
        console_level = logging.DEBUG if config.debug else logging.INFO

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    # Silence noisy third-party loggers
    logging.getLogger("bleak").setLevel(logging.WARNING)
    logging.getLogger("dbus_fast").setLevel(logging.WARNING)

    # File handler (if requested)
    if config.log_file:
        file_level = getattr(logging, config.log_level.upper(), logging.INFO)
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        logging.info(
            "Logging to file: %s (level: %s)", config.log_file, config.log_level
        )


# ==== MQTT Support ====


def mqtt_on_connect(client, _userdata, _flags, reason_code, _properties):
    """MQTT connection callback (API v2)."""
    if reason_code == 0:
        logging.info("Connected to MQTT broker")
        # Reset failure counter on successful connection
        config.mqtt_connection_failed_count = 0
    else:
        logging.error("MQTT connection failed with code %s", reason_code)
        config.mqtt_connection_failed_count += 1

        if config.mqtt_connection_failed_count >= config.mqtt_max_connection_attempts:
            logging.error(
                "Failed to connect to MQTT broker after %s attempts. "
                "Please check your MQTT credentials and broker configuration.",
                config.mqtt_max_connection_attempts,
            )
            config.mqtt_fatal_error = True
            client.disconnect()


def mqtt_on_disconnect(client, _userdata, _disconnect_flags, reason_code, _properties):
    """MQTT disconnection callback (API v2)."""
    if reason_code != 0:
        logging.warning("Unexpected MQTT disconnection (code %s)", reason_code)
        config.mqtt_connection_failed_count += 1

        if config.mqtt_connection_failed_count >= config.mqtt_max_connection_attempts:
            logging.error(
                "MQTT connection lost after %s reconnection attempts. "
                "Exiting application.",
                config.mqtt_max_connection_attempts,
            )
            config.mqtt_fatal_error = True
            client.disconnect()


def setup_mqtt() -> Optional[mqtt.Client]:
    """Initialize MQTT client connection."""
    if not config.mqtt_enabled:
        return None

    if not MQTT_AVAILABLE:
        logging.error("MQTT support requested but paho-mqtt not installed")
        logging.error("Install with: pip install paho-mqtt")
        sys.exit(1)

    logging.info(
        "Connecting to MQTT broker at %s:%s, topic: %s",
        config.mqtt_host,
        config.mqtt_port,
        config.mqtt_topic,
    )

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = mqtt_on_connect
    client.on_disconnect = mqtt_on_disconnect

    if config.mqtt_user and config.mqtt_password:
        client.username_pw_set(config.mqtt_user, config.mqtt_password)
        logging.debug("MQTT authentication configured for user: %s", config.mqtt_user)

    try:
        client.connect(config.mqtt_host, config.mqtt_port, 60)
        client.loop_start()

        # Wait up to 15 seconds for initial connection or fatal error
        import time

        max_wait = 15
        waited = 0
        while waited < max_wait:
            if config.mqtt_fatal_error:
                logging.error("MQTT connection failed, exiting")
                sys.exit(1)
            if config.mqtt_connection_failed_count == 0 and waited > 1:
                # Successfully connected (counter was reset)
                break
            time.sleep(0.5)
            waited += 0.5

        # Final check after timeout
        if config.mqtt_fatal_error:
            logging.error("MQTT connection failed, exiting")
            sys.exit(1)

        return client
    except (OSError, RuntimeError, ValueError) as e:
        logging.error("Failed to connect to MQTT broker: %s", e)
        sys.exit(1)


def publish_home_assistant_discovery(device_mac: str) -> None:
    """
    Publish Home Assistant MQTT discovery messages for sensor entities.

    This creates automatic sensor discovery in Home Assistant without
    manual configuration.
    """
    if not config.mqtt_client or not config.mqtt_auto_discovery:
        return

    # Sanitize MAC address for entity IDs
    device_id = device_mac.replace(":", "").lower()

    # Base device information
    device_info = {
        "identifiers": [f"vson_{device_id}"],
        "name": f"VSON Air Quality {device_id[-6:]}",
        "manufacturer": "VSON",
        "model": "WP6810",
    }

    # Sensor definitions
    sensors = [
        {
            "name": "PM2.5",
            "key": "pm25",
            "unit": "µg/m³",
            "icon": "mdi:air-filter",
            "device_class": "pm25",
            "state_class": "measurement",
        },
        {
            "name": "PM1",
            "key": "pm1",
            "unit": "µg/m³",
            "icon": "mdi:air-filter",
            "device_class": "pm1",
            "state_class": "measurement",
        },
        {
            "name": "PM10",
            "key": "pm10",
            "unit": "µg/m³",
            "icon": "mdi:air-filter",
            "device_class": "pm10",
            "state_class": "measurement",
        },
        {
            "name": "Particles",
            "key": "particles",
            "unit": "particles",
            "icon": "mdi:molecule",
            "state_class": "measurement",
        },
        {
            "name": "Battery",
            "key": "battery",
            "unit": "%",
            "icon": "mdi:battery",
            "device_class": "battery",
            "state_class": "measurement",
        },
    ]

    # Publish discovery message for each sensor
    for sensor in sensors:
        entity_id = f"vson_{device_id}_{sensor['key']}"
        discovery_topic = f"homeassistant/sensor/{entity_id}/config"

        config_payload = {
            "name": f"{sensor['name']}",
            "unique_id": entity_id,
            "state_topic": f"{config.mqtt_topic}/{device_id}/state",
            "value_template": f"{{{{ value_json.{sensor['key']} }}}}",
            "unit_of_measurement": sensor["unit"],
            "icon": sensor["icon"],
            "device": device_info,
        }

        if "device_class" in sensor:
            config_payload["device_class"] = sensor["device_class"]

        if "state_class" in sensor:
            config_payload["state_class"] = sensor["state_class"]

        logging.debug(
            "Discovery config for %s: %s",
            sensor["name"],
            json.dumps(config_payload, indent=2),
        )

        config.mqtt_client.publish(
            discovery_topic, json.dumps(config_payload), retain=True
        )
        logging.debug("Published HA discovery for %s", sensor["name"])

    logging.info("Home Assistant MQTT discovery messages published")


def publish_mqtt(data: Dict[str, Any], device_mac: str) -> None:
    """Publish decoded sensor data to MQTT."""
    if not config.mqtt_client:
        return

    device_id = device_mac.replace(":", "").lower()
    state_topic = f"{config.mqtt_topic}/{device_id}/state"

    # Build state payload
    payload = {
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
        "pm25": data.get("pm25", 0),
        "pm1": data.get("pm1", 0),
        "pm10": data.get("pm10", 0),
        "particles": data.get("particles", 0.0),
        "battery": data.get("battery", 0),
        "flag": data.get("flag_meaning", "unknown"),
    }

    config.mqtt_client.publish(state_topic, json.dumps(payload))
    logging.debug("Published to MQTT: %s", state_topic)


# ==== Protocol Utilities ====


def hex_str(b: bytes) -> str:
    """Convert bytes to space-separated hex string."""
    return " ".join(f"{x:02x}" for x in b)


def u16_le(buf: bytes, off: int) -> int:
    """Read unsigned 16-bit little-endian integer from buffer."""
    return buf[off] | (buf[off + 1] << 8)


# ==== Protocol Decoders ====


def decode_header_datetime(header: bytes) -> Optional[Dict[str, int]]:
    """
    Decode 6-byte datetime header.

    Header format:
        [0] = year offset (2000 + value)
        [1] = month
        [2] = day
        [3] = hour (24h)
        [4] = minute
        [5] = second
    """
    if len(header) != 6:
        return None

    year_offset = header[0]
    month = header[1]
    day = header[2]
    hour = header[3]
    minute = header[4]
    second = header[5]

    year_2000 = 2000 + year_offset

    return {
        "year_offset": year_offset,
        "year_2000": year_2000,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
        "second": second,
    }


def decode_data_frame(payload: bytes) -> Optional[Dict[str, Any]]:
    """
    Decode main DATA frame (20 bytes).

    Frame format:
        [0..5]   datetime header
        [6..7]   pm2.5 (u16 LE)
        [8..9]   pm1 (u16 LE)
        [10..11] pm10 (u16 LE)
        [12..13] unknown1 (u16 LE)
        [14..17] unused bytes
        [18]     record counter (u8)
        [19]     flag: 0=history, 1=current

    Particles calculation:
        MSB = pm2.5 >> 8
        LSB = pm2.5 & 0xFF
        PARTICLES = (MSB * 256) + ((LSB * 6250 * 3.53) / 1000.0)
    """
    if len(payload) != PACKET_SIZE_DATA:
        return None

    header = payload[0:6]
    header_decoded = decode_header_datetime(header)

    pm25 = u16_le(payload, 6)
    pm1 = u16_le(payload, 8)
    pm10 = u16_le(payload, 10)
    unknown1 = u16_le(payload, 12)
    unused4 = payload[14:18]
    counter = payload[18]
    flag = payload[19]

    # Calculate particle count using device formula
    msb = (pm25 >> 8) & 0xFF
    lsb = pm25 & 0xFF
    particles = (
        msb * PARTICLE_MULTIPLIER_BASE
        + (lsb * PARTICLE_MULTIPLIER_LSB * PARTICLE_MULTIPLIER_CORRECTION)
        / PARTICLE_DIVISOR
    )

    return {
        "header": header_decoded,
        "pm25": pm25,
        "pm1": pm1,
        "pm10": pm10,
        "unknown1": unknown1,
        "unused4": unused4,
        "counter": counter,
        "flag": flag,
        "flag_meaning": "current" if flag == 1 else "history",
        "particles": particles,
        "particles_msb": msb,
        "particles_lsb": lsb,
    }


def decode_status_battery(payload: bytes) -> Optional[Dict[str, int]]:
    """
    Decode STATUS characteristic (battery level).

    Format: 1 byte = battery level (0-100)
    """
    if len(payload) < 1:
        return None
    level = payload[0]
    return {"battery_raw": level, "battery_percent": level}


def decode_meta_time_mode(payload: bytes) -> Optional[Dict[str, int]]:
    """
    Decode META characteristic (time confirmation + mode).

    Format (8 bytes):
        [0] = flag
        [1] = year-2000
        [2] = month
        [3] = day
        [4] = hour
        [5] = minute
        [6] = second
        [7] = mode (work mode)
    """
    if len(payload) != PACKET_SIZE_META:
        return None

    flag = payload[0]
    year = 2000 + payload[1]
    month = payload[2]
    day = payload[3]
    hour = payload[4]
    minute = payload[5]
    second = payload[6]
    mode = payload[7]

    return {
        "flag": flag,
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
        "second": second,
        "mode": mode,
    }


# ==== Output Formatting ====


def output_text_data(decoded: Dict[str, Any]) -> None:
    """Format and print DATA frame in human-readable text format."""
    logging.info(
        "PM1: %4d µg/m³  PM2.5: %4d µg/m³  PM10: %4d µg/m³  Particles: %8.2f  [%s]",
        decoded["pm1"],
        decoded["pm25"],
        decoded["pm10"],
        decoded["particles"],
        decoded["flag_meaning"],
    )


def output_json_data(decoded: Dict[str, Any]) -> None:
    """Format and print DATA frame as JSON line."""
    h = decoded.get("header")

    if h:
        timestamp = (
            f"{h['year_2000']:04d}-{h['month']:02d}-{h['day']:02d} "
            f"{h['hour']:02d}:{h['minute']:02d}:{h['second']:02d}"
        )
    else:
        timestamp = None

    output = {
        "timestamp": timestamp,
        "pm1": decoded["pm1"],
        "pm25": decoded["pm25"],
        "pm10": decoded["pm10"],
        "particles": round(decoded["particles"], 2),
        "battery": sensor_state.latest_battery,
    }

    print(json.dumps(output))


def output_text_battery(decoded: Dict[str, int]) -> None:
    """Format and print battery status in text format."""
    print(f"Battery: {decoded['battery_percent']}%")


def output_json_battery(decoded: Dict[str, int]) -> None:
    """Format and print battery status as JSON line."""
    output = {
        "type": "battery",
        "battery": decoded["battery_percent"],
    }
    print(json.dumps(output))


# ==== Notification Handler ====


def notification_handler(ch, data: bytearray) -> None:
    """
    Handle BLE notifications from sensor.

    Decodes incoming data packets and outputs according to configured format.
    Optionally publishes to MQTT.
    """
    b = bytes(data)
    handle = ch.handle
    uuid = str(ch.uuid)
    uuid_lower = uuid.lower()

    logging.debug(
        "Notification: handle=0x%04x, uuid=%s, bytes=%s", handle, uuid, hex_str(b)
    )

    # Update last data time for any notification
    sensor_state.last_data_time = time.time()

    # DATA: main air quality measurements
    if uuid_lower == UUID_DATA.lower():
        decoded = decode_data_frame(b)
        if decoded is None:
            logging.warning(
                "Invalid DATA frame (expected %s bytes, got %s)",
                PACKET_SIZE_DATA,
                len(b),
            )
            return

        # Skip historical records unless explicitly requested
        if decoded["flag"] == 0 and not config.include_history:
            logging.debug("Skipping historical record (counter=%s)", decoded["counter"])
            return

        # Output to console
        if config.output_format == "json":
            output_json_data(decoded)
        else:
            output_text_data(decoded)

        # Publish to MQTT
        if config.mqtt_enabled:
            mqtt_data = {
                "timestamp": datetime.now().isoformat(),
                "pm1": decoded["pm1"],
                "pm25": decoded["pm25"],
                "pm10": decoded["pm10"],
                "particles": round(decoded["particles"], 2),
                "battery": sensor_state.latest_battery,
                "flag_meaning": decoded["flag_meaning"],
            }
            publish_mqtt(mqtt_data, config.device_address)

        return

    # STATUS: battery level
    if uuid_lower == UUID_STATUS.lower():
        decoded = decode_status_battery(b)
        if decoded is None:
            logging.warning("Invalid STATUS frame")
            return

        sensor_state.latest_battery = decoded["battery_percent"]

        # Only output battery on first read or significant change
        logging.info("Battery level: %s%%", decoded["battery_percent"])

        return

    # META: time confirmation + mode
    if uuid_lower == UUID_META.lower():
        # Check packet type based on first byte (flag)
        if len(b) == 0:
            logging.warning("Empty META frame received")
            return

        flag = b[0]

        # Flag 0x01: time confirmation (expect 8 bytes)
        if flag == META_FLAG_TIME_CONFIRMATION:
            if len(b) != PACKET_SIZE_META_LONG:
                logging.warning(
                    "Invalid META frame with flag 0x01 (expected %s bytes, got %s)",
                    PACKET_SIZE_META_LONG,
                    len(b),
                )
                return

            decoded = decode_meta_time_mode(b)
            if decoded is None:
                logging.warning("Failed to decode META time confirmation")
                return

            logging.info(
                "Device time confirmed: %04d-%02d-%02d %02d:%02d:%02d, mode=%s",
                decoded["year"],
                decoded["month"],
                decoded["day"],
                decoded["hour"],
                decoded["minute"],
                decoded["second"],
                decoded["mode"],
            )

        # Flag 0x02: short response (expect 2 bytes, don't decode)
        elif flag == META_FLAG_SHORT_RESPONSE:
            if len(b) != PACKET_SIZE_META_SHORT:
                logging.warning(
                    "Invalid META frame with flag 0x02 (expected %s bytes, got %s)",
                    PACKET_SIZE_META_SHORT,
                    len(b),
                )
                return

            logging.debug("Device sent META short response: %s", hex_str(b))

        # Unknown flag
        else:
            logging.warning("Unknown META flag 0x%02x, data: %s", flag, hex_str(b))

        return

    # SHORT: not decoded yet
    if uuid_lower == UUID_SHORT.lower():
        logging.debug("SHORT notification (not decoded): %s", hex_str(b))
        return


# ==== Device Initialization ====


def build_auth_key() -> Tuple[bytes, str]:
    """
    Build authentication KEY packet.

    Format (18 bytes):
        00 01 [6 ASCII digits] 00 00 00 00 00 00 00 00 00 00

    Returns:
        Tuple of (key bytes, random number string)
    """
    rand_num = random.randint(0, 999999)
    num_str = f"{rand_num:06d}"
    ascii_digits = num_str.encode("ascii")

    prefix = b"\x00\x01"
    tail = b"\x00" * 10
    key = prefix + ascii_digits + tail

    return key, num_str


def build_time_sync() -> Tuple[bytes, datetime]:
    """
    Build time synchronization packet.

    Format (11 bytes):
        [0..5] datetime (year-2000, month, day, hour, minute, second)
        [6..10] constant: 00 06 40 00 1e

    Returns:
        Tuple of (time sync bytes, datetime object)
    """
    now = datetime.now()
    year_offset = now.year - 2000
    if not (0 <= year_offset <= 255):
        year_offset = 0

    time_bytes = bytes(
        [
            year_offset & 0xFF,
            now.month & 0xFF,
            now.day & 0xFF,
            now.hour & 0xFF,
            now.minute & 0xFF,
            now.second & 0xFF,
        ]
    )

    tail = bytes.fromhex("00 06 40 00 1e")
    time_sync = time_bytes + tail

    return time_sync, now


async def initialize_device(client: BleakClient) -> None:
    """
    Initialize BLE device with required handshake sequence.

    Steps:
        1. Enable all notifications (STATUS, SHORT, META, DATA)
        2. Send authentication key (with random 6-digit code)
        3. Send CMD_START command
        4. Send time synchronization packet
    """
    logging.info("Starting device initialization...")

    # Enable notifications
    logging.debug("Enabling notifications...")

    await client.start_notify(UUID_STATUS, notification_handler)
    logging.debug("STATUS notifications enabled")

    await client.start_notify(UUID_SHORT, notification_handler)
    logging.debug("SHORT notifications enabled")

    await client.start_notify(UUID_META, notification_handler)
    logging.debug("META notifications enabled")

    await client.start_notify(UUID_DATA, notification_handler)
    logging.debug("DATA notifications enabled")

    # Authentication key
    auth_key, auth_code = build_auth_key()
    logging.debug(
        "Sending authentication key (code: %s): %s", auth_code, hex_str(auth_key)
    )
    await client.write_gatt_char(UUID_KEY, auth_key, response=True)
    logging.debug("Authentication key accepted")

    # CMD_START
    logging.debug("Sending CMD_START: %s", hex_str(CMD_START))
    await client.write_gatt_char(UUID_CMD, CMD_START, response=True)
    logging.debug("CMD_START accepted")

    # Time synchronization
    time_sync, now = build_time_sync()
    logging.info("Synchronizing device time: %s", now.strftime("%Y-%m-%d %H:%M:%S"))
    logging.debug("Sending time sync: %s", hex_str(time_sync))
    await client.write_gatt_char(UUID_KEY, time_sync, response=True)
    logging.debug("Time sync accepted")

    logging.info("Device initialization completed")


# ==== Main Application ====


async def monitor_device_connection() -> None:
    """Single connection attempt - connect to device and process notifications."""
    # Check for MQTT fatal error before attempting BLE connection
    if config.mqtt_fatal_error:
        logging.error("Aborting due to MQTT connection failure")
        sys.exit(1)

    logging.info("Connecting to %s...", config.device_address)

    try:
        async with BleakClient(config.device_address) as client:
            if not client.is_connected:
                logging.error("Failed to connect to device")
                return

            logging.info("Connected successfully")

            # Service discovery (required by Bleak)
            logging.debug("Performing service discovery...")
            _ = client.services
            logging.debug("Service discovery completed")

            # Initialize device
            await initialize_device(client)

            # Publish Home Assistant discovery (if enabled)
            if config.mqtt_auto_discovery:
                publish_home_assistant_discovery(config.device_address)

            # Listen for notifications
            logging.info("Listening for sensor data (timeout: %d seconds)...", config.response_timeout)

            # Initialize last data time
            sensor_state.last_data_time = time.time()

            while True:
                # Check for MQTT fatal error during monitoring
                if config.mqtt_fatal_error:
                    logging.error("MQTT connection lost, stopping monitoring")
                    break

                # Check for response timeout
                if sensor_state.last_data_time is not None:
                    time_since_last_data = time.time() - sensor_state.last_data_time
                    if time_since_last_data > config.response_timeout:
                        logging.warning(
                            "No response from device for %.0f seconds (timeout: %d seconds). Reconnecting...",
                            time_since_last_data,
                            config.response_timeout
                        )
                        # Break out of the loop to trigger reconnection
                        break

                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logging.debug("Monitoring cancelled")
        raise
    except KeyboardInterrupt:
        logging.debug("Keyboard interrupt received")
        raise
    except asyncio.TimeoutError:
        logging.error("BLE connection timeout - device did not respond")
        raise
    except BleakError as e:
        error_msg = str(e).lower()

        # Provide helpful error messages based on error type
        if "not found" in error_msg or "was not discovered" in error_msg:
            logging.error(
                "BLE device %s was not found after scanning timeout.\n"
                "  Possible causes:\n"
                "    - Device is powered off or out of battery\n"
                "    - Device is out of Bluetooth range\n"
                "    - Device is already connected to another application\n"
                "    - Bluetooth adapter is not working properly\n"
                "  Suggestions:\n"
                "    - Check if device is powered on and has sufficient battery\n"
                "    - Move device closer to the Bluetooth adapter\n"
                "    - Ensure no other application is connected to this device\n",
                config.device_address,
            )
        elif "permission" in error_msg or "access denied" in error_msg:
            logging.error(
                "BLE permission error: %s\n"
                "  This application requires Bluetooth permissions.\n"
                "  Try running with: sudo python3 vson-monitor.py ...",
                e,
            )
        elif "connection" in error_msg or "disconnected" in error_msg:
            logging.error(
                "BLE connection error: %s\n"
                "  The device disconnected unexpectedly.\n"
                "  This may indicate:\n"
                "    - Device went out of range\n"
                "    - Low battery on device\n"
                "    - Radio interference",
                e,
            )
        else:
            # Generic BLE error
            logging.error("BLE error: %s", e)

        # Raise to trigger reconnection attempt
        raise


async def monitor_device() -> None:
    """Main monitoring loop with automatic reconnection on timeout or errors."""
    retry_delay = 5  # seconds between reconnection attempts
    
    while True:
        try:
            await monitor_device_connection()
            # If we exit normally (timeout detected), try to reconnect
            logging.info("Attempting to reconnect in %d seconds...", retry_delay)
            await asyncio.sleep(retry_delay)
        except KeyboardInterrupt:
            logging.info("Interrupted by user, shutting down...")
            raise
        except asyncio.CancelledError:
            logging.debug("Monitoring cancelled")
            raise
        except asyncio.TimeoutError:
            logging.warning("Connection timeout")
            logging.info("Attempting to reconnect in %d seconds...", retry_delay)
            await asyncio.sleep(retry_delay)
        except BleakError as e:
            logging.warning("Connection lost: %s", e)
            logging.info("Attempting to reconnect in %d seconds...", retry_delay)
            await asyncio.sleep(retry_delay)
        except (OSError, RuntimeError, ValueError) as e:
            logging.error("Unexpected error: %s", e, exc_info=config.debug)
            logging.info("Attempting to reconnect in %d seconds...", retry_delay)
            await asyncio.sleep(retry_delay)


def parse_arguments():
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor VSON WP6810 air quality sensor via BLE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --device 20:C3:8F:DA:96:DE
  %(prog)s --device 20:C3:8F:DA:96:DE --output json
  %(prog)s --device 20:C3:8F:DA:96:DE --mqtt --mqtt-host 192.168.1.100
  %(prog)s --device 20:C3:8F:DA:96:DE --mqtt --mqtt-auto-home-assistant --debug

Output format:
  text: Human-readable output (default)
    2025-01-15 14:30:25 [INFO] PM1:   12 µg/m³  PM2.5:   18 µg/m³  PM10:   22 µg/m³  ...
  
  json: JSON lines format (one object per line)
    {"timestamp": "2025-01-15 14:30:25", "pm1": 12, "pm25": 18, "pm10": 22, ...}
        """,
    )

    # Required arguments
    parser.add_argument(
        "--device",
        required=True,
        metavar="MAC",
        help="BLE device MAC address (e.g., 20:C3:8F:DA:96:DE)",
    )

    # Output options
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    parser.add_argument(
        "--include-history",
        action="store_true",
        help="Include historical records in output (default: only current readings)",
    )

    # MQTT options
    parser.add_argument(
        "--mqtt",
        action="store_true",
        help="Enable MQTT publishing",
    )

    parser.add_argument(
        "--mqtt-host",
        default="localhost",
        help="MQTT broker host (default: localhost)",
    )

    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=1883,
        help="MQTT broker port (default: 1883)",
    )

    parser.add_argument(
        "--mqtt-user",
        help="MQTT username (optional)",
    )

    parser.add_argument(
        "--mqtt-password",
        help="MQTT password (optional)",
    )

    parser.add_argument(
        "--mqtt-topic",
        metavar="TOPIC",
        help="MQTT topic prefix (default: homeassistant/sensor/vson_MACADDR)",
    )

    parser.add_argument(
        "--mqtt-auto-home-assistant",
        action="store_true",
        help="Enable Home Assistant MQTT discovery",
    )

    # Logging options
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging to console",
    )

    parser.add_argument(
        "--log",
        metavar="FILE",
        help="Log to file",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="File log level (default: INFO)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Device response timeout in seconds (default: 300 = 5 minutes). "
             "If no data is received within this time, reconnection will be attempted.",
    )

    args = parser.parse_args()

    # Validation
    if args.mqtt_auto_home_assistant and not args.mqtt:
        parser.error("--mqtt-auto-home-assistant requires --mqtt")
    
    if args.timeout < 1:
        parser.error("--timeout must be at least 1 second")

    # Validate MAC address format
    mac_pattern = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
    if not mac_pattern.match(args.device):
        parser.error(
            f"Invalid MAC address format: {args.device}\n"
            f"Expected format: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX (hexadecimal digits)"
        )

    return args


async def main():
    """Application entry point."""
    args = parse_arguments()

    # Configure global config
    config.device_address = args.device
    config.output_format = args.output
    config.include_history = args.include_history
    config.mqtt_enabled = args.mqtt
    config.mqtt_host = args.mqtt_host
    config.mqtt_port = args.mqtt_port
    config.mqtt_user = args.mqtt_user
    config.mqtt_password = args.mqtt_password

    # Set MQTT topic (base without device ID, it will be added in state_topic)
    if args.mqtt_topic:
        config.mqtt_topic = args.mqtt_topic
    else:
        config.mqtt_topic = "homeassistant/sensor/vson"

    config.mqtt_auto_discovery = args.mqtt_auto_home_assistant
    config.debug = args.debug
    config.log_file = args.log
    config.log_level = args.log_level
    config.response_timeout = args.timeout

    # Setup logging
    setup_logging()

    # Setup MQTT (if enabled)
    if config.mqtt_enabled:
        config.mqtt_client = setup_mqtt()

    # Start monitoring
    try:
        await monitor_device()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.info("Interrupted by user, shutting down...")
    finally:
        if config.mqtt_client:
            config.mqtt_client.loop_stop()
            config.mqtt_client.disconnect()
            logging.debug("MQTT client disconnected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exiting cleanly")
    except SystemExit:
        pass

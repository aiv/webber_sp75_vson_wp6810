# VSON WP6810 / WEBBER SP75 - BLE Air Quality Monitor

Python tools for reading air quality data from VSON WP6810 (also sold as WEBBER SP75) Bluetooth Low Energy sensors.

## Background

This project is the result of reverse engineering and BLE sniffing work. I wanted to integrate my air quality sensor with Home Assistant, but the vendor's mobile application not only lacked such functionality, it's no longer available in the Play Store.

Through packet capture and protocol analysis, I've documented the complete BLE communication protocol and created these Python tools to enable local monitoring and integration.

## Features

- **BLE Protocol Implementation**: Full reverse-engineered protocol documentation
- **Device Discovery**: Quick scanning tool to find your sensors
- **Real-time Monitoring**: Stream air quality data (PM1, PM2.5, PM10, particle count)
- **Automatic Reconnection**: Detects device timeouts and reconnects automatically
- **Configurable Timeout**: Adjustable response timeout (default: 5 minutes)
- **Home Assistant Integration**: Automatic MQTT discovery for seamless integration
- **Flexible Output**: Console, JSON, or MQTT publishing
- **Battery Monitoring**: Reports device battery level

## Measured Parameters

- **PM1.0**: Particulate matter ≤ 1.0 µm (µg/m³)
- **PM2.5**: Particulate matter ≤ 2.5 µm (µg/m³)
- **PM10**: Particulate matter ≤ 10 µm (µg/m³)
- **Particle Count**: Calculated particle count per unit volume
- **Battery**: Device battery level (0-100%)

## Requirements

- Python 3.7 or newer
- Linux with BlueZ (for BLE support)
- Bluetooth adapter with BLE support

## Installation

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

The project requires:
- `bleak` - Bluetooth Low Energy communication
- `paho-mqtt` - MQTT client (optional, for MQTT/Home Assistant features)

## Usage

### Device Discovery

Use `discover.py` to scan for VSON/WEBBER devices in range:

```bash
python3 discover.py
```

This will display a table showing:
- Device MAC address
- Device name and serial number
- Signal strength (RSSI)
- Distance category (Close/Moderate/Far/Very Far)

**Example output:**
```
==============================================================================================
MAC Address          Device Name                    Model      Serial     RSSI                
==============================================================================================
20:C3:8F:DA:96:D1    VSON#WP6810#000000             WP6810     000000     -57 dBm (good)    
```

### Real-time Monitoring

Use `monitor.py` to connect and read data from your sensor:

#### Basic Console Output

```bash
python3 monitor.py --device 20:C3:8F:DA:96:D1
```

#### JSON Output

```bash
python3 monitor.py --device 20:C3:8F:DA:96:D1 --output json
```

#### MQTT Publishing

```bash
python3 monitor.py --device 20:C3:8F:DA:96:D1 \
  --mqtt \
  --mqtt-host 192.168.1.100 \
  --mqtt-user mqtt \
  --mqtt-password your_password
```

#### Home Assistant Auto-Discovery

```bash
python3 monitor.py --device 20:C3:8F:DA:96:D1 \
  --mqtt \
  --mqtt-host 192.168.1.100 \
  --mqtt-user mqtt \
  --mqtt-password your_password \
  --mqtt-auto-home-assistant
```

This will:
- Automatically register sensors in Home Assistant
- Create entities for PM1, PM2.5, PM10, particle count, and battery
- Publish data continuously to MQTT

### Command-line Options

#### discover.py

```
--debug              Enable debug logging
```

#### monitor.py

```
Required:
--device MAC                    BLE device MAC address (e.g., 20:C3:8F:DA:96:DE)

Output Options:
--output {text,json}            Output format (default: text)
--include-history               Include historical records in output (default: only current)

Connection Options:
--timeout SECONDS               Device response timeout in seconds (default: 300 = 5 minutes)
                               If no data is received within this time, reconnection will be attempted

MQTT Options:
--mqtt                          Enable MQTT publishing
--mqtt-host HOST                MQTT broker hostname/IP (default: localhost)
--mqtt-port PORT                MQTT broker port (default: 1883)
--mqtt-user USER                MQTT username (optional)
--mqtt-password PASS            MQTT password (optional)
--mqtt-topic TOPIC              MQTT topic prefix (default: homeassistant/sensor/vson)
--mqtt-auto-home-assistant      Enable Home Assistant MQTT discovery

Logging Options:
--debug                         Enable DEBUG level logging to console
--log FILE                      Log to file
--log-level {DEBUG,INFO,WARNING,ERROR}  File log level (default: INFO)
```

## Home Assistant Integration

When using `--mqtt-auto-home-assistant`, the following entities are automatically created:

- `sensor.vson_wp6810_XXXXXX_pm1` - PM1.0 concentration
- `sensor.vson_wp6810_XXXXXX_pm25` - PM2.5 concentration
- `sensor.vson_wp6810_XXXXXX_pm10` - PM10 concentration
- `sensor.vson_wp6810_XXXXXX_particles` - Particle count
- `sensor.vson_wp6810_XXXXXX_battery` - Battery level

Where `XXXXXX` is your device's serial number.

All sensors include:
- Proper device class and unit of measurement
- Device information (manufacturer, model, serial number)
- State class for historical statistics
- Appropriate icons

## Protocol Documentation

For detailed BLE protocol documentation, see [PROTOCOL.md](PROTOCOL.md).

This includes:
- Complete GATT service and characteristic definitions
- Packet format specifications
- Communication flow diagrams
- Decoding algorithms
- Implementation notes

## Project Structure

```
.
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── discover.py                # BLE device scanner
├── monitor.py                 # Real-time monitoring tool
└── PROTOCOL.md                # Complete BLE protocol documentation
```

## Troubleshooting

### Device Not Found

- Ensure the device is powered on and in range
- Check that Bluetooth is enabled on your system
- Try running `discover.py` to verify the device is visible
- Verify the MAC address is correct

### Connection Drops

- Move closer to the device
- Reduce interference from other Bluetooth/WiFi devices
- Check device battery level
- The monitor will automatically attempt to reconnect after connection loss

### Device Stops Responding

If your device occasionally stops sending data:
- The monitor automatically detects timeouts (default: 5 minutes)
- Automatic reconnection attempts will be made every 5 seconds
- Adjust timeout with `--timeout SECONDS` if needed (e.g., `--timeout 120` for 2 minutes)

## Limitations

- **Read-only**: No device configuration or settings modification
- **Single Connection**: Device supports only one active BLE connection

## Contributing

This is a reverse-engineered protocol implementation. If you discover:
- Additional protocol features
- Firmware variations
- Bug fixes or improvements

Feel free to open issues or submit pull requests.

## License

This project is licensed under the GNU General Public License v3.0.

You are free to:
- Use this software for any purpose
- Study and modify the source code
- Share and distribute the software
- Distribute modified versions

Under the condition that derivative works must also be licensed under GPL-3.0.

## Disclaimer

This is an unofficial, reverse-engineered implementation. Not affiliated with or endorsed by VSON or WEBBER.

Use at your own risk. The author is not responsible for any damage to your device or data loss.

## Author

Mariusz "Aiv" Dalewski

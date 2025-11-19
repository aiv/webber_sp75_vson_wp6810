# VSON WP6810 BLE Protocol Documentation

This document describes the Bluetooth Low Energy (BLE) protocol used by the VSON WP6810 air quality sensor.

## Table of Contents

- [Overview](#overview)
- [BLE Services and Characteristics](#ble-services-and-characteristics)
- [Communication Flow](#communication-flow)
- [Packet Formats](#packet-formats)
- [Data Decoding](#data-decoding)
- [Implementation Notes](#implementation-notes)

---

## Overview

The VSON WP6810 is a BLE air quality sensor that measures:
- PM1.0 (particulate matter ≤ 1.0 µm)
- PM2.5 (particulate matter ≤ 2.5 µm)
- PM10 (particulate matter ≤ 10 µm)
- Particle count

### Additional Features
- **Battery Monitoring**: Device reports its own battery level (0-100%)

### Device Information
- **Manufacturer**: VSON
- **Model**: WP6810
- **Alternative Names**: WEBBER SP75
- **Device Name Format**: `VSON#WP6810#XXXXXX` (where XXXXXX is serial number)
- **Protocol Type**: BLE GATT

---

## BLE Services and Characteristics

### Service: Unknown Custom Service

The device uses custom UUIDs for all characteristics. No standard GATT services are used.

### Characteristics Overview

| Characteristic | UUID | Handle | Type | Purpose |
|----------------|------|--------|------|---------|
| **KEY** | `0000fff1-0000-1000-8000-00805f9b34fb` | 0x0025 | Write | Authentication & time sync |
| **CMD** | `0000fff3-0000-1000-8000-00805f9b34fb` | 0x002b | Write | Commands (start/stop) |
| **STATUS** | `0000fff4-0000-1000-8000-00805f9b34fb` | 0x002d | Notify | Battery level |
| **DATA** | `0000ffe1-0000-1000-8000-00805f9b34fb` | 0x0036 | Notify | Air quality measurements |
| **SHORT** | `0000ffe3-0000-1000-8000-00805f9b34fb` | 0x003d | Notify | Unknown (not decoded) |
| **META** | `0000ffe4-0000-1000-8000-00805f9b34fb` | 0x0040 | Notify | Time confirmation & mode |

### Characteristic Details

#### KEY (Write)
**UUID**: `0000fff1-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x0025  
**Properties**: Write with response

**Purpose**: Used for two types of operations:
1. Authentication handshake (18 bytes)
2. Time synchronization (11 bytes)

---

#### CMD (Write)
**UUID**: `0000fff3-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x002b  
**Properties**: Write with response

**Purpose**: Send commands to device
- `0x03` - Start data streaming

---

#### STATUS (Notify)
**UUID**: `0000fff4-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x002d  
**CCCD Handle**: 0x002f  
**Properties**: Notify

**Purpose**: Reports battery level
- Sends 1 byte: battery percentage (0-100)
- Sent once on connection after initialization

---

#### DATA (Notify)
**UUID**: `0000ffe1-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x0036  
**CCCD Handle**: 0x0037  
**Properties**: Notify

**Purpose**: Main air quality data stream
- Packet size: 20 bytes
- Contains: timestamp, PM values, particle count, record counter
- Sent continuously (approximately every 1-2 seconds)
- Includes both current readings and historical records

---

#### SHORT (Notify)
**UUID**: `0000ffe3-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x003d  
**CCCD Handle**: 0x003e  
**Properties**: Notify

**Purpose**: Unknown
- Not fully decoded
- Rarely sends data
- May be reserved for future use

---

#### META (Notify)
**UUID**: `0000ffe4-0000-1000-8000-00805f9b34fb`  
**Handle**: 0x0040  
**CCCD Handle**: 0x0042  
**Properties**: Notify

**Purpose**: Time confirmation and device mode responses
- Two packet types based on first byte (flag):
  - `0x01`: Time confirmation (8 bytes)
  - `0x02`: Short response (2 bytes)
- Sent in response to KEY writes

---

## Communication Flow

```
┌─────────┐                                          ┌─────────────┐
│  Client │                                          │ VSON WP6810 │
└────┬────┘                                          └──────┬──────┘
     │                                                      │
     │ 1. BLE Connection                                    │
     ├─────────────────────────────────────────────────────>|
     │                                                      │
     │ 2. Service Discovery                                 │
     ├─────────────────────────────────────────────────────>|
     │                                         Services     │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │ 3. Enable Notifications (STATUS)                     │
     ├─────────────────────────────────────────────────────>|
     │                                                      │
     │ 4. Enable Notifications (SHORT)                      │
     ├─────────────────────────────────────────────────────>|
     │                                                      │
     │ 5. Enable Notifications (META)                       │
     ├─────────────────────────────────────────────────────>|
     │                                                      │
     │ 6. Enable Notifications (DATA)                       │
     ├─────────────────────────────────────────────────────>|
     │                                                      │
     │ 7. Write AUTH_KEY (18 bytes)                         │
     │    Format: 00 01 [6 ASCII digits] 00*10              │
     ├─────────────────────────────────────────────────────>|
     │                                         ACK          │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │ 8. Write CMD_START (0x03)                            │
     ├─────────────────────────────────────────────────────>|
     │                                         ACK          │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │ 9. Write TIME_SYNC (11 bytes)                        │
     │    Format: [YY MM DD HH MM SS] 00 06 40 00 1e        │
     ├─────────────────────────────────────────────────────>|
     │                                         ACK          │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                      10. STATUS      │
     │                               (Battery notification) │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                      11. META        │
     │                      (Time confirmation: flag 0x01)  │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                      12. META        │
     │                          (Short response: flag 0x02) │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                            ╔═══════════════════════╗ │
     │                            ║  Continuous streaming ║ │
     │                            ╚═══════════════════════╝ │
     │                                                      │
     │                                      13. DATA        │
     │                         (Current reading: flag 0x01) │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                      14. DATA        │
     │                       (Historical record: flag 0x00) │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                      15. DATA        │
     │                         (Current reading: flag 0x01) │
     <──────────────────────────────────────────────────────┤
     │                                                      │
     │                                       ...            │
     │                            (repeats every 1-2s)      │
     │                                                      │
```

### Initialization Sequence

1. **BLE Connection**: Connect to device using its MAC address
2. **Service Discovery**: Discover GATT services and characteristics
3. **Enable Notifications**: Subscribe to all 4 notification characteristics (STATUS, SHORT, META, DATA)
4. **Authentication**: Send AUTH_KEY packet with random 6-digit code
5. **Start Command**: Send CMD_START (0x03) to begin data transmission
6. **Time Sync**: Send current time to device for timestamp synchronization
7. **Data Reception**: Device starts sending STATUS, META, and continuous DATA notifications

---

## Packet Formats

### 1. AUTH_KEY Packet (Write to KEY)

**Length**: 18 bytes  
**Direction**: Client → Device

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    2     bytes   Magic: 0x00 0x01
0x02    6     ASCII   Random 6-digit number (e.g., "123456")
0x08    10    bytes   Padding: all zeros
```

**Example**:
```
00 01 31 32 33 34 35 36 00 00 00 00 00 00 00 00 00 00
│  │  └─────┬──────┘  └──────────┬──────────────────┘
│  │        │                    │
│  │        │                    └─ Padding (10 zeros)
│  │        └─ ASCII "123456"
│  └─ Magic byte
└─ Magic byte
```

**Purpose**: Authentication handshake. The 6-digit random number serves as a simple authentication token.

---

### 2. TIME_SYNC Packet (Write to KEY)

**Length**: 11 bytes  
**Direction**: Client → Device

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    1     u8      Year offset from 2000 (e.g., 25 for 2025)
0x01    1     u8      Month (1-12)
0x02    1     u8      Day (1-31)
0x03    1     u8      Hour (0-23)
0x04    1     u8      Minute (0-59)
0x05    1     u8      Second (0-59)
0x06    5     bytes   Constant: 0x00 0x06 0x40 0x00 0x1e
```

**Example** (2025-01-15 14:30:45):
```
19 01 0f 0e 1e 2d 00 06 40 00 1e
│  │  │  │  │  │  └────┬──────┘
│  │  │  │  │  │       └─ Constant tail
│  │  │  │  │  └─ Second: 45
│  │  │  │  └─ Minute: 30
│  │  │  └─ Hour: 14
│  │  └─ Day: 15
│  └─ Month: 1
└─ Year: 2025 - 2000 = 25 (0x19)
```

**Purpose**: Synchronize device clock with client time for accurate timestamps.

---

### 3. CMD_START Packet (Write to CMD)

**Length**: 1 byte  
**Direction**: Client → Device

```
Value   Description
-----   -----------
0x03    Start data streaming
```

**Purpose**: Instructs device to begin sending air quality data.

---

### 4. STATUS Notification (Battery)

**Length**: 1 byte  
**Direction**: Device → Client

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    1     u8      Battery percentage (0-100)
```

**Example**:
```
5a
└─ Battery: 90%
```

**Purpose**: Reports current battery charge level.

---

### 5. DATA Notification (Air Quality)

**Length**: 20 bytes  
**Direction**: Device → Client

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    1     u8      Year offset from 2000
0x01    1     u8      Month (1-12)
0x02    1     u8      Day (1-31)
0x03    1     u8      Hour (0-23)
0x04    1     u8      Minute (0-59)
0x05    1     u8      Second (0-59)
0x06    2     u16 LE  PM2.5 value (µg/m³)
0x08    2     u16 LE  PM1.0 value (µg/m³)
0x0a    2     u16 LE  PM10 value (µg/m³)
0x0c    2     u16 LE  Unknown field
0x0e    4     bytes   Unused (padding)
0x12    1     u8      Record counter
0x13    1     u8      Flag: 0x00=history, 0x01=current
```

**Example** (2025-01-15 14:30:45, PM2.5=18, PM1=12, PM10=22):
```
19 01 0f 0e 1e 2d 12 00 0c 00 16 00 00 00 00 00 00 00 05 01
│  │  │  │  │  │  └──┤  └──┤  └──┤  └──┤  └──┴──┴──┤  │  │
│  │  │  │  │  │     │     │     │     │           │  │  │
│  │  │  │  │  │     │     │     │     │           │  │  └─ Flag: 0x01 (current)
│  │  │  │  │  │     │     │     │     │           │  └─ Counter: 5
│  │  │  │  │  │     │     │     │     │           └─ Unused (4 bytes): 00 00 00 00
│  │  │  │  │  │     │     │     │     └─ Unknown (2 bytes): 00 00
│  │  │  │  │  │     │     │     └─ PM10: 0x0016 = 22 µg/m³ (LE)
│  │  │  │  │  │     │     └─ PM1: 0x000c = 12 µg/m³ (LE)
│  │  │  │  │  │     └─ PM2.5: 0x0012 = 18 µg/m³ (LE)
│  │  │  │  │  └─ Second: 45 (0x2d)
│  │  │  │  └─ Minute: 30 (0x1e)
│  │  │  └─ Hour: 14 (0x0e)
│  │  └─ Day: 15 (0x0f)
│  └─ Month: 1 (0x01)
└─ Year: 25 (0x19) → 2025 - 2000 = 25
```

**Flag Values**:
- `0x00`: Historical record (stored in device memory)
- `0x01`: Current real-time measurement

**Purpose**: Transmits air quality measurements with timestamp. Device sends both historical records and current readings.

---

### 6. META Notification (Time Confirmation)

**Type 1 - Time Confirmation** (flag = 0x01)

**Length**: 8 bytes  
**Direction**: Device → Client

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    1     u8      Flag: 0x01 (time confirmation)
0x01    1     u8      Year offset from 2000
0x02    1     u8      Month (1-12)
0x03    1     u8      Day (1-31)
0x04    1     u8      Hour (0-23)
0x05    1     u8      Minute (0-59)
0x06    1     u8      Second (0-59)
0x07    1     u8      Mode (work mode/state)
```

**Example**:
```
01 19 01 0f 0e 1e 2d 00
│  │  │  │  │  │  │  │
│  │  │  │  │  │  │  └─ Mode: 0
│  │  │  │  │  │  └─ Second: 45
│  │  │  │  │  └─ Minute: 30
│  │  │  │  └─ Hour: 14
│  │  │  └─ Day: 15
│  │  └─ Month: 1
│  └─ Year: 25 (2025)
└─ Flag: 0x01
```

**Purpose**: Confirms time synchronization by echoing back the received time plus device mode.

---

**Type 2 - Short Response** (flag = 0x02)

**Length**: 2 bytes  
**Direction**: Device → Client

```
Offset  Size  Type    Description
------  ----  ------  -----------
0x00    1     u8      Flag: 0x02 (short response)
0x01    1     u8      Status/response code
```

**Example**:
```
02 00
│  │
│  └─ Response code: 0
└─ Flag: 0x02
```

**Purpose**: Unknown acknowledgment or status response.

---

## Data Decoding

### Reading Multi-byte Values

All multi-byte integers are **little-endian** (least significant byte first).

**Example** - Reading PM2.5 value:
```python
def u16_le(buffer: bytes, offset: int) -> int:
    """Read unsigned 16-bit little-endian integer."""
    return buffer[offset] | (buffer[offset + 1] << 8)

# Bytes at offset 6-7: 12 00
pm25 = u16_le(data, 6)  # Result: 0x0012 = 18
```

### Datetime Decoding

Timestamps use a compact 6-byte format with year relative to 2000.

```python
def decode_datetime(header: bytes) -> dict:
    """Decode 6-byte datetime header."""
    return {
        "year": 2000 + header[0],
        "month": header[1],
        "day": header[2],
        "hour": header[3],
        "minute": header[4],
        "second": header[5],
    }
```

### Particle Count Calculation

The particle count is derived from the PM2.5 value using a device-specific formula:

```python
# Extract MSB and LSB from PM2.5 value
msb = (pm25 >> 8) & 0xFF
lsb = pm25 & 0xFF

# Calculate particle count
particles = (msb * 256) + ((lsb * 6250 * 3.53) / 1000.0)
```

**Constants**:
- `PARTICLE_MULTIPLIER_BASE = 256`
- `PARTICLE_MULTIPLIER_LSB = 6250`
- `PARTICLE_MULTIPLIER_CORRECTION = 3.53`
- `PARTICLE_DIVISOR = 1000.0`

**Example**:
```
PM2.5 = 0x0012 = 18
MSB = 0x00 = 0
LSB = 0x12 = 18

particles = (0 * 256) + ((18 * 6250 * 3.53) / 1000.0)
         = 0 + (397125 / 1000.0)
         = 397.125
```

## Protocol Version

**Version**: 1.0 (as of January 2025)  
**Device Firmware**: Unknown (not exposed via BLE)  
**Compatibility**: VSON WP6810 / WEBBER SP75

### Known Limitations

1. **No Device Configuration**
   - Measurement interval cannot be changed
   - No calibration commands
   - No factory reset via BLE

2. **Unimplemented Features**
   - SHORT characteristic purpose unknown
   - Historical record retrieval not selective (all or nothing)
   - No real-time clock adjustment after sync

3. **Protocol Quirks**
   - AUTH_KEY characteristic also used for time sync
   - META responses have two different formats
   - Unknown field in DATA packet (bytes 12-13)

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-01-18 | 1.0 | Initial documentation |

---

## License

This documentation is provided as-is for educational and development purposes.

## Contributing

If you discover protocol details not covered here, please contribute:
- Unknown field meanings
- SHORT characteristic behavior
- Additional commands
- Firmware version information

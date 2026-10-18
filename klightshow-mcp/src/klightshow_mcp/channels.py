"""Tesla light show 48-channel map, value encoding and named channel groups.

Channel order follows the Tesla xLights model (teslamotors/light-show).
Values are xLights effect brightness scaled to 0..255.
"""

CHANNEL_NAMES = [
    "Left Outer Main Beam", "Right Outer Main Beam",      # 0, 1
    "Left Inner Main Beam", "Right Inner Main Beam",      # 2, 3
    "Left Signature", "Right Signature",                  # 4, 5
    "Left Channel 4", "Right Channel 4",                  # 6, 7
    "Left Channel 5", "Right Channel 5",                  # 8, 9
    "Left Channel 6", "Right Channel 6",                  # 10, 11
    "Left Front Turn", "Right Front Turn",                # 12, 13
    "Left Front Fog", "Right Front Fog",                  # 14, 15
    "Left Aux Park", "Right Aux Park",                    # 16, 17
    "Left Side Marker", "Right Side Marker",              # 18, 19
    "Left Side Repeater", "Right Side Repeater",          # 20, 21
    "Left Rear Turn", "Right Rear Turn",                  # 22, 23
    "Brake Lights",                                       # 24
    "Left Tail", "Right Tail",                            # 25, 26
    "Reverse Lights",                                     # 27
    "Rear Fog Lights",                                    # 28
    "License Plate",                                      # 29
    "Left Falcon Door", "Right Falcon Door",              # 30, 31
    "Left Front Door", "Right Front Door",                # 32, 33
    "Left Mirror", "Right Mirror",                        # 34, 35
    "Left Front Window", "Left Rear Window",              # 36, 37
    "Right Front Window", "Right Rear Window",            # 38, 39
    "Liftgate",                                           # 40
    "Left Front Door Handle", "Left Rear Door Handle",    # 41, 42
    "Right Front Door Handle", "Right Rear Door Handle",  # 43, 44
    "Charge Port",                                        # 45
    "Unused 46", "Unused 47",                             # 46, 47
]
assert len(CHANNEL_NAMES) == 48

LIGHT_CHANNELS = list(range(0, 30))
CLOSURE_CHANNELS = list(range(30, 46))

# Channels that can ramp on every supported model (main beams, channels 4-6).
RAMPING_CHANNELS = [0, 1, 2, 3, 6, 7, 8, 9, 10, 11]

# Light values (xLights brightness %).
OFF = 0
ON = 255
RAMP_VALUES = {
    "off_500": 26,   # 10%
    "off_1000": 51,  # 20%
    "off_2000": 77,  # 30%
    "on_500": 179,   # 70%
    "on_1000": 204,  # 80%
    "on_2000": 230,  # 90%
}

# Closure commands (Idle = empty timeline).
CLOSURE_VALUES = {"idle": 0, "open": 64, "dance": 128, "close": 192, "stop": 255}


def closure_state(value: int) -> str:
    if value < 32:
        return "idle"
    if value < 96:
        return "open"
    if value < 160:
        return "dance"
    if value < 224:
        return "close"
    return "stop"


# Physical closures: name -> (channels, command limit per show, supports dance)
CLOSURES = {
    "falcon_door_left": ([30], 6, True),
    "falcon_door_right": ([31], 6, True),
    "front_door_left": ([32], 6, False),
    "front_door_right": ([33], 6, False),
    "mirror_left": ([34], 20, False),
    "mirror_right": ([35], 20, False),
    "window_left_front": ([36], 6, True),
    "window_left_rear": ([37], 6, True),
    "window_right_front": ([38], 6, True),
    "window_right_rear": ([39], 6, True),
    "liftgate": ([40], 6, True),
    "door_handle_left_front": ([41], 20, False),
    "door_handle_left_rear": ([42], 20, False),
    "door_handle_right_front": ([43], 20, False),
    "door_handle_right_rear": ([44], 20, False),
    "charge_port": ([45], 3, True),
}

GROUPS = {
    # lights
    "outer_main": [0, 1],
    "inner_main": [2, 3],
    "main_beams": [0, 1, 2, 3],
    "signature": [4, 5],
    "ch4": [6, 7], "ch5": [8, 9], "ch6": [10, 11],
    "ch456": [6, 7, 8, 9, 10, 11],
    "front_turn": [12, 13],
    "fog": [14, 15],
    "aux_park": [16, 17],
    "side_markers": [18, 19],
    "side_repeaters": [20, 21],
    "rear_turn": [22, 23],
    "turn_signals": [12, 13, 20, 21, 22, 23],
    "brake": [24],
    "tail": [25, 26],
    "red": [24, 25, 26],
    "reverse": [27],
    "rear_fog": [28],
    "license": [29],
    "front_lights": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
    "rear_lights": [22, 23, 24, 25, 26, 27, 28, 29],
    "all_lights": LIGHT_CHANNELS,
    "left_lights": [c for c in LIGHT_CHANNELS if CHANNEL_NAMES[c].startswith("Left")],
    "right_lights": [c for c in LIGHT_CHANNELS if CHANNEL_NAMES[c].startswith("Right")],
    # closures
    "mirrors": [34, 35],
    "windows": [36, 37, 38, 39],
    "liftgate": [40],
    "charge_port": [45],
    "falcon_doors": [30, 31],
    "front_doors": [32, 33],
    "door_handles": [41, 42, 43, 44],
}


def resolve_channels(spec) -> list[int]:
    """Accept a group name, a channel index, a channel name, or a list of those."""
    if isinstance(spec, (list, tuple)):
        out: list[int] = []
        for s in spec:
            for c in resolve_channels(s):
                if c not in out:
                    out.append(c)
        return out
    if isinstance(spec, int):
        if not 0 <= spec < 48:
            raise ValueError(f"channel {spec} out of range 0..47")
        return [spec]
    s = str(spec).strip()
    if s.isdigit():
        return resolve_channels(int(s))
    key = s.lower().replace(" ", "_").replace("-", "_")
    if key in GROUPS:
        return list(GROUPS[key])
    for i, name in enumerate(CHANNEL_NAMES):
        if name.lower() == s.lower():
            return [i]
    raise ValueError(f"unknown channel or group: {spec!r}. Groups: {', '.join(GROUPS)}")


def is_closure(channels: list[int]) -> bool:
    return any(c in CLOSURE_CHANNELS for c in channels)

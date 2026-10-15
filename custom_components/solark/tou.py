"""Captured work-mode form fields and validation for TOU writes."""
from __future__ import annotations

import re
from typing import Any

# Only replay the work-mode form captured in the portal, never all inverter settings.
TOU_FORM_FIELDS = (
    "safetyType", "battMode", "solarSell", "pvMaxLimit", "energyMode",
    "peakAndVallery", "sysWorkMode", "zeroExportPower", "solarMaxSellPower",
    *(f"sellTime{i}" for i in range(1, 7)),
    *(f"sellTime{i}Pac" for i in range(1, 7)),
    *(f"cap{i}" for i in range(1, 7)),
    *(f"sellTime{i}Volt" for i in range(1, 7)),
    *(f"{day}On" for day in (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    )),
    *(f"time{i}on" for i in range(1, 7)),
    *(f"genTime{i}on" for i in range(1, 7)),
)
BOOLEAN_FIELDS = {key for key in TOU_FORM_FIELDS if key.endswith(("On", "on"))}

# Battery tab is a separate complete form. Do not merge it into the TOU form.
# The portal also sent sdStartVol="undefined"; that is a UI artifact, not a setting.
BATTERY_FORM_FIELDS = (
    "safetyType", "battMode", "batteryCap", "batteryMaxCurrentCharge",
    "batteryMaxCurrentDischarge", "batteryEmptyV", "batteryImpedance",
    "batteryEfficiency", "batteryShutdownCap", "batteryLowCap", "batteryRestartCap",
    "batteryShutdownVolt", "batteryLowVolt", "batteryRestartVolt", "batteryOn",
    "floatVolt", "lithiumMode", "sdChargeOn", "sdStartCap", "sdBatteryCurrent",
    "genChargeOn", "gridSignal", "generatorStartVolt", "generatorStartCap",
    "generatorBatteryCurrent", "equChargeCycle", "equChargeTime", "absorptionVolt",
    "equVoltCharge", "tempco", "genSignal", "sdStartVolt", "generatorForcedStart",
    "bmsErrStop", "signalIslandModeEnable", "lowPowerMode", "disableFloatCharge",
    "lowNoiseMode",
)
BATTERY_CONTROL_FIELDS = {"sdChargeOn", "sdStartCap", "sdBatteryCurrent"}


def battery_form_payload(serial: str, settings: dict[str, Any]) -> dict[str, str]:
    """Preserve the captured battery form without inventing missing defaults."""
    payload = {"sn": serial}
    for key in BATTERY_FORM_FIELDS:
        value = settings.get(key)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError("Incomplete or invalid battery settings form")
        payload[key] = str(value)
    return payload


def modbus_position(settings: dict[str, Any]) -> int | None:
    """Return a valid portal Modbus position (1–16), excluding missing values."""
    value = settings.get("modbusSn")
    if isinstance(value, bool) or not re.fullmatch(r"(?:[1-9]|1[0-6])", str(value)):
        return None
    return int(value)


def is_master(settings: dict[str, Any]) -> bool:
    """Modbus position 1 is master; never infer a role from list order or alias."""
    return modbus_position(settings) == 1


def form_payload(serial: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Require a complete form and reproduce the portal's wire types."""
    if any(settings.get(key) is None for key in TOU_FORM_FIELDS):
        raise ValueError("Incomplete TOU settings; refusing to overwrite the work-mode form")
    payload: dict[str, Any] = {"sn": serial}
    for key in TOU_FORM_FIELDS:
        value = settings[key]
        if key in BOOLEAN_FIELDS:
            if value not in (True, False, 0, 1, "0", "1"):
                raise ValueError("Invalid TOU boolean setting")
            payload[key] = value in (True, 1, "1")
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            payload[key] = str(value)
        else:
            raise ValueError("Invalid TOU form setting")
    return payload


def validate_changes(changes: dict[str, Any]) -> dict[str, str]:
    """Restrict writes to the supported TOU controls."""
    if not changes:
        raise ValueError("No TOU changes supplied")
    result = {}
    for key, value in changes.items():
        if re.fullmatch(r"time[1-6]on", key) or key == "sdChargeOn":
            if value not in (True, False, 0, 1, "0", "1"):
                raise ValueError("Grid charge enable must be boolean")
            result[key] = "1" if value in (True, 1, "1") else "0"
        elif re.fullmatch(r"cap[1-6]", key) or key == "sdStartCap":
            if isinstance(value, bool):
                raise ValueError("SOC must be an integer from 0 to 100")
            try:
                numeric = float(value)
            except (ValueError, TypeError) as err:
                raise ValueError("SOC must be an integer from 0 to 100") from err
            if not 0 <= numeric <= 100 or not numeric.is_integer():
                raise ValueError("SOC must be an integer from 0 to 100")
            result[key] = str(int(numeric))
        elif key == "sdBatteryCurrent":
            if isinstance(value, bool):
                raise ValueError("Grid charge current must be a nonnegative integer")
            try:
                numeric = float(value)
            except (ValueError, TypeError) as err:
                raise ValueError("Invalid grid charge current") from err
            if not 0 <= numeric or not numeric.is_integer():
                raise ValueError("Grid charge current must be a nonnegative integer")
            result[key] = str(int(numeric))
        elif re.fullmatch(r"sellTime[1-6]", key):
            if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError("TOU time must use HH:MM in inverter local time")
            result[key] = value
        elif key == "peakAndVallery" and str(value) in ("0", "1"):
            result[key] = str(value)
        else:
            raise ValueError("Unsupported TOU setting")
    if set(result) & BATTERY_CONTROL_FIELDS and set(result) - BATTERY_CONTROL_FIELDS:
        raise ValueError("Battery and TOU settings require separate form writes")
    return result

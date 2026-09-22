"""Home Assistant metadata regression tests for Energy Dashboard entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.solark.sensor import PLANT_SENSORS


def _description(key: str):
    return next(item for item in PLANT_SENSORS if item.key == key)


def test_aggregate_pv_energy_metadata() -> None:
    for key in ("energy_today", "energy_total"):
        description = _description(key)
        assert description.device_class == SensorDeviceClass.ENERGY
        assert description.native_unit_of_measurement == "kWh"
    assert _description("energy_today").state_class == SensorStateClass.TOTAL
    assert _description("energy_total").state_class == SensorStateClass.TOTAL_INCREASING


def test_aggregate_pv_power_metadata() -> None:
    description = _description("pv_power")
    assert description.device_class == SensorDeviceClass.POWER
    assert description.state_class == SensorStateClass.MEASUREMENT
    assert description.native_unit_of_measurement == "W"

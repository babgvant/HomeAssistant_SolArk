"""Declarative plant, gateway, inverter, and battery sensors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolArkDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class SolArkSensorDescription(SensorEntityDescription):
    """Describe a normalized sensor."""


def power(key: str, name: str, category: EntityCategory | None = None) -> SolArkSensorDescription:
    return SolArkSensorDescription(key=key, name=name, native_unit_of_measurement="W", device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, entity_category=category)


def energy(key: str, name: str, daily: bool = False, category: EntityCategory | None = None) -> SolArkSensorDescription:
    return SolArkSensorDescription(key=key, name=name, native_unit_of_measurement="kWh", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL if daily else SensorStateClass.TOTAL_INCREASING, entity_category=category)


PLANT_SENSORS = (
    power("pv_power", "PV Power"), power("battery_power", "Battery Power"),
    power("grid_power", "Grid Power (Net)"), power("load_power", "Load Power"),
    power("grid_import_power", "Grid Import Power"), power("grid_export_power", "Grid Export Power"),
    SolArkSensorDescription(key="battery_soc", name="Battery SOC", native_unit_of_measurement="%", device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT),
    energy("energy_today", "Energy Today", daily=True), energy("energy_total", "Energy Total"),
    power("battery_charge_power", "Battery Charge Power"), power("battery_discharge_power", "Battery Discharge Power"),
    power("generator_power", "Generator Power"), power("smart_load_power", "Smart Load Power"),
    energy("energy_month", "PV Energy This Month", daily=True), energy("energy_year", "PV Energy This Year", daily=True),
    SolArkSensorDescription(key="efficiency", name="Efficiency", native_unit_of_measurement="%", state_class=SensorStateClass.MEASUREMENT),
    SolArkSensorDescription(key="last_update", name="Last Update", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
)

GATEWAY_SENSORS = (
    SolArkSensorDescription(key="status", name="Status", entity_category=EntityCategory.DIAGNOSTIC),
    SolArkSensorDescription(key="signal", name="Signal", native_unit_of_measurement="%", state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC),
    SolArkSensorDescription(key="last_communication", name="Last Communication", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
    SolArkSensorDescription(key="connected_inverter_count", name="Connected Inverters", state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC),
)

D = EntityCategory.DIAGNOSTIC
INVERTER_SENSORS = (
    power("pv_power", "PV Power", D), power("load_power", "Load Power", D), power("grid_power", "Grid Power", D),
    power("battery_power", "Battery Power", D), power("generator_power", "Generator Power", D),
    energy("pv_energy_today", "PV Energy Today", True, D), energy("pv_energy", "PV Energy", False, D),
    energy("load_energy", "Load Energy", False, D), energy("grid_import_energy", "Grid Import Energy", False, D),
    energy("grid_export_energy", "Grid Export Energy", False, D), energy("battery_charge_energy", "Battery Charge Energy", False, D),
    energy("battery_discharge_energy", "Battery Discharge Energy", False, D),
    SolArkSensorDescription(key="grid_voltage_l1", name="Grid Voltage L1", native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="grid_voltage_l2", name="Grid Voltage L2", native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="grid_frequency", name="Grid Frequency", native_unit_of_measurement="Hz", device_class=SensorDeviceClass.FREQUENCY, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="inverter_temperature", name="Temperature", native_unit_of_measurement="°C", device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="status", name="Status", entity_category=D),
    SolArkSensorDescription(key="last_update", name="Last Update", device_class=SensorDeviceClass.TIMESTAMP, entity_category=D),
)

BATTERY_SENSORS = (
    SolArkSensorDescription(key="battery_soc", name="SOC", native_unit_of_measurement="%", device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="battery_voltage", name="Voltage", native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    SolArkSensorDescription(key="battery_current", name="Current", native_unit_of_measurement="A", device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    power("battery_power", "Power", D),
    SolArkSensorDescription(key="battery_temperature", name="Temperature", native_unit_of_measurement="°C", device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, entity_category=D),
    energy("battery_charge_energy", "Charge Energy", False, D), energy("battery_discharge_energy", "Discharge Energy", False, D),
)

FALLBACK_ENERGY = (
    ("grid_import_energy", "Grid Import Energy", "grid_import_power"), ("grid_export_energy", "Grid Export Energy", "grid_export_power"),
    ("battery_charge_energy", "Battery Charge Energy", "battery_charge_power"), ("battery_discharge_energy", "Battery Discharge Energy", "battery_discharge_power"),
    ("load_energy", "Load Energy", "load_power"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolArkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data
    entities: list[SensorEntity] = [SolArkSensor(coordinator, entry, "plant", data["plant"]["id"], desc) for desc in PLANT_SENSORS]
    entities += [SolArkIntegratedEnergySensor(coordinator, entry, key, name, source) for key, name, source in FALLBACK_ENERGY]
    for serial in data["gateways"]:
        entities += [SolArkSensor(coordinator, entry, "gateway", serial, desc) for desc in GATEWAY_SENSORS]
    for serial, inverter in data["inverters"].items():
        entities += [SolArkSensor(coordinator, entry, "inverter", serial, desc) for desc in INVERTER_SENSORS]
        if inverter.get("battery"):
            entities += [SolArkSensor(coordinator, entry, "inverter_battery", serial, desc) for desc in BATTERY_SENSORS]
    async_add_entities(entities)


class SolArkSensor(CoordinatorEntity[SolArkDataUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator: SolArkDataUpdateCoordinator, entry: ConfigEntry, scope: str, stable_id: str, description: SolArkSensorDescription) -> None:
        super().__init__(coordinator)
        self.entry, self.scope, self.stable_id = entry, scope, stable_id
        self.entity_description = description
        self._attr_has_entity_name = True
        legacy = scope == "plant" and description in PLANT_SENSORS[:9]
        self._attr_unique_id = f"{entry.entry_id}_{description.key}" if legacy else f"{entry.entry_id}:{scope}:{stable_id}:{description.key}"
        self._attr_device_info = self._device_info()

    def _device_info(self) -> dict[str, Any]:
        data, plant = self.coordinator.data, self.coordinator.data["plant"]
        plant_ids = {(DOMAIN, self.entry.entry_id), (DOMAIN, f"plant:{plant['id']}")}
        if self.scope == "plant":
            return {"identifiers": plant_ids, "name": plant["name"], "manufacturer": "Sol-Ark", "model": "Plant"}
        if self.scope == "gateway":
            item = data["gateways"][self.stable_id]
            return {"identifiers": {(DOMAIN, f"gateway:{self.stable_id}")}, "name": item["name"], "manufacturer": "Sol-Ark", "model": item.get("model"), "serial_number": item["serial"], "sw_version": item.get("sw_version"), "hw_version": item.get("hw_version"), "via_device": (DOMAIN, f"plant:{plant['id']}")}
        inv = data["inverters"][self.stable_id]
        gateway = inv.get("gateway_serial")
        via = (DOMAIN, f"gateway:{gateway}") if gateway in data["gateways"] else (DOMAIN, f"plant:{plant['id']}")
        battery = self.scope == "inverter_battery"
        return {"identifiers": {(DOMAIN, f"inverter-battery:{self.stable_id}" if battery else f"inverter:{self.stable_id}")}, "name": f"{inv['name']} Battery" if battery else inv["name"], "manufacturer": "Sol-Ark", "model": "Aggregate battery" if battery else inv.get("model"), "serial_number": None if battery else inv["serial"], "sw_version": None if battery else inv.get("sw_version"), "hw_version": None if battery else inv.get("hw_version"), "via_device": (DOMAIN, f"inverter:{self.stable_id}") if battery else via}

    def _values(self) -> dict[str, Any]:
        data = self.coordinator.data
        if self.scope == "plant": return data["plant"]["values"]
        if self.scope == "gateway": return data["gateways"].get(self.stable_id, {}).get("values", {})
        inv = data["inverters"].get(self.stable_id, {})
        return (inv.get("battery") or {}).get("values", {}) if self.scope == "inverter_battery" else inv.get("values", {})

    @property
    def native_value(self) -> Any:
        value = self._values().get(self.entity_description.key)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and isinstance(value, str):
            try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError: return None
        return value

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class SolArkIntegratedEnergySensor(CoordinatorEntity[SolArkDataUpdateCoordinator], RestoreSensor):
    """Restore and integrate an authoritative plant power stream."""
    _attr_device_class, _attr_native_unit_of_measurement = SensorDeviceClass.ENERGY, "kWh"
    _attr_state_class, _attr_suggested_display_precision, _attr_has_entity_name = SensorStateClass.TOTAL_INCREASING, 3, True

    def __init__(self, coordinator: SolArkDataUpdateCoordinator, entry: ConfigEntry, key: str, name: str, power_key: str) -> None:
        super().__init__(coordinator)
        self.power_key, self._attr_name, self._attr_unique_id = power_key, name, f"{entry.entry_id}_{key}"
        plant = coordinator.data["plant"]
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id), (DOMAIN, f"plant:{plant['id']}")}}
        self._total, self._last_power, self._last_sample = 0.0, None, None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_sensor_data()
        if restored and restored.native_value is not None:
            try: self._total = float(restored.native_value)
            except (TypeError, ValueError): pass

    @property
    def native_value(self) -> float: return round(self._total, 6)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data["plant"]["values"].get(self.power_key) is not None

    def _handle_coordinator_update(self) -> None:
        try:
            sample = datetime.fromisoformat(self.coordinator.data["fetched_at"])
            current = float(self.coordinator.data["plant"]["values"][self.power_key])
        except (KeyError, TypeError, ValueError):
            self._last_power = self._last_sample = None
            self.async_write_ha_state(); return
        if self._last_power is not None and self._last_sample is not None:
            seconds = (sample - self._last_sample).total_seconds()
            interval = self.coordinator.update_interval.total_seconds() if self.coordinator.update_interval else 60
            if 0 < seconds <= max(interval * 3, 180):
                self._total += ((self._last_power + current) / 2) * seconds / 3_600_000
        self._last_power, self._last_sample = current, sample
        self.async_write_ha_state()

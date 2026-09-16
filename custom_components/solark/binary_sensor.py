"""Binary telemetry for Sol-Ark plants and equipment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolArkDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class SolArkBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a normalized binary sensor."""


ONLINE = SolArkBinarySensorDescription(
    key="online", name="Online", device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)
FLOW_BINARY_SENSORS = (
    SolArkBinarySensorDescription(key="grid_connected", name="Grid Connected", device_class=BinarySensorDeviceClass.CONNECTIVITY),
    SolArkBinarySensorDescription(key="generator_on", name="Generator On", device_class=BinarySensorDeviceClass.POWER),
    SolArkBinarySensorDescription(key="bms_communication_fault", name="BMS Communication Fault", device_class=BinarySensorDeviceClass.PROBLEM, entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SolArkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data
    entities: list[BinarySensorEntity] = [
        SolArkBinarySensor(coordinator, entry, "plant", data["plant"]["id"], description)
        for description in FLOW_BINARY_SENSORS
    ]
    for serial in data["gateways"]:
        entities.append(SolArkBinarySensor(coordinator, entry, "gateway", serial, ONLINE))
    for serial in data["inverters"]:
        entities.append(SolArkBinarySensor(coordinator, entry, "inverter", serial, ONLINE))
        entities.extend(
            SolArkBinarySensor(coordinator, entry, "inverter", serial, description)
            for description in FLOW_BINARY_SENSORS
        )
    for serial in data["batteries"]:
        entities.append(SolArkBinarySensor(coordinator, entry, "battery", serial, ONLINE))
    async_add_entities(entities)


class SolArkBinarySensor(CoordinatorEntity[SolArkDataUpdateCoordinator], BinarySensorEntity):
    """Represent boolean telemetry from the normalized coordinator model."""

    def __init__(self, coordinator: SolArkDataUpdateCoordinator, entry: ConfigEntry, scope: str, stable_id: str, description: SolArkBinarySensorDescription) -> None:
        super().__init__(coordinator)
        self.entry, self.scope, self.stable_id = entry, scope, stable_id
        self.entity_description = description
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}:{scope}:{stable_id}:{description.key}"
        self._attr_device_info = self._device_info()

    def _device_info(self) -> dict[str, Any]:
        data, plant = self.coordinator.data, self.coordinator.data["plant"]
        if self.scope == "plant":
            return {"identifiers": {(DOMAIN, self.entry.entry_id), (DOMAIN, f"plant:{plant['id']}")}, "name": plant["name"], "manufacturer": "Sol-Ark", "model": "Plant"}
        if self.scope == "gateway":
            item = data["gateways"][self.stable_id]
            return {"identifiers": {(DOMAIN, f"gateway:{self.stable_id}")}, "name": item["name"], "manufacturer": "Sol-Ark", "model": item.get("model"), "serial_number": item["serial"], "via_device": (DOMAIN, f"plant:{plant['id']}")}
        if self.scope == "battery":
            item = data["batteries"][self.stable_id]
            inverter_serial = item.get("inverter_serial")
            via = (DOMAIN, f"inverter:{inverter_serial}") if inverter_serial in data["inverters"] else (DOMAIN, f"plant:{plant['id']}")
            return {"identifiers": {(DOMAIN, f"battery:{self.stable_id}")}, "name": item["name"], "manufacturer": "Sol-Ark", "model": item.get("model"), "serial_number": item["serial"], "via_device": via}
        item = data["inverters"][self.stable_id]
        gateway = item.get("gateway_serial")
        via = (DOMAIN, f"gateway:{gateway}") if gateway in data["gateways"] else (DOMAIN, f"plant:{plant['id']}")
        return {"identifiers": {(DOMAIN, f"inverter:{self.stable_id}")}, "name": item["name"], "manufacturer": "Sol-Ark", "model": item.get("model"), "serial_number": item["serial"], "via_device": via}

    def _values(self) -> dict[str, Any]:
        data = self.coordinator.data
        if self.scope == "plant":
            return data["plant"]["values"]
        return data[f"{self.scope}s"].get(self.stable_id, {}).get("values", {})

    @property
    def is_on(self) -> bool | None:
        value = self._values().get(self.entity_description.key)
        return bool(value) if value is not None else None

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

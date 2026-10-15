"""Battery SOC targets for the six inverter TOU periods."""
from homeassistant.components.number import NumberEntity, NumberMode

from .tou_entity import SolArkTOUEntity, setup_tou_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_tou_entities(hass, entry, async_add_entities, lambda coordinator, serial: (
        *(SolArkTOUSOC(coordinator, entry, serial, f"cap{slot}", f"TOU {slot} battery SOC")
          for slot in range(1, 7)),
        SolArkTOUSOC(coordinator, entry, serial, "sdStartCap", "Grid charge start SOC"),
        SolArkGridChargeCurrent(coordinator, entry, serial, "sdBatteryCurrent", "Grid charge current"),
    ))


class SolArkTOUSOC(SolArkTOUEntity, NumberEntity):
    """Writable battery target, expressed as an integer percentage."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:battery-clock"

    @property
    def native_value(self):
        try:
            return float(self.setting) if self.setting is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float):
        await self.async_write(value)


class SolArkGridChargeCurrent(SolArkTOUSOC):
    """DC charging current, bounded by the inverter's battery charge limit."""

    _attr_native_unit_of_measurement = "A"
    _attr_icon = "mdi:current-dc"

    @property
    def native_max_value(self):
        settings = (self.coordinator.data or {}).get(self.serial, {})
        try:
            value = float(settings["batteryMaxCurrentCharge"])
            return value if 0 <= value < float("inf") else 0
        except (KeyError, TypeError, ValueError):
            return 0

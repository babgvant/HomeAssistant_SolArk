"""Battery SOC targets for the six inverter TOU periods."""
from homeassistant.components.number import NumberEntity, NumberMode

from .tou_entity import SolArkTOUEntity, setup_tou_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_tou_entities(hass, entry, async_add_entities, lambda coordinator, serial: (
        SolArkTOUSOC(coordinator, entry, serial, f"cap{slot}", f"TOU {slot} battery SOC")
        for slot in range(1, 7)))


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

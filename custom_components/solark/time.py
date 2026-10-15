"""Start times for the six inverter TOU periods."""
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.exceptions import HomeAssistantError

from .tou_entity import SolArkTOUEntity, setup_tou_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_tou_entities(hass, entry, async_add_entities, lambda coordinator: (
        SolArkTOUTime(coordinator, entry, f"sellTime{slot}", f"TOU {slot} start time")
        for slot in range(1, 7)))


class SolArkTOUTime(SolArkTOUEntity, TimeEntity):
    """Wall-clock time in the inverter's configured timezone."""

    @property
    def native_value(self):
        try:
            return time.fromisoformat(str(self.setting)) if self.setting is not None else None
        except ValueError:
            return None

    async def async_set_value(self, value: time):
        if value.second or value.microsecond or value.tzinfo is not None:
            raise HomeAssistantError("TOU start times require local hours and minutes")
        await self.async_write(value.strftime("%H:%M"))

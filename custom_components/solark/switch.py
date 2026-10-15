"""TOU schedule and grid charging permissions."""
from homeassistant.components.switch import SwitchEntity

from .tou_entity import SolArkTOUEntity, setup_tou_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_tou_entities(hass, entry, async_add_entities, lambda coordinator, serial: (
        SolArkTOUSwitch(coordinator, entry, serial, "peakAndVallery", "Time of use"),
        SolArkTOUSwitch(coordinator, entry, serial, "sdChargeOn", "Grid charging"),
        *(SolArkTOUSwitch(coordinator, entry, serial, f"time{slot}on", f"TOU {slot} grid charging")
          for slot in range(1, 7)),
    ))


class SolArkTOUSwitch(SolArkTOUEntity, SwitchEntity):
    """Control a single permission without changing other settings."""

    @property
    def is_on(self):
        return self.setting in (True, 1, "1") if self.setting is not None else None

    async def async_turn_on(self, **kwargs):
        await self.async_write("1")

    async def async_turn_off(self, **kwargs):
        await self.async_write("0")

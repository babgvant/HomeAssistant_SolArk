"""TOU schedule enable control."""
from homeassistant.components.switch import SwitchEntity

from .tou_entity import SolArkTOUEntity, setup_tou_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_tou_entities(hass, entry, async_add_entities, lambda coordinator, serial: (
        SolArkTOUSwitch(coordinator, entry, serial, "peakAndVallery", "Time of use"),))


class SolArkTOUSwitch(SolArkTOUEntity, SwitchEntity):
    """Enable or disable TOU without changing the six periods."""

    @property
    def is_on(self):
        return str(self.setting) == "1" if self.setting is not None else None

    async def async_turn_on(self, **kwargs):
        await self.async_write("1")

    async def async_turn_off(self, **kwargs):
        await self.async_write("0")

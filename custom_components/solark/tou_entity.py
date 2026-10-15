"""TOU polling and shared inverter control behavior."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .api import SolArkCloudAPIError, SolArkCloudAuthenticationError
from .const import DOMAIN
from .tou import BATTERY_CONTROL_FIELDS, battery_form_payload, is_master, modbus_position


class SolArkTOUCoordinator(DataUpdateCoordinator):
    """Poll settings separately so unavailable controls do not interrupt telemetry."""

    def __init__(self, hass, entry, telemetry):
        self.telemetry = telemetry
        self.api = telemetry.api
        self.master_serial: str | None = None
        self.api.tou_master_serial = None
        self._write_revision = 0
        super().__init__(hass, logging.getLogger(__name__), name="Sol-Ark TOU",
                         update_interval=timedelta(minutes=1), config_entry=entry)

    async def _async_update_data(self):
        revision = self._write_revision
        settings = {}
        complete = True
        for serial in self.telemetry.data.get("inverters", {}):
            try:
                settings[serial] = await self.api.async_get_tou_settings(serial)
                if modbus_position(settings[serial]) is None:
                    complete = False
            except SolArkCloudAuthenticationError as err:
                self.master_serial = self.api.tou_master_serial = None
                raise ConfigEntryAuthFailed("Sol-Ark credentials were rejected") from err
            except (SolArkCloudAPIError, ValueError, TypeError):
                complete = False
        masters = [serial for serial, values in settings.items() if is_master(values)]
        # An unreadable inverter could hide another master. Never choose arbitrarily.
        self.master_serial = masters[0] if complete and len(masters) == 1 else None
        self.api.tou_master_serial = self.master_serial
        if self.master_serial is None:
            return {}
        # A write can complete while another inverter's read is awaiting I/O.
        if revision != self._write_revision and self.master_serial in (self.data or {}):
            settings[self.master_serial] = self.data[self.master_serial]
        return {self.master_serial: settings[self.master_serial]}

    @property
    def master_inverters(self):
        """Expose only the detected master when present in discovered topology."""
        inverters = self.telemetry.data.get("inverters", {})
        return {self.master_serial: inverters[self.master_serial]} if self.master_serial in inverters else {}

    async def async_write(self, serial: str, changes: dict[str, Any]):
        if serial not in self.master_inverters:
            raise HomeAssistantError("TOU writes require a detected Modbus master")
        try:
            settings = await self.api.async_set_tou_settings(serial, changes)
        except (SolArkCloudAPIError, ValueError, TypeError) as err:
            raise HomeAssistantError("Unable to update Sol-Ark TOU settings") from err
        self._write_revision += 1
        self.async_set_updated_data({**(self.data or {}), serial: settings})


class SolArkTOUEntity(CoordinatorEntity):
    """Attach TOU controls to the existing inverter device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, serial: str, key: str, name: str):
        super().__init__(coordinator)
        self.serial = serial
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}:inverter:{serial}:tou:{key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"inverter:{serial}")}}

    @property
    def setting(self):
        return (self.coordinator.data or {}).get(self.serial, {}).get(self.key)

    @property
    def available(self):
        if self.key in BATTERY_CONTROL_FIELDS:
            try:
                battery_form_payload(self.serial, (self.coordinator.data or {}).get(self.serial, {}))
            except ValueError:
                return False
        return (super().available and self.serial in self.coordinator.master_inverters
                and self.setting is not None)

    async def async_write(self, value):
        await self.coordinator.async_write(self.serial, {self.key: value})


def setup_tou_entities(hass, entry, async_add_entities, factory):
    """Add controls when the master is detected, including after a failed first poll."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["tou_coordinator"]
    seen: set[str] = set()

    def add_master():
        for serial in coordinator.master_inverters:
            if serial not in seen:
                seen.add(serial)
                async_add_entities(factory(coordinator, serial))

    entry.async_on_unload(coordinator.async_add_listener(add_master))
    add_master()

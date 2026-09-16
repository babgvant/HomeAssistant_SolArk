"""Coordinator and normalized data model for Sol-Ark Cloud."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Awaitable

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SolArkCloudAPI, SolArkCloudAPIError, SolArkCloudAuthenticationError
from .const import CONF_PLANT_ID, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .models import INVERTER_PARAMETER_IDS, PARAMETER_KEYS, battery_values, flow_values, number

_LOGGER = logging.getLogger(__name__)
METADATA_INTERVAL = timedelta(minutes=30)
INVERTER_DETAIL_INTERVAL = timedelta(minutes=5)
_number = number
_flow_values = flow_values
_battery_values = battery_values


class SolArkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch Sol-Ark data while isolating optional endpoint failures."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: SolArkCloudAPI,
    ) -> None:
        self.api = api
        self.entry = entry
        self._metadata: dict[str, Any] | None = None
        self._metadata_at: datetime | None = None
        self._inverter_details: dict[str, tuple[Any, Any, Any]] = {}
        self._inverter_details_at: datetime | None = None
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        super().__init__(
            hass,
            _LOGGER,
            name=f"Sol-Ark {entry.data[CONF_PLANT_ID]}",
            update_interval=timedelta(seconds=interval),
            update_method=self._async_update_data,
            config_entry=entry,
        )

    async def _optional(self, name: str, request: Awaitable[Any], errors: dict[str, str]) -> Any:
        try:
            return await request
        except SolArkCloudAuthenticationError:
            raise
        except (SolArkCloudAPIError, ValueError, TypeError) as err:
            errors[name] = type(err).__name__
            _LOGGER.debug("Optional Sol-Ark endpoint %s failed: %s", name, type(err).__name__)
            return None

    async def _refresh_metadata(self, errors: dict[str, str]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if self._metadata is not None and self._metadata_at and now - self._metadata_at < METADATA_INTERVAL:
            return self._metadata
        plant, gateways, inverters, batteries = await asyncio.gather(
            self._optional("plant_metadata", self.api.async_get_plant_metadata(), errors),
            self._optional("gateways", self.api.async_get_gateways(), errors),
            self._optional("inverters", self.api.async_get_inverters(), errors),
            self._optional("batteries", self.api.async_get_batteries(), errors),
        )
        if self._metadata is None:
            self._metadata = {}
        if plant is not None:
            self._metadata["plant"] = plant
        if gateways is not None:
            self._metadata["gateways"] = gateways
        if inverters is not None:
            self._metadata["inverters"] = inverters
        if batteries is not None:
            self._metadata["batteries"] = batteries
        self._metadata_at = now
        return self._metadata

    async def _async_update_data(self) -> dict[str, Any]:
        errors: dict[str, str] = {}
        try:
            metadata = await self._refresh_metadata(errors)
            flow = await self.api.async_get_plant_flow()
            realtime = await self._optional(
                "plant_realtime", self.api.async_get_plant_realtime(), errors
            ) or {}
        except SolArkCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed("Sol-Ark credentials were rejected") from err
        except SolArkCloudAPIError as err:
            raise UpdateFailed(str(err)) from err

        plant_raw = metadata.get("plant", {})
        plant_values = _flow_values(flow)
        plant_values.update(
            {
                "status": plant_raw.get("status"),
                "energy_today": _number(realtime.get("etoday")),
                "energy_month": _number(realtime.get("emonth")),
                "energy_year": _number(realtime.get("eyear")),
                "energy_total": _number(realtime.get("etotal")),
                "efficiency": _number(realtime.get("efficiency")),
                "last_update": realtime.get("updateAt"),
            }
        )
        plant_id = str(self.entry.data[CONF_PLANT_ID])
        normalized: dict[str, Any] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "endpoint_errors": errors,
            "plant": {
                "id": plant_id,
                "name": plant_raw.get("name") or self.entry.title or "Sol-Ark Plant",
                "status": plant_raw.get("status"),
                "values": plant_values,
            },
            "gateways": {},
            "inverters": {},
            "batteries": {},
        }

        for raw in metadata.get("gateways", []):
            serial = raw.get("sn")
            if not serial:
                continue
            normalized["gateways"][str(serial)] = {
                "serial": str(serial),
                "name": raw.get("alias") or raw.get("devName") or "Sol-Ark Gateway",
                "model": raw.get("model"),
                "sw_version": raw.get("softVer"),
                "hw_version": raw.get("hardVer"),
                "values": {
                    "status": raw.get("status"),
                    "online": raw.get("status") not in (None, 0),
                    "signal": _number(raw.get("signal")),
                    "last_communication": raw.get("lldt") or raw.get("updateAt"),
                    "upload_interval": _number(raw.get("uploadCycle")),
                    "connected_inverter_count": 0,
                },
            }

        inverter_raw = [item for item in metadata.get("inverters", []) if item.get("sn") and item.get("id") is not None]
        now = datetime.now(timezone.utc)
        refresh_details = (
            self._inverter_details_at is None
            or now - self._inverter_details_at >= INVERTER_DETAIL_INTERVAL
        )
        if refresh_details:
            tasks = []
            for raw in inverter_raw:
                serial = str(raw["sn"])
                inverter_id = raw["id"]
                tasks.append(
                    asyncio.gather(
                        self._optional("inverter_flow", self.api.async_get_inverter_flow(inverter_id), errors),
                        self._optional("inverter_battery", self.api.async_get_inverter_battery(inverter_id, serial), errors),
                        self._optional("inverter_measurements", self.api.async_get_inverter_measurements(inverter_id, serial, INVERTER_PARAMETER_IDS), errors),
                    )
                )
            try:
                refreshed = await asyncio.gather(*tasks) if tasks else []
            except SolArkCloudAuthenticationError as err:
                raise ConfigEntryAuthFailed("Sol-Ark credentials were rejected") from err
            for raw, detail in zip(inverter_raw, refreshed):
                self._inverter_details[str(raw["sn"])] = tuple(detail)
            self._inverter_details_at = now
        details = [self._inverter_details.get(str(raw["sn"]), ({}, {}, {})) for raw in inverter_raw]

        for raw, detail in zip(inverter_raw, details):
            serial = str(raw["sn"])
            flow_data, battery_data, measurements = detail
            values = _flow_values(flow_data or {})
            for parameter_id, value in (measurements or {}).items():
                key = PARAMETER_KEYS.get(parameter_id)
                if key and values.get(key) is None:
                    values[key] = _number(value)
            values.update(
                {
                    "status": raw.get("status"),
                    "online": raw.get("status") not in (None, 0),
                    "pv_energy_today": _number(raw.get("etoday")) or values.get("pv_energy_today"),
                    "pv_energy": _number(raw.get("etotal")) or values.get("pv_energy"),
                    "last_update": raw.get("updateAt"),
                }
            )
            battery_values = _battery_values(battery_data or {})
            gateway = raw.get("gatewayVO") or {}
            gateway_serial = gateway.get("gsn") or raw.get("gsn")
            normalized["inverters"][serial] = {
                "id": str(raw["id"]),
                "serial": serial,
                "name": raw.get("alias") or f"Sol-Ark Inverter {serial[-4:]}",
                "model": raw.get("model"),
                "sw_version": (raw.get("version") or {}).get("softVer"),
                "hw_version": (raw.get("version") or {}).get("hardVer"),
                "gateway_serial": str(gateway_serial) if gateway_serial else None,
                "values": values,
                "battery": {"values": battery_values} if any(value is not None for value in battery_values.values()) else None,
            }
            if gateway_serial and str(gateway_serial) in normalized["gateways"]:
                normalized["gateways"][str(gateway_serial)]["values"]["connected_inverter_count"] += 1

        # Individually addressable battery records are metadata-only until the API
        # supplies a stable serial and useful telemetry fields.
        for raw in metadata.get("batteries", []):
            serial = raw.get("sn")
            if serial:
                normalized["batteries"][str(serial)] = {
                    "serial": str(serial),
                    "name": raw.get("alias") or f"Sol-Ark Battery {str(serial)[-4:]}",
                    "model": raw.get("model"),
                    "inverter_serial": raw.get("invSn"),
                    "gateway_serial": raw.get("gsn"),
                    "values": {"status": raw.get("status"), "online": raw.get("status") not in (None, 0)},
                }

        load_energy_today = [
            inverter["values"].get("load_energy_today")
            for inverter in normalized["inverters"].values()
        ]
        if load_energy_today and all(value is not None for value in load_energy_today):
            normalized["plant"]["values"]["load_energy_today"] = sum(load_energy_today)

        normalized["features"] = {
            "plant_flow": bool(flow),
            "plant_pv_energy": realtime.get("etotal") is not None,
            "gateways": bool(normalized["gateways"]),
            "multiple_inverters": len(normalized["inverters"]) > 1,
            "individual_batteries": bool(normalized["batteries"]),
            "native_inverter_energy": any(
                inverter["values"].get("grid_import_energy") is not None
                for inverter in normalized["inverters"].values()
            ),
        }
        return normalized

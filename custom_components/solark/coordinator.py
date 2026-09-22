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
from .models import INVERTER_PARAMETER_IDS, PARAMETER_KEYS, balance, battery_values, complete_inverter_sum, flow_values, merge_inverter_topology, number

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
            # Some Sol-Ark responses intermittently omit a parallel slave. Once a
            # physical inverter has been discovered, keep it in the expected topology
            # so a short response cannot turn a partial aggregate into a valid total.
            self._metadata["inverters"] = merge_inverter_topology(
                self._metadata.get("inverters", []), inverters
            )
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
            generation_use = await self._optional(
                "plant_generation_use",
                self.api.async_get_plant_generation_use(),
                errors,
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
            "debug_diagnostics": {
                "plant": {
                    "plant_flow": {
                        "endpoint": "/api/v1/plant/energy/{plant_id}/flow",
                        "raw_pv_power": _number(flow.get("pvPower")),
                        "raw_ac_coupled_power": _number(flow.get("minPower")),
                        "load_power": _number(flow.get("loadOrEpsPower")),
                        "battery_power": _number(flow.get("battPower")),
                        "grid_power": _number(flow.get("gridOrMeterPower")),
                        "direction_flags": {
                            key: flow.get(key)
                            for key in ("toBat", "batTo", "toGrid", "gridTo")
                        },
                    },
                    "plant_realtime": {
                        "endpoint": "/api/v1/plant/{plant_id}/realtime",
                        "inverter_ac_power": _number(realtime.get("pac")),
                        "raw_pv_energy_today": _number(realtime.get("etoday")),
                        "raw_pv_cumulative_energy": _number(realtime.get("etotal")),
                    },
                    "generation_use": {
                        "endpoint": "/api/v1/plant/energy/{plant_id}/generation/use",
                        "raw_pv_energy": _number(generation_use.get("pv")),
                        "load_energy": _number(generation_use.get("load")),
                        "battery_charge_energy": _number(generation_use.get("batteryCharge")),
                        "grid_export_energy": _number(generation_use.get("gridSell")),
                    },
                },
                "inverters": {},
            },
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

        for inverter_index, (raw, detail) in enumerate(zip(inverter_raw, details), 1):
            serial = str(raw["sn"])
            flow_data, battery_data, measurements = detail
            values = _flow_values(flow_data or {})
            measurement_values = {
                PARAMETER_KEYS[parameter_id]: _number(value)
                for parameter_id, value in (measurements or {}).items()
                if parameter_id in PARAMETER_KEYS
            }
            for parameter_id, value in (measurements or {}).items():
                key = PARAMETER_KEYS.get(parameter_id)
                if key and values.get(key) is None:
                    values[key] = _number(value)
            values.update(
                {
                    "status": raw.get("status"),
                    "online": raw.get("status") not in (None, 0),
                    "pv_energy_today": _number(raw.get("etoday")) if _number(raw.get("etoday")) is not None else values.get("pv_energy_today"),
                    "pv_energy": _number(raw.get("etotal")) if _number(raw.get("etotal")) is not None else values.get("pv_energy"),
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
            # Deliberately use a positional label rather than serial/id so downloaded
            # diagnostics remain safe to share with maintainers.
            normalized["debug_diagnostics"]["inverters"][f"inverter_{inverter_index}"] = {
                "summary": {
                    "endpoint": "/api/v1/plant/{plant_id}/inverters",
                    "inverter_ac_power": _number(raw.get("pac")),
                    "raw_pv_energy_today": _number(raw.get("etoday")),
                    "raw_pv_cumulative_energy": _number(raw.get("etotal")),
                },
                "flow": {
                    "endpoint": "/api/v1/inverter/{inverter_id}/flow",
                    "raw_pv_power": _number((flow_data or {}).get("pvPower")),
                    "raw_ac_coupled_power": _number((flow_data or {}).get("minPower")),
                    "load_power": _number((flow_data or {}).get("loadOrEpsPower")),
                    "battery_power": _number((flow_data or {}).get("battPower")),
                    "grid_power": _number((flow_data or {}).get("gridOrMeterPower")),
                },
                "day_parameters": {
                    "endpoint": "/api/v1/inverter/{inverter_id}/day",
                    **{
                        key: values.get(key)
                        if key not in measurement_values
                        else measurement_values[key]
                        for key in (
                            "pv_power", "pv_energy_today", "pv_energy",
                            "inverter_power", "load_power", "load_energy_today",
                            "battery_power", "battery_charge_energy_today",
                            "battery_discharge_energy_today", "grid_power",
                            "grid_import_energy_today", "grid_export_energy_today",
                        )
                    },
                },
                "battery_realtime": {
                    "endpoint": "/api/v1/inverter/battery/{inverter_id}/realtime",
                    "battery_power": _number((battery_data or {}).get("power")),
                    "battery_charge_energy_today": _number((battery_data or {}).get("etodayChg")),
                    "battery_discharge_energy_today": _number((battery_data or {}).get("etodayDischg")),
                },
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

        # PV flow and counters are demonstrably per-inverter in parallel systems;
        # Sol-Ark's nominal plant PV fields can omit a slave. Publish no partial sum.
        # Conversely, load/grid/battery power remain the authoritative plant-flow
        # values: their direction flags are plant-level and summing device fields can
        # double-count master/system readings on other firmware/API variants.
        aggregation: dict[str, dict[str, Any]] = {}
        for plant_key, inverter_key in (
            ("pv_power", "pv_power"),
            ("energy_today", "pv_energy_today"),
            ("energy_total", "pv_energy"),
        ):
            total, contributors = complete_inverter_sum(
                normalized["inverters"], inverter_key
            )
            aggregation[plant_key] = {
                "contributing_inverters": contributors,
                "expected_inverters": len(normalized["inverters"]),
                "aggregation_method": "sum_per_inverter",
            }
            normalized["plant"]["values"][plant_key] = total

        for key in (
            "load_power", "grid_power", "grid_import_power", "grid_export_power",
            "battery_power", "battery_charge_power", "battery_discharge_power",
        ):
            aggregation[key] = {
                "aggregation_method": "authoritative_site_flow",
                "expected_inverters": len(normalized["inverters"]),
            }

        plant_power = normalized["plant"]["values"]
        balance_keys = (
            "pv_power", "grid_import_power", "battery_discharge_power",
            "load_power", "grid_export_power", "battery_charge_power",
        )
        power_balance = balance(plant_power, balance_keys[:3], balance_keys[3:])
        if power_balance is not None:
            normalized["energy_balance"] = {
                **{key: power_balance[key] for key in balance_keys},
                "source_power": power_balance["source"],
                "sink_power": power_balance["sink"],
                "power_balance_error": power_balance["error"],
                # Compatibility with the first diagnostic implementation.
                "sources_power": power_balance["source"],
                "sinks_power": power_balance["sink"],
                "balance_error": power_balance["error"],
            }
            _LOGGER.debug("Sol-Ark site power balance: %s", normalized["energy_balance"])
        else:
            normalized["energy_balance"] = None
        normalized["aggregation"] = aggregation

        load_energy_today = [
            inverter["values"].get("load_energy_today")
            for inverter in normalized["inverters"].values()
        ]
        if load_energy_today and all(value is not None for value in load_energy_today):
            normalized["plant"]["values"]["load_energy_today"] = sum(load_energy_today)

        daily_inverter_keys = (
            "grid_import_energy_today", "battery_discharge_energy_today",
            "load_energy_today", "grid_export_energy_today",
            "battery_charge_energy_today",
        )
        daily: dict[str, Any] = {"pv_energy_today": plant_power.get("energy_today")}
        daily_sources: dict[str, Any] = {
            "pv_energy_today": {
                "endpoint": "/api/v1/plant/{plant_id}/inverters",
                "aggregation_method": "complete_sum_per_inverter",
            }
        }
        for key in daily_inverter_keys:
            total, contributors = complete_inverter_sum(normalized["inverters"], key)
            daily[key] = total
            daily_sources[key] = {
                "endpoint": "/api/v1/inverter/{inverter_id}/day",
                "aggregation_method": "complete_sum_per_inverter",
                "contributing_inverter_count": len(contributors),
                "expected_inverter_count": len(normalized["inverters"]),
            }
        # Battery realtime supplies the same native daily counters on firmware that
        # omits parameter IDs 81/82 from the day endpoint.
        for key in ("battery_charge_energy_today", "battery_discharge_energy_today"):
            if daily[key] is None:
                battery_total = 0.0
                available = True
                for inverter in normalized["inverters"].values():
                    value = (inverter.get("battery") or {}).get("values", {}).get(key)
                    if value is None:
                        available = False
                        break
                    battery_total += value
                if available and normalized["inverters"]:
                    daily[key] = battery_total
                    daily_sources[key]["endpoint"] = "/api/v1/inverter/battery/{inverter_id}/realtime"
        energy_keys = (
            "pv_energy_today", "grid_import_energy_today",
            "battery_discharge_energy_today", "load_energy_today",
            "grid_export_energy_today", "battery_charge_energy_today",
        )
        energy_balance = balance(daily, energy_keys[:3], energy_keys[3:])
        normalized["energy_balance_today"] = None if energy_balance is None else {
            **{key: energy_balance[key] for key in energy_keys},
            "source_energy": energy_balance["source"],
            "sink_energy": energy_balance["sink"],
            "energy_balance_error": energy_balance["error"],
            "sources": daily_sources,
        }
        normalized["debug_diagnostics"]["power_balance"] = normalized["energy_balance"]
        normalized["debug_diagnostics"]["energy_balance_today"] = normalized["energy_balance_today"]
        _LOGGER.debug(
            "Sol-Ark endpoint measurement diagnostics: %s",
            normalized["debug_diagnostics"],
        )

        normalized["features"] = {
            "plant_flow": bool(flow),
            "plant_pv_energy": realtime.get("etotal") is not None,
            "plant_generation_use": bool(generation_use),
            "gateways": bool(normalized["gateways"]),
            "multiple_inverters": len(normalized["inverters"]) > 1,
            "individual_batteries": bool(normalized["batteries"]),
            "native_inverter_energy": any(
                inverter["values"].get("grid_import_energy") is not None
                for inverter in normalized["inverters"].values()
            ),
        }
        return normalized

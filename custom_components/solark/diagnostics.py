"""Diagnostics support for SolArk integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_PASSWORD, CONF_USERNAME, CONF_PLANT_ID, INTEGRATION_VERSION

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "access_token",
    "refresh_token",
    "token",
    CONF_PLANT_ID,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get("coordinator")

    diag: dict[str, Any] = {
        "integration_version": INTEGRATION_VERSION,
        "entry": {
            "title": "SolArk Cloud",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }

    if coordinator is not None:
        coordinator_data = coordinator.data or {}
        inverters = coordinator_data.get("inverters", {})
        gateways = coordinator_data.get("gateways", {})
        batteries = coordinator_data.get("batteries", {})
        diag["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_successful_refresh": coordinator_data.get("fetched_at"),
            "plant_count": 1 if coordinator_data.get("plant") else 0,
            "gateway_count": len(gateways),
            "inverter_count": len(inverters),
            "battery_count": len(batteries),
            "detected_models": sorted(
                {
                    str(item["model"])
                    for item in (*gateways.values(), *inverters.values(), *batteries.values())
                    if item.get("model")
                }
            ),
            "features": coordinator_data.get("features", {}),
            "endpoint_errors": coordinator_data.get("endpoint_errors", {}),
            "aggregation": coordinator_data.get("aggregation", {}),
            "energy_balance": coordinator_data.get("energy_balance"),
            "plant_data_keys": sorted(
                coordinator_data.get("plant", {}).get("values", {}).keys()
            ),
            "inverter_data_keys": sorted(
                {
                    key
                    for item in inverters.values()
                    for key in item.get("values", {})
                }
            ),
        }

    return diag

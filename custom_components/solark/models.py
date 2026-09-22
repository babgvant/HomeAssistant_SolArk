"""Pure normalization helpers for Sol-Ark API data."""
from __future__ import annotations

from typing import Any

INVERTER_PARAMETER_IDS = (16,17,18,19,20,21,23,24,25,26,27,28,29,30,31,34,35,44,45,46,60,67,68,70,71,73,75,76,77,78,79,80,81,82,83,84,85,86,91,92,93,94,96,97,98,101,102,103,104,209,210,465,466,467,596,597,598,599,600,601,602,603,604,607,608,609,610,611)

PARAMETER_KEYS = {
    16:"battery_soc",17:"battery_temperature",18:"battery_voltage",19:"battery_current",20:"battery_power",21:"load_power",23:"grid_power",24:"grid_frequency",25:"grid_current_l1",26:"grid_current_l2",27:"grid_current_l3",28:"inverter_temperature",29:"inverter_power",30:"pv_current_1",31:"pv_current_2",34:"pv_voltage_1",35:"pv_voltage_2",44:"grid_voltage_l1",45:"grid_voltage_l2",46:"grid_voltage_l3",60:"output_frequency",67:"output_voltage_l1",68:"output_voltage_l2",70:"output_current_l1",71:"output_current_l2",73:"bms_soc",75:"dc_temperature",76:"ac_temperature",77:"generator_power",78:"smart_load_power",79:"battery_charge_energy",80:"battery_discharge_energy",81:"battery_charge_energy_today",82:"battery_discharge_energy_today",83:"load_energy_today",84:"load_energy",85:"load_power_l1",86:"load_power_l2",91:"grid_import_energy_today",92:"grid_export_energy_today",93:"grid_import_energy",94:"grid_export_energy",96:"pv_energy_today",97:"pv_energy",98:"bms_voltage",101:"bms_current",102:"battery_charge_current_limit",103:"battery_discharge_current_limit",104:"bms_temperature",209:"generator_energy_today",210:"generator_energy",465:"output_voltage_l3",466:"output_current_l3",467:"pv_power",596:"generator_voltage",597:"generator_frequency",598:"load_voltage_l1",599:"load_voltage_l2",600:"pv_power_1",601:"pv_power_2",602:"pv_power_3",603:"pv_current_3",604:"pv_voltage_3",607:"generator_voltage",608:"generator_power",609:"generator_energy_today",610:"generator_energy",611:"generator_frequency",
}


def number(value: Any) -> float | None:
    """Convert numeric values while preserving missing/malformed data."""
    if value is None or isinstance(value, bool): return None
    try: return float(value)
    except (TypeError, ValueError): return None


def flow_values(flow: dict[str, Any]) -> dict[str, Any]:
    """Normalize plant/inverter flow with public signs: import/discharge positive."""
    pv, micro = number(flow.get("pvPower")), number(flow.get("minPower"))
    if pv is not None and micro is not None and (flow.get("existsMin") or flow.get("microOn") or micro): pv += micro
    magnitude = number(flow.get("battPower")); battery = abs(magnitude) if magnitude is not None else None
    if battery is not None and flow.get("toBat"): battery = -battery
    magnitude = number(flow.get("gridOrMeterPower")); grid = abs(magnitude) if magnitude is not None else None
    if grid is not None and flow.get("toGrid"): grid = -grid
    values = {
        "pv_power":pv,"battery_power":battery,"battery_charge_power":max(-battery,0.0) if battery is not None else None,"battery_discharge_power":max(battery,0.0) if battery is not None else None,
        "grid_power":grid,"grid_import_power":max(grid,0.0) if grid is not None else None,"grid_export_power":max(-grid,0.0) if grid is not None else None,
        "load_power":number(flow.get("loadOrEpsPower")),"generator_power":number(flow.get("genPower")),"smart_load_power":micro,"battery_soc":number(flow.get("soc")),
        "generator_on":flow.get("genOn"),"grid_connected":bool(flow.get("gridTo") or flow.get("toGrid")) if magnitude is not None else None,"bms_communication_fault":flow.get("bmsCommFaultFlag"),
    }
    if isinstance(flow.get("pv"), list):
        for index, item in enumerate(flow["pv"], 1):
            if isinstance(item, dict): values[f"pv_power_{index}"] = number(item.get("power"))
    return values


def battery_values(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize inverter-associated aggregate battery telemetry."""
    # This endpoint already uses the public convention: positive discharge,
    # negative charge. Flow instead supplies an unsigned magnitude plus flags.
    power = number(data.get("power"))
    values = {
        "battery_power":power,"battery_charge_power":max(-power,0.0) if power is not None else None,"battery_discharge_power":max(power,0.0) if power is not None else None,
        "battery_soc":number(data.get("bmsSoc")) or number(data.get("soc")),"battery_voltage":number(data.get("bmsVolt")) or number(data.get("voltage")),"battery_current":number(data.get("bmsCurrent")) or number(data.get("current")),
        "battery_temperature":number(data.get("bmsTemp")),"battery_charge_current_limit":number(data.get("chargeCurrentLimit")),"battery_discharge_current_limit":number(data.get("dischargeCurrentLimit")),
        "battery_charge_energy_today":number(data.get("etodayChg")),"battery_discharge_energy_today":number(data.get("etodayDischg")),"battery_charge_energy":number(data.get("etotalChg")),"battery_discharge_energy":number(data.get("etotalDischg")),"battery_status":data.get("status"),
    }
    if values["battery_temperature"] is not None and values["battery_temperature"] <= -100: values["battery_temperature"] = None
    return values


def latest_parameter_values(data: dict[str, Any]) -> dict[int, Any]:
    """Extract the latest record from each inverter-day parameter series."""
    infos = data.get("infos")
    if isinstance(infos, dict): infos = infos.get("list")
    if not isinstance(infos, list): return {}
    result: dict[int, Any] = {}
    for series in infos:
        if not isinstance(series, dict) or series.get("id") is None: continue
        records = series.get("records")
        if isinstance(records, dict): records = records.get("list")
        if not isinstance(records, list): continue
        for record in reversed(records):
            if isinstance(record, dict) and record.get("value") is not None:
                result[int(series["id"])] = record["value"]
                break
    return result


def trapezoid_kwh(previous_watts: float, current_watts: float, seconds: float) -> float:
    """Integrate two power samples into kWh using the trapezoidal rule."""
    if seconds <= 0: return 0.0
    return ((previous_watts + current_watts) / 2.0) * seconds / 3_600_000.0


def complete_inverter_sum(
    inverters: dict[str, dict[str, Any]], key: str
) -> tuple[float | None, list[str]]:
    """Sum a proven per-inverter field only when every inverter contributes.

    A partial total is more harmful than an unavailable value for a site aggregate:
    Home Assistant would otherwise record a false drop whenever one Sol-Ark endpoint
    omits a parallel inverter.
    """
    contributors: list[str] = []
    total = 0.0
    for serial, inverter in inverters.items():
        value = number(inverter.get("values", {}).get(key))
        if value is None:
            continue
        contributors.append(serial)
        total += value
    if not inverters or len(contributors) != len(inverters):
        return None, contributors
    return total, contributors


def merge_inverter_topology(
    previous: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Retain discovered inverters when Sol-Ark returns a transient short list."""
    by_serial = {
        str(item["sn"]): item
        for item in previous
        if isinstance(item, dict) and item.get("sn")
    }
    for item in current:
        if isinstance(item, dict) and item.get("sn"):
            by_serial[str(item["sn"])] = item
    return list(by_serial.values())

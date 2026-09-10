"""Print a secret-safe structural inventory of a browser HAR file."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit


SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-access-token",
}


def normalize_path(path: str) -> str:
    """Replace likely identifiers while retaining API route structure."""
    parts = []
    for part in path.split("/"):
        if re.fullmatch(r"\d+", part):
            part = "{id}"
        elif re.fullmatch(r"[0-9a-fA-F-]{16,}", part):
            part = "{id}"
        parts.append(part)
    return "/".join(parts)


def shape(value: object, depth: int = 0) -> object:
    """Return field names and value types without retaining values."""
    if depth >= 7:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        variants = []
        seen = set()
        for item in value[:10]:
            item_shape = shape(item, depth + 1)
            signature = json.dumps(item_shape, sort_keys=True)
            if signature not in seen:
                variants.append(item_shape)
                seen.add(signature)
        return {"list": variants, "count": len(value)}
    if value is None:
        return "null"
    return type(value).__name__


def parse_json(text: str) -> object | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def list_value(value: object) -> list[object]:
    """Accept either a raw list or the API's {list: [...]} wrapper."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("list"), list):
        return value["list"]
    return []


def main() -> None:
    har_path = Path(sys.argv[1])
    with har_path.open("r", encoding="utf-8-sig") as handle:
        har = json.load(handle)

    inventory: dict[tuple[str, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "count": 0,
            "statuses": Counter(),
            "query_keys": set(),
            "request_header_names": set(),
            "request_shapes": [],
            "response_shapes": [],
            "mime_types": set(),
        }
    )
    semantic: dict[str, list[object]] = defaultdict(list)
    for entry in har.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        response = entry.get("response", {})
        parsed = urlsplit(request.get("url", ""))
        query_values = dict(parse_qsl(parsed.query))
        key = (
            request.get("method", ""),
            parsed.netloc.lower(),
            normalize_path(parsed.path),
        )
        item = inventory[key]
        item["count"] += 1
        item["statuses"][response.get("status")] += 1
        item["query_keys"].update(key for key, _ in parse_qsl(parsed.query))
        item["query_keys"].update(q.get("name", "") for q in request.get("queryString", []))
        item["request_header_names"].update(
            header.get("name", "").lower()
            for header in request.get("headers", [])
            if header.get("name", "").lower() not in SENSITIVE_HEADERS
        )
        post = request.get("postData", {})
        request_json = parse_json(post.get("text", ""))
        if request_json is not None:
            candidate = shape(request_json)
            if candidate not in item["request_shapes"]:
                item["request_shapes"].append(candidate)
        content = response.get("content", {})
        if content.get("mimeType"):
            item["mime_types"].add(content["mimeType"].split(";")[0])
        response_json = parse_json(content.get("text", ""))
        if response_json is not None:
            candidate = shape(response_json)
            if candidate not in item["response_shapes"]:
                item["response_shapes"].append(candidate)

        if "--measurements" in sys.argv and isinstance(response_json, dict):
            data = response_json.get("data")
            route = key[2]
            summary: object | None = None
            if route.endswith("/day") and isinstance(data, dict):
                infos = list_value(data.get("infos", []))
                summary = {
                    "request": {
                        key: query_values.get(key)
                        for key in ("date", "edate", "params", "lan")
                        if key in query_values
                    },
                    "series": [
                        {"id": row.get("id"), "label": row.get("label"), "unit": row.get("unit")}
                        for row in infos if isinstance(row, dict)
                    ],
                }
            elif route.endswith("/generation/use") and isinstance(data, dict):
                summary = data
            elif route.endswith("/flow") and isinstance(data, dict):
                summary = data
            elif "/battery/" in route and route.endswith("/realtime") and isinstance(data, dict):
                wanted = (
                    "etodayChg", "etodayDischg", "emonthChg", "emonthDischg",
                    "eyearChg", "eyearDischg", "etotalChg", "etotalDischg",
                    "power", "capacity", "bmsSoc", "bmsVolt", "bmsCurrent", "bmsTemp",
                    "chargeCurrentLimit", "dischargeCurrentLimit", "status",
                    "batterySoc1", "batteryCurrent1", "batteryVolt1", "batteryPower1",
                    "batteryTemp1", "numberOfBatteries",
                )
                summary = {field: data.get(field) for field in wanted}
            elif route.endswith("/realtime") and isinstance(data, dict):
                summary = data
            elif route == "/api/v1/inverter/params" and isinstance(data, dict):
                infos = list_value(data.get("infos", []))
                summary = [
                    {
                        "group": group.get("groupName"),
                        "fields": [
                            {"id": field.get("id"), "label": field.get("label"), "unit": field.get("unit")}
                            for field in list_value(group.get("groupContent", []))
                        ],
                    }
                    for group in infos if isinstance(group, dict)
                ]
            elif route == "/api/v1/plant/{id}/inverters" and isinstance(data, dict):
                infos = list_value(data.get("infos", []))
                summary = [
                    {
                        "device": f"inverter_{index + 1}",
                        "status": row.get("status"), "type": row.get("type"),
                        "model": row.get("model"), "pac": row.get("pac"),
                        "etoday": row.get("etoday"), "etotal": row.get("etotal"),
                        "gateway_present": bool(row.get("gatewayVO")),
                    }
                    for index, row in enumerate(infos) if isinstance(row, dict)
                ]
            if summary is not None and summary not in semantic[route]:
                semantic[route].append(summary)

    if "--measurements" in sys.argv:
        json.dump(semantic, sys.stdout, indent=2)
        print()
        return

    output = []
    for (method, host, path), item in sorted(inventory.items()):
        if not ("solark" in host or path.startswith(("/api/", "/oauth/", "/rest/"))):
            continue
        output.append(
            {
                "method": method,
                "host": host,
                "path": path,
                "count": item["count"],
                "statuses": dict(item["statuses"]),
                "query_keys": sorted(key for key in item["query_keys"] if key),
                "request_header_names": sorted(item["request_header_names"]),
                "request_shapes": item["request_shapes"],
                "response_shapes": item["response_shapes"],
                "mime_types": sorted(item["mime_types"]),
            }
        )
    if "--routes" in sys.argv:
        for item in output:
            if item["method"] == "OPTIONS":
                continue
            print(
                f'{item["method"]}\t{item["path"]}\t'
                f'query={",".join(item["query_keys"])}\t'
                f'status={item["statuses"]}\tcount={item["count"]}'
            )
        return

    selectors = [arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--match=")]
    if selectors:
        output = [
            item for item in output
            if any(selector.lower() in item["path"].lower() for selector in selectors)
            and item["method"] != "OPTIONS"
        ]
    json.dump(output, sys.stdout, indent=2, sort_keys=False)
    print()


if __name__ == "__main__":
    main()

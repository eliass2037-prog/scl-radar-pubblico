#!/usr/bin/env python3
"""Verify low-latency EUMETSAT MSG Rapid Scan imagery over Locarno.

Uses public EUMETView WMS (no token) and records actual layer time dimensions
plus a small GetMap test. It does not fabricate a cloud percentage.
"""
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://view.eumetsat.int/geoserver/wms"
OUT = Path("rapid_scan_status.json")
BBOX = "8.45,45.95,9.20,46.42"
LAYERS = [
    "msg_rss:rgb_naturalenhncd_nrt",
    "msg_rss:rgb_natural_nrt",
    "msg_rss:rgb_microphysics_nrt",
    "msg_rss:ir039_nrt",
]


def request(params, limit=5_000_000):
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "SCL-Rapid-Scan/1.0"})
    with urllib.request.urlopen(req, timeout=50) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("WMS response too large")
        return body, response.status, response.headers.get("Content-Type", "")


def main():
    result = {
        "source": "EUMETSAT EUMETView MSG Rapid Scan",
        "service": "MSG RSS SEVIRI",
        "nominal_cadence_minutes": 5,
        "area": "Locarno / Lago Maggiore",
        "bbox": BBOX,
        "status": "checking",
        "cloud_percent": None,
        "layers": []
    }
    try:
        xml, status, _ = request({
            "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"
        })
        root = ET.fromstring(xml)
        layer_nodes = [x for x in root.iter() if x.tag.split("}")[-1] == "Layer"]
        for target in LAYERS:
            found = None
            for node in layer_nodes:
                name = next((c.text for c in node if c.tag.split("}")[-1] == "Name"), None)
                if name != target:
                    continue
                title = next((c.text for c in node if c.tag.split("}")[-1] == "Title"), None)
                dims = []
                for c in node:
                    tag = c.tag.split("}")[-1]
                    if tag in ("Dimension", "Extent") and c.attrib.get("name", "").lower() == "time":
                        dims.append({
                            "tag": tag,
                            "default": c.attrib.get("default"),
                            "nearestValue": c.attrib.get("nearestValue"),
                            "value": (c.text or "")[-500:]
                        })
                found = {"name": name, "title": title, "time": dims}
                if dims and dims[0].get("default"):
                    scan = datetime.fromisoformat(dims[0]["default"].replace("Z", "+00:00"))
                    found["scan_time_utc"] = scan.isoformat()
                break
            if not found:
                result["layers"].append({"name": target, "available": False})
                continue

            # Request a current WMS map without TIME: EUMETView serves the latest
            # available image for near-real-time RSS layers.
            image, http, ctype = request({
                "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
                "LAYERS": target, "STYLES": "", "FORMAT": "image/png",
                "TRANSPARENT": "FALSE", "SRS": "EPSG:4326", "BBOX": BBOX,
                "WIDTH": "640", "HEIGHT": "400"
            }, limit=4_000_000)
            found.update({
                "available": True,
                "map_http_status": http,
                "map_content_type": ctype,
                "map_bytes": len(image),
                "map_valid_png": image.startswith(b"\x89PNG\r\n\x1a\n")
            })
            result["layers"].append(found)

        good = [x for x in result["layers"] if x.get("available") and x.get("map_valid_png")]
        fresh = [x for x in good if x.get("scan_time_utc") and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(x["scan_time_utc"])).total_seconds() <= 45 * 60]
        result["status"] = "rapid_scan_fresh" if fresh else ("rapid_scan_stale" if good else "rapid_scan_wms_unavailable")
        result["fresh_layers"] = [x["name"] for x in fresh]
        result["usable_layers"] = [x["name"] for x in good]
        result["recommended_day_layer"] = next((x["name"] for x in good if "naturalenhncd" in x["name"]), None)
        result["recommended_fallback_layer"] = next((x["name"] for x in good if "ir039" in x["name"]), None)
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

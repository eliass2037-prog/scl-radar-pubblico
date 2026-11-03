#!/usr/bin/env python3
"""Non-destructive check of EUMETSAT MSG Rapid Scan Cloud Mask availability.

This diagnostic deliberately does NOT estimate cloud cover or change cloud.json.
It verifies the official RSS-CLM collection catalogue and whether EUMETView
publishes a matching WMS layer. The actual product is a five-minute RSS
collection, distinct from the generic msg_fes:clm WMS layer.
"""
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

COLLECTION = "EO:EUM:DAT:MSG:RSS-CLM"
SEARCH = "https://api.eumetsat.int/data/search-products/1.0.0/os"
WMS = "https://view.eumetsat.int/geoserver/wms"
OUT = Path("rapid_scan_status.json")


def get(url, timeout=40, limit=8_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": "SCL-Rapid-Scan-Diagnostic/1.0", "Accept": "application/json, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response too large")
        return data, response.status, response.headers.get("Content-Type", "")


def product_summary(obj):
    if isinstance(obj, list):
        return [product_summary(x) for x in obj[:5]]
    if not isinstance(obj, dict):
        return {"value": str(obj)[:300]}
    keep = {}
    for key, value in obj.items():
        lk = key.lower()
        if any(s in lk for s in ("identifier", "title", "date", "time", "link", "href", "id", "size", "satellite", "instrument")):
            if isinstance(value, (str, int, float, bool)) or value is None:
                keep[key] = value
            elif isinstance(value, list):
                keep[key] = value[:4]
            elif isinstance(value, dict):
                keep[key] = {k: v for k, v in list(value.items())[:8] if isinstance(v, (str, int, float, bool)) or v is None}
    return keep


def main():
    report = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "collection": COLLECTION,
        "expected_cadence": "5 minutes (EUMETSAT RSS-CLM catalogue)",
        "status": "unverified",
        "cloud_percent": None,
        "note": "Catalogue/WMS diagnostic only; no cloud percentage is calculated."
    }

    query = urllib.parse.urlencode({"pi": COLLECTION, "c": "5", "format": "json"})
    try:
        data, status, ctype = get(SEARCH + "?" + query)
        report["catalogue_http_status"] = status
        report["catalogue_content_type"] = ctype
        payload = json.loads(data.decode("utf-8"))
        report["catalogue_response_keys"] = list(payload.keys())[:30] if isinstance(payload, dict) else []
        # OpenSearch implementations commonly use features, products, entries or items.
        records = []
        if isinstance(payload, dict):
            for key in ("features", "products", "items", "entries", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    records = value
                    break
            if not records and isinstance(payload.get("feed"), dict):
                records = payload["feed"].get("entry", []) or []
        report["catalogue_records_found"] = len(records)
        report["latest_products"] = [product_summary(x) for x in records[:5]]
        report["catalogue_status"] = "products_found" if records else "response_received_no_records_parsed"
    except Exception as exc:
        report["catalogue_status"] = "error"
        report["catalogue_error"] = str(exc)[:500]

    try:
        params = urllib.parse.urlencode({"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"})
        data, status, ctype = get(WMS + "?" + params)
        report["wms_http_status"] = status
        root = ET.fromstring(data)
        matches = []
        for layer in root.iter():
            if layer.tag.split("}")[-1] != "Layer":
                continue
            name = title = None
            for child in layer:
                tag = child.tag.split("}")[-1]
                if tag == "Name":
                    name = child.text
                elif tag == "Title":
                    title = child.text
            label = (str(name or "") + " " + str(title or "")).lower()
            if "rapid" in label or "rss" in label or "cloud mask" in label or "clm" in label:
                matches.append({"name": name, "title": title})
        report["wms_matching_layers"] = matches[:60]
        report["wms_rss_layer_found"] = any("rss" in str(x.get("name", "")).lower() or "rapid" in str(x.get("title", "")).lower() for x in matches)
        report["wms_status"] = "capabilities_received"
    except Exception as exc:
        report["wms_status"] = "error"
        report["wms_error"] = str(exc)[:500]

    if report.get("catalogue_status") == "products_found":
        report["status"] = "rss_catalogue_products_found"
    elif report.get("catalogue_status") == "response_received_no_records_parsed":
        report["status"] = "catalogue_needs_inspection"
    else:
        report["status"] = "rss_catalogue_not_verified"

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

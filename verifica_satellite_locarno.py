#!/usr/bin/env python3
"""Verifica NON distruttiva della disponibilita' EUMETView Cloud Mask.
Non pubblica stime meteorologiche prima della verifica del formato dati.
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

URL = 'https://view.eumetsat.int/geoserver/wms'
OUT = Path('diagnostica_satellite.json')

def main():
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(), 'location': 'Locarno', 'status': 'unverified', 'source': 'EUMETSAT EUMETView', 'cloud_percent': None}
    try:
        q = urllib.parse.urlencode({'SERVICE':'WMS','REQUEST':'GetCapabilities','VERSION':'1.3.0'})
        req = urllib.request.Request(URL+'?'+q, headers={'User-Agent':'SCL-Cloud-Diagnostic/1.0'})
        with urllib.request.urlopen(req, timeout=35) as response:
            data = response.read(8_000_000)
            result['http_status'] = response.status
        root = ET.fromstring(data)
        layers = []
        for layer in root.iter():
            if layer.tag.split('}')[-1] != 'Layer':
                continue
            name = title = None
            for child in layer:
                tag = child.tag.split('}')[-1]
                if tag == 'Name': name = child.text
                if tag == 'Title': title = child.text
            if name and ('clm' in (name+' '+(title or '')).lower() or 'cloud mask' in (title or '').lower()):
                layers.append({'name':name, 'title':title})
        result['matching_layers'] = layers[:40]
        result['status'] = 'capabilities_received' if layers else 'no_cloud_mask_layer_found'
        result['next_step'] = 'Verify actual layer, time dimension, legend and pixel classes before producing cloud percentage.'
    except Exception as exc:
        result['status'] = 'connection_or_parsing_error'
        result['error'] = str(exc)[:500]
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'capabilities_received' else 1

if __name__ == '__main__':
    sys.exit(main())

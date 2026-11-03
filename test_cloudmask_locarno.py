#!/usr/bin/env python3
"""Secondo test EUMETView: scarica immagine e legenda Cloud Mask.
Non interpreta arbitrariamente i colori come percentuali di nuvolosita'.
"""
import json, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE='https://view.eumetsat.int/geoserver/wms'
LAYER='msg_fes:clm'
OUT=Path('test_satellite_output'); OUT.mkdir(exist_ok=True)

def request(params, filename, limit=12000000):
    url=BASE+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'SCL-Cloud-Diagnostic/2.0'})
    with urllib.request.urlopen(req,timeout=65) as resp:
        content=resp.read(limit+1)
        if len(content)>limit: raise ValueError('Response too large')
        ctype=resp.headers.get('Content-Type','')
        code=resp.status
    (OUT/filename).write_bytes(content)
    return {'status':code,'content_type':ctype,'bytes':len(content),'file':filename,'preview':content[:250].decode('utf-8','replace') if b'xml' in content[:100].lower() or b'exception' in content[:200].lower() else None}

def tag(e): return e.tag.split('}')[-1]

def main():
    report={'utc':datetime.now(timezone.utc).isoformat(),'layer':LAYER,'cloud_percent':None,'tests':{}}
    try:
        cap=request({'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetCapabilities'},'capabilities.xml')
        report['tests']['capabilities']=cap
        root=ET.fromstring((OUT/'capabilities.xml').read_bytes())
        for lyr in root.iter():
            if tag(lyr)!='Layer': continue
            name=next((x.text for x in lyr if tag(x)=='Name'),None)
            if name!=LAYER: continue
            report['layer_found']=True
            report['dimensions']=[{'tag':tag(x),'name':x.attrib.get('name'),'attributes':x.attrib,'value':(x.text or '')[:400]} for x in lyr if tag(x) in ('Dimension','Extent')]
            report['styles']=[{'name':next((x.text for x in st if tag(x)=='Name'),None),'legend_urls':[x.attrib.get('xlink:href') or next((v for k,v in x.attrib.items() if k.endswith('}href')),None) for x in st.iter() if tag(x)=='OnlineResource']} for st in lyr if tag(st)=='Style']
            break
        # WMS 1.1.1 avoids EPSG:4326 lat/lon axis inversion.
        # Area ~ 60 km across Locarno/Lago Maggiore; sample pixels for inspection only.
        common={'SERVICE':'WMS','VERSION':'1.1.1','LAYERS':LAYER,'STYLES':'','FORMAT':'image/png','TRANSPARENT':'FALSE'}
        p=dict(common,REQUEST='GetMap',SRS='EPSG:4326',BBOX='8.45,45.95,9.20,46.42',WIDTH='600',HEIGHT='450')
        report['tests']['map']=request(p,'cloudmask_locarno.png')
        report['tests']['legend']=request({'SERVICE':'WMS','VERSION':'1.1.1','REQUEST':'GetLegendGraphic','LAYER':LAYER,'FORMAT':'image/png'},'cloudmask_legend.png')
        report['status']='images_received' if all(report['tests'][k]['content_type'].lower().startswith('image/') for k in ('map','legend')) else 'check_server_response'
    except Exception as e:
        report['status']='error';report['error']=str(e)[:700]
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='images_received' else 1
if __name__=='__main__': raise SystemExit(main())

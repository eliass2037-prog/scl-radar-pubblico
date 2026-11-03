#!/usr/bin/env python3
"""Read the EUMETSAT MSG Cloud Mask WMS around Locarno, publish fresh cloud.json.
Fail closed: never turn a missing/stale/unrecognised satellite image into clear skies.
"""
import io,json,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
BASE='https://view.eumetsat.int/geoserver/wms'
LAYER='msg_fes:clm'
OUT=Path('cloud.json')
def fetch(params):
 url=BASE+'?'+urllib.parse.urlencode(params)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SCL-Cloud-Mask/1.0'}),timeout=60) as r:
  data=r.read(4_000_001)
  if len(data)>4_000_000:raise ValueError('response too large')
  return data

def run():
 root=ET.fromstring(fetch({'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetCapabilities'}))
 stamp=None
 for layer in root.iter():
  if layer.tag.split('}')[-1]!='Layer':continue
  if not any(x.tag.split('}')[-1]=='Name' and x.text==LAYER for x in layer):continue
  for x in layer:
   if x.tag.split('}')[-1]=='Dimension' and x.attrib.get('name')=='time':
    stamp=x.attrib.get('default')
  break
 if not stamp:raise ValueError('no satellite timestamp')
 dt=datetime.fromisoformat(stamp.replace('Z','+00:00'))
 age=abs((datetime.now(timezone.utc)-dt).total_seconds())
if age>60*60:raise ValueError('satellite image is stale')
    # Download satellite image
    png=fetch({'SERVICE':'WMS','VERSION':'1.1.1','REQUEST':'GetMap','LAYERS':LAYER,
               'STYLES':'','FORMAT':'image/png','TRANSPARENT':'FALSE','SRS':'EPSG:4326',
               'BBOX':'8.73,46.13,8.87,46.21','WIDTH':'400','HEIGHT':'400','TIME':stamp})
 im=Image.open(io.BytesIO(png)).convert('RGB')
 cloudy=clear=0
 # Sample only inner 60% to avoid edge artifacts. Pure white: cloud;
 # green (1,192,0) and blue clear classes. Reject unrecognised pixels.
 for y in range(80,320,2):
  for x in range(80,320,2):
   r,g,b=im.getpixel((x,y))
   if min(r,g,b)>=245:cloudy+=1
   elif g>=155 and r<=65 and b<=90:clear+=1
   elif b>=125 and r<=80 and g<=180:clear+=1
 total=cloudy+clear
 if total<500 or total<0.8*120*120:raise ValueError('unrecognised image palette')
 return {'status':'ok','source':'EUMETSAT MSG Cloud Mask','timestamp':int(dt.timestamp()),
         'cloud_percent':round(100*cloudy/total,1),'valid_pixels':total,
         'area':'Locarno / Lago Maggiore','method':'cloud mask area fraction; not optical cloud fraction'}
if __name__=='__main__':
 try:data=run()
 except Exception as e:data={'status':'unavailable','source':'EUMETSAT MSG Cloud Mask','error':str(e)[:150]}
 OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(data))

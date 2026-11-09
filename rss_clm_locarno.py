#!/usr/bin/env python3
"""EUMETSAT RSS-CLM -> validated cloud.json. Never infer clear skies on errors."""
import io, json, os, re, sys, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
OUT = Path("cloud.json")
COLLECTION = "EO:EUM:DAT:MSG:RSS-CLM"
LAT, LON = 46.17, 8.80
MAX_AGE_MIN = 45

def run():
    import eumdac
    import eccodes
    key = os.environ.get("EUMETSAT_CONSUMER_KEY") or os.environ.get("EUMETSAT_API_KEY")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET") or os.environ.get("EUMETSAT_API_SECRET")
    if not key or not secret:
        raise RuntimeError("EUMETSAT_CONSUMER_KEY / EUMETSAT_CONSUMER_SECRET secrets missing")
    token = eumdac.AccessToken((key, secret))
    store = eumdac.DataStore(token)
    collection = store.get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    candidates = list(collection.search(dtstart=now-timedelta(hours=4), dtend=now))
    if not candidates:
        raise RuntimeError("No RSS-CLM products in last four hours")
    def sensing(product):
        match = re.search(r"(20\d{12})", str(product))
        if not match: return datetime.min.replace(tzinfo=timezone.utc)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    product = max(candidates, key=sensing)
    observed = sensing(product)
    age = (now-observed).total_seconds()/60
    if age < -5 or age > MAX_AGE_MIN:
        raise RuntimeError(f"RSS-CLM is stale: {age:.1f} minutes")
    stream = io.BytesIO()
    with product.open() as src:
        while True:
            part = src.read(1024*1024)
            if not part: break
            if stream.tell()+len(part)>25_000_000: raise RuntimeError("Satellite download too large")
            stream.write(part)
    stream.seek(0)
    with zipfile.ZipFile(stream) as z:
        grbs = [n for n in z.namelist() if n.lower().endswith((".grb",".grib",".grib2")) and not n.startswith("__MACOSX")]
        if len(grbs)!=1: raise RuntimeError("Unexpected GRIB files")
        data = z.read(grbs[0])
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".grb") as temp:
        temp.write(data);temp.flush()
        with open(temp.name,"rb") as fh:
            gid=eccodes.codes_grib_new_from_file(fh)
            if gid is None: raise RuntimeError("No GRIB message")
            try:
                # Locate closest georeferenced pixel (never use an unverified image palette).
                lats=eccodes.codes_get_array(gid,"latitudes")
                lons=eccodes.codes_get_array(gid,"longitudes")
                vals=eccodes.codes_get_array(gid,"values")
                if not (len(lats)==len(lons)==len(vals)): raise RuntimeError("GRIB coordinate mismatch")
                # Local geographic radius, approximate kilometers; ignore missing/out-of-range.
                import numpy as np
                lat=np.asarray(lats);lon=np.asarray(lons);v=np.asarray(vals)
                d=((lat-LAT)*111)**2+((lon-LON)*77)**2
                valid=np.isfinite(v)&np.isin(v,[0,1,2])
                # Diagnostics from the actual GRIB, visible in GitHub Actions logs.
                # Do not publish an unverified cloud percentage.
                for radius in (5,10,15,20,30):
                    inside=d<=radius**2
                    classes={str(cls):int(np.count_nonzero(inside & np.isfinite(v) & (v==cls))) for cls in (0,1,2,3)}
                    print(json.dumps({"diagnostic":"local_grib","radius_km":radius,"total_pixels":int(inside.sum()),"valid_pixels":int(np.count_nonzero(inside&valid)),"classes":classes}),flush=True)
                if np.any(valid):
                    idx=np.flatnonzero(valid)[np.argmin(d[valid])]
                    print(json.dumps({"diagnostic":"nearest_valid","distance_km":round(float(np.sqrt(d[idx])),2),"latitude":round(float(lat[idx]),4),"longitude":round(float(lon[idx]),4),"class":int(v[idx])}),flush=True)
                else:
                    print(json.dumps({"diagnostic":"no_valid_pixels_in_grib","finite_pixels":int(np.count_nonzero(np.isfinite(v)))}),flush=True)
                region=(d<=10**2)&valid
                if int(region.sum())<10: raise RuntimeError("Too few valid local cloud-mask pixels; see local_grib diagnostics in Actions logs")
                cloud=float(np.mean(v[region]==2)*100)
                nearest=int(np.argmin(d))
                if float(d[nearest])>25: raise RuntimeError("No pixel near Locarno")
                return {"status":"ok","source":"EUMETSAT RSS-CLM GRIB2","timestamp":int(observed.timestamp()),"cloud_percent":round(cloud,1),"valid_pixels":int(region.sum()),"area":"Locarno / Lago Maggiore","method":"GRIB2 class 2 cloudy, classes 0/1 clear; 10 km radius","pixel_class":int(v[nearest]),"age_minutes_at_publication":round(age,1)}
            finally: eccodes.codes_release(gid)

if __name__=="__main__":
    try: result=run()
    except Exception as exc: result={"status":"unavailable","source":"EUMETSAT RSS-CLM GRIB2","cloud_percent":None,"error":str(exc)[:240]}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result))

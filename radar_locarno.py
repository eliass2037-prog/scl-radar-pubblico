
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
from pyproj import CRS, Transformer

BASE = (
    "https://data.geo.admin.ch/api/stac/v1/collections/"
    "ch.meteoschweiz.ogd-radar-precip/items/"
)

OUTPUT = Path("radar.json")
LON = 8.7995
LAT = 46.1691


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def get_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "SCL-Radar/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    today = datetime.now(timezone.utc).date()

    for offset_days in range(3):
        day = today - timedelta(days=offset_days)
        item_id = day.strftime("%Y%m%d") + "-ch"

        try:
            item = get_json(BASE + item_id)
        except Exception as error:
            print("Catalogo non disponibile:", item_id, error)
            continue

        files = [
            (name, asset["href"])
            for name, asset in item.get("assets", {}).items()
            if name.lower().startswith("rzc")
            and name.lower().endswith(".h5")
            and asset.get("href", "").startswith("https://")
        ]

        if not files:
            continue

        filename, url = max(files, key=lambda entry: entry[0])
        print("RADAR:", filename)

        request = urllib.request.Request(
            url, headers={"User-Agent": "SCL-Radar/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()

        Path("radar_test.h5").write_bytes(content)

        with h5py.File("radar_test.h5", "r") as radar:
            where = radar["where"].attrs
            projection = decode(where["projdef"])

            transformer = Transformer.from_crs(
                CRS.from_epsg(4326),
                CRS.from_user_input(projection),
                always_xy=True,
            )

            x, y = transformer.transform(LON, LAT)
            x0, y0 = transformer.transform(
                float(where["LL_lon"]),
                float(where["LL_lat"]),
            )

            xscale = float(where["xscale"])
            yscale = float(where["yscale"])

            col = math.floor((x - x0) / xscale)
            row = int(where["ysize"]) - 1 - math.floor(
                (y - y0) / yscale
            )

            dataset = radar["dataset1/data1/data"]

            if not (
                0 <= row < dataset.shape[0]
                and 0 <= col < dataset.shape[1]
            ):
                raise RuntimeError("Locarno fuori dalla griglia radar")

            value = float(dataset[row, col])
            attributes = radar["dataset1/data1/what"].attrs

            gain = float(attributes["gain"])
            offset_value = float(attributes["offset"])

            precipitation = (
                round(value * gain + offset_value, 2)
                if math.isfinite(value)
                else None
            )

            measurement = radar["what"].attrs
            date = decode(measurement["date"])
            time = decode(measurement["time"])

            observed = datetime.strptime(
                date + time, "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc)

        result = {
            "localita": "Locarno",
            "precipitazioni_mm_h": precipitation,
            "aggiornamento": observed.isoformat(),
            "stato": (
                "ok" if precipitation is not None
                else "dato_non_disponibile"
            ),
            "fonte": "MeteoSvizzera RZC",
            "file": filename,
        }

        OUTPUT.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print("JSON GENERATO:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    raise RuntimeError("Nessun file radar RZC disponibile")


if __name__ == "__main__":
    main()

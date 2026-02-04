import xml.etree.ElementTree as ET
import requests
import json
from datetime import datetime
import time

# --- CONFIGURACIÓN ---
REGIONS = {
    "Cataluña": "http://infocar.dgt.es/datex2/sct/SituationPublication/all/content.xml",
    "País Vasco": "http://infocar.dgt.es/datex2/dt-gv/SituationPublication/all/content.xml",
    "Resto España": "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml"
}

TRANSLATIONS = {
    "highest": "Negro (Corte Total)",
    "high": "Rojo (Grave)",
    "medium": "Naranja (Moderado)",
    "low": "Amarillo (Leve)",
    "unknown": "Desconocido"
}

def get_road_geometry(lon1, lat1, lon2, lat2):
    """Obtiene la ruta real. Si tarda más de 2 seg, devuelve línea recta para no bloquear."""
    try:
        # Usamos un timeout muy corto para que el script no se quede colgado
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=2) 
        if r.status_code == 200:
            data = r.json()
            if data.get("routes"):
                return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    # Fallback rápido: línea recta
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Descargando {region_name}...")
        response = requests.get(url, timeout=20)
        root = ET.fromstring(response.content)

        ns = {
            'sit': 'http://levelC/schema/3/situation',
            'loc': 'http://levelC/schema/3/locationReferencing',
            '_0': 'http://datex2.eu/schema/1_0/1_0'
        }
        
        records = root.findall(".//sit:situationRecord", ns) + root.findall(".//_0:situationRecord", ns)
        print(f"Procesando {len(records)} registros en {region_name}...")

        for i, record in enumerate(records):
            is_v3 = 'levelC' in record.tag
            pref = 'sit:' if is_v3 else '_0:'
            
            # Severidad y descripción
            sev_elem = record.find(f"{pref}severity", ns)
            sev_raw = sev_elem.text if sev_elem is not None else "unknown"
            desc = f"<b>Gravedad:</b> {TRANSLATIONS.get(sev_raw, sev_raw)}"
            
            # Coordenadas
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # Búsqueda de tramos (Lineal)
            linear = record.find(".//loc:linearLocation", ns) or record.find(".//_0:locationContainedInGroup", ns)
            if linear is not None:
                f_pt = linear.find(".//loc:from//loc:pointCoordinates", ns) or linear.find(".//_0:from//_0:pointCoordinates", ns)
                t_pt = linear.find(".//loc:to//loc:pointCoordinates", ns) or linear.find(".//_0:to//_0:pointCoordinates", ns)
                if f_pt is not None and t_pt is not None:
                    lat_f, lon_f = (f_pt.find(".//loc:latitude", ns) or f_pt.find("_0:latitude", ns)).text, \
                                   (f_pt.find(".//loc:longitude", ns) or f_pt.find("_0:longitude", ns)).text
                    lat_t, lon_t = (t_pt.find(".//loc:latitude", ns) or t_pt.find("_0:latitude", ns)).text, \
                                   (t_pt.find(".//loc:longitude", ns) or t_pt.find("_0:longitude", ns)).text

            # Si hay tramo, pedimos curvas (solo para los primeros 50 para no saturar OSRM)
            if lat_f and lat_t:
                # Limitamos las peticiones a OSRM para que el workflow no se cuelgue
                if i < 60: 
                    coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t)
                    time.sleep(0.1) # Pequeño respiro para el servidor
                else:
                    coords = [[float(lon_f), float(lat_f)], [float(lon_t), float(lat_t)]]
                
                all_incidents.append({"type": "Feature", "properties": {"description": desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                all_incidents.append({"type": "Feature", "properties": {"description": desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(lon_f), float(lat_f)]}})
            else:
                # Punto único
                p_pt = record.find(".//loc:pointCoordinates", ns) or record.find(".//_0:pointCoordinates", ns) or record.find(".//loc:pointByCoordinates//loc:pointCoordinates", ns)
                if p_pt is not None:
                    l_lat = p_pt.find(".//loc:latitude", ns) or p_pt.find("_0:latitude", ns)
                    l_lon = p_pt.find(".//loc:longitude", ns) or p_pt.find("_0:longitude", ns)
                    if l_lat is not None:
                        all_incidents.append({"type": "Feature", "properties": {"description": desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(l_lon.text), float(l_lat.text)]}})

    except Exception as e:
        print(f"Salto en {region_name}: {e}")

if __name__ == "__main__":
    res = []
    for n, u in REGIONS.items():
        process_xml_from_url(u, n, res)
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": res}, f, indent=2, ensure_ascii=False)
    print("GeoJSON generado.")
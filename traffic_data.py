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
    "unknown": "Desconocido",
    "roadClosed": "Carretera Cortada",
    "roadworks": "Obras",
    "heavy": "Retención Fuerte"
}

def get_road_geometry(lon1, lat1, lon2, lat2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("routes"):
            return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        ns = {
            'sit': 'http://levelC/schema/3/situation',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
            '_0': 'http://datex2.eu/schema/1_0/1_0'
        }
        
        records = root.findall(".//sit:situationRecord", ns) + root.findall(".//_0:situationRecord", ns)
        print(f"Registros brutos: {len(records)}")

        count = 0
        for record in records:
            is_v3 = 'levelC' in record.tag
            pref = 'sit:' if is_v3 else '_0:'
            
            # --- SEVERIDAD (IMPORTANTE PARA COLORES) ---
            sev_elem = record.find(f"{pref}severity", ns)
            sev_raw = sev_elem.text if sev_elem is not None else "unknown"
            
            # Recuperamos el truco del comentario oculto para el index.html
            desc = [f"", f"<b>Gravedad:</b> {TRANSLATIONS.get(sev_raw, sev_raw)}"]
            
            # Carretera
            road = record.find(".//loc:roadName", ns) or record.find(".//_0:roadNumber", ns)
            if road is not None and road.text: desc.append(f"<b>Carretera:</b> {road.text}")
            
            final_desc = "<br>".join(desc)

            # --- GEOMETRÍA (Búsqueda mejorada) ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # 1. Intentar Tramo (Lineal)
            linear = record.find(".//loc:linearLocation", ns) or record.find(".//_0:locationContainedInGroup", ns)
            if linear is not None:
                f_pt = linear.find(".//loc:from//loc:pointCoordinates", ns) or linear.find(".//_0:from//_0:pointCoordinates", ns)
                t_pt = linear.find(".//loc:to//loc:pointCoordinates", ns) or linear.find(".//_0:to//_0:pointCoordinates", ns)
                if f_pt is not None and t_pt is not None:
                    lat_f, lon_f = f_pt.find(".//loc:latitude", ns).text if is_v3 else f_pt.find("_0:latitude", ns).text, \
                                   f_pt.find(".//loc:longitude", ns).text if is_v3 else f_pt.find("_0:longitude", ns).text
                    lat_t, lon_t = t_pt.find(".//loc:latitude", ns).text if is_v3 else t_pt.find("_0:latitude", ns).text, \
                                   t_pt.find(".//loc:longitude", ns).text if is_v3 else t_pt.find("_0:longitude", ns).text

            if lat_f and lat_t:
                # Dibujar ruta con curvas
                coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t)
                all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                # Añadir punto para el icono
                all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(lon_f), float(lat_f)]}})
                count += 1
            else:
                # 2. Intentar Punto Único (Si no hay tramo)
                # Buscamos en todas las rutas posibles del XML
                p_pt = record.find(".//loc:pointCoordinates", ns) or \
                       record.find(".//_0:pointCoordinates", ns) or \
                       record.find(".//loc:pointByCoordinates//loc:pointCoordinates", ns)
                
                if p_pt is not None:
                    l_lat = p_pt.find(".//loc:latitude", ns) or p_pt.find("_0:latitude", ns)
                    l_lon = p_pt.find(".//loc:longitude", ns) or p_pt.find("_0:longitude", ns)
                    if l_lat is not None and l_lon is not None:
                        all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(l_lon.text), float(l_lat.text)]}})
                        count += 1

        print(f"OK: {count} procesados.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    total = []
    for n, u in REGIONS.items():
        process_xml_from_url(u, n, total)
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": total}, f, indent=2, ensure_ascii=False)
    print(f"\nFinalizado: {len(total)} elementos en el mapa.")
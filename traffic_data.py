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
    "roadworks": "Obras"
}

def get_road_geometry(lon1, lat1, lon2, lat2):
    """Consulta a OSRM para obtener el trazado real."""
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data.get("routes") and len(data["routes"]) > 0:
                return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=25)
        root = ET.fromstring(response.content)

        ns = {
            'sit': 'http://levelC/schema/3/situation',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
            '_0': 'http://datex2.eu/schema/1_0/1_0'
        }
        
        # Buscar todos los registros posibles
        records = root.findall(".//sit:situationRecord", ns) + root.findall(".//_0:situationRecord", ns)
        
        for i, record in enumerate(records):
            is_v3 = 'levelC' in record.tag
            pref = 'sit:' if is_v3 else '_0:'
            
            # --- SEVERIDAD ---
            sev_elem = record.find(f"{pref}severity", ns)
            sev_raw = sev_elem.text if (sev_elem is not None and sev_elem.text) else "unknown"
            
            description = [f"", f"<b>Gravedad:</b> {TRANSLATIONS.get(sev_raw, sev_raw)}"]

            # --- CARRETERA ---
            road_elem = record.find(".//loc:roadName", ns) if is_v3 else record.find(".//_0:roadNumber", ns)
            if road_elem is not None and road_elem.text:
                description.append(f"<b>Carretera:</b> {road_elem.text}")

            final_desc = "<br>".join(description)

            # --- GEOMETRÍA ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # 1. Buscar Tramos Lineales
            linear = record.find(".//loc:linearLocation", ns) or record.find(".//_0:locationContainedInGroup", ns)
            if linear is not None:
                f_pt = linear.find(".//loc:from//loc:pointCoordinates", ns) or linear.find(".//_0:from//_0:pointCoordinates", ns)
                t_pt = linear.find(".//loc:to//loc:pointCoordinates", ns) or linear.find(".//_0:to//_0:pointCoordinates", ns)
                
                if f_pt is not None and t_pt is not None:
                    lat_f_el = f_pt.find(".//loc:latitude", ns) if is_v3 else f_pt.find("_0:latitude", ns)
                    lon_f_el = f_pt.find(".//loc:longitude", ns) if is_v3 else f_pt.find("_0:longitude", ns)
                    lat_t_el = t_pt.find(".//loc:latitude", ns) if is_v3 else t_pt.find("_0:latitude", ns)
                    lon_t_el = t_pt.find(".//loc:longitude", ns) if is_v3 else t_pt.find("_0:longitude", ns)
                    
                    if all(el is not None for el in [lat_f_el, lon_f_el, lat_t_el, lon_t_el]):
                        lat_f, lon_f, lat_t, lon_t = lat_f_el.text, lon_f_el.text, lat_t_el.text, lon_t_el.text

            # Procesar
            if lat_f and lat_t:
                # Si es un tramo, pedimos la curva (límite 60 para no saturar)
                coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t) if i < 60 else [[float(lon_f), float(lat_f)], [float(lon_t), float(lat_t)]]
                all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                # Punto para el icono
                all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(lon_f), float(lat_f)]}})
            else:
                # Si no es tramo, buscar punto único
                p_pt = record.find(".//loc:pointByCoordinates//loc:pointCoordinates", ns) or record.find(".//_0:pointCoordinates", ns)
                if p_pt is not None:
                    lat_el = p_pt.find(".//loc:latitude", ns) or p_pt.find("_0:latitude", ns)
                    lon_el = p_pt.find(".//loc:longitude", ns) or p_pt.find("_0:longitude", ns)
                    if lat_el is not None and lon_el is not None:
                        all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(lon_el.text), float(lat_el.text)]}})

        print(f"OK: {region_name} terminada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    results = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, results)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": results}, f, indent=2, ensure_ascii=False)
    print(f"\nFinalizado con {len(results)} elementos.")
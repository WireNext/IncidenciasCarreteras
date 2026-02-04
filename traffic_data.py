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
    "heavy": "Retención Fuerte",
    "laneClosures": "Carriles Cerrados"
}

def translate(value):
    return TRANSLATIONS.get(value, value)

def format_datetime(datetime_str):
    try:
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%Y - %H:%M:%S")
    except:
        return datetime_str

def get_road_geometry(lon1, lat1, lon2, lat2):
    """Consulta a OSRM para obtener el trazado real de la carretera."""
    try:
        # Timeout corto de 2 segundos para no bloquear el script
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data.get("routes"):
                return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    # Fallback: si falla el servidor de rutas, devolvemos la línea recta original
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        ns_v3 = {
            'sit': 'http://levelC/schema/3/situation',
            'com': 'http://levelC/schema/3/common',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension'
        }
        ns_v2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
        
        records = root.findall(".//sit:situationRecord", ns_v3) or root.findall(".//_0:situationRecord", ns_v2)
        
        for i, record in enumerate(records):
            curr_ns = ns_v3 if 'levelC' in record.tag else ns_v2
            pref = 'sit:' if curr_ns == ns_v3 else '_0:'
            
            description = []
            
            # --- 1. SEVERIDAD (Para el index.html) ---
            sev_elem = record.find(f"{pref}severity", curr_ns)
            sev_raw = sev_elem.text if sev_elem is not None and sev_elem.text else "unknown"
            # Importante: mantenemos el tag oculto para que tu JS pinte los colores
            description.append(f"")
            description.append(f"<b>Gravedad:</b> {translate(sev_raw)}")

            # --- 2. TEXTOS Y CARRETERA ---
            road = record.find(".//loc:roadName", ns_v3) or record.find(".//_0:roadNumber", ns_v2)
            if road is not None and road.text:
                description.append(f"<b>Carretera:</b> {road.text}")

            final_desc = "<br>".join(description)

            # --- 3. GEOMETRÍA INTELIGENTE ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # Intentar encontrar tramo lineal (V3 o V2)
            if curr_ns == ns_v3:
                f_pt = record.find(".//loc:from//loc:pointCoordinates", ns_v3)
                t_pt = record.find(".//loc:to//loc:pointCoordinates", ns_v3)
                if f_pt is not None and t_pt is not None:
                    lat_f, lon_f = f_pt.find("loc:latitude", ns_v3).text, f_pt.find("loc:longitude", ns_v3).text
                    lat_t, lon_t = t_pt.find("loc:latitude", ns_v3).text, t_pt.find("loc:longitude", ns_v3).text
            else:
                linear = record.find(".//_0:locationContainedInGroup", ns_v2)
                if linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""):
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", ns_v2)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", ns_v2)
                    if f_pt is not None and t_pt is not None:
                        lat_f, lon_f = f_pt.find("_0:latitude", ns_v2).text, f_pt.find("_0:longitude", ns_v2).text
                        lat_t, lon_t = t_pt.find("_0:latitude", ns_v2).text, t_pt.find("_0:longitude", ns_v2).text

            # Procesar Línea o Punto
            if lat_f and lat_t:
                # LLAMADA AL MOTOR DE RUTAS (Limitado a los primeros 60 para evitar bloqueos)
                if i < 60:
                    coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t)
                    time.sleep(0.1) # Respiro para el servidor
                else:
                    coords = [[float(lon_f), float(lat_f)], [float(lon_t), float(lat_t)]]
                
                all_incidents.append({
                    "type": "Feature", 
                    "properties": {"description": final_desc, "region": region_name}, 
                    "geometry": {"type": "LineString", "coordinates": coords}
                })
                lat_p, lon_p = lat_f, lon_f # Usar el inicio para la gota
            else:
                p_pt = record.find(".//loc:point//loc:pointCoordinates", ns_v3) or record.find(".//_0:pointCoordinates", ns_v2)
                lat_p, lon_p = (p_pt.find(".//latitude", curr_ns).text, p_pt.find(".//longitude", curr_ns).text) if p_pt is not None else (None, None)

            # Añadir el Punto (Gota con icono)
            if lat_p and lon_p:
                all_incidents.append({
                    "type": "Feature", 
                    "properties": {"description": final_desc, "region": region_name}, 
                    "geometry": {"type": "Point", "coordinates": [float(lon_p), float(lat_p)]}
                })

        print(f"OK: {region_name} finalizada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    final_results = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, final_results)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": final_results}, f, indent=2, ensure_ascii=False)
    print(f"\nTerminado: {len(final_results)} elementos con rutas inteligentes.")
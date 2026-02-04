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

def get_road_geometry(start_coords, end_coords):
    """
    Obtiene la polilínea real siguiendo la carretera usando OSRM.
    start_coords y end_coords son [lon, lat]
    """
    # Evitar trazados si los puntos son idénticos
    if start_coords == end_coords:
        return [start_coords]

    url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[0]},{start_coords[1]};{end_coords[0]},{end_coords[1]}?overview=full&geometries=geojson"
    
    try:
        # Añadimos un pequeño delay para ser respetuosos con la API gratuita
        time.sleep(0.1) 
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok':
                # Retorna la lista de coordenadas que forman la curva
                return data['routes'][0]['geometry']['coordinates']
    except Exception as e:
        print(f"  [!] No se pudo curvar la línea: {e}")
    
    # Si falla, devolvemos la línea recta original
    return [start_coords, end_coords]

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
        
        for record in records:
            curr_ns = ns_v3 if 'levelC' in record.tag else ns_v2
            pref = 'sit:' if curr_ns == ns_v3 else '_0:'
            
            description = []
            sev_elem = record.find(f"{pref}severity", curr_ns)
            sev_raw = sev_elem.text if sev_elem is not None and sev_elem.text else "unknown"
            description.append(f"<b>Gravedad:</b> {translate(sev_raw)}")

            time_elem = record.find(f"{pref}situationRecordCreationTime", curr_ns)
            if time_elem is not None:
                description.append(f"<b>Fecha:</b> {format_datetime(time_elem.text)}")

            tipo = "Incidente"
            for tag in ["roadOrCarriagewayOrLaneManagementType", "roadMaintenanceType", "obstructionType", "constructionWorkType"]:
                t_elem = record.find(f".//{pref}{tag}", curr_ns)
                if t_elem is not None and t_elem.text:
                    tipo = translate(t_elem.text)
                    break
            description.append(f"<b>Incidente:</b> {tipo}")

            road = record.find(".//loc:roadName", ns_v3) or record.find(".//_0:roadNumber", ns_v2)
            road_name = road.text if road is not None else "Desconocida"
            if road is not None: description.append(f"<b>Carretera:</b> {road_name}")

            final_desc = "<br>".join(description)

            # --- GEOMETRÍA ---
            lat_p, lon_p = None, None
            
            if curr_ns == ns_v3:
                f_pt = record.find(".//loc:from//loc:pointCoordinates", ns_v3)
                t_pt = record.find(".//loc:to//loc:pointCoordinates", ns_v3)
                if f_pt is not None and t_pt is not None:
                    p1 = [float(f_pt.find("loc:longitude", ns_v3).text), float(f_pt.find("loc:latitude", ns_v3).text)]
                    p2 = [float(t_pt.find("loc:longitude", ns_v3).text), float(t_pt.find("loc:latitude", ns_v3).text)]
                    
                    # LLAMADA A OSRM PARA CURVAR LA LÍNEA
                    coords = get_road_geometry(p1, p2)
                    
                    all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                    lat_p, lon_p = p1[1], p1[0]
                else:
                    p_pt = record.find(".//loc:point//loc:pointCoordinates", ns_v3)
                    if p_pt is not None:
                        lat_p, lon_p = p_pt.find("loc:latitude", ns_v3).text, p_pt.find("loc:longitude", ns_v3).text

            else: # Caso V2
                linear = record.find(".//_0:locationContainedInGroup", ns_v2)
                is_linear = linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or "")
                
                if is_linear:
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", ns_v2)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", ns_v2)
                    if f_pt is not None and t_pt is not None:
                        p1 = [float(f_pt.find("_0:longitude", ns_v2).text), float(f_pt.find("_0:latitude", ns_v2).text)]
                        p2 = [float(t_pt.find("_0:longitude", ns_v2).text), float(t_pt.find("_0:latitude", ns_v2).text)]
                        
                        # LLAMADA A OSRM PARA CURVAR LA LÍNEA
                        coords = get_road_geometry(p1, p2)
                        
                        all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                        lat_p, lon_p = p1[1], p1[0]
                else:
                    p_pt = record.find(".//_0:pointCoordinates", ns_v2)
                    if p_pt is not None:
                        lat_p, lon_p = p_pt.find("_0:latitude", ns_v2).text, p_pt.find("_0:longitude", ns_v2).text

            if lat_p and lon_p:
                all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "Point", "coordinates": [float(lon_p), float(lat_p)]}})

        print(f"OK: {region_name} finalizada.")
    except Exception as e:
        print(f"Error crítico en {region_name}: {e}")

if __name__ == "__main__":
    final_results = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, final_results)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": final_results}, f, indent=2, ensure_ascii=False)
    print(f"\nTerminado: {len(final_results)} elementos procesados.")
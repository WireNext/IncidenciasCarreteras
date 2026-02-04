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

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        # Namespaces
        ns_v3 = {
            'sit': 'http://levelC/schema/3/situation',
            'com': 'http://levelC/schema/3/common',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension'
        }
        ns_v2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
        
        # Intentamos encontrar registros de ambas versiones
        records = root.findall(".//sit:situationRecord", ns_v3) or root.findall(".//_0:situationRecord", ns_v2)
        
        for record in records:
            # Detectar qué namespace usar para este record específico
            curr_ns = ns_v3 if 'levelC' in record.tag else ns_v2
            pref = 'sit:' if curr_ns == ns_v3 else '_0:'
            
            description = []
            
            # --- 1. SEVERIDAD (COLORES) ---
            sev_elem = record.find(f"{pref}severity", curr_ns)
            sev_raw = sev_elem.text if sev_elem is not None and sev_elem.text else "unknown"
            description.append(f"")
            description.append(f"<b>Gravedad:</b> {translate(sev_raw)}")

            # --- 2. TEXTOS ---
            time_elem = record.find(f"{pref}situationRecordCreationTime", curr_ns)
            if time_elem is not None:
                description.append(f"<b>Fecha:</b> {format_datetime(time_elem.text)}")

            # Buscar Tipo (iteramos por posibles etiquetas)
            tipo = "Incidente"
            for tag in ["roadOrCarriagewayOrLaneManagementType", "roadMaintenanceType", "obstructionType", "constructionWorkType"]:
                t_elem = record.find(f".//{pref}{tag}", curr_ns)
                if t_elem is not None and t_elem.text:
                    tipo = translate(t_elem.text)
                    break
            description.append(f"<b>Incidente:</b> {tipo}")

            # Carretera y KM
            road = record.find(".//loc:roadName", ns_v3) or record.find(".//_0:roadNumber", ns_v2)
            if road is not None and road.text:
                description.append(f"<b>Carretera:</b> {road.text}")

            km = record.find(".//lse:kilometerPoint", ns_v3) or record.find(".//_0:referencePointDistance", ns_v2)
            if km is not None and km.text:
                val_km = km.text if curr_ns == ns_v3 else f"{float(km.text)/1000:.1f}"
                description.append(f"<b>KM:</b> {val_km}")

            final_desc = "<br>".join(description)

            # --- 3. GEOMETRÍA (Puntos y Líneas) ---
            # Caso V3 (DGT)
            if curr_ns == ns_v3:
                f_pt = record.find(".//loc:from//loc:pointCoordinates", ns_v3)
                t_pt = record.find(".//loc:to//loc:pointCoordinates", ns_v3)
                if f_pt is not None and t_pt is not None:
                    # Línea
                    coords = [[float(f_pt.find("loc:longitude", ns_v3).text), float(f_pt.find("loc:latitude", ns_v3).text)],
                              [float(t_pt.find("loc:longitude", ns_v3).text), float(t_pt.find("loc:latitude", ns_v3).text)]]
                    all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                    # Punto (gota)
                    lat_p, lon_p = f_pt.find("loc:latitude", ns_v3).text, f_pt.find("loc:longitude", ns_v3).text
                else:
                    p_pt = record.find(".//loc:point//loc:pointCoordinates", ns_v3)
                    lat_p, lon_p = (p_pt.find("loc:latitude", ns_v3).text, p_pt.find("loc:longitude", ns_v3).text) if p_pt is not None else (None, None)
            
            # Caso V2 (Cataluña/PV)
            else:
                linear = record.find(".//_0:locationContainedInGroup", ns_v2)
                if linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""):
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", ns_v2)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", ns_v2)
                    if f_pt is not None and t_pt is not None:
                        coords = [[float(f_pt.find("_0:longitude", ns_v2).text), float(f_pt.find("_0:latitude", ns_v2).text)],
                                  [float(t_pt.find("_0:longitude", ns_v2).text), float(t_pt.find("_0:latitude", ns_v2).text)]]
                        all_incidents.append({"type": "Feature", "properties": {"description": final_desc, "region": region_name}, "geometry": {"type": "LineString", "coordinates": coords}})
                        lat_p, lon_p = f_pt.find("_0:latitude", ns_v2).text, f_pt.find("_0:longitude", ns_v2).text
                    else: lat_p, lon_p = None, None
                else:
                    p_pt = record.find(".//_0:pointCoordinates", ns_v2)
                    lat_p, lon_p = (p_pt.find("_0:latitude", ns_v2).text, p_pt.find("_0:longitude", ns_v2).text) if p_pt is not None else (None, None)

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
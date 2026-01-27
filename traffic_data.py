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

# Traducciones de tipos de incidentes
INCIDENT_TYPE_TRANSLATIONS = {
    "damagedVehicle": "Vehículo Averiado",
    "roadClosed": "Corte Total",
    "roadworks": "Obras",
    "heavy": "Retención",
    "laneClosures": "Cierre de carril",
    "snowChainsMandatory": "Cadenas Obligatorias",
    "flooding": "Inundación",
    "fog": "Niebla"
}

def translate_incident_type(value):
    return INCIDENT_TYPE_TRANSLATIONS.get(value, value)

def format_datetime(datetime_str):
    try:
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%Y - %H:%M:%S")
    except:
        return datetime_str

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Descargando {region_name}...")
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        # Detectar si es V3 (DGT nueva) o V2 (Tradicional)
        is_v3 = 'http://levelC/schema/3' in root.tag or 'http://datex2.eu/schema/3' in root.tag
        
        ns_v3 = {
            'sit': 'http://levelC/schema/3/situation',
            'com': 'http://levelC/schema/3/common',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension'
        }
        ns_v2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
        ns = ns_v3 if is_v3 else ns_v2

        record_path = ".//sit:situationRecord" if is_v3 else ".//_0:situationRecord"
        
        for record in root.findall(record_path, ns):
            description = []
            
            # --- 1. EXTRAER GRAVEDAD (LÓGICA DE COLORES) ---
            # Buscamos la etiqueta 'severity'
            severity_elem = record.find("sit:severity", ns) if is_v3 else record.find("_0:severity", ns)
            severity_val = severity_elem.text if severity_elem is not None else "unknown"
            # Lo añadimos oculto o visible para que el JS lo lea
            description.append(f"")
            description.append(f"<b>Severidad:</b> {severity_val.capitalize()}")

            # --- 2. EXTRAER DATOS DE TEXTO ---
            time_elem = record.find("sit:situationRecordCreationTime", ns) if is_v3 else record.find("_0:situationRecordCreationTime", ns)
            if time_elem is not None:
                description.append(f"<b>Fecha:</b> {format_datetime(time_elem.text)}")

            # Tipo de incidente
            type_tags = ["sit:roadOrCarriagewayOrLaneManagementType", "sit:roadMaintenanceType", "sit:obstructionType"] if is_v3 else ["_0:obstructionType", "_0:constructionWorkType"]
            for tag in type_tags:
                t = record.find(f".//{tag}", ns)
                if t is not None:
                    description.append(f"<b>Tipo:</b> {translate_incident_type(t.text)}")
                    break

            # Carretera y KM
            road = record.find(".//loc:roadName", ns) if is_v3 else record.find(".//_0:roadNumber", ns)
            if road is not None:
                description.append(f"<b>Carretera:</b> {road.text}")

            km = record.find(".//lse:kilometerPoint", ns) if is_v3 else record.find(".//_0:referencePointDistance", ns)
            if km is not None:
                val_km = km.text if is_v3 else f"{float(km.text)/1000:.1f}"
                description.append(f"<b>KM:</b> {val_km}")

            final_desc = "<br>".join(description)

            # --- 3. LÓGICA DE GEOMETRÍA (PUNTOS Y LÍNEAS) ---
            lat, lon = None, None
            
            if is_v3:
                # Caso DGT: Buscar en 'from' (inicio de obra) o 'point'
                point = record.find(".//loc:from//loc:pointCoordinates", ns) or record.find(".//loc:point//loc:pointCoordinates", ns)
                if point is not None:
                    lat, lon = point.find("loc:latitude", ns).text, point.find("loc:longitude", ns).text
            else:
                # Caso Cataluña/PV: Buscar lineal primero
                linear = record.find(".//_0:locationContainedInGroup", ns)
                if linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""):
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", ns)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", ns)
                    if f_pt is not None and t_pt is not None:
                        # Añadir línea simplificada para no saturar
                        coords = [[float(f_pt.find("_0:longitude", ns).text), float(f_pt.find("_0:latitude", ns).text)],
                                  [float(t_pt.find("_0:longitude", ns).text), float(t_pt.find("_0:latitude", ns).text)]]
                        all_incidents.append({
                            "type": "Feature",
                            "properties": {"description": final_desc, "region": region_name},
                            "geometry": {"type": "LineString", "coordinates": coords}
                        })
                        # El punto para la "gota" será el de inicio
                        lat, lon = f_pt.find("_0:latitude", ns).text, f_pt.find("_0:longitude", ns).text
                
                if lat is None: # Si no fue lineal, buscar punto simple
                    p_pt = record.find(".//_0:pointCoordinates", ns)
                    if p_pt is not None:
                        lat, lon = p_pt.find("_0:latitude", ns).text, p_pt.find("_0:longitude", ns).text

            if lat and lon:
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}
                })

        print(f"OK: {region_name} procesada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    results = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, results)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": results}, f, indent=2, ensure_ascii=False)
    print(f"Éxito: {len(results)} elementos guardados.")
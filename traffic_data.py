import xml.etree.ElementTree as ET
import requests
import json
from datetime import datetime

# --- CONFIGURACIÓN ---
REGIONS = {
    "Cataluña": "http://infocar.dgt.es/datex2/sct/SituationPublication/all/content.xml",
    "País Vasco": "http://infocar.dgt.es/datex2/dt-gv/SituationPublication/all/content.xml",
    "Resto España": "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml"
}

# Diccionario de traducciones
INCIDENT_TYPE_TRANSLATIONS = {
    "roadClosed": "Corte Total",
    "roadworks": "Obras",
    "laneClosures": "Cierre de carril",
    "singleAlternateLineTraffic": "Tráfico alterno",
    "heavy": "Retención",
    "brokenDownVehicle": "Vehículo Averiado",
    "both": "Ambos Sentidos",
    "negative": "Decreciente",
    "positive": "Creciente"
}

def translate_incident_type(value):
    return INCIDENT_TYPE_TRANSLATIONS.get(value, value)

def format_datetime(datetime_str):
    try:
        # Limpiar formatos con milisegundos y offsets
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

        # Detectar versión
        is_v3 = 'http://levelC/schema/3' in root.tag or 'http://datex2.eu/schema/3' in root.tag
        
        # Definición de Namespaces para V3 (DGT) basado en tu XML
        ns_v3 = {
            'sit': 'http://levelC/schema/3/situation',
            'com': 'http://levelC/schema/3/common',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension'
        }
        # Namespace para V2 (Cataluña/País Vasco)
        ns_v2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}

        ns = ns_v3 if is_v3 else ns_v2
        record_path = ".//sit:situationRecord" if is_v3 else ".//_0:situationRecord"
        records = root.findall(record_path, ns)

        for record in records:
            description_lines = []
            lat, lon = None, None

            if is_v3:
                # 1. Información de Texto
                time_val = record.find("sit:situationRecordCreationTime", ns)
                if time_val is not None:
                    description_lines.append(f"<b>Fecha:</b> {format_datetime(time_val.text)}")

                # Buscar tipo de incidente en varias etiquetas posibles de v3
                type_tag = record.find(".//sit:roadOrCarriagewayOrLaneManagementType", ns) or \
                           record.find(".//sit:roadMaintenanceType", ns) or \
                           record.find(".//sit:obstructionType", ns)
                if type_tag is not None:
                    description_lines.append(f"<b>Tipo:</b> {translate_incident_type(type_tag.text)}")

                road = record.find(".//loc:roadName", ns)
                if road is not None:
                    description_lines.append(f"<b>Carretera:</b> {road.text}")

                km = record.find(".//lse:kilometerPoint", ns)
                if km is not None:
                    description_lines.append(f"<b>KM:</b> {km.text}")

                # 2. Coordenadas (Buscamos en loc:from o loc:point)
                point = record.find(".//loc:from//loc:pointCoordinates", ns) or \
                        record.find(".//loc:point//loc:pointCoordinates", ns)
                
                if point is not None:
                    lat_el = point.find("loc:latitude", ns)
                    lon_el = point.find("loc:longitude", ns)
                    if lat_el is not None and lon_el is not None:
                        lat, lon = float(lat_el.text), float(lon_el.text)
            else:
                # --- Lógica V2 ---
                time_val = record.find("_0:situationRecordCreationTime", ns)
                if time_val is not None:
                    description_lines.append(f"<b>Fecha:</b> {format_datetime(time_val.text)}")
                
                road = record.find(".//_0:roadNumber", ns)
                if road is not None:
                    description_lines.append(f"<b>Carretera:</b> {road.text}")

                lat_el = record.find(".//_0:latitude", ns)
                lon_el = record.find(".//_0:longitude", ns)
                if lat_el is not None and lon_el is not None:
                    lat, lon = float(lat_el.text), float(lon_el.text)

            if lat and lon:
                all_incidents.append({
                    "type": "Feature",
                    "properties": {
                        "description": "<br>".join(description_lines),
                        "region": region_name
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]}
                })

        print(f"OK: {len(records)} procesados en {region_name}.")

    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    combined_incidents = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, combined_incidents)

    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": combined_incidents}, f, indent=2, ensure_ascii=False)

    print(f"\nÉxito: Generados {len(combined_incidents)} incidentes totales.")
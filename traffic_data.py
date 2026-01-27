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

# Namespaces para ambas versiones
NS_V2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
NS_V3 = {
    'com': 'http://datex2.eu/schema/3/common',
    'sit': 'http://datex2.eu/schema/3/situation',
    'loc': 'http://datex2.eu/schema/3/locationReferencing'
}

INCIDENT_TYPE_TRANSLATIONS = {
 "damagedVehicle": "Vehículo Averiado",
    "roadClosed": "Corte Total",
    "restrictions": "Restricciones",
    "narrowLanes": "Carriles Estrechos",
    "flooding": "Inundación",
    "vehicleStuck": "Vehiculo Parado",
    "both": "Ambos Sentidos",
    "negative": "Decreciente",
    "positive": "Creciente",
    "useOfSpecifiedLaneAllowed": "Uso especifico de carril",
    "useUnderSpecifiedRestrictions": "Uso con restricciones",
    "congested": "Congestionada",
    "freeFlow": "Sin retención",
    "constructionWork": "Obras",
    "impossible": "Carretera Cortada",
    "objectOnTheRoad": "Objeto en Calzada",
    "heavy": "Retención",
    "vehicleOnFire": "Vehiculo en llamas",
    "intermittentShortTermClosures": "Cortes intermitentes",
    "laneClosures": "Cierre de algún carril",
    "rockfalls": "Caida de piedras",
    "trafficContolInOperation": "Itinerario alternativo",
    "laneOrCarriagewayClosed": "Arcen cerrado",
    "snowploughsInUse": "Quitanieves en la via",
    "snowfall": "Nieve en la via",
    "snowChainsMandatory": "Uso obligatorio de cadenas",
    "rain": "Lluvia",
    "MaintenanceWorks": "Trabajos de mantenimiento",
    "fog": "Niebla",
    "strongWinds": "Fuertes vientos",
    "spillageOnTheRoad": "Derrame en la carretera"
}

def translate_incident_type(value):
    return INCIDENT_TYPE_TRANSLATIONS.get(value, value)

def format_datetime(datetime_str):
    try:
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%Y - %H:%M:%S")
    except Exception:
        return datetime_str

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Descargando {region_name}...")
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        is_v3 = 'http://datex2.eu/schema/3' in root.tag
        
        # Namespaces exactos del fragmento que has enviado
        NS_V3 = {
            'sit': 'http://levelC/schema/3/situation',
            'com': 'http://levelC/schema/3/common',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
        }
        NS_V2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
        
        ns = NS_V3 if is_v3 else NS_V2
        record_path = ".//sit:situationRecord" if is_v3 else ".//_0:situationRecord"
        records = root.findall(record_path, ns)

        for record in records:
            description_lines = []
            lat, lon = None, None
            
            if is_v3:
                # 1. Extraer Datos de Texto
                # Fecha
                crea_time = record.find("sit:situationRecordCreationTime", ns)
                if crea_time is not None:
                    description_lines.append(f"<b>Fecha:</b> {format_datetime(crea_time.text)}")
                
                # Tipo de Incidente (puede estar en varios sitios)
                for tag in ["sit:roadOrCarriagewayOrLaneManagementType", "sit:obstructionType", "sit:constructionWorkType"]:
                    type_elem = record.find(f".//{tag}", ns)
                    if type_elem is not None:
                        description_lines.append(f"<b>Tipo:</b> {translate_incident_type(type_elem.text)}")
                        break
                
                # Carretera
                road = record.find(".//loc:roadName", ns)
                if road is not None:
                    description_lines.append(f"<b>Carretera:</b> {road.text}")

                # Kilómetro (está en lse:kilometerPoint dentro de loc:from o loc:point)
                km = record.find(".//lse:kilometerPoint", ns)
                if km is not None:
                    description_lines.append(f"<b>KM:</b> {km.text}")

                # 2. Extraer Coordenadas (Priorizamos 'from' en lineales o 'point' en fijos)
                # Buscamos primero en un punto simple, si no en el inicio de un tramo
                point_coord = record.find(".//loc:from//loc:pointCoordinates", ns) or \
                              record.find(".//loc:point//loc:pointCoordinates", ns)
                
                if point_coord is not None:
                    lat_elem = point_coord.find("loc:latitude", ns)
                    lon_elem = point_coord.find("loc:longitude", ns)
                    if lat_elem is not None and lon_elem is not None:
                        lat, lon = float(lat_elem.text), float(lon_elem.text)

            else:
                # --- Lógica antigua para Cataluña / País Vasco ---
                fields = [
                    ("_0:situationRecordCreationTime", "Fecha", format_datetime),
                    (".//_0:roadNumber", "Carretera", None),
                    (".//_0:referencePointDistance", "KM", lambda x: f"{float(x)/1000:.1f}")
                ]
                for path, label, func in fields:
                    elem = record.find(path, ns)
                    if elem is not None:
                        val = func(elem.text) if func else elem.text
                        description_lines.append(f"<b>{label}:</b> {val}")
                
                lat_elem = record.find(".//_0:latitude", ns)
                lon_elem = record.find(".//_0:longitude", ns)
                if lat_elem is not None and lon_elem is not None:
                    lat, lon = float(lat_elem.text), float(lon_elem.text)

            # Guardar si tenemos coordenadas
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

# --- INICIO DEL PROGRAMA ---
if __name__ == "__main__":
    combined_incidents = []
    
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, combined_incidents)

    # Guardar el resultado final en el GeoJSON que lee tu index.html
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({
            "type": "FeatureCollection", 
            "features": combined_incidents
        }, f, indent=2, ensure_ascii=False)

    print(f"\nÉxito: Archivo 'traffic_data.geojson' generado con {len(combined_incidents)} incidentes.")
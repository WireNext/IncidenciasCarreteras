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

        # Detectar si es el formato nuevo v3 (DGT) o el viejo v2 (Resto)
        is_v3 = 'http://datex2.eu/schema/3' in root.tag
        ns = NS_V3 if is_v3 else NS_V2
        
        # Ruta para encontrar los registros de incidentes
        record_path = ".//sit:situationRecord" if is_v3 else ".//_0:situationRecord"
        records = root.findall(record_path, ns)

        for record in records:
            description_lines = []
            
            # --- DEFINICIÓN DE CAMPOS SEGÚN LA VERSIÓN ---
            if is_v3:
                fields = [
                    ("sit:situationRecordCreationTime", "Fecha de Creación", format_datetime),
                    (".//sit:obstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//sit:environmentalObstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//sit:vehicleObstructionType", "Tipo de Incidente", translate_incident_type),
                    (".//sit:constructionWorkType", "Tipo de Incidente", translate_incident_type),
                    (".//sit:complianceOption", "Aviso", translate_incident_type),
                    (".//sit:impactOnTraffic", "Impacto", translate_incident_type),
                    (".//loc:roadName", "Carretera", None),
                    (".//loc:mileage", "Punto Kilométrico", lambda x: f"{x} km"),
                ]
            else:
                fields = [
                    ("_0:situationRecordCreationTime", "Fecha de Creación", format_datetime),
                    (".//_0:obstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:environmentalObstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:vehicleObstructionType", "Tipo de Incidente", translate_incident_type),
                    (".//_0:constructionWorkType", "Tipo de Incidente", translate_incident_type),
                    (".//_0:directionRelative", "Dirección", translate_incident_type),
                    (".//_0:networkManagementType", "Aviso", translate_incident_type),
                    (".//_0:impactOnTraffic", "Impacto", translate_incident_type),
                    (".//_0:roadNumber", "Carretera", None),
                    (".//_0:referencePointDistance", "Punto Kilométrico", lambda x: f"{float(x)/1000:.1f} km"),
                ]

            # Extraer los datos para la descripción HTML
            for path, label, func in fields:
                elem = record.find(path, ns)
                if elem is not None and elem.text:
                    val = func(elem.text) if func else elem.text
                    description_lines.append(f"<b>{label}:</b> {val}")

            final_description = "<br>".join(description_lines)

            # --- EXTRACCIÓN DE COORDENADAS ---
            # En v3 están en loc:latitude, en v2 en _0:latitude
            lat_path = ".//loc:latitude" if is_v3 else ".//_0:latitude"
            lon_path = ".//loc:longitude" if is_v3 else ".//_0:longitude"
            
            lat_elem = record.find(lat_path, ns)
            lon_elem = record.find(lon_path, ns)

            if lat_elem is not None and lon_elem is not None:
                all_incidents.append({
                    "type": "Feature",
                    "properties": {
                        "description": final_description,
                        "region": region_name
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lon_elem.text), float(lat_elem.text)]
                    }
                })

        print(f"OK: {len(records)} incidentes procesados.")

    except Exception as e:
        print(f"Error procesando {region_name}: {e}")

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
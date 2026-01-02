import xml.etree.ElementTree as ET
import requests
import json
from datetime import datetime
import time

# Lista de regiones con sus respectivas URLs de archivos XML
REGIONS = {
    "Cataluña": "http://infocar.dgt.es/datex2/sct/SituationPublication/all/content.xml",
    "País Vasco": "http://infocar.dgt.es/datex2/dt-gv/SituationPublication/all/content.xml",
    "Resto España": "http://infocar.dgt.es/datex2/dgt/SituationPublication/all/content.xml"
}

# Definir el espacio de nombres para el XML
NS = {
    '_0': 'http://datex2.eu/schema/1_0/1_0',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
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
        response = requests.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        for situation in root.findall(".//_0:situation", NS):
            situation_record = situation.find(".//_0:situationRecord", NS)
            if situation_record is not None:
                description = []
                
                # --- EXTRACCIÓN DE DATOS PARA DESCRIPCIÓN ---
                fields = [
                    (".//_0:situationRecordCreationTime", "Fecha de Creación", format_datetime),
                    (".//_0:obstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:environmentalObstructionType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:vehicleObstructionType", "Tipo de Incidente", translate_incident_type),
                    (".//_0:constructionWorkType", "Tipo de Incidente", translate_incident_type),
                    (".//_0:directionRelative", "Dirección", translate_incident_type),
                    (".//_0:networkManagementType", "Aviso", translate_incident_type),
                    (".//_0:impactOnTraffic", "Impacto", translate_incident_type),
                    (".//_0:roadNumber", "Carretera", None),
                    (".//_0:poorEnvironmentType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:roadMaintenanceType", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:equipmentRequirement", "Tipo de Obstrucción", translate_incident_type),
                    (".//_0:poorEnvironmentType", "Tipo de Obstrucción", translate_incident_type),
                ]

                for path, label, func in fields:
                    elem = situation_record.find(path, NS)
                    if elem is not None and elem.text:
                        val = func(elem.text) if func else elem.text
                        description.append(f"<b>{label}:</b> {val}")

                pk = situation_record.find(".//_0:referencePointDistance", NS)
                if pk is not None:
                    description.append(f"<b>Punto Kilométrico:</b> {float(pk.text) / 1000:.1f} km")

                final_description = "<br>".join(description)
                geometry_found = False

                # --- LÓGICA DE GEOMETRÍA ---
                
                # 1. Intentar Tramo Lineal (Línea + Gota de aviso)
                linear_loc = situation_record.find(".//_0:locationContainedInGroup", NS)
                if linear_loc is not None:
                    xsi_type = linear_loc.get("{http://www.w3.org/2001/XMLSchema-instance}type")
                    if xsi_type and "_0:Linear" in xsi_type:
                        from_pt = linear_loc.find(".//_0:from//_0:pointCoordinates", NS)
                        to_pt = linear_loc.find(".//_0:to//_0:pointCoordinates", NS)
                        
                        if from_pt is not None and to_pt is not None:
                            geometry_found = True
                            lon_f, lat_f = from_pt.find("_0:longitude", NS).text, from_pt.find("_0:latitude", NS).text
                            lon_t, lat_t = to_pt.find("_0:longitude", NS).text, to_pt.find("_0:latitude", NS).text
                            
                            osrm_url = f"http://router.project-osrm.org/route/v1/driving/{lon_f},{lat_f};{lon_t},{lat_t}?overview=full&geometries=geojson"
                            try:
                                r = requests.get(osrm_url, timeout=5)
                                data = r.json()
                                if data.get("routes"):
                                    full_geometry = data["routes"][0]["geometry"]
                                    
                                    # AÑADIMOS LA LÍNEA
                                    all_incidents.append({
                                        "type": "Feature",
                                        "properties": {"description": final_description},
                                        "geometry": full_geometry
                                    })

                                    # AÑADIMOS LA GOTA (en el punto medio de la línea calculada)
                                    coords = full_geometry["coordinates"]
                                    mid_point = coords[len(coords)//2]
                                    all_incidents.append({
                                        "type": "Feature",
                                        "properties": {"description": final_description},
                                        "geometry": {"type": "Point", "coordinates": mid_point}
                                    })
                                else:
                                    # Fallback a línea recta si falla OSRM
                                    straight_line = [[float(lon_f), float(lat_f)], [float(lon_t), float(lat_t)]]
                                    all_incidents.append({
                                        "type": "Feature",
                                        "properties": {"description": final_description},
                                        "geometry": {"type": "LineString", "coordinates": straight_line}
                                    })
                                time.sleep(0.5)
                            except:
                                pass

                # 2. Si no es lineal, añadir como Punto único normal
                if not geometry_found:
                    point_loc = situation_record.find(".//_0:pointCoordinates", NS)
                    if point_loc is not None:
                        lat = point_loc.find("_0:latitude", NS)
                        lon = point_loc.find("_0:longitude", NS)
                        if lat is not None and lon is not None:
                            all_incidents.append({
                                "type": "Feature",
                                "properties": {"description": final_description},
                                "geometry": {"type": "Point", "coordinates": [float(lon.text), float(lat.text)]}
                            })

    except Exception as e:
        print(f"Error procesando {region_name}: {e}")

all_incidents = []
for name, url in REGIONS.items():
    print(f"Procesando: {name}")
    process_xml_from_url(url, name, all_incidents)

with open("traffic_data.geojson", "w", encoding='utf-8') as f:
    json.dump({"type": "FeatureCollection", "features": all_incidents}, f, indent=2, ensure_ascii=False)

print("GeoJSON generado con éxito.")
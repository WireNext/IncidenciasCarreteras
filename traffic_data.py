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

# Namespaces para soportar V2 y V3
NS = {
    'sit': 'http://levelC/schema/3/situation',
    'com': 'http://levelC/schema/3/common',
    'loc': 'http://levelC/schema/3/locationReferencing',
    'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
    '_0': 'http://datex2.eu/schema/1_0/1_0'
}

TRANSLATIONS = {
    "damagedVehicle": "Vehículo Averiado",
    "roadClosed": "Corte Total",
    "restrictions": "Restricciones",
    "narrowLanes": "Carriles Estrechos",
    "flooding": "Inundación",
    "vehicleStuck": "Vehículo Parado",
    "both": "Ambos Sentidos",
    "negative": "Decreciente",
    "positive": "Creciente",
    "useOfSpecifiedLaneAllowed": "Uso específico de carril",
    "useUnderSpecifiedRestrictions": "Uso con restricciones",
    "congested": "Congestionada",
    "freeFlow": "Sin retención",
    "constructionWork": "Obras",
    "impossible": "Carretera Cortada",
    "objectOnTheRoad": "Objeto en Calzada",
    "heavy": "Retención",
    "vehicleOnFire": "Vehículo en llamas",
    "intermittentShortTermClosures": "Cortes intermitentes",
    "laneClosures": "Cierre de algún carril",
    "rockfalls": "Caída de piedras",
    "trafficContolInOperation": "Itinerario alternativo",
    "laneOrCarriagewayClosed": "Arcén cerrado",
    "snowploughsInUse": "Quitanieves en la vía",
    "snowfall": "Nieve en la vía",
    "snowChainsMandatory": "Uso obligatorio de cadenas",
    "rain": "Lluvia",
    "MaintenanceWorks": "Trabajos de mantenimiento",
    "fog": "Niebla",
    "strongWinds": "Fuertes vientos",
    "spillageOnTheRoad": "Derrame en la carretera",
    "highest": "Negro (Corte Total)",
    "high": "Rojo (Grave)",
    "medium": "Naranja (Moderado)",
    "low": "Amarillo (Leve)"
}

def translate(value):
    return TRANSLATIONS.get(value, value)

def format_datetime(datetime_str):
    try:
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%Y - %H:%M:%S")
    except:
        return datetime_str

def get_osrm_geometry(p1, p2):
    """ Obtiene la polilínea real de la carretera entre dos puntos [lon, lat] """
    url = f"http://router.project-osrm.org/route/v1/driving/{p1[0]},{p1[1]};{p2[0]},{p2[1]}?overview=full&geometries=geojson"
    try:
        time.sleep(0.4) # Respetar rate limit de OSRM
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("routes"):
            return data["routes"][0]["geometry"]
    except:
        pass
    return {"type": "LineString", "coordinates": [p1, p2]}

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        # Buscamos records tanto en V2 como en V3
        records = root.findall(".//sit:situationRecord", NS) or root.findall(".//_0:situationRecord", NS)
        
        for record in records:
            is_v3 = 'levelC' in record.tag
            pref = 'sit:' if is_v3 else '_0:'
            
            desc_parts = []
            
            # --- 1. SEVERIDAD ---
            sev = record.find(f"{pref}severity", NS)
            if sev is not None:
                desc_parts.append(f"<b>Gravedad:</b> {translate(sev.text)}")

            # --- 2. TIEMPO ---
            time_e = record.find(f"{pref}situationRecordCreationTime", NS)
            if time_e is not None:
                desc_parts.append(f"<b>Fecha:</b> {format_datetime(time_e.text)}")

            # --- 3. TIPO DE INCIDENTE (Múltiples etiquetas) ---
            tags = ["obstructionType", "environmentalObstructionType", "vehicleObstructionType", 
                    "constructionWorkType", "roadMaintenanceType", "poorEnvironmentType"]
            for tag in tags:
                elem = record.find(f".//{pref}{tag}", NS)
                if elem is not None and elem.text:
                    desc_parts.append(f"<b>Tipo:</b> {translate(elem.text)}")
                    break

            # --- 4. CARRETERA Y KM ---
            road = record.find(".//loc:roadName", NS) if is_v3 else record.find(".//_0:roadNumber", NS)
            if road is not None and road.text:
                desc_parts.append(f"<b>Carretera:</b> {road.text}")

            km = record.find(".//lse:kilometerPoint", NS) if is_v3 else record.find(".//_0:referencePointDistance", NS)
            if km is not None and km.text:
                val_km = km.text if is_v3 else f"{float(km.text)/1000:.1f}"
                desc_parts.append(f"<b>KM:</b> {val_km}")

            final_desc = "<br>".join(desc_parts)

            # --- 5. GEOMETRÍA ---
            geometry_added = False
            
            # Intento de Tramo Lineal
            f_pt, t_pt = None, None
            if is_v3:
                f_pt = record.find(".//loc:from//loc:pointCoordinates", NS)
                t_pt = record.find(".//loc:to//loc:pointCoordinates", NS)
            else:
                linear = record.find(".//_0:locationContainedInGroup", NS)
                if linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""):
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", NS)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", NS)

            if f_pt is not None and t_pt is not None:
                p1 = [float(f_pt.find(f"{'loc' if is_v3 else '_0'}:longitude", NS).text), 
                      float(f_pt.find(f"{'loc' if is_v3 else '_0'}:latitude", NS).text)]
                p2 = [float(t_pt.find(f"{'loc' if is_v3 else '_0'}:longitude", NS).text), 
                      float(t_pt.find(f"{'loc' if is_v3 else '_0'}:latitude", NS).text)]
                
                # Curvar línea con OSRM
                road_geom = get_osrm_geometry(p1, p2)
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": road_geom
                })
                # Punto para la "gota" de aviso (usamos el inicio)
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "Point", "coordinates": p1}
                })
                geometry_added = True

            # Si no hubo línea, buscar punto único
            if not geometry_added:
                p_pt = record.find(f".//{'loc:point//loc' if is_v3 else '_0'}:pointCoordinates", NS)
                if p_pt is not None:
                    lon = p_pt.find(f"{'loc' if is_v3 else '_0'}:longitude", NS).text
                    lat = p_pt.find(f"{'loc' if is_v3 else '_0'}:latitude", NS).text
                    all_incidents.append({
                        "type": "Feature",
                        "properties": {"description": final_desc, "region": region_name},
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}
                    })

        print(f"OK: {region_name} terminada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    final_data = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, final_data)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": final_data}, f, indent=2, ensure_ascii=False)
    
    print(f"\nProceso finalizado. {len(final_data)} elementos guardados en traffic_data.geojson")
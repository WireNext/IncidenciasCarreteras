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

# Diccionario de traducciones extendido
TRANSLATIONS = {
    # Gravedad
    "highest": "Negro (Corte Total)",
    "high": "Rojo (Grave)",
    "medium": "Naranja (Moderado)",
    "low": "Amarillo (Leve)",
    "unknown": "Desconocido",
    # Tipos
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
            
            # --- 1. SEVERIDAD (Para colores y texto) ---
            sev_elem = record.find("sit:severity", ns) if is_v3 else record.find("_0:severity", ns)
            sev_raw = sev_elem.text if sev_elem is not None else "unknown"
            
            # El truco: Ponemos el raw en un comentario oculto para el JS y el traducido para el humano
            description.append(f"")
            description.append(f"<b>Gravedad:</b> {translate(sev_raw)}")

            # --- 2. DATOS GENERALES ---
            time_elem = record.find("sit:situationRecordCreationTime", ns) if is_v3 else record.find("_0:situationRecordCreationTime", ns)
            if time_elem is not None:
                description.append(f"<b>Fecha:</b> {format_datetime(time_elem.text)}")

            # Buscar tipo de incidente
            found_type = False
            for tag in ["sit:roadOrCarriagewayOrLaneManagementType", "sit:roadMaintenanceType", "sit:obstructionType", "_0:obstructionType"]:
                t = record.find(f".//{tag}", ns)
                if t is not None:
                    description.append(f"<b>Incidente:</b> {translate(t.text)}")
                    found_type = True
                    break
            
            # Carretera y Punto Kilométrico
            road = record.find(".//loc:roadName", ns) if is_v3 else record.find(".//_0:roadNumber", ns)
            if road is not None:
                description.append(f"<b>Carretera:</b> {road.text}")

            km = record.find(".//lse:kilometerPoint", ns) if is_v3 else record.find(".//_0:referencePointDistance", ns)
            if km is not None:
                val_km = km.text if is_v3 else f"{float(km.text)/1000:.1f}"
                description.append(f"<b>Punto KM:</b> {val_km}")

            final_desc = "<br>".join(description)

            # --- 3. GEOMETRÍA (Líneas para tramos y Puntos para iconos) ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # Intentar buscar tramo (Lineal)
            if is_v3:
                from_pt = record.find(".//loc:from//loc:pointCoordinates", ns)
                to_pt = record.find(".//loc:to//loc:pointCoordinates", ns)
                if from_pt is not None and to_pt is not None:
                    lat_f, lon_f = from_pt.find("loc:latitude", ns).text, from_pt.find("loc:longitude", ns).text
                    lat_t, lon_t = to_pt.find("loc:latitude", ns).text, to_pt.find("loc:longitude", ns).text
            else:
                linear = record.find(".//_0:locationContainedInGroup", ns)
                if linear is not None and "_0:Linear" in (linear.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""):
                    f_pt = linear.find(".//_0:from//_0:pointCoordinates", ns)
                    t_pt = linear.find(".//_0:to//_0:pointCoordinates", ns)
                    if f_pt is not None and t_pt is not None:
                        lat_f, lon_f = f_pt.find("_0:latitude", ns).text, f_pt.find("_0:longitude", ns).text
                        lat_t, lon_t = t_pt.find("_0:latitude", ns).text, t_pt.find("_0:longitude", ns).text

            # Si tenemos dos puntos, dibujamos la LÍNEA
            if lat_f and lat_t:
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {
                        "type": "LineString", 
                        "coordinates": [[float(lon_f), float(lat_f)], [float(lon_t), float(lat_t)]]
                    }
                })
                # Usamos el primer punto para poner la gota/icono
                lat_icon, lon_icon = lat_f, lon_f
            else:
                # Si no es lineal, buscamos un punto único
                p_pt = record.find(".//loc:point//loc:pointCoordinates", ns) if is_v3 else record.find(".//_0:pointCoordinates", ns)
                if p_pt is not None:
                    lat_icon, lon_icon = p_pt.find(".//latitude", ns).text if is_v3 else p_pt.find("_0:latitude", ns).text, \
                                         p_pt.find(".//longitude", ns).text if is_v3 else p_pt.find("_0:longitude", ns).text
                else:
                    lat_icon, lon_icon = None, None

            # Añadir el PUNTO (la gota con el icono)
            if lat_icon and lon_icon:
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "Point", "coordinates": [float(lon_icon), float(lat_icon)]}
                })

        print(f"OK: {region_name} terminada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    total_data = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, total_data)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": total_data}, f, indent=2, ensure_ascii=False)
    print(f"\nÉxito: Se han generado {len(total_data)} elementos (puntos y líneas).")
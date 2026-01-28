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

def get_road_geometry(lon1, lat1, lon2, lat2):
    """Consulta a OSRM para obtener la línea curva real de la carretera"""
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("routes"):
            return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    # Si falla, devuelve la línea recta original
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=25)
        root = ET.fromstring(response.content)

        ns_v3 = {'sit': 'http://levelC/schema/3/situation', 'loc': 'http://levelC/schema/3/locationReferencing', 'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension'}
        ns_v2 = {'_0': 'http://datex2.eu/schema/1_0/1_0'}
        
        records = root.findall(".//sit:situationRecord", ns_v3) or root.findall(".//_0:situationRecord", ns_v2)
        
        for record in records:
            curr_ns = ns_v3 if 'levelC' in record.tag else ns_v2
            pref = 'sit:' if curr_ns == ns_v3 else '_0:'
            
            # --- DATOS Y SEVERIDAD ---
            sev_elem = record.find(f"{pref}severity", curr_ns)
            sev_raw = sev_elem.text if sev_elem is not None else "unknown"
            desc = [f"", f"<b>Gravedad:</b> {TRANSLATIONS.get(sev_raw, sev_raw)}"]
            
            road = record.find(".//loc:roadName", ns_v3) or record.find(".//_0:roadNumber", ns_v2)
            if road is not None: desc.append(f"<b>Carretera:</b> {road.text}")

            final_desc = "<br>".join(desc)

            # --- GEOMETRÍA CON CURVAS ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # Buscar coordenadas de inicio y fin
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

            if lat_f and lat_t:
                # LLAMADA A OSRM PARA CURVAS
                curved_coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t)
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "LineString", "coordinates": curved_coords}
                })
                # Añadir punto para el icono
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "Point", "coordinates": [float(lon_f), float(lat_f)]}
                })
                time.sleep(0.1) # Evitar saturar el servidor de rutas
            else:
                # Si es un solo punto...
                p_pt = record.find(".//loc:point//loc:pointCoordinates", ns_v3) or record.find(".//_0:pointCoordinates", ns_v2)
                if p_pt is not None:
                    lat = p_pt.find(".//latitude", curr_ns).text if curr_ns == ns_v3 else p_pt.find("_0:latitude", ns_v2).text
                    lon = p_pt.find(".//longitude", curr_ns).text if curr_ns == ns_v3 else p_pt.find("_0:longitude", ns_v2).text
                    all_incidents.append({
                        "type": "Feature",
                        "properties": {"description": final_desc, "region": region_name},
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}
                    })

        print(f"OK: {region_name} finalizada.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    final_data = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, final_data)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": final_data}, f, indent=2, ensure_ascii=False)
    print(f"Terminado. {len(final_data)} elementos guardados con rutas inteligentes.")
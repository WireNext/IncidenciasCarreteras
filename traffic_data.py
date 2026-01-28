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
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("routes"):
            return data["routes"][0]["geometry"]["coordinates"]
    except:
        pass
    return [[float(lon1), float(lat1)], [float(lon2), float(lat2)]]

def process_xml_from_url(url, region_name, all_incidents):
    try:
        print(f"Procesando {region_name}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        # Namespaces para V3 y V2
        ns = {
            'sit': 'http://levelC/schema/3/situation',
            'loc': 'http://levelC/schema/3/locationReferencing',
            'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
            'com': 'http://levelC/schema/3/common',
            '_0': 'http://datex2.eu/schema/1_0/1_0'
        }
        
        # Buscamos registros en cualquier namespace
        records = root.findall(".//sit:situationRecord", ns) + root.findall(".//_0:situationRecord", ns)
        print(f"Detectados {len(records)} registros brutos en {region_name}.")

        count = 0
        for record in records:
            is_v3 = 'levelC' in record.tag
            pref = 'sit:' if is_v3 else '_0:'
            
            # --- 1. SEVERIDAD ---
            sev_elem = record.find(f"{pref}severity", ns)
            sev_raw = sev_elem.text if sev_elem is not None else "unknown"
            desc = [f"", f"<b>Gravedad:</b> {TRANSLATIONS.get(sev_raw, sev_raw)}"]
            
            # --- 2. CARRETERA Y TEXTOS ---
            road = record.find(".//loc:roadName", ns) or record.find(".//_0:roadNumber", ns)
            if road is not None and road.text: desc.append(f"<b>Carretera:</b> {road.text}")

            final_desc = "<br>".join(desc)

            # --- 3. GEOMETRÍA (Búsqueda Exhaustiva) ---
            lat_f, lon_f, lat_t, lon_t = None, None, None, None
            
            # Intentar encontrar tramos lineales (V3 y V2)
            linear_v3 = record.find(".//loc:linearLocation", ns)
            linear_v2 = record.find(".//_0:locationContainedInGroup", ns)

            if linear_v3 is not None:
                # En V3 las coordenadas pueden estar en loc:from y loc:to
                f_pt = linear_v3.find(".//loc:from//loc:pointCoordinates", ns)
                t_pt = linear_v3.find(".//loc:to//loc:pointCoordinates", ns)
                if f_pt is not None and t_pt is not None:
                    lat_f, lon_f = f_pt.find("loc:latitude", ns).text, f_pt.find("loc:longitude", ns).text
                    lat_t, lon_t = t_pt.find("loc:latitude", ns).text, t_pt.find("loc:longitude", ns).text

            elif linear_v2 is not None:
                f_pt = linear_v2.find(".//_0:from//_0:pointCoordinates", ns)
                t_pt = linear_v2.find(".//_0:to//_0:pointCoordinates", ns)
                if f_pt is not None and t_pt is not None:
                    lat_f, lon_f = f_pt.find("_0:latitude", ns).text, f_pt.find("_0:longitude", ns).text
                    lat_t, lon_t = t_pt.find("_0:latitude", ns).text, t_pt.find("_0:longitude", ns).text

            # --- PROCESAR RESULTADO ---
            if lat_f and lat_t:
                # TRAMO CON CURVAS
                curved_coords = get_road_geometry(lon_f, lat_f, lon_t, lat_t)
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "LineString", "coordinates": curved_coords}
                })
                # PUNTO PARA ICONO
                all_incidents.append({
                    "type": "Feature",
                    "properties": {"description": final_desc, "region": region_name},
                    "geometry": {"type": "Point", "coordinates": [float(lon_f), float(lat_f)]}
                })
                count += 1
            else:
                # BUSCAR PUNTO ÚNICO (Si no hubo tramo)
                p_pt = record.find(".//loc:pointCoordinates", ns) or record.find(".//_0:pointCoordinates", ns)
                if p_pt is not None:
                    l_lat = p_pt.find(".//loc:latitude", ns) or p_pt.find("_0:latitude", ns)
                    l_lon = p_pt.find(".//loc:longitude", ns) or p_pt.find("_0:longitude", ns)
                    if l_lat is not None and l_lon is not None:
                        all_incidents.append({
                            "type": "Feature",
                            "properties": {"description": final_desc, "region": region_name},
                            "geometry": {"type": "Point", "coordinates": [float(l_lon.text), float(l_lat.text)]}
                        })
                        count += 1

        print(f"OK: {count} incidentes válidos extraídos de {region_name}.")
    except Exception as e:
        print(f"Error en {region_name}: {e}")

if __name__ == "__main__":
    final_data = []
    for name, url in REGIONS.items():
        process_xml_from_url(url, name, final_data)
    
    with open("traffic_data.geojson", "w", encoding='utf-8') as f:
        json.dump({"type": "FeatureCollection", "features": final_data}, f, indent=2, ensure_ascii=False)
    print(f"\nÉxito total: {len(final_data)} elementos guardados.")
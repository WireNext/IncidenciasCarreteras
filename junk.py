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

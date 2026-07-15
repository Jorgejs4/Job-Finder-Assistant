from datetime import datetime
from notion_client import Client
import config

class NotionSync:
    def __init__(self):
        self.notion = Client(auth=config.NOTION_TOKEN)
        self.database_id = config.NOTION_DATABASE_ID
        self.data_source_id = None
        self.schema_properties = {}
        try:
            db_info = self.notion.databases.retrieve(database_id=self.database_id)
            data_sources = db_info.get("data_sources", [])
            if data_sources:
                self.data_source_id = data_sources[0]["id"]
                print(f"[Notion] Inicializado con Data Source ID: {self.data_source_id}")
                ds_info = self.notion.data_sources.retrieve(data_source_id=self.data_source_id)
                self.schema_properties = ds_info.get("properties", {})
            else:
                print(f"[Notion] Inicializado con Database ID: {self.database_id}")
                self.schema_properties = db_info.get("properties", {})
            print(f"[Notion] Propiedades de la base de datos detectadas: {list(self.schema_properties.keys())}")
        except Exception as e:
            print(f"[Notion] Error al recuperar detalles de la base de datos: {e}")

    def _query(self, filter_body: dict) -> list:
        if self.data_source_id:
            response = self.notion.data_sources.query(
                data_source_id=self.data_source_id,
                filter=filter_body
            )
        else:
            response = self.notion.request(
                path=f"databases/{self.database_id}/query",
                method="POST",
                body={
                    "filter": filter_body
                }
            )
        return response.get("results", [])

    def clean_deleted_items(self) -> int:
        """
        Busca las páginas donde el usuario ha marcado el checkbox "Eliminar" 
        y las archiva (elimina) de Notion.
        """
        print("[Notion] Buscando ofertas marcadas para eliminar...")
        count = 0
        try:
            results = self._query({
                "property": "Eliminar",
                "checkbox": {
                    "equals": True
                }
            })
            for page in results:
                # Archivar la página (eliminarla)
                self.notion.pages.update(page_id=page["id"], archived=True)
                count += 1
                
            if count > 0:
                print(f"[Notion] Se eliminaron {count} ofertas archivadas.")
        except Exception as e:
            print(f"[Notion] Error al limpiar ofertas eliminadas: {e}")
            
        return count

    def delete_all_items(self) -> int:
        """
        Busca todas las páginas en la base de datos de Notion y las archiva (elimina).
        """
        print("[Notion] Eliminando todos los elementos de la base de datos...")
        count = 0
        has_more = True
        start_cursor = None
        
        while has_more:
            try:
                body = {}
                if start_cursor:
                    body["start_cursor"] = start_cursor
                    
                if self.data_source_id:
                    response = self.notion.data_sources.query(
                        data_source_id=self.data_source_id,
                        **body
                    )
                else:
                    response = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )
                
                results = response.get("results", [])
                if not results:
                    break
                    
                for page in results:
                    self.notion.pages.update(page_id=page["id"], archived=True)
                    count += 1
                
                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor", None)
            except Exception as e:
                print(f"[Notion] Error al eliminar elementos de la base de datos: {e}")
                break
                
        print(f"[Notion] Se eliminaron {count} ofertas de la base de datos.")
        return count


    def check_if_job_exists(self, link: str) -> bool:
        """
        Verifica si una oferta ya existe en la base de datos de Notion 
        utilizando su URL única.
        """
        if not link:
            return False
            
        if link.startswith("//"):
            link = "https:" + link
            
        try:
            results = self._query({
                "property": "URL",
                "url": {
                    "equals": link
                }
            })
            return len(results) > 0
        except Exception as e:
            print(f"[Notion] Error al verificar existencia del enlace {link}: {e}")
            return False

    def _parse_salary_to_num(self, salary_str: str):
        if not salary_str:
            return None
        import re
        # Limpiar puntos y espacios que sirven como separadores de miles
        cleaned = re.sub(r'(?<=\d)[.\s](?=\d{3})', '', salary_str)
        # Limpieza básica
        cleaned_simple = cleaned.replace('.', '').replace(',', '').strip()
        match = re.search(r'\d+', cleaned_simple)
        if match:
            val = int(match.group())
            if val < 1000 and ('k' in salary_str.lower() or 'mil' in salary_str.lower()):
                val *= 1000
            return val
        return None

    def add_job_to_notion(self, job_data: dict) -> bool:
        """
        Añade una oferta de empleo a la base de datos de Notion.
        """
        # Sanitizar campos de texto para evitar errores de longitud en la API de Notion (límite 2000 chars)
        def clean_text(text: str, limit: int = 1900) -> str:
            if not text:
                return ""
            # Eliminar caracteres extraños y recortar
            text_str = str(text).replace("\u0000", "")
            return text_str[:limit] + "..." if len(text_str) > limit else text_str

        puesto = clean_text(job_data.get("title", "Puesto Desconocido"), 100)
        empresa = clean_text(job_data.get("company", "Desconocida"), 100)
        ubicacion = clean_text(job_data.get("location", "España"), 100)
        salario_raw = clean_text(job_data.get("salary", "No especificado"), 100)
        salario_num = self._parse_salary_to_num(salario_raw)
        match_score = int(job_data.get("match_score", 0))
        
        # Modalidad de trabajo
        work_mode_raw = job_data.get("work_mode", "Presencial")
        if work_mode_raw not in ["Presencial", "Remoto", "Híbrido"]:
            # Fallback en caso de que varíe ligeramente
            work_mode_lower = str(work_mode_raw).lower()
            if "remot" in work_mode_lower or "teletrabaj" in work_mode_lower or "distancia" in work_mode_lower:
                work_mode = "Remoto"
            elif "hibrid" in work_mode_lower or "híbrid" in work_mode_lower or "semipresencial" in work_mode_lower:
                work_mode = "Híbrido"
            else:
                work_mode = "Presencial"
        else:
            work_mode = work_mode_raw

        # Determinar el formato de la propiedad 'Modalidad' según el tipo definido en Notion
        modalidad_prop = {}
        modalidad_type = "select"  # por defecto
        if self.schema_properties and "Modalidad" in self.schema_properties:
            modalidad_type = self.schema_properties["Modalidad"].get("type", "select")
            
        if modalidad_type == "rich_text":
            modalidad_prop = {
                "rich_text": [
                    {
                        "text": {
                            "content": work_mode
                        }
                    }
                ]
            }
        else:
            modalidad_prop = {
                "select": {
                    "name": work_mode
                }
            }

        # Formatear el stack como lista para Notion rich_text
        tech_stack = []
        for tech in job_data.get("tech_stack", []):
            clean_tech = clean_text(tech.strip(), 50)
            if clean_tech and clean_tech not in tech_stack:
                tech_stack.append(clean_tech)
        
        stack_str = ", ".join(tech_stack[:20])

        consejos = clean_text(job_data.get("tailored_advice", "Sin consejos adicionales."), 1900)
        enlace = job_data.get("link", "")
        if enlace.startswith("//"):
            enlace = "https:" + enlace
        
        # Validar y parsear fecha de publicación
        fecha_pub = None
        date_str = job_data.get("date_posted", "")
        try:
            # Si tiene formato de fecha simple
            if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
                fecha_pub = date_str[:10]
            else:
                # Si no es fecha válida, usamos la fecha de hoy
                fecha_pub = datetime.today().strftime('%Y-%m-%d')
        except Exception:
            fecha_pub = datetime.today().strftime('%Y-%m-%d')

        fecha_det = datetime.today().strftime('%Y-%m-%d')

        # Estructura de propiedades para crear la página en Notion
        properties = {
            "Puesto": {
                "title": [
                    {
                        "text": {
                            "content": puesto
                        }
                    }
                ]
            },
            "Empresa": {
                "rich_text": [
                    {
                        "text": {
                            "content": empresa if empresa else "Desconocida"
                        }
                    }
                ]
            },
            "Ubicacion": {
                "rich_text": [
                    {
                        "text": {
                            "content": ubicacion
                        }
                    }
                ]
            },
            "Modalidad": modalidad_prop,
            "Stack": {
                "rich_text": [
                    {
                        "text": {
                            "content": stack_str
                        }
                    }
                ]
            },
            "Consejos": {
                "rich_text": [
                    {
                        "text": {
                            "content": consejos
                        }
                    }
                ]
            },
            "Eliminar": {
                "checkbox": False
            },
            "URL": {
                "url": enlace if enlace else "https://www.google.com"
            },
            "Match": {
                "number": match_score
            },
            "Fecha de publicacion": {
                "date": {
                    "start": fecha_pub
                }
            },
            "Fecha Deteccion": {
                "date": {
                    "start": fecha_det
                }
            }
        }

        if salario_num is not None:
            properties["Salario"] = {
                "number": salario_num
            }

        # Origen del salario (Estimado por IA vs Directo de la oferta)
        salary_is_estimate = job_data.get("salary_is_estimate")
        if salary_is_estimate is not None:
            origen = "Estimado (IA)" if salary_is_estimate else "Directo"
            # Si el campo "Origen Salario" existe en el esquema, usarlo
            if self.schema_properties and "Origen Salario" in self.schema_properties:
                modalidad_type_origen = self.schema_properties["Origen Salario"].get("type", "select")
                if modalidad_type_origen == "rich_text":
                    properties["Origen Salario"] = {
                        "rich_text": [{"text": {"content": origen}}]
                    }
                else:
                    properties["Origen Salario"] = {
                        "select": {"name": origen}
                    }
            else:
                # Si no existe el campo, añadir la info al inicio de Consejos
                prefix = f"[{origen}] "
                consejos_val = properties.get("Consejos", {}).get("rich_text", [{}])
                if consejos_val and isinstance(consejos_val, list) and consejos_val:
                    existing = consejos_val[0].get("text", {}).get("content", "")
                    if not existing.startswith("["):
                        properties["Consejos"] = {
                            "rich_text": [{"text": {"content": prefix + existing}}]
                        }

        # Filtrar las propiedades enviadas para incluir únicamente las que existen en el esquema de la base de datos
        if self.schema_properties:
            properties = {k: v for k, v in properties.items() if k in self.schema_properties}

        try:
            self.notion.pages.create(
                parent={"database_id": self.database_id},
                properties=properties
            )
            print(f"[Notion] Añadida con éxito: {puesto} en {empresa} ({ubicacion}) [{work_mode}] - Match: {match_score}% - Salario: {salario_num}€")
            return True
        except Exception as e:
            print(f"[Notion] Error al crear la página para {puesto}: {e}")
            return False

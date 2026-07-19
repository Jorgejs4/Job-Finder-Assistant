from datetime import datetime
from notion_client import Client
import unicodedata
import config


def _normalize_key(s: str) -> str:
    """Elimina tildes y normaliza para comparación robusta de nombres de propiedades."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()

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

        # Índice normalizado para buscar propiedades sin importar tildes
        self._prop_index = {}
        for key in self.schema_properties:
            self._prop_index[_normalize_key(key)] = key

    def _find_prop(self, name: str) -> str:
        """Busca una propiedad por nombre normalizado (sin tildes). Devuelve el nombre real o None."""
        return self._prop_index.get(_normalize_key(name))

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
                self.notion.pages.update(page_id=page["id"], archived=True)
                count += 1
                
            if count > 0:
                print(f"[Notion] Se eliminaron {count} ofertas archivadas.")
        except Exception as e:
            print(f"[Notion] Error al limpiar ofertas eliminadas: {e}")
            
        return count

    def delete_all_items(self) -> int:
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

    def get_existing_urls(self) -> list:
        urls = []
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    response = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    response = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in response.get("results", []):
                    url_val = page.get("properties", {}).get("URL", {}).get("url")
                    if url_val:
                        urls.append(url_val)
                if not response.get("has_more"):
                    break
                start_cursor = response.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo URLs: {e}")
                break
        return urls

    def get_all_jobs_for_fuzzy(self) -> list:
        jobs = []
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    resp = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    resp = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    title_arr = props.get("Puesto", {}).get("title", [])
                    title_text = title_arr[0].get("text", {}).get("content", "") if title_arr else ""
                    empresa_arr = props.get("Empresa", {}).get("rich_text", [])
                    empresa_text = empresa_arr[0].get("text", {}).get("content", "") if empresa_arr else ""
                    url = props.get("URL", {}).get("url", "")
                    jobs.append({"title": title_text, "company": empresa_text, "link": url})

                if not resp.get("has_more"):
                    break
                start_cursor = resp.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo ofertas para fuzzy: {e}")
                break
        return jobs

    def update_job_status(self, page_id: str, status: str) -> bool:
        prop_name = self._find_prop("Estado")
        if not prop_name:
            return False

        estado_type = self.schema_properties[prop_name].get("type", "select")
        if estado_type == "rich_text":
            prop = {"rich_text": [{"text": {"content": status}}]}
        else:
            prop = {"select": {"name": status}}

        try:
            self.notion.pages.update(page_id=page_id, properties={prop_name: prop})
            return True
        except Exception as e:
            print(f"[Notion] Error actualizando Estado: {e}")
            return False

    def update_job_fields(self, job_data: dict) -> bool:
        """Actualiza campos enriquecidos de un job existente en Notion (por URL)."""
        url = job_data.get("link", "")
        if not url:
            return False
        if url.startswith("//"):
            url = "https:" + url

        try:
            results = self._query({"property": "URL", "url": {"equals": url}})
            if not results:
                return False
            page_id = results[0]["id"]
        except Exception as e:
            print(f"[Notion] Error buscando job por URL: {e}")
            return False

        props = {}

        match_score = job_data.get("match_score")
        if match_score is not None:
            prop_name = self._find_prop("Match")
            if prop_name:
                props[prop_name] = {"number": int(match_score)}

        work_mode = job_data.get("work_mode")
        if work_mode:
            prop_name = self._find_prop("Modalidad")
            if prop_name:
                modalidad_type = self.schema_properties[prop_name].get("type", "select")
                if modalidad_type == "rich_text":
                    props[prop_name] = {"rich_text": [{"text": {"content": work_mode}}]}
                else:
                    props[prop_name] = {"select": {"name": work_mode}}

        tech_stack = job_data.get("tech_stack")
        if tech_stack:
            prop_name = self._find_prop("Stack")
            if prop_name:
                stack_str = ", ".join(str(t).strip() for t in tech_stack[:20])
                props[prop_name] = {"rich_text": [{"text": {"content": stack_str[:1900]}}]}

        tailored_advice = job_data.get("tailored_advice")
        if tailored_advice:
            prop_name = self._find_prop("Consejos")
            if prop_name:
                props[prop_name] = {"rich_text": [{"text": {"content": str(tailored_advice)[:1900]}}]}

        salary = job_data.get("salary")
        if salary:
            prop_name = self._find_prop("Salario")
            if prop_name:
                salario_num = self._parse_salary_to_num(str(salary))
                if salario_num:
                    props[prop_name] = {"number": salario_num}

        required_experience = job_data.get("required_experience")
        if required_experience is not None:
            prop_name = self._find_prop("Exp")
            if prop_name:
                props[prop_name] = {"number": int(required_experience)}

        cover_letter = job_data.get("cover_letter")
        if cover_letter:
            prop_name = self._find_prop("Carta Presentacion")
            if prop_name:
                props[prop_name] = {"rich_text": [{"text": {"content": str(cover_letter)[:1900]}}]}

        custom_cv_url = job_data.get("custom_cv_url")
        if custom_cv_url:
            prop_name = self._find_prop("CV")
            if prop_name:
                props[prop_name] = {"url": custom_cv_url}

        if not props:
            return False

        try:
            self.notion.pages.update(page_id=page_id, properties=props)
            print(f"[Notion] Actualizado: {job_data.get('title', '?')[:40]} ({len(props)} campos)")
            return True
        except Exception as e:
            print(f"[Notion] Error actualizando job: {e}")
            return False

    def get_all_jobs_for_analysis(self) -> list:
        """
        Devuelve lista completa de ofertas activas con todos los campos.
        Usado para skills gap analysis e informes de mercado.
        """
        jobs = []
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    resp = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    resp = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    # Extraer título
                    title_arr = props.get("Puesto", {}).get("title", [])
                    title = title_arr[0].get("text", {}).get("content", "") if title_arr else ""
                    # Extraer empresa
                    empresa_arr = props.get("Empresa", {}).get("rich_text", [])
                    company = empresa_arr[0].get("text", {}).get("content", "") if empresa_arr else ""
                    # Extraer URL
                    url = props.get("URL", {}).get("url", "")
                    # Extraer Match
                    match_score = props.get("Match", {}).get("number", 0)
                    # Extraer Salario
                    salary = props.get("Salario", {}).get("number")
                    # Extraer Modalidad
                    modalidad = props.get("Modalidad", {})
                    work_mode = modalidad.get("select", {}).get("name", "") if modalidad.get("type") == "select" else ""
                    if not work_mode:
                        rt = modalidad.get("rich_text", [])
                        work_mode = rt[0].get("text", {}).get("content", "") if rt else ""
                    # Extraer Stack
                    stack_arr = props.get("Stack", {}).get("rich_text", [])
                    stack_str = stack_arr[0].get("text", {}).get("content", "") if stack_arr else ""
                    tech_stack = [t.strip() for t in stack_str.split(",") if t.strip()]
                    # Extraer Estado
                    estado = props.get("Estado", {})
                    status = estado.get("select", {}).get("name", "Nuevo") if estado.get("type") == "select" else ""
                    if not status:
                        rt = estado.get("rich_text", [])
                        status = rt[0].get("text", {}).get("content", "Nuevo") if rt else "Nuevo"
                    # Extraer Exp
                    exp = props.get("Exp", {}).get("number", 0)

                    jobs.append({
                        "title": title,
                        "company": company,
                        "link": url,
                        "match_score": match_score,
                        "salary": salary,
                        "work_mode": work_mode,
                        "tech_stack": tech_stack,
                        "status": status,
                        "required_experience": exp,
                    })

                if not resp.get("has_more"):
                    break
                start_cursor = resp.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo ofertas para análisis: {e}")
                break
        return jobs

    def get_all_jobs_full(self) -> list:
        """
        Devuelve todas las ofertas con page_id y todos los campos necesarios
        para rellenar los vacíos (cover letter, CV, etc).
        """
        jobs = []
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    resp = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    resp = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in resp.get("results", []):
                    props = page.get("properties", {})

                    def _rt(prop_name):
                        arr = props.get(prop_name, {}).get("rich_text", [])
                        return arr[0].get("text", {}).get("content", "") if arr else ""

                    def _title(prop_name):
                        arr = props.get(prop_name, {}).get("title", [])
                        return arr[0].get("text", {}).get("content", "") if arr else ""

                    def _num(prop_name):
                        return props.get(prop_name, {}).get("number", 0)

                    def _select(prop_name):
                        s = props.get(prop_name, {})
                        if s.get("type") == "select":
                            return s.get("select", {}).get("name", "")
                        return ""

                    def _url(prop_name):
                        return props.get(prop_name, {}).get("url", "")

                    title = _title("Puesto")
                    company = _rt("Empresa")
                    stack_str = _rt("Stack")
                    tech_stack = [t.strip() for t in stack_str.split(",") if t.strip()]
                    advice = _rt("Consejos")
                    cover_letter_raw = props.get("Carta Presentación", props.get("Carta Presentacion", {}))
                    cl_texts = cover_letter_raw.get("rich_text", [])
                    has_cover_letter = bool(cl_texts and cl_texts[0].get("text", {}).get("content", ""))

                    cv_raw = props.get("CV", {})
                    has_cv = bool(cv_raw.get("url"))

                    jobs.append({
                        "page_id": page["id"],
                        "title": title,
                        "company": company,
                        "link": _url("URL"),
                        "match_score": _num("Match"),
                        "salary": _num("Salario"),
                        "work_mode": _select("Modalidad"),
                        "tech_stack": tech_stack,
                        "required_experience": _num("Exp"),
                        "advice": advice,
                        "has_cover_letter": has_cover_letter,
                        "has_cv": has_cv,
                    })

                if not resp.get("has_more"):
                    break
                start_cursor = resp.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo ofertas full: {e}")
                break
        return jobs

    def update_cover_letter(self, page_id: str, cover_letter: str) -> bool:
        """
        Actualiza el campo 'Carta Presentación' de una página en Notion.
        """
        prop_name = self._find_prop("Carta Presentación")
        if not prop_name:
            return False

        try:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    prop_name: {
                        "rich_text": [{"text": {"content": cover_letter[:1900]}}]
                    }
                }
            )
            return True
        except Exception as e:
            print(f"[Notion] Error actualizando Carta Presentación: {e}")
            return False

    def _parse_salary_to_num(self, salary_str: str):
        if not salary_str:
            return None
        import re
        cleaned = re.sub(r'(?<=\d)[.\s](?=\d{3})', '', salary_str)
        cleaned_simple = cleaned.replace('.', '').replace(',', '').strip()
        match = re.search(r'\d+', cleaned_simple)
        if match:
            val = int(match.group())
            if val < 1000 and ('k' in salary_str.lower() or 'mil' in salary_str.lower()):
                val *= 1000
            return val
        return None

    def add_job_to_notion(self, job_data: dict) -> bool:
        def clean_text(text: str, limit: int = 1900) -> str:
            if not text:
                return ""
            text_str = str(text).replace("\u0000", "")
            return text_str[:limit] + "..." if len(text_str) > limit else text_str

        puesto = clean_text(job_data.get("title", "Puesto Desconocido"), 100)
        empresa = clean_text(job_data.get("company", "Desconocida"), 100)
        ubicacion = clean_text(job_data.get("location", "España"), 100)
        salario_raw = clean_text(job_data.get("salary", "No especificado"), 100)
        salario_num = self._parse_salary_to_num(salario_raw)
        match_score = int(job_data.get("match_score", 0))
        
        work_mode_raw = job_data.get("work_mode", "Presencial")
        if work_mode_raw not in ["Presencial", "Remoto", "Híbrido"]:
            work_mode_lower = str(work_mode_raw).lower()
            if "remot" in work_mode_lower or "teletrabaj" in work_mode_lower or "distancia" in work_mode_lower:
                work_mode = "Remoto"
            elif "hibrid" in work_mode_lower or "híbrid" in work_mode_lower or "semipresencial" in work_mode_lower:
                work_mode = "Híbrido"
            else:
                work_mode = "Presencial"
        else:
            work_mode = work_mode_raw

        modalidad_prop = {}
        modalidad_type = "select"
        mod_prop = self._find_prop("Modalidad")
        if mod_prop:
            modalidad_type = self.schema_properties[mod_prop].get("type", "select")
            
        if modalidad_type == "rich_text":
            modalidad_prop = {"rich_text": [{"text": {"content": work_mode}}]}
        else:
            modalidad_prop = {"select": {"name": work_mode}}

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
        
        fecha_pub = None
        date_str = job_data.get("date_posted", "")
        try:
            if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
                fecha_pub = date_str[:10]
            else:
                fecha_pub = datetime.today().strftime('%Y-%m-%d')
        except Exception:
            fecha_pub = datetime.today().strftime('%Y-%m-%d')

        fecha_det = datetime.today().strftime('%Y-%m-%d')

        # Construir properties usando nombres reales de Notion (con _find_prop)
        p = {}
        for logical_name, prop_val in [
            ("Puesto", {"title": [{"text": {"content": puesto}}]}),
            ("Empresa", {"rich_text": [{"text": {"content": empresa if empresa else "Desconocida"}}]}),
            ("Ubicacion", {"rich_text": [{"text": {"content": ubicacion}}]}),
            ("Modalidad", modalidad_prop),
            ("Stack", {"rich_text": [{"text": {"content": stack_str}}]}),
            ("Consejos", {"rich_text": [{"text": {"content": consejos}}]}),
            ("Eliminar", {"checkbox": False}),
            ("URL", {"url": enlace if enlace else "https://www.google.com"}),
            ("Match", {"number": match_score}),
            ("Fecha de publicacion", {"date": {"start": fecha_pub}}),
            ("Fecha Deteccion", {"date": {"start": fecha_det}}),
        ]:
            real = self._find_prop(logical_name)
            if real:
                p[real] = prop_val

        if salario_num is not None:
            sal_prop = self._find_prop("Salario")
            if sal_prop:
                p[sal_prop] = {"number": salario_num}

        salary_is_estimate = job_data.get("salary_is_estimate")
        if salary_is_estimate is not None:
            origen = "Estimado (IA)" if salary_is_estimate else "Directo"
            origen_prop = self._find_prop("Origen Salario")
            if origen_prop:
                origen_type = self.schema_properties[origen_prop].get("type", "select")
                if origen_type == "rich_text":
                    p[origen_prop] = {"rich_text": [{"text": {"content": origen}}]}
                else:
                    p[origen_prop] = {"select": {"name": origen}}

        required_exp = job_data.get("required_experience")
        exp_prop = self._find_prop("Exp")
        if required_exp is not None and exp_prop:
            p[exp_prop] = {"number": int(required_exp)}

        # Estado de aplicación (nuevo job siempre entra como "Nuevo")
        estado_prop = self._find_prop("Estado")
        if estado_prop:
            estado_type = self.schema_properties[estado_prop].get("type", "select")
            if estado_type == "rich_text":
                p[estado_prop] = {"rich_text": [{"text": {"content": "Nuevo"}}]}
            else:
                p[estado_prop] = {"select": {"name": "Nuevo"}}

        # Carta de presentación (si se genera)
        cover_letter = job_data.get("cover_letter")
        cl_prop = self._find_prop("Carta Presentación")
        if cover_letter and cl_prop:
            p[cl_prop] = {"rich_text": [{"text": {"content": clean_text(cover_letter, 1900)}}]}

        # CV personalizado (enlace al PDF)
        cv_url = job_data.get("custom_cv_url")
        cv_prop = self._find_prop("CV")
        if cv_url and cv_prop:
            p[cv_prop] = {"url": cv_url}

        try:
            self.notion.pages.create(
                parent={"database_id": self.database_id},
                properties=p
            )
            print(f"[Notion] Añadida con éxito: {puesto} en {empresa} ({ubicacion}) [{work_mode}] - Match: {match_score}% - Salario: {salario_num}€")
            return True
        except Exception as e:
            print(f"[Notion] Error al crear la página para {puesto}: {e}")
            return False

    def find_existing_job(self, title: str, company: str) -> dict | None:
        """Busca un job existente por título y empresa en Notion."""
        try:
            result = self._query_notion(
                filter_obj={
                    "and": [
                        {"property": "Puesto", "title": {"equals": title[:100]}},
                        {"property": "Empresa", "rich_text": {"equals": company[:200]}},
                    ]
                }
            )
            pages = result.get("results", [])
            if pages:
                return {"page_id": pages[0]["id"], "properties": pages[0].get("properties", {})}
        except Exception as e:
            print(f"[Notion] Error buscando job {title} @ {company}: {e}")
        return None

    def update_cv_url(self, page_id: str, cv_url: str):
        """Actualiza el campo CV (URL) de un job existente en Notion."""
        cv_prop = self._find_prop("CV")
        if not cv_prop:
            return
        try:
            self.notion.pages.update(
                page_id=page_id,
                properties={cv_prop: {"url": cv_url}}
            )
            print(f"[Notion] CV actualizado para page {page_id[:8]}...")
        except Exception as e:
            print(f"[Notion] Error actualizando CV: {e}")

    def get_all_statuses(self) -> dict:
        """
        Lee el Estado de todas las páginas activas en Notion.
        Devuelve dict {url: status} para sincronización bidireccional.
        """
        statuses = {}
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    resp = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    resp = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    url = props.get("URL", {}).get("url", "")
                    if not url:
                        continue

                    estado = props.get("Estado", {})
                    status = "Nuevo"
                    if estado.get("type") == "select":
                        status = estado.get("select", {}).get("name", "Nuevo")
                    elif estado.get("type") == "rich_text":
                        rt = estado.get("rich_text", [])
                        status = rt[0].get("text", {}).get("content", "Nuevo") if rt else "Nuevo"

                    statuses[url] = status

                if not resp.get("has_more"):
                    break
                start_cursor = resp.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo estados: {e}")
                break
        return statuses

    def update_job_eliminar(self, link: str, eliminate: bool) -> bool:
        """Marca/desmarca el checkbox 'Eliminar' en Notion por URL."""
        if not link:
            return False
        if link.startswith("//"):
            link = "https:" + link
        try:
            results = self._query({"property": "URL", "url": {"equals": link}})
            if not results:
                return False
            page_id = results[0]["id"]
            prop_name = self._find_prop("Eliminar")
            if not prop_name:
                return False
            self.notion.pages.update(
                page_id=page_id,
                properties={prop_name: {"checkbox": eliminate}}
            )
            action = "marcado" if eliminate else "desmarcado"
            print(f"[Notion] Eliminar {action} para {link[:60]}")
            return True
        except Exception as e:
            print(f"[Notion] Error actualizando Eliminar: {e}")
            return False

    def get_all_archived(self) -> dict:
        """
        Lee el checkbox 'Eliminar' de todas las paginas activas en Notion.
        Devuelve dict {url: bool} para sincronizar archivado bidireccional.
        """
        archived = {}
        start_cursor = None
        while True:
            try:
                body = {"page_size": 100}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                if self.data_source_id:
                    resp = self.notion.data_sources.query(
                        data_source_id=self.data_source_id, **body
                    )
                else:
                    resp = self.notion.request(
                        path=f"databases/{self.database_id}/query",
                        method="POST",
                        body=body
                    )

                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    url = props.get("URL", {}).get("url", "")
                    if not url:
                        continue

                    eliminar = props.get("Eliminar", {})
                    is_eliminated = eliminar.get("checkbox", False) if eliminar.get("type") == "checkbox" else False
                    archived[url] = is_eliminated

                if not resp.get("has_more"):
                    break
                start_cursor = resp.get("next_cursor")
            except Exception as e:
                print(f"[Notion] Error obteniendo archivados: {e}")
                break
        return archived

"""
Script para re-analizar todos los trabajos existentes en Notion
y rellenar los campos 'Exp' y 'Origen Salario' que faltan.
"""
import os
import sys
import json
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
import config
from utils.gemini_client import GeminiClient

NOTION_API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}


def query_all_pages(database_id: str) -> list:
    """Obtiene todas las páginas de la base de datos."""
    all_pages = []
    start_cursor = None
    while True:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        resp = requests.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=HEADERS,
            json=body
        )
        data = resp.json()
        all_pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
    return all_pages


def get_job_description_from_notion(page: dict) -> str:
    """Extrae toda la info disponible de una página de Notion para re-análisis."""
    props = page.get("properties", {})
    
    title_parts = props.get("Puesto", {}).get("title", [])
    title = title_parts[0].get("text", {}).get("content", "") if title_parts else ""
    
    empresa_parts = props.get("Empresa", {}).get("rich_text", [])
    empresa = empresa_parts[0].get("text", {}).get("content", "") if empresa_parts else ""
    
    ubicacion_parts = props.get("Ubicacion", {}).get("rich_text", [])
    ubicacion = ubicacion_parts[0].get("text", {}).get("content", "") if ubicacion_parts else ""
    
    stack_parts = props.get("Stack", {}).get("rich_text", [])
    stack = stack_parts[0].get("text", {}).get("content", "") if stack_parts else ""
    
    consejos_parts = props.get("Consejos", {}).get("rich_text", [])
    consejos = consejos_parts[0].get("text", {}).get("content", "") if consejos_parts else ""
    
    url = props.get("URL", {}).get("url", "")
    
    modalidad = ""
    modalidad_prop = props.get("Modalidad", {})
    if modalidad_prop.get("type") == "select":
        modalidad = modalidad_prop.get("select", {}).get("name", "")
    elif modalidad_prop.get("type") == "rich_text":
        rt = modalidad_prop.get("rich_text", [])
        modalidad = rt[0].get("text", {}).get("content", "") if rt else ""
    
    # Construir descripción para el análisis
    parts = [
        f"Puesto: {title}",
        f"Empresa: {empresa}",
        f"Ubicación: {ubicacion}",
        f"Modalidad: {modalidad}",
        f"Stack tecnológico: {stack}",
        f"Consejos del análisis anterior: {consejos}",
    ]
    desc = "\n".join(p for p in parts if p)
    
    # Si tenemos la URL, intentar obtener la descripción original
    if url:
        desc += f"\nURL de la oferta: {url}"
    
    return desc


def analyze_job_for_missing_fields(gemini: GeminiClient, title: str, description: str) -> dict:
    """Usa Gemini para estimar los años de experiencia y si el salario es estimado."""
    try:
        prompt = f"""
        Analiza esta oferta de empleo y responde ÚNICAMENTE con un JSON válido:
        
        Oferta: {title}
        Información disponible:
        {description[:2000]}
        
        Determina:
        1. "required_experience": Número entero de años de experiencia que pide la empresa.
           - Si dice "junior" → 0
           - Si dice "mid-level" o "2-3 años" → 2
           - Si dice "senior" → 5
           - Si no menciona nada → 0
           - Si dice "3 años de experiencia" → 3
           - Máximo 20.
        
        2. "salary_is_estimate": true si el salario fue estimado por IA (la oferta original no mencionaba salario), false si la oferta original sí especificaba salario.
        
        Responde SOLO con el JSON, sin texto adicional:
        {{"required_experience": 0, "salary_is_estimate": true}}
        """
        
        import google.generativeai as genai
        model = genai.GenerativeModel(gemini.model_name)
        
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Limpiar la respuesta
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        return json.loads(text)
    except Exception as e:
        print(f"  Error en análisis IA: {e}")
        return None


def update_notion_page(page_id: str, exp: int = None, salary_is_estimate: bool = None):
    """Actualiza un campo en una página de Notion."""
    properties = {}
    
    if exp is not None and "Exp" in config.get_location_for.__code__.co_consts:
        # Verificar que el campo existe en el esquema
        properties["Exp"] = {"number": exp}
    
    if exp is not None:
        properties["Exp"] = {"number": exp}
    
    if salary_is_estimate is not None:
        origen = "Estimado (IA)" if salary_is_estimate else "Directo"
        properties["Origen Salario"] = {"select": {"name": origen}}
    
    if not properties:
        return False
    
    resp = requests.patch(
        f"{NOTION_API}/pages/{page_id}",
        headers=HEADERS,
        json={"properties": properties}
    )
    return resp.status_code == 200


def main():
    print("=" * 60)
    print("  RE-ANÁLISIS DE OFERTAS EXISTENTES EN NOTION")
    print("=" * 60)
    
    config.validate_config()
    
    database_id = config.NOTION_DATABASE_ID
    print(f"[Notion] Consultando base de datos: {database_id}")
    
    pages = query_all_pages(database_id)
    print(f"[Notion] Total de páginas encontradas: {len(pages)}")
    
    # Filtrar las que necesitan re-análisis
    need_analysis = []
    for page in pages:
        props = page.get("properties", {})
        page_id = page["id"]
        
        # Título
        title_parts = props.get("Puesto", {}).get("title", [])
        title = title_parts[0].get("text", {}).get("content", "") if title_parts else "Sin título"
        
        # Exp
        exp = props.get("Exp", {}).get("number")
        
        # Origen Salario
        origen = props.get("Origen Salario", {}).get("select", {}).get("name") if props.get("Origen Salario", {}).get("select") else None
        if not origen:
            origen_rt = props.get("Origen Salario", {}).get("rich_text", [])
            if origen_rt:
                origen = origen_rt[0].get("text", {}).get("content")
        
        missing = []
        if exp is None:
            missing.append("Exp")
        if not origen:
            missing.append("Origen Salario")
        
        if missing:
            need_analysis.append({
                "id": page_id,
                "title": title,
                "missing": missing,
                "has_exp": exp is not None,
                "has_origen": bool(origen)
            })
    
    print(f"[Análisis] Trabajos que necesitan re-análisis: {len(need_analysis)}")
    print(f"  - Sin Exp: {sum(1 for j in need_analysis if 'Exp' in j['missing'])}")
    print(f"  - Sin Origen Salario: {sum(1 for j in need_analysis if 'Origen Salario' in j['missing'])}")
    
    if not need_analysis:
        print("[OK] Todos los campos están rellenados.")
        return
    
    # Inicializar Gemini
    gemini = GeminiClient()
    
    # Procesar cada trabajo
    updated = 0
    errors = 0
    
    for idx, job in enumerate(need_analysis, 1):
        print(f"\n[{idx}/{len(need_analysis)}] {job['title']}")
        print(f"  Faltan: {', '.join(job['missing'])}")
        
        # Obtener descripción del trabajo desde Notion
        description = get_job_description_from_notion(
            next(p for p in pages if p["id"] == job["id"])
        )
        
        # Analizar con Gemini
        result = analyze_job_for_missing_fields(gemini, job["title"], description)
        
        if result:
            exp_val = result.get("required_experience")
            origen_val = result.get("salary_is_estimate")
            
            print(f"  Resultado: Exp={exp_val}, SalarioEstimado={origen_val}")
            
            # Actualizar solo los campos que faltan
            success = update_notion_page(
                job["id"],
                exp=exp_val if "Exp" in job["missing"] else None,
                salary_is_estimate=origen_val if "Origen Salario" in job["missing"] else None
            )
            
            if success:
                updated += 1
                print(f"  ✓ Actualizado en Notion")
            else:
                errors += 1
                print(f"  ✗ Error al actualizar")
        else:
            errors += 1
            print(f"  ✗ No se pudo analizar")
        
        # Rate limit: 1 llamada cada 4 segundos (15 RPM)
        time.sleep(4)
    
    print("\n" + "=" * 60)
    print(f"  RE-ANÁLISIS COMPLETADO")
    print(f"  - Actualizados: {updated}")
    print(f"  - Errores: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()

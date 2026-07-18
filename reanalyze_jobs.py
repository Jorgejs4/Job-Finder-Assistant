"""
Script para re-analizar TODOS los trabajos en Notion
y corregir los campos 'Exp' y 'Origen Salario'.

Uso:
  python reanalyze_jobs.py          # Re-analizar TODOS los trabajos
  python reanalyze_jobs.py --missing # Solo los que tengan Exp vacío
"""
import os
import sys
import re
import json
import time
import argparse
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


def extract_regex_experience(title: str, description: str) -> int:
    """Pre-extracción por regex del texto disponible en Notion."""
    text = f"{title} {description}".lower()

    patterns_anios = [
        r'(\d+)\s*a[ñn]os?\s+de\s+experiencia',
        r'experiencia\s+(?:mínima?\s+)?(?:de\s+)?(\d+)\s*a[ñn]os?',
        r'mínimo\s+de?\s*(\d+)\s*a[ñn]os?',
        r'al menos\s+(\d+)\s*a[ñn]os?',
        r'(\d+)\s*years?\s+(?:of\s+)?experience',
        r'experiencia\s+de\s+(\d+)\s*a[ñn]os?',
    ]
    for pat in patterns_anios:
        m = re.search(pat, text)
        if m:
            val = int(m.group(1))
            if 0 < val <= 20:
                return val

    patterns_meses = [
        r'(\d+)\s*meses?\s+de\s+experiencia',
        r'experiencia\s+(?:mínima?\s+)?(?:de\s+)?(\d+)\s*meses?',
        r'al menos\s+(\d+)\s*meses?',
        r'mínimo\s+de?\s*(\d+)\s*meses?',
    ]
    for pat in patterns_meses:
        m = re.search(pat, text)
        if m:
            months = int(m.group(1))
            if 0 < months <= 240:
                return max(1, round(months / 12))

    range_match = re.search(r'(\d+)\s*[-–a]\s*(\d+)\s*a[ñn]os', text)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        if 0 < low <= 20 and 0 < high <= 20:
            return (low + high) // 2

    if re.search(r'\bsenior\b', text):
        return 5
    if re.search(r'\b(mid[- ]?level|intermedio|pleno)\b', text):
        return 3
    if re.search(r'\b(junior|trainee|práctic|becario)\b', text):
        return 0

    return 0


def get_job_data_from_notion(page: dict) -> dict:
    """Extrae toda la info disponible de una página de Notion."""
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

    exp = props.get("Exp", {}).get("number")

    origen = props.get("Origen Salario", {}).get("select", {}).get("name") if props.get("Origen Salario", {}).get("select") else None
    if not origen:
        origen_rt = props.get("Origen Salario", {}).get("rich_text", [])
        if origen_rt:
            origen = origen_rt[0].get("text", {}).get("content")

    parts = [
        f"Puesto: {title}",
        f"Empresa: {empresa}",
        f"Ubicación: {ubicacion}",
        f"Modalidad: {modalidad}",
        f"Stack tecnológico: {stack}",
        f"Consejos del análisis: {consejos}",
    ]
    desc = "\n".join(p for p in parts if p)

    if url:
        desc += f"\nURL de la oferta: {url}"

    return {
        "title": title,
        "description": desc,
        "exp": exp,
        "origen": origen,
        "url": url,
    }


def analyze_job(gemini: GeminiClient, title: str, description: str, regex_hint: int) -> dict:
    """Usa Gemini para estimar experiencia y origen de salario, con retry en 429."""
    import time as _time

    for attempt in range(4):
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(gemini.model_name)

            hint_text = ""
            if regex_hint > 0:
                hint_text = f"\nPISTA: el texto fue pre-analizado por regex y se detectó un valor de {regex_hint} años. Úsalo como referencia."

            prompt = f"""
            Analiza esta oferta de empleo y responde ÚNICAMENTE con un JSON válido:

            Oferta: {title}
            Información disponible:
            {description[:2000]}
            {hint_text}

            Determina:
            1. "required_experience": Número entero de años de experiencia que pide la empresa.
               - Si la oferta dice explícitamente 'X años de experiencia', devuelve X.
               - Si menciona un rango como '2-4 años', devuelve el número más bajo del rango.
               - Si pone 'junior' o 'trainee' o 'becario' → 0
               - Si pone 'mid-level', 'intermedio' o 'pleno' → 3
               - Si pone 'senior' sin número concreto → 5
               - Si habla de 'experiencia mínima' o 'al menos X años' → X
               - Si no menciona nada → 0
               - Máximo 20.

            2. "salary_is_estimate": true si el salario fue estimado por IA (la oferta original no mencionaba salario), false si la oferta original sí especificaba salario explícitamente.

            Responde SOLO con el JSON, sin texto adicional:
            {{"required_experience": 0, "salary_is_estimate": true}}
            """

            response = model.generate_content(prompt)
            text = response.text.strip()

            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            return json.loads(text)
        except Exception as e:
            if "429" in str(e) and attempt < 3:
                wait = (attempt + 1) * 15
                print(f"  Rate limit (429). Esperando {wait}s...")
                _time.sleep(wait)
            else:
                print(f"  Error en análisis IA: {e}")
                return None


def update_notion_page(page_id: str, exp: int = None, salary_is_estimate: bool = None):
    """Actualiza campos en una página de Notion."""
    properties = {}
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
    parser = argparse.ArgumentParser(description="Re-analizar ofertas en Notion")
    parser.add_argument("--missing", action="store_true", help="Solo re-analizar los que tengan Exp vacío")
    args = parser.parse_args()

    print("=" * 60)
    print("  RE-ANÁLISIS DE OFERTAS EN NOTION")
    print(f"  Modo: {'Solo sin Exp' if args.missing else 'TODOS'}")
    print("=" * 60)

    config.validate_config()

    database_id = config.NOTION_DATABASE_ID
    print(f"[Notion] Consultando base de datos...")

    pages = query_all_pages(database_id)
    print(f"[Notion] Total de páginas: {len(pages)}")

    to_process = []
    for page in pages:
        data = get_job_data_from_notion(page)
        if args.missing and data["exp"] is not None:
            continue
        to_process.append({"page": page, "data": data})

    print(f"[Análisis] Trabajos a re-analizar: {len(to_process)}")

    if not to_process:
        print("[OK] Nada que hacer.")
        return

    gemini = GeminiClient()

    updated = 0
    errors = 0
    skipped = 0

    for idx, item in enumerate(to_process, 1):
        page = item["page"]
        data = item["data"]
        title = data["title"]
        page_id = page["id"]

        print(f"\n[{idx}/{len(to_process)}] {title}")

        regex_hint = extract_regex_experience(title, data["description"])
        print(f"  Regex hint: {regex_hint} años")

        result = analyze_job(gemini, title, data["description"], regex_hint)

        if result:
            exp_val = result.get("required_experience", 0)
            origen_val = result.get("salary_is_estimate", True)

            if exp_val == 0 and regex_hint > 0:
                exp_val = regex_hint
                print(f"  Gemini devolvió 0, usando regex hint: {regex_hint}")
            else:
                print(f"  Gemini: Exp={exp_val}, SalarioEstimado={origen_val}")

            if exp_val == data["exp"]:
                print(f"  Sin cambios (Exp ya era {exp_val})")
                skipped += 1
            else:
                success = update_notion_page(page_id, exp=exp_val, salary_is_estimate=origen_val)
                if success:
                    updated += 1
                    print(f"  ✓ Actualizado: Exp {data['exp']} → {exp_val}")
                else:
                    errors += 1
                    print(f"  ✗ Error al actualizar")
        else:
            errors += 1
            print(f"  ✗ No se pudo analizar")

        time.sleep(2)

    print("\n" + "=" * 60)
    print(f"  RE-ANÁLISIS COMPLETADO")
    print(f"  - Actualizados: {updated}")
    print(f"  - Sin cambios: {skipped}")
    print(f"  - Errores: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()

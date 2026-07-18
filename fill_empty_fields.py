#!/usr/bin/env python3
"""
Rellena los campos vacíos (Carta Presentación + CV) de todas las ofertas en Notion.
Uso: python fill_empty_fields.py [--only-cartas] [--only-cvs] [--dry-run]
"""
import os
import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from utils.cv_parser import parse_cv
from utils.gemini_client import GeminiClient
from utils.cv_generator import CVGenerator
from notion_sync import NotionSync


def main():
    parser = argparse.ArgumentParser(description="Rellena campos vacíos en Notion")
    parser.add_argument("--only-cartas", action="store_true", help="Solo generar cartas de presentación")
    parser.add_argument("--only-cvs", action="store_true", help="Solo generar CVs personalizados")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar qué se haría sin ejecutar")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de ofertas a procesar (0=todas)")
    args = parser.parse_args()

    do_cartas = not args.only_cvs
    do_cvs = not args.only_cartas

    print("=" * 60)
    print("  RELLENANDO CAMPOS VACÍOS EN NOTION")
    print("=" * 60)

    config.validate_config()
    config.load_preferences()

    notion = NotionSync()
    gemini = GeminiClient()
    cv_gen = CVGenerator()

    # Cargar CV original
    cv_path = Path(config.CV_PATH)
    if not cv_path.exists():
        print(f"[Error] CV no encontrado: {cv_path}")
        sys.exit(1)
    cv_text = parse_cv(str(cv_path))
    print(f"[CV] Cargado: {len(cv_text)} caracteres")

    # Verificar campos en Notion
    has_cl = bool(notion._find_prop("Carta Presentación"))
    has_cv = bool(notion._find_prop("CV"))
    print(f"[Notion] Campo 'Carta Presentación': {'✅' if has_cl else '❌ No existe'}")
    print(f"[Notion] Campo 'CV': {'✅' if has_cv else '❌ No existe'}")

    if do_cartas and not has_cl:
        print("[Error] El campo 'Carta Presentación' no existe en Notion. Créalo primero.")
        sys.exit(1)
    if do_cvs and not has_cv:
        print("[Error] El campo 'CV' no existe en Notion. Créalo primero (tipo URL).")
        sys.exit(1)

    # Obtener todas las ofertas
    print("\n[Notion] Cargando todas las ofertas...")
    jobs = notion.get_all_jobs_full()
    print(f"[Notion] {len(jobs)} ofertas encontradas")

    # Filtrar las que necesitan datos
    needs_cl = [j for j in jobs if do_cartas and not j["has_cover_letter"]]
    needs_cv = [j for j in jobs if do_cvs and not j["has_cv"]]

    print(f"\n📊 Resumen:")
    print(f"  - Sin carta de presentación: {len(needs_cl)}")
    print(f"  - Sin CV personalizado: {len(needs_cv)}")
    print(f"  - Total a procesar: {len(set(j['page_id'] for j in needs_cl + needs_cv))}")

    if not needs_cl and not needs_cv:
        print("\n✅ Todos los campos están rellenos. Nada que hacer.")
        return

    if args.dry_run:
        print("\n🔍 [DRY RUN] Se procesarían:")
        for j in needs_cl:
            print(f"  📝 Carta: {j['title']} @ {j['company']}")
        for j in needs_cv:
            print(f"  📄 CV: {j['title']} @ {j['company']}")
        return

    # Procesar
    print()
    updated = 0
    errors = 0
    total = len(set(j['page_id'] for j in needs_cl + needs_cv))
    processed = 0

    for i, job in enumerate(jobs, 1):
        if args.limit and processed >= args.limit:
            print(f"\n[Límite] {args.limit} ofertas procesadas. Para continuar: python fill_empty_fields.py --limit {args.limit}")
            break

        page_id = job["page_id"]
        needs_this_cl = do_cartas and not job["has_cover_letter"]
        needs_this_cv = do_cvs and not job["has_cv"]

        if not needs_this_cl and not needs_this_cv:
            continue

        print(f"[{i}/{len(jobs)}] {job['title']} @ {job['company']}")
        success = False

        # Generar carta de presentación
        if needs_this_cl:
            try:
                desc = f"Puesto: {job['title']}. Empresa: {job['company']}. "
                desc += f"Modalidad: {job['work_mode']}. "
                desc += f"Tecnologías: {', '.join(job['tech_stack'])}. "
                desc += f"Experiencia requerida: {job['required_experience']} años. "
                if job['advice']:
                    desc += f"Consejos: {job['advice']}"

                cover_letter = gemini.generate_cover_letter(
                    cv_text=cv_text,
                    offer_title=job["title"],
                    company=job.get("company", ""),
                    offer_description=desc,
                )
                if notion.update_cover_letter(page_id, cover_letter):
                    print(f"  ✅ Carta generada")
                    success = True
                else:
                    print(f"  ❌ Error guardando carta en Notion")
                    errors += 1
                time.sleep(1)
            except Exception as e:
                print(f"  ❌ Error generando carta: {e}")
                errors += 1

        # Generar CV personalizado
        if needs_this_cv:
            try:
                job_data = {
                    "title": job["title"],
                    "company": job["company"],
                    "tech_stack": job["tech_stack"],
                    "tailored_advice": job["advice"],
                }
                _, cv_pdf_path, cl_pdf_path = cv_gen.generate(gemini, cv_text, job_data, cv_pdf_path=config.CV_PATH)
                if cv_pdf_path:
                    slug = os.path.basename(cv_pdf_path)
                    cv_url = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                    cv_prop = notion._find_prop("CV")
                    if cv_prop:
                        notion.notion.pages.update(
                            page_id=page_id,
                            properties={cv_prop: {"url": cv_url}}
                        )
                        print(f"  ✅ CV generado: {slug}")
                        success = True
                    else:
                        print(f"  ❌ Campo CV no encontrado")
                        errors += 1
                else:
                    print(f"  ❌ Error generando CV")
                    errors += 1
                time.sleep(1)
            except Exception as e:
                print(f"  ❌ Error generando CV: {e}")
                errors += 1

        if success:
            updated += 1
        processed += 1
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"  COMPLETADO")
    print(f"  - Actualizadas: {updated}")
    print(f"  - Errores: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()

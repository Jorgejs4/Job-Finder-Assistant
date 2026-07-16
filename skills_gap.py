#!/usr/bin/env python3
"""
Skills Gap Analysis — Analiza las ofertas en Notion y detecta qué habilidades
faltan en tu CV pero son más demandadas por el mercado.

Uso:
    python skills_gap.py              # Analiza las últimas 25 ofertas
    python skills_gap.py --top 50     # Analiza las últimas 50 ofertas
    python skills_gap.py --output skills_gap_report.md  # Guarda en archivo
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from utils.cv_parser import parse_cv
from utils.gemini_client import GeminiClient
from notion_sync import NotionSync


def main():
    parser = argparse.ArgumentParser(description="Skills Gap Analysis")
    parser.add_argument("--top", type=int, default=25, help="Número de ofertas a analizar")
    parser.add_argument("--output", type=str, help="Archivo de salida (markdown)")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()

    print("=" * 60)
    print("   SKILLS GAP ANALYSIS")
    print("=" * 60)

    # Config
    try:
        config.validate_config()
    except ValueError as e:
        print(f"[Error] {e}")
        sys.exit(1)

    # CV
    cv_path = Path(config.CV_PATH)
    if not cv_path.exists():
        print(f"[Error] CV no encontrado: {cv_path}")
        sys.exit(1)

    print(f"[CV] Leyendo: {cv_path.name}...")
    cv_text = parse_cv(str(cv_path))
    print(f"[CV] OK ({len(cv_text)} caracteres)")

    # Notion
    notion = NotionSync()
    print(f"[Notion] Obteniendo ofertas...")
    all_jobs = notion.get_all_jobs_for_analysis()
    print(f"[Notion] {len(all_jobs)} ofertas totales en la base de datos")

    if not all_jobs:
        print("[Error] No hay ofertas en Notion para analizar")
        sys.exit(1)

    # Tomar las últimas N ofertas (ordenadas por fecha de detección)
    jobs_to_analyze = all_jobs[:args.top]
    print(f"[Análisis] Analizando {len(jobs_to_analyze)} ofertas con Gemini...")

    # Gemini
    gemini = GeminiClient()
    result = gemini.analyze_skills_gap(cv_text, jobs_to_analyze)

    # Output
    if args.json:
        output = {
            "missing_skills": result.missing_skills,
            "summary": result.summary,
            "recommendations": result.recommendations,
            "jobs_analyzed": len(jobs_to_analyze),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print("\n" + "=" * 60)
        print("   RESULTADO — SKILLS GAP")
        print("=" * 60)
        print(f"\n📊 Resumen: {result.summary}\n")
        
        if result.missing_skills:
            print("🔴 Skills faltantes (ordenadas por demanda):\n")
            for i, skill in enumerate(result.missing_skills, 1):
                print(f"  {i}. {skill['skill']} — {skill['count']} ofertas ({skill['percentage']:.0f}%)")
                print(f"     💡 {skill['advice']}")
                print()
        
        if result.recommendations:
            print("🎯 Recomendaciones:\n")
            for i, rec in enumerate(result.recommendations, 1):
                print(f"  {i}. {rec}")
            print()

    # Guardar en archivo si se pide
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(f"# Skills Gap Analysis\n\n")
            f.write(f"**Ofertas analizadas:** {len(jobs_to_analyze)}\n\n")
            f.write(f"## Resumen\n\n{result.summary}\n\n")
            if result.missing_skills:
                f.write("## Skills Faltantes\n\n")
                f.write("| # | Skill | Demandas | % | Consejo |\n")
                f.write("|---|-------|----------|---|--------|\n")
                for i, skill in enumerate(result.missing_skills, 1):
                    f.write(f"| {i} | {skill['skill']} | {skill['count']} | {skill['percentage']:.0f}% | {skill['advice']} |\n")
                f.write("\n")
            if result.recommendations:
                f.write("## Recomendaciones\n\n")
                for i, rec in enumerate(result.recommendations, 1):
                    f.write(f"{i}. {rec}\n")
        print(f"[OK] Guardado en {args.output}")


if __name__ == "__main__":
    main()

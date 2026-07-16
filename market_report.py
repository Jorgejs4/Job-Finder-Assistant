#!/usr/bin/env python3
"""
Market Report — Genera un informe de mercado semanal con tendencias de tech,
rangos salariales, empresas que más contratan y análisis de demanda.

Uso:
    python market_report.py                    # Informe HTML en stdout
    python market_report.py --output report.html  # Guarda en archivo
    python market_report.py --email             # Envía por email
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
from utils.notifications import EmailNotifier
from notion_sync import NotionSync


def main():
    parser = argparse.ArgumentParser(description="Market Report Generator")
    parser.add_argument("--top", type=int, default=50, help="Número de ofertas a analizar")
    parser.add_argument("--output", type=str, help="Archivo HTML de salida")
    parser.add_argument("--email", action="store_true", help="Enviar por email")
    args = parser.parse_args()

    print("=" * 60)
    print("   MARKET REPORT — INFORME DE MERCADO")
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

    cv_text = parse_cv(str(cv_path))

    # Notion
    notion = NotionSync()
    print(f"[Notion] Obteniendo ofertas...")
    all_jobs = notion.get_all_jobs_for_analysis()
    print(f"[Notion] {len(all_jobs)} ofertas totales")

    if not all_jobs:
        print("[Error] No hay ofertas para generar el informe")
        sys.exit(1)

    jobs_to_analyze = all_jobs[:args.top]
    print(f"[Análisis] Generando informe con {len(jobs_to_analyze)} ofertas...")

    # Gemini
    gemini = GeminiClient()
    report_html = gemini.generate_market_report(cv_text, jobs_to_analyze)

    # Stats básicas
    all_techs = {}
    companies = {}
    remote_count = 0
    salaries = []

    for job in jobs_to_analyze:
        for tech in job.get("tech_stack", []):
            all_techs[tech] = all_techs.get(tech, 0) + 1
        company = job.get("company", "N/A")
        companies[company] = companies.get(company, 0) + 1
        if job.get("work_mode") == "Remoto":
            remote_count += 1
        salary = job.get("salary")
        if salary:
            try:
                salaries.append(int(str(salary).replace(".", "").replace(",", "")))
            except (ValueError, TypeError):
                pass

    avg_salary = sum(salaries) // len(salaries) if salaries else 0
    remote_pct = (remote_count / len(jobs_to_analyze) * 100) if jobs_to_analyze else 0

    # Construir email HTML completo
    full_html = f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#1f2937">
    <div style="background:linear-gradient(135deg,#059669,#0d9488);color:#fff;padding:24px;border-radius:12px 12px 0 0">
        <h1 style="margin:0;font-size:22px">📊 Informe de Mercado Semanal</h1>
        <p style="margin:8px 0 0 0;opacity:0.9">Ofertas analizadas: {len(jobs_to_analyze)} | Salario promedio: {avg_salary}€ | Remoto: {remote_pct:.0f}%</p>
    </div>
    <div style="padding:20px;border:1px solid #e5e7eb">
        {report_html}
    </div>
    <div style="background:#f9fafb;padding:16px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;text-align:center;font-size:12px;color:#9ca3af">
        Generado automáticamente por Job Scraper Assistant — {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}
    </div>
</body>
</html>"""

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_html)
        print(f"[OK] Informe guardado en {args.output}")

    if args.email:
        notifier = EmailNotifier()
        if notifier.enabled:
            subject = f"[Job Scraper] Informe de Mercado — {len(jobs_to_analyze)} ofertas"
            msg = __import__('email.mime.multipart', fromlist=['MIMEMultipart']).MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = notifier.smtp_user
            msg["To"] = notifier.notify_to
            from email.mime.text import MIMEText
            msg.attach(MIMEText(full_html, "html"))
            
            import smtplib
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
                    server.login(notifier.smtp_user, notifier.smtp_password)
                    server.sendmail(notifier.smtp_user, notifier.notify_to, msg.as_string())
                print(f"[Email] Informe enviado a {notifier.notify_to}")
            except Exception as e:
                print(f"[Email] Error: {e}")
        else:
            print("[Email] No configurado. Configura SMTP_GMAIL_USER, SMTP_GMAIL_PASSWORD, NOTIFY_EMAIL")

    if not args.output and not args.email:
        print("\n" + full_html)


if __name__ == "__main__":
    main()

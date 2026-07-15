import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Any


class EmailNotifier:
    """
    Envía resúmenes de ejecución del scraper por email.
    Configura SMTP_GMAIL_USER, SMTP_GMAIL_PASSWORD y NOTIFY_EMAIL en .env
    """
    def __init__(self):
        self.smtp_user = os.getenv("SMTP_GMAIL_USER", "")
        self.smtp_password = os.getenv("SMTP_GMAIL_PASSWORD", "")
        self.notify_to = os.getenv("NOTIFY_EMAIL", self.smtp_user)
        self.enabled = bool(self.smtp_user and self.smtp_password and self.notify_to)

    def send_summary(
        self,
        jobs_added: int,
        jobs_analyzed: int,
        scraper_stats: Dict[str, Dict[str, Any]],
        top_jobs: List[Dict[str, Any]],
        errors: List[str],
    ):
        if not self.enabled:
            print("[Email] Notificación deshabilitada (faltan SMTP_GMAIL_USER/SMTP_GMAIL_PASSWORD/NOTIFY_EMAIL)")
            return False

        date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        subject = f"[Job Scraper] Resumen {date_str} — {jobs_added} ofertas nuevas"

        html = self._build_html(date_str, jobs_added, jobs_analyzed, scraper_stats, top_jobs, errors)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = self.notify_to
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.notify_to, msg.as_string())
            print(f"[Email] Resumen enviado a {self.notify_to}")
            return True
        except Exception as e:
            print(f"[Email] Error enviando email: {e}")
            return False

    def _build_html(
        self,
        date_str: str,
        jobs_added: int,
        jobs_analyzed: int,
        scraper_stats: Dict[str, Dict[str, Any]],
        top_jobs: List[Dict[str, Any]],
        errors: List[str],
    ) -> str:
        scraper_rows = ""
        for name, stats in scraper_stats.items():
            found = stats.get("found", 0)
            failed = stats.get("failed", False)
            status_icon = "&#10060;" if failed else "&#9989;"
            scraper_rows += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #eee;font-weight:600">{name}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{found}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{status_icon}</td>
            </tr>"""

        top_jobs_html = ""
        for j in top_jobs[:10]:
            score = j.get("match_score", 0)
            color = "#22c55e" if score >= 70 else "#eab308" if score >= 50 else "#ef4444"
            top_jobs_html += f"""
            <tr>
                <td style="padding:6px;border-bottom:1px solid #eee">{j.get('title', 'N/A')}</td>
                <td style="padding:6px;border-bottom:1px solid #eee">{j.get('company', 'N/A')}</td>
                <td style="padding:6px;border-bottom:1px solid #eee">{j.get('source', 'N/A')}</td>
                <td style="padding:6px;border-bottom:1px solid #eee;text-align:center">
                    <span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-weight:600">{score}%</span>
                </td>
                <td style="padding:6px;border-bottom:1px solid #eee">
                    <a href="{j.get('link', '#')}" style="color:#3b82f6">Ver</a>
                </td>
            </tr>"""

        errors_html = ""
        if errors:
            errors_list = "".join(f"<li>{e}</li>" for e in errors)
            errors_html = f"""
            <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;margin:20px 0">
                <h3 style="color:#dc2626;margin:0 0 8px 0">&#9888; Errores en la ejecución</h3>
                <ul style="margin:0;padding-left:20px;color:#7f1d1d">{errors_list}</ul>
            </div>"""

        return f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#1f2937">
            <div style="background:linear-gradient(135deg,#1e40af,#7c3aed);color:#fff;padding:24px;border-radius:12px 12px 0 0">
                <h1 style="margin:0;font-size:22px">&#128205; Resumen Job Scraper</h1>
                <p style="margin:8px 0 0 0;opacity:0.9">{date_str}</p>
            </div>

            <div style="background:#f9fafb;padding:20px;border:1px solid #e5e7eb">
                <div style="display:flex;gap:16px;flex-wrap:wrap">
                    <div style="background:#fff;border-radius:8px;padding:16px;flex:1;min-width:140px;text-align:center;border:1px solid #e5e7eb">
                        <div style="font-size:28px;font-weight:700;color:#22c55e">{jobs_added}</div>
                        <div style="font-size:13px;color:#6b7280">Nuevas ofertas</div>
                    </div>
                    <div style="background:#fff;border-radius:8px;padding:16px;flex:1;min-width:140px;text-align:center;border:1px solid #e5e7eb">
                        <div style="font-size:28px;font-weight:700;color:#3b82f6">{jobs_analyzed}</div>
                        <div style="font-size:13px;color:#6b7280">Analizadas por IA</div>
                    </div>
                    <div style="background:#fff;border-radius:8px;padding:16px;flex:1;min-width:140px;text-align:center;border:1px solid #e5e7eb">
                        <div style="font-size:28px;font-weight:700;color:#8b5cf6">{len(scraper_stats)}</div>
                        <div style="font-size:13px;color:#6b7280">Scrapers activos</div>
                    </div>
                </div>
            </div>

            <div style="padding:20px;border:1px solid #e5e7eb;border-top:none">
                <h2 style="margin:0 0 12px 0;font-size:17px">&#128202; Scrapers</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px">
                    <thead>
                        <tr style="background:#f3f4f6">
                            <th style="padding:8px;text-align:left">Plataforma</th>
                            <th style="padding:8px;text-align:center">Ofertas</th>
                            <th style="padding:8px;text-align:center">Estado</th>
                        </tr>
                    </thead>
                    <tbody>{scraper_rows}</tbody>
                </table>

                {errors_html}

                <h2 style="margin:24px 0 12px 0;font-size:17px">&#127919; Top ofertas</h2>
                <table style="width:100%;border-collapse:collapse;font-size:13px">
                    <thead>
                        <tr style="background:#f3f4f6">
                            <th style="padding:6px;text-align:left">Puesto</th>
                            <th style="padding:6px;text-align:left">Empresa</th>
                            <th style="padding:6px;text-align:left">Fuente</th>
                            <th style="padding:6px;text-align:center">Match</th>
                            <th style="padding:6px;text-align:left">Enlace</th>
                        </tr>
                    </thead>
                    <tbody>{top_jobs_html}</tbody>
                </table>
            </div>

            <div style="background:#f9fafb;padding:16px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;text-align:center;font-size:12px;color:#9ca3af">
                Generado automáticamente por Job Scraper Assistant
            </div>
        </body>
        </html>
        """

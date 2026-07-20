"""
Webhook Notifier — Envía notificaciones a servicios externos cuando
se detectan ofertas con alto nivel de compatibilidad.

Soporta:
- Webhooks genéricos (POST JSON a cualquier URL)
- Slack (con formato de bloques)
- Discord (con embeds)

Configuración:
  WEBHOOK_URL=https://hooks.slack.com/services/...  (o Discord, o URL genérica)
  WEBHOOK_MIN_MATCH=80  (match mínimo para trigger, default: 80)
"""
import os
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any


class WebhookNotifier:
    def __init__(self):
        self.url = os.getenv("WEBHOOK_URL", "")
        _wm = os.getenv("WEBHOOK_MIN_MATCH", "80")
        self.min_match = int(_wm) if _wm else 80
        self.enabled = bool(self.url)
        
        if self.enabled:
            # Detectar tipo de webhook
            if "slack.com" in self.url:
                self.webhook_type = "slack"
            elif "discord.com" in self.url or "discordapp.com" in self.url:
                self.webhook_type = "discord"
            else:
                self.webhook_type = "generic"
            print(f"[Webhook] Configurado: tipo={self.webhook_type}, min_match={self.min_match}%")
        else:
            print("[Webhook] No configurado (WEBHOOK_URL no establecido)")

    def notify_high_match_jobs(self, jobs: List[Dict[str, Any]], stats: Dict[str, Any] = None) -> int:
        """
        Envía notificación para ofertas con match >= min_match.
        Retorna el número de notificaciones enviadas.
        """
        if not self.enabled:
            return 0

        high_match_jobs = [j for j in jobs if j.get("match_score", 0) >= self.min_match]
        
        if not high_match_jobs:
            return 0

        sent = 0
        for job in high_match_jobs:
            try:
                if self.webhook_type == "slack":
                    self._send_slack(job)
                elif self.webhook_type == "discord":
                    self._send_discord(job)
                else:
                    self._send_generic(job, stats)
                sent += 1
            except Exception as e:
                print(f"[Webhook] Error enviando notificación: {e}")

        print(f"[Webhook] {sent}/{len(high_match_jobs)} notificaciones enviadas")
        return sent

    def notify_summary(self, jobs_added: int, jobs_analyzed: int, scraper_stats: Dict) -> bool:
        """
        Envía un resumen general de la ejecución.
        """
        if not self.enabled:
            return False

        try:
            if self.webhook_type == "slack":
                self._send_slack_summary(jobs_added, jobs_analyzed, scraper_stats)
            elif self.webhook_type == "discord":
                self._send_discord_summary(jobs_added, jobs_analyzed, scraper_stats)
            else:
                self._send_generic_summary(jobs_added, jobs_analyzed, scraper_stats)
            return True
        except Exception as e:
            print(f"[Webhook] Error enviando resumen: {e}")
            return False

    def _send_slack(self, job: Dict[str, Any]):
        """Envía notificación formateada para Slack."""
        score = job.get("match_score", 0)
        emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Nueva oferta de alta compatibilidad"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Puesto:*\n{job.get('title', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Empresa:*\n{job.get('company', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Match:*\n{score}%"},
                    {"type": "mrkdwn", "text": f"*Modalidad:*\n{job.get('work_mode', 'N/A')}"},
                ]
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Salario:*\n{job.get('salary', 'N/A')}€"},
                    {"type": "mrkdwn", "text": f"*Fuente:*\n{job.get('source', 'N/A')}"},
                ]
            }
        ]

        if job.get("tech_stack"):
            techs = ", ".join(job["tech_stack"][:5])
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Stack:* {techs}"}
            })

        if job.get("tailored_advice"):
            advice = job["tailored_advice"][:200]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Consejo:* {advice}"}
            })

        if job.get("link"):
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔗 Ver oferta"},
                        "url": job["link"]
                    }
                ]
            })

        payload = {"blocks": blocks}
        self._post(payload)

    def _send_discord(self, job: Dict[str, Any]):
        """Envía notificación formateada para Discord."""
        score = job.get("match_score", 0)
        color = 0x22c55e if score >= 80 else 0xeab308 if score >= 60 else 0xef4444
        
        embed = {
            "title": f"{'🟢' if score >= 80 else '🟡' if score >= 60 else '🔴'} {job.get('title', 'N/A')}",
            "description": f"**{job.get('company', 'N/A')}** — {job.get('work_mode', 'N/A')}",
            "color": color,
            "fields": [
                {"name": "Match", "value": f"{score}%", "inline": True},
                {"name": "Salario", "value": f"{job.get('salary', 'N/A')}€", "inline": True},
                {"name": "Fuente", "value": job.get('source', 'N/A'), "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

        if job.get("tech_stack"):
            embed["fields"].append({
                "name": "Stack",
                "value": ", ".join(job["tech_stack"][:5]),
                "inline": False
            })

        if job.get("link"):
            embed["url"] = job["link"]

        payload = {"embeds": [embed]}
        self._post(payload)

    def _send_generic(self, job: Dict[str, Any], stats: Dict = None):
        """Envía notificación JSON genérica."""
        payload = {
            "event": "high_match_job",
            "timestamp": datetime.utcnow().isoformat(),
            "job": {
                "title": job.get("title"),
                "company": job.get("company"),
                "match_score": job.get("match_score"),
                "work_mode": job.get("work_mode"),
                "salary": job.get("salary"),
                "source": job.get("source"),
                "tech_stack": job.get("tech_stack", []),
                "link": job.get("link"),
                "tailored_advice": job.get("tailored_advice"),
            }
        }
        if stats:
            payload["run_stats"] = stats
        self._post(payload)

    def _send_slack_summary(self, jobs_added: int, jobs_analyzed: int, scraper_stats: Dict):
        """Envía resumen de ejecución a Slack."""
        scrapers_ok = sum(1 for s in scraper_stats.values()
                         if not s.get("failed") and s.get("found", 0) > 0)
        scrapers_total = len(scraper_stats)
        
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📊 Resumen de ejecución Job Scraper"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Ofertas nuevas:*\n{jobs_added}"},
                    {"type": "mrkdwn", "text": f"*Analizadas IA:*\n{jobs_analyzed}"},
                    {"type": "mrkdwn", "text": f"*Scrapers OK:*\n{scrapers_ok}/{scrapers_total}"},
                ]
            }
        ]
        payload = {"blocks": blocks}
        self._post(payload)

    def _send_discord_summary(self, jobs_added: int, jobs_analyzed: int, scraper_stats: Dict):
        """Envía resumen de ejecución a Discord."""
        scrapers_ok = sum(1 for s in scraper_stats.values()
                         if not s.get("failed") and s.get("found", 0) > 0)
        embed = {
            "title": "📊 Resumen de ejecución Job Scraper",
            "color": 0x3b82f6,
            "fields": [
                {"name": "Ofertas nuevas", "value": str(jobs_added), "inline": True},
                {"name": "Analizadas IA", "value": str(jobs_analyzed), "inline": True},
                {"name": "Scrapers OK", "value": f"{scrapers_ok}/{len(scraper_stats)}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        payload = {"embeds": [embed]}
        self._post(payload)

    def _send_generic_summary(self, jobs_added: int, jobs_analyzed: int, scraper_stats: Dict):
        """Envía resumen JSON genérico."""
        payload = {
            "event": "run_summary",
            "timestamp": datetime.utcnow().isoformat(),
            "jobs_added": jobs_added,
            "jobs_analyzed": jobs_analyzed,
            "scraper_stats": scraper_stats,
        }
        self._post(payload)

    def _post(self, payload: dict):
        """Envía POST con el payload a la URL del webhook."""
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                self.url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code >= 400:
                print(f"[Webhook] Error HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                print(f"[Webhook] OK (HTTP {resp.status_code})")

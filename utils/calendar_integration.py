"""
Integración con Google Calendar para recordatorios de follow-up y entrevistas.
Genera eventos .ics que el usuario puede importar en su calendario.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path


def create_followup_event(title: str, company: str, link: str, days_since_applied: int) -> str:
    """
    Genera un archivo .ics para un recordatorio de follow-up.
    Devuelve la ruta del archivo generado.
    """
    event_title = f"Follow-up: {title} @ {company}"
    now = datetime.now()
    event_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    event_end = event_start + timedelta(minutes=15)

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//JobScraperAI//FollowUp//ES
BEGIN:VEVENT
DTSTART:{event_start.strftime('%Y%m%dT%H%M%S')}
DTEND:{event_end.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{event_title}
DESCRIPTION:Oferta aplicada hace {days_since_applied} días.\\nVer oferta: {link}
URL:{link}
BEGIN:VALARM
TRIGGER:-PT0M
ACTION:DISPLAY
DESCRIPTION:Follow-up pendiente: {title} @ {company}
END:VALARM
END:VEVENT
END:VCALENDAR"""

    output_dir = Path(__file__).resolve().parent.parent / "results"
    os.makedirs(output_dir, exist_ok=True)
    filename = f"followup_{company[:20].replace(' ', '_')}_{now.strftime('%Y%m%d')}.ics"
    filepath = output_dir / filename
    filepath.write_text(ics_content, encoding="utf-8")
    return str(filepath)


def create_interview_event(title: str, company: str, link: str, interview_date: str = None) -> str:
    """
    Genera un archivo .ics para un evento de entrevista.
    Si no se proporciona fecha, usa mañana a las 10:00.
    Devuelve la ruta del archivo generado.
    """
    event_title = f"Entrevista: {title} @ {company}"

    if interview_date:
        try:
            event_start = datetime.strptime(interview_date, "%Y-%m-%d %H:%M")
        except ValueError:
            event_start = datetime.now() + timedelta(days=1)
            event_start = event_start.replace(hour=10, minute=0, second=0, microsecond=0)
    else:
        event_start = datetime.now() + timedelta(days=1)
        event_start = event_start.replace(hour=10, minute=0, second=0, microsecond=0)

    event_end = event_start + timedelta(hours=1)

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//JobScraperAI//Interview//ES
BEGIN:VEVENT
DTSTART:{event_start.strftime('%Y%m%dT%H%M%S')}
DTEND:{event_end.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{event_title}
DESCRIPTION:Preparar: revisar empresa, practicar preguntas técnicas.\\nOferta: {link}
URL:{link}
BEGIN:VALARM
TRIGGER:-PT60M
ACTION:DISPLAY
DESCRIPTION:Entrevista en 1 hora: {title} @ {company}
END:VALARM
BEGIN:VALARM
TRIGGER:-P1D
ACTION:DISPLAY
DESCRIPTION:Entrevista mañana: {title} @ {company}
END:VALARM
END:VEVENT
END:VCALENDAR"""

    output_dir = Path(__file__).resolve().parent.parent / "results"
    os.makedirs(output_dir, exist_ok=True)
    filename = f"interview_{company[:20].replace(' ', '_')}_{event_start.strftime('%Y%m%d')}.ics"
    filepath = output_dir / filename
    filepath.write_text(ics_content, encoding="utf-8")
    return str(filepath)

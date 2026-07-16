import os
import json
import hashlib
from pathlib import Path
from fpdf import FPDF


class CVGenerator:
    """
    Genera un CV personalizado en PDF para cada oferta de empleo.
    Usa Gemini para adaptar el contenido y fpdf2 para renderizar el PDF.
    """
    def __init__(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.join(Path(__file__).resolve().parent.parent, "results", "cvs")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, gemini_client, cv_text: str, job_data: dict) -> str:
        """
        Genera un CV personalizado en PDF para una oferta específica.
        Devuelve la ruta del PDF generado, o None si falla.
        """
        title = job_data.get("title", "")
        company = job_data.get("company", "")
        advice = job_data.get("tailored_advice", "")
        tech_stack = ", ".join(job_data.get("tech_stack", [])[:10])

        # Nombre de archivo basado en hash del título+empresa
        slug = hashlib.md5(f"{title}-{company}".encode()).hexdigest()[:12]
        pdf_path = os.path.join(self.output_dir, f"cv_{slug}.pdf")

        if os.path.exists(pdf_path):
            return pdf_path

        # Pedir a Gemini que genere el contenido del CV
        try:
            cv_content = gemini_client.generate_custom_cv(cv_text, title, company, advice, tech_stack)
        except Exception as e:
            print(f"  - [CV] Error generando contenido con Gemini: {e}")
            return None

        # Renderizar a PDF
        try:
            self._render_pdf(cv_content, pdf_path)
            print(f"  - [CV] PDF generado: {os.path.basename(pdf_path)}")
            return pdf_path
        except Exception as e:
            print(f"  - [CV] Error renderizando PDF: {e}")
            return None

    def _render_pdf(self, cv_data: dict, output_path: str):
        """Renderiza los datos del CV a un PDF profesional."""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # -- Nombre y contacto --
        name = cv_data.get("name", "")
        if name:
            pdf.set_font("Helvetica", "B", 20)
            pdf.cell(0, 10, name, new_x="LMARGIN", new_y="NEXT")

        contact = cv_data.get("contact", "")
        if contact:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 6, contact, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        pdf.ln(4)

        # -- Resumen profesional --
        summary = cv_data.get("summary", "")
        if summary:
            self._section(pdf, "PERFIL PROFESIONAL")
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, summary)
            pdf.ln(3)

        # -- Experiencia --
        experience = cv_data.get("experience", [])
        if experience:
            self._section(pdf, "EXPERIENCIA")
            for exp in experience:
                role = exp.get("role", "")
                company_name = exp.get("company", "")
                period = exp.get("period", "")
                desc = exp.get("description", "")

                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 6, role, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 5, f"{company_name} | {period}" if period else company_name, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                if desc:
                    pdf.set_font("Helvetica", "", 10)
                    pdf.multi_cell(0, 5, desc)
                pdf.ln(2)

        # -- Formación --
        education = cv_data.get("education", [])
        if education:
            self._section(pdf, "FORMACIÓN")
            for edu in education:
                degree = edu.get("degree", "")
                inst = edu.get("institution", "")
                year = edu.get("year", "")
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, degree, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 5, f"{inst} | {year}" if year else inst, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

        # -- Habilidades --
        skills = cv_data.get("skills", [])
        if skills:
            self._section(pdf, "HABILIDADES")
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, " | ".join(skills))
            pdf.ln(3)

        # -- Proyectos relevantes --
        projects = cv_data.get("projects", [])
        if projects:
            self._section(pdf, "PROYECTOS RELEVANTES")
            for proj in projects:
                proj_name = proj.get("name", "")
                proj_desc = proj.get("description", "")
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, proj_name, new_x="LMARGIN", new_y="NEXT")
                if proj_desc:
                    pdf.set_font("Helvetica", "", 10)
                    pdf.multi_cell(0, 5, proj_desc)
                pdf.ln(1)

        pdf.output(output_path)

    def _section(self, pdf, title):
        """Dibuja un título de sección con línea separadora."""
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(30, 64, 175)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(3)
        pdf.set_text_color(0, 0, 0)

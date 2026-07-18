import os
import json
import hashlib
import base64
from pathlib import Path
from fpdf import FPDF

from utils.photo_extractor import extract_photo


class CVGenerator:
    """
    Genera CVs personalizados en HTML (preview) + PDF (descarga).
    Usa Gemini para contenido y fpdf2 para renderizar el PDF.
    """
    def __init__(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.join(Path(__file__).resolve().parent.parent, "results", "cvs")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self._photo_path = None

    def _ensure_photo(self, cv_pdf_path: str):
        """Extrae la foto del CV source una sola vez."""
        if self._photo_path is not None:
            return self._photo_path
        self._photo_path = extract_photo(cv_pdf_path, self.output_dir)
        return self._photo_path

    @staticmethod
    def _slug(title: str, company: str) -> str:
        return hashlib.md5(f"{title}-{company}".encode()).hexdigest()[:12]

    def generate(self, gemini_client, cv_text: str, job_data: dict, cv_pdf_path: str = None, feedback: str = None, cover_letter: str = None, language: str = "es") -> tuple:
        """
        Genera CV personalizado (HTML + PDF) + Carta de Presentación (PDF) usando Gemini.
        Retorna (html_path, pdf_path, cover_letter_pdf_path) o (None, None, None) si falla.
        """
        title = job_data.get("title", "")
        company = job_data.get("company", "")
        advice = job_data.get("tailored_advice", "")
        tech_stack = ", ".join(job_data.get("tech_stack", [])[:10])

        slug = self._slug(title, company)
        html_path = os.path.join(self.output_dir, f"cv_{slug}.html")
        pdf_path = os.path.join(self.output_dir, f"cv_{slug}.pdf")
        cl_pdf_path = os.path.join(self.output_dir, f"cover_{slug}.pdf")

        # Extraer foto si tenemos el PDF source
        photo_path = None
        if cv_pdf_path:
            photo_path = self._ensure_photo(cv_pdf_path)

        # Pedir a Gemini que genere el contenido (con feedback si existe)
        try:
            cv_content = gemini_client.generate_cv_content(
                cv_text, title, company, advice, tech_stack, feedback=feedback, language=language
            )
        except Exception as e:
            print(f"  - [CV] Error generando contenido con Gemini: {e}")
            return None, None, None

        # Renderizar HTML + PDF del CV
        try:
            self._render_html(cv_content, photo_path, html_path, language=language)
            print(f"  - [CV] HTML generado: {os.path.basename(html_path)}")
        except Exception as e:
            print(f"  - [CV] Error renderizando HTML: {e}")
            html_path = None

        try:
            self._render_pdf(cv_content, photo_path, pdf_path)
            print(f"  - [CV] PDF generado: {os.path.basename(pdf_path)}")
        except Exception as e:
            print(f"  - [CV] Error renderizando PDF: {e}")
            pdf_path = None

        # Generar PDF de Carta de Presentación
        if cover_letter:
            try:
                self._render_cover_letter_pdf(
                    cover_letter, cv_content, photo_path, cl_pdf_path,
                    company=company, role_title=title
                )
                print(f"  - [Carta] PDF generado: {os.path.basename(cl_pdf_path)}")
            except Exception as e:
                print(f"  - [Carta] Error renderizando PDF: {e}")
                cl_pdf_path = None
        else:
            cl_pdf_path = None

        return html_path, pdf_path, cl_pdf_path

    def generate_from_data(self, cv_content: dict, title: str = "", company: str = "", photo_path: str = None, cover_letter: str = None, language: str = "es") -> tuple:
        """
        Genera CV a partir de datos pre-computed (sin Gemini).
        Retorna (html_path, pdf_path, cover_letter_pdf_path).
        """
        slug = self._slug(title, company)
        html_path = os.path.join(self.output_dir, f"cv_{slug}.html")
        pdf_path = os.path.join(self.output_dir, f"cv_{slug}.pdf")
        cl_pdf_path = os.path.join(self.output_dir, f"cover_{slug}.pdf")

        try:
            self._render_html(cv_content, photo_path, html_path, language=language)
        except Exception as e:
            print(f"  - [CV] Error renderizando HTML: {e}")
            html_path = None

        try:
            self._render_pdf(cv_content, photo_path, pdf_path)
        except Exception as e:
            print(f"  - [CV] Error renderizando PDF: {e}")
            pdf_path = None

        if cover_letter:
            try:
                self._render_cover_letter_pdf(
                    cover_letter, cv_content, photo_path, cl_pdf_path,
                    company=company, role_title=title
                )
            except Exception as e:
                print(f"  - [Carta] Error renderizando PDF: {e}")
                cl_pdf_path = None
        else:
            cl_pdf_path = None

        return html_path, pdf_path, cl_pdf_path

    def regenerate_with_feedback(self, gemini_client, cv_text: str, job_data: dict, feedback: str, cv_pdf_path: str = None, cover_letter: str = None, language: str = "es") -> tuple:
        """
        Regenera un CV incorporando el feedback del usuario.
        Sobreescribe HTML + PDF existentes.
        Retorna (html_path, pdf_path, cover_letter_pdf_path).
        """
        print(f"  - [CV] Regenerando con feedback: {feedback[:80]}...")
        return self.generate(gemini_client, cv_text, job_data, cv_pdf_path=cv_pdf_path, feedback=feedback, cover_letter=cover_letter, language=language)

    def generate_cover_letter_pdf(self, cover_letter_text: str, job_data: dict, cv_pdf_path: str = None) -> str:
        """
        Genera solo el PDF de la carta de presentación (sin CV).
        Retorna la ruta del PDF o None si falla.
        """
        title = job_data.get("title", "")
        company = job_data.get("company", "")
        slug = self._slug(title, company)
        cl_pdf_path = os.path.join(self.output_dir, f"cover_{slug}.pdf")

        photo_path = None
        if cv_pdf_path:
            photo_path = self._ensure_photo(cv_pdf_path)

        # Usar datos básicos del CV si no tenemos contenido completo
        cv_content = {
            "name": job_data.get("candidate_name", ""),
            "contact": job_data.get("candidate_contact", ""),
        }

        try:
            self._render_cover_letter_pdf(
                cover_letter_text, cv_content, photo_path, cl_pdf_path,
                company=company, role_title=title
            )
            print(f"  - [Carta] PDF generado: {os.path.basename(cl_pdf_path)}")
            return cl_pdf_path
        except Exception as e:
            print(f"  - [Carta] Error renderizando PDF: {e}")
            return None

    def _render_html(self, cv_data: dict, photo_path: str = None, output_path: str = None, language: str = "es"):
        """Renderiza el CV a HTML usando Jinja2."""
        from jinja2 import Environment, FileSystemLoader

        templates_dir = os.path.join(Path(__file__).resolve().parent.parent, "templates")
        env = Environment(loader=FileSystemLoader(templates_dir))
        template = env.get_template("cv_template.html")

        # Preparar foto como base64
        photo_b64 = None
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                photo_b64 = base64.b64encode(f.read()).decode()

        # Normalizar skills: si es lista, convertir a dict agrupado
        skills = cv_data.get("skills", {})
        if isinstance(skills, list):
            skills = {"Tecnologías": skills}

        # Normalizar experience: description como lista de bullet points
        experience = cv_data.get("experience", [])
        for exp in experience:
            desc = exp.get("description", "")
            if isinstance(desc, str):
                exp["description"] = [b.strip() for b in desc.split("\n") if b.strip()]

        section_names = {
            "es": {"summary": "Perfil Profesional", "experience": "Experiencia Laboral", "education": "Formación", "skills": "Habilidades", "projects": "Proyectos Relevantes"},
            "en": {"summary": "Professional Summary", "experience": "Work Experience", "education": "Education", "skills": "Skills", "projects": "Projects"},
        }.get(language, {
            "summary": "Perfil Profesional", "experience": "Experiencia Laboral", "education": "Formación", "skills": "Habilidades", "projects": "Proyectos Relevantes"
        })

        html = template.render(
            name=cv_data.get("name", ""),
            contact=cv_data.get("contact", ""),
            photo_base64=photo_b64,
            summary=cv_data.get("summary", ""),
            experience=experience,
            education=cv_data.get("education", []),
            skills=skills,
            projects=cv_data.get("projects", []),
            language=language,
            section_names=section_names,
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    def _render_pdf(self, cv_data: dict, photo_path: str = None, output_path: str = None):
        """Renderiza los datos del CV a un PDF profesional con foto."""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # -- Foto + Nombre --
        has_photo = photo_path and os.path.exists(photo_path)
        if has_photo:
            pdf.image(photo_path, x=160, y=12, w=30)
            name_width = 140
        else:
            name_width = 190

        name = cv_data.get("name", "")
        if name:
            pdf.set_font("Helvetica", "B", 20)
            pdf.cell(name_width, 10, name, new_x="LMARGIN", new_y="NEXT")

        contact = cv_data.get("contact", "")
        if contact:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(name_width, 6, contact, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

        pdf.ln(4)

        # -- Resumen profesional --
        summary = cv_data.get("summary", "")
        if summary:
            self._section(pdf, "PERFIL PROFESIONAL")
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, summary)
            pdf.ln(3)

        # -- Experiencia con bullet points --
        experience = cv_data.get("experience", [])
        if experience:
            self._section(pdf, "EXPERIENCIA LABORAL")
            for exp in experience:
                role = exp.get("role", "")
                company_name = exp.get("company", "")
                period = exp.get("period", "")

                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 6, role, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 5, f"{company_name} | {period}" if period else company_name, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

                desc = exp.get("description", "")
                if desc:
                    pdf.set_font("Helvetica", "", 10)
                    if isinstance(desc, list):
                        for bullet in desc:
                            pdf.cell(5, 5, "")
                            pdf.set_font("Helvetica", "", 10)
                            pdf.multi_cell(0, 5, f"- {bullet}")
                    else:
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

        # -- Habilidades agrupadas --
        skills = cv_data.get("skills", [])
        if skills:
            self._section(pdf, "HABILIDADES")
            pdf.set_font("Helvetica", "", 10)
            if isinstance(skills, dict):
                for category, items in skills.items():
                    if isinstance(items, list):
                        skills_str = ", ".join(items)
                    else:
                        skills_str = str(items)
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.cell(0, 5, f"{category}:", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 10)
                    pdf.cell(5, 5, "")
                    pdf.multi_cell(0, 5, skills_str)
            elif isinstance(skills, list):
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

    def _render_cover_letter_pdf(self, cover_letter_text: str, cv_data: dict, photo_path: str = None, output_path: str = None, company: str = "", role_title: str = ""):
        """Renderiza una carta de presentación a PDF usando WeasyPrint + template HTML."""
        from jinja2 import Environment, FileSystemLoader
        from weasyprint import HTML

        templates_dir = os.path.join(Path(__file__).resolve().parent.parent, "templates")
        env = Environment(loader=FileSystemLoader(templates_dir))
        template = env.get_template("cover_letter_template.html")

        photo_b64 = None
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                photo_b64 = base64.b64encode(f.read()).decode()

        paragraphs = [p.strip() for p in cover_letter_text.split("\n") if p.strip()]

        from datetime import date
        today = date.today().strftime("%d de %B de %Y")

        html = template.render(
            name=cv_data.get("name", ""),
            contact=cv_data.get("contact", ""),
            photo_base64=photo_b64,
            date=today,
            company=company,
            role_title=role_title,
            location="",
            paragraphs=paragraphs,
            closing_greeting="Atentamente,",
            language="es",
        )

        HTML(string=html).write_pdf(output_path)

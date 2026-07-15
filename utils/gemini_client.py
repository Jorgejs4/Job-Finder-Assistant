import json
import google.generativeai as genai
from pydantic import BaseModel, Field
from typing import List, Optional
import config

# Configurar el SDK de Gemini
if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)

class ProfileAnalysis(BaseModel):
    recommended_roles: List[str] = Field(
        description="Lista de títulos de puestos de trabajo ideales para buscar basados en el CV (máximo 4, ej: 'React Developer', 'Frontend Engineer')."
    )
    key_skills: List[str] = Field(
        description="Lista de habilidades técnicas y herramientas principales (ej: ['Python', 'Docker', 'React'])."
    )
    years_of_experience: float = Field(
        description="Años estimados de experiencia laboral detectados en el CV."
    )
    summary: str = Field(
        description="Un breve resumen profesional del candidato en español."
    )

class OfferMatch(BaseModel):
    match_score: int = Field(
        description="Puntuación de coincidencia del 0 al 100 de qué tan bien encaja el CV en la oferta. Sé riguroso y objetivo, puntuando bajo si el rol no coincide en absoluto."
    )
    tech_stack: List[str] = Field(
        description="Lista de tecnologías y herramientas requeridas por la oferta (ej: ['Docker', 'AWS', 'FastAPI']). Extrae las tecnologías reales mencionadas en la oferta, no pongas siempre las mismas."
    )
    tailored_advice: str = Field(
        description="Consejos concretos en español para modificar o adaptar el CV para esta oferta específica de forma personalizada (ej: 'Resalta tu experiencia con Java en tu rol anterior y menciona tu proyecto de Vercel'). Debe ser personalizado según el puesto."
    )
    estimated_salary: int = Field(
        description="Salario estimado anual bruto en euros (EUR) para esta oferta. Si la oferta indica el salario o rango (ej: '30.000€ - 35.000€' o '2.500€/mes'), calcula el salario anual bruto correspondiente como un entero (ej: 32000). Si la oferta NO especifica ningún salario, la IA debe estimar un salario anual bruto de mercado realista para este puesto en España considerando el rol, las tecnologías requeridas, la modalidad y la experiencia solicitada, y devolverlo como un entero (ej: 28000). No devuelvas null ni 0."
    )
    work_mode: str = Field(
        description="Modalidad de trabajo detectada en la oferta. Debe ser exactamente uno de estos valores: 'Presencial', 'Remoto', 'Híbrido'."
    )
    salary_is_estimate: bool = Field(
        description="True si el salario fue estimado por la IA porque la oferta original no mencionaba ningún salario ni rango salarial. False si la oferta original sí especificaba explícitamente un salario o rango."
    )
    required_experience: int = Field(
        description="Número de años de experiencia laboral que pide la empresa para el puesto. Si la oferta menciona explícitamente los años (ej: '3 años de experiencia'), devuelve ese número. Si solo pone 'junior' o no menciona experiencia, devuelve 0. Si pone 'senior' sin número concreto, devuelve 5. Máximo 20."
    )

class GeminiClient:
    def __init__(self):
        # Permite configurar el modelo desde las variables de entorno (ej. para cambiar a gemini-1.5-flash-latest, etc.)
        import os
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.model = genai.GenerativeModel(self.model_name)

    def _generate_with_retry(self, prompt: str, schema) -> str:
        """
        Realiza la llamada a la API de Gemini con reintentos automáticos y
        retroceso exponencial si se excede la cuota (error 429 / ResourceExhausted).
        """
        import time
        from google.api_core.exceptions import ResourceExhausted
        
        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2
        )
        
        for attempt in range(5):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                return response.text
            except ResourceExhausted:
                wait_time = (2 ** attempt) * 5 + 5  # 10s, 15s, 25s, 45s, 85s
                print(f"\n[Gemini] Límite de cuota (429) excedido. Esperando {wait_time}s para reintentar (intento {attempt+1}/5)...")
                time.sleep(wait_time)
            except Exception as e:
                raise e
                
        raise RuntimeError("No se pudo conectar con la API de Gemini tras 5 intentos debido a la cuota (429).")

    def analyze_cv(self, cv_text: str) -> ProfileAnalysis:
        """
        Analiza el texto de un CV para extraer roles sugeridos, 
        habilidades clave y años de experiencia en formato estructurado.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            print("[Gemini] Usando MOCK_GEMINI para análisis de CV.")
            return ProfileAnalysis(
                recommended_roles=["Desarrollador Python", "Desarrollador Java", "Full-stack Developer", "Backend Engineer"],
                key_skills=["Python", "JavaScript", "Java", "SQL", "Docker", "Git"],
                years_of_experience=1.5,
                summary="Desarrollador de software junior con formación en CFGS de Desarrollo de Aplicaciones Multiplataforma e Ingeniería Industrial, y experiencia desarrollando proyectos propios de IA y automatización."
            )

        prompt = f"""
        Analiza el siguiente Currículum Vitae (CV) o perfil profesional. 
        Extrae la información clave y sugiere hasta 4 títulos de trabajo específicos que se adapten perfectamente a este perfil para realizar una búsqueda de empleo efectiva en portales de empleo.
        Asegúrate de que los puestos recomendados estén alineados estrictamente con el perfil del candidato.
        Para maximizar la cantidad de ofertas encontradas en portales españoles (como InfoJobs o Indeed España), incluye tanto el término en inglés como su traducción o equivalente común en español (por ejemplo, 'Desarrollador Junior' y 'Junior Developer', 'Frontend Developer' y 'Desarrollador Frontend', etc.) como roles separados en la lista de recomendados.

        Texto del CV:
        ---
        {cv_text}
        ---
        """
        
        response_text = self._generate_with_retry(prompt, ProfileAnalysis)
        
        # Cargar el resultado JSON estructurado
        data = json.loads(response_text)
        return ProfileAnalysis(**data)

    def match_offer(self, cv_text: str, offer_title: str, offer_description: str) -> OfferMatch:
        """
        Compara el CV con una oferta de empleo y devuelve un Match Score, 
        el stack tecnológico detectado, modalidad, salario y consejos de optimización.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            # Smart Mock basado en el título y descripción
            title_lower = offer_title.lower()
            desc_lower = offer_description.lower()
            
            # Determinar match score basado en las palabras clave del título en comparación con el perfil
            match_score = 0
            if any(x in title_lower for x in ["desarrollador", "developer", "engineer", "programador", "analista"]):
                match_score += 40
            if "python" in title_lower or "python" in desc_lower:
                match_score += 30
            if "javascript" in title_lower or "javascript" in desc_lower or "react" in title_lower or "react" in desc_lower:
                match_score += 15
            if "java" in title_lower or "java" in desc_lower:
                match_score += 15
            if "c" in title_lower:
                match_score += 5
            
            # Penalizar fuertemente roles no relacionados
            if any(x in title_lower for x in ["cementerio", "operario", "reponedor", "limpieza", "camarero", "conductor", "mozo"]):
                match_score = 5  # Muy bajo para que el filtro de >=50 lo descarte
                
            match_score = max(5, min(100, match_score))
            
            # Extraer stack tecnológico dinámicamente
            possible_techs = ["Python", "JavaScript", "Java", "C", "Docker", "Git", "SQL", "React", "Node.js", "Django", "FastAPI", "AWS", "Oracle"]
            tech_stack = []
            for tech in possible_techs:
                if tech.lower() in title_lower or tech.lower() in desc_lower:
                    tech_stack.append(tech)
            if not tech_stack:
                tech_stack = ["Python", "Git"]
                
            # Clasificar modalidad dinámicamente
            work_mode = "Presencial"
            if "remoto" in title_lower or "remoto" in desc_lower or "remote" in title_lower or "remote" in desc_lower or "teletrabajo" in desc_lower:
                work_mode = "Remoto"
            elif "hibrido" in desc_lower or "híbrido" in desc_lower or "hybrid" in desc_lower or "flexibilidad" in desc_lower:
                work_mode = "Híbrido"
                
            # Estimar salario dinámicamente
            import re
            salary_match = re.search(r'(\d{2})[\s.]?(\d{3})', offer_description)
            if salary_match:
                estimated_salary = int(salary_match.group(1) + salary_match.group(2))
            else:
                if "python" in title_lower:
                    estimated_salary = 35000
                elif "desarrollador" in title_lower or "developer" in title_lower:
                    estimated_salary = 30000
                else:
                    estimated_salary = 24000
                    
            # Consejos adaptados
            if "python" in title_lower:
                tailored_advice = "Resalta tu proyecto de tienda online con recomendador de IA en Python y tu curso Elements of AI."
            elif "java" in title_lower:
                tailored_advice = "Destaca tu formación superior en CFGS DAM y tus conocimientos de base de datos Oracle y Java."
            else:
                tailored_advice = f"Destaca tus conocimientos en {', '.join(tech_stack[:3])} en tu CV. Resalta los proyectos de tu portafolio relacionados con estas herramientas."
                
            print(f"  - [Smart Mock] Match: {match_score}%, Stack: {tech_stack}, Mod: {work_mode}, Sal: {estimated_salary}€")
            return OfferMatch(
                match_score=match_score,
                tech_stack=tech_stack,
                tailored_advice=tailored_advice,
                estimated_salary=estimated_salary,
                work_mode=work_mode,
                salary_is_estimate=len(re.findall(r'(\d{2})[\s.]?(\d{3})', offer_description)) == 0,
                required_experience=0
            )

        prompt = f"""
        Eres un reclutador experto y especialista en optimización de CVs. 
        Compara el siguiente currículum con la oferta de empleo provista.

        1. Calcula una puntuación de compatibilidad (Match Score de 0 a 100). Si la oferta es para un puesto manual o no relacionado con el perfil de desarrollo del candidato (como operario de cementerio, reponedor, personal de limpieza, etc.), el Match Score DEBE ser muy bajo (por debajo de 10).
        2. Identifica las tecnologías y herramientas requeridas en la oferta (tech_stack) a partir del texto de la descripción. Extrae tecnologías reales y no inventes ni uses un stack estático.
        3. Escribe consejos breves, personalizados y accionables para adaptar el currículum del candidato a esta oferta específica (por ejemplo, destacar sus proyectos relacionados, enfocar sus estudios de CFGS en las tecnologías demandadas, etc.). Los consejos DEBEN ser específicos para esta oferta y no repetitivos.
        4. Identifica o calcula el salario anual bruto estimado (estimated_salary) en euros. Si el texto no menciona el salario, la IA DEBE estimar un salario anual bruto realista para este puesto en España considerando las tecnologías requeridas, la modalidad y la experiencia solicitada (ej. 28000 para juniors, 35000 para mid, etc.).
        5. Determina la modalidad de trabajo (work_mode) de la oferta en una de estas opciones exactas: 'Presencial', 'Remoto' o 'Híbrido' (teletrabajo parcial).
        6. Determina los años de experiencia requeridos (required_experience). Si la oferta dice explícitamente 'X años de experiencia', devuelve X. Si pone 'junior' devuelve 0, 'mid-level' o 'intermedio' devuelve 2, 'senior' devuelve 5. Si no menciona nada, devuelve 0.

        Currículum del candidato:
        ---
        {cv_text}
        ---

        Oferta de Empleo:
        Puesto: {offer_title}
        Descripción:
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, OfferMatch)
        
        data = json.loads(response_text)
        return OfferMatch(**data)

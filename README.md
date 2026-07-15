# Asistente Inteligente de Empleo con IA y Notion

Este proyecto recopila automáticamente ofertas de empleo de **InfoJobs**, **LinkedIn** e **Indeed** (con fallback a API externa), analiza la compatibilidad (Match Score) de cada oferta respecto a tu currículum usando la **API de Gemini (Gratuita)**, te ofrece consejos específicos para adaptar tu CV, y sincroniza todo en una base de datos de **Notion**.

Se ejecuta de forma **100% gratuita** utilizando **GitHub Actions** sin necesidad de tener tu ordenador encendido, o de manera local mediante **Docker**.

---

## Características

1. **Análisis de Perfil:** Lee tu CV (PDF, DOCX, TXT o JSON) y extrae de forma inteligente tus habilidades y los mejores roles a buscar.
2. **Scraping Híbrido:** Scrapea InfoJobs (RSS), LinkedIn (Guest API) e Indeed, y cuenta con un fallback a la API consolidada de **JSearch** (RapidAPI) si hay bloqueos.
3. **Scoring y Consejos:** Para cada oferta, Gemini calcula un porcentaje de coincidencia y redacta sugerencias de optimización para tu CV.
4. **Base de Datos en Notion:** Sincroniza ofertas en tiempo real evitando duplicadas.
5. **Borrado Automático integrado:** Si marcas la casilla **"Eliminar"** de una fila en Notion, el script la borrará en la siguiente ejecución.

---

## 🛠️ Configuración de Credenciales (Gemini y Notion)

Sigue los pasos detallados en la guía de configuración del artefacto para crear tu base de datos de Notion y obtener la API key de Gemini.

---

## 💻 Ejecución Local

### Opción A: Con Python nativo
1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Copia `.env.example` como `.env` y rellena tus claves:
   ```bash
   cp .env.example .env
   ```
3. Guarda tu currículum como `cv.pdf` en la raíz del proyecto.
4. Ejecuta el script principal:
   ```bash
   python main.py
   ```

### Opción B: Con Docker
1. Rellena tu archivo `.env` local.
2. Asegúrate de tener tu archivo `cv.pdf` en la raíz del proyecto.
3. Construye y ejecuta el contenedor:
   ```bash
   docker-compose up --build
   ```

---

## 🚀 Despliegue en la Nube 100% Gratis (GitHub Actions)

Para que el script funcione automáticamente en la nube sin tu ordenador encendido:

1. **Crea un repositorio privado** en GitHub.
2. Sube todos los archivos del proyecto a tu repositorio (incluyendo tu `cv.pdf` en la raíz).
3. En tu repositorio de GitHub, ve a **Settings > Secrets and variables > Actions**.
4. Haz clic en **New repository secret** y añade las siguientes claves:
   * `GEMINI_API_KEY`: Tu API Key de Google AI Studio.
   * `NOTION_TOKEN`: Tu token secreto de integración.
   * `NOTION_DATABASE_ID`: El ID de tu base de datos de Notion.
   * `RAPIDAPI_KEY` *(Opcional)*: Clave de RapidAPI para el fallback de JSearch.
   * `DESIRED_LOCATIONS` *(Opcional)*: Ubicaciones de búsqueda (ej: `Madrid,Remoto`).
   * `YEARS_OF_EXPERIENCE` *(Opcional)*: Tus años de experiencia (ej: `3`).
   * `MIN_SALARY` *(Opcional)*: Salario mínimo anual (ej: `35000`).

El flujo de trabajo se ejecutará automáticamente **dos veces al día (a las 8:00 y las 20:00 UTC)**. También puedes iniciarlo manualmente desde la pestaña **Actions** en GitHub seleccionando *"Job Scraper and Notion Sync"* y haciendo clic en **Run workflow**.

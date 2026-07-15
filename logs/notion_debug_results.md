# Análisis y Solución de Sincronización con Notion & Dockerización

Hemos analizado el proyecto, depurado la integración con Notion y configurado la dockerización junto con la acción de GitHub Actions como un cron job. Aquí tienes todos los detalles técnicos de los problemas resueltos y los cambios realizados:

---

## 1. Correcciones en Notion

El problema por el cual no se escribía nada en Notion se debía a varios factores:

### A. Desajuste de Schema (Propiedades de la Base de Datos)
El script original intentaba subir propiedades con nombres y tipos que no coincidían con la configuración real de tu base de datos de Notion. Tras inspeccionar dinámicamente tu base de datos mediante la API, identificamos las propiedades exactas y sus tipos:

| Propiedad en base de datos (Notion) | Tipo en Notion | Propiedad enviada originalmente | Tipo original (Erróneo) |
| :--- | :--- | :--- | :--- |
| **`Puesto`** *(Nombre de la página)* | `title` | `Puesto` | `title` |
| **`Empresa`** | `rich_text` | `Empresa` | `select` ❌ |
| **`Ubicacion`** *(Sin acento)* | `rich_text` | `Ubicación` *(Con acento)* | `rich_text` ❌ |
| **`Salario`** | `number` | `Salario` | `rich_text` ❌ |
| **`Match`** | `number` | `Match Score` | `number` ❌ |
| **`Stack`** | `rich_text` | `Stack Tecnológico` | `multi_select` ❌ |
| **`Fecha de publicacion`** | `date` | `Fecha Publicación` | `date` ❌ |
| **`Fecha Deteccion`** *(Sin acento)* | `date` | `Fecha Detección` | `date` ❌ |
| **`URL`** | `url` | `Enlace Oferta` | `url` ❌ |
| **`Consejos`** | `rich_text` | `Consejos CV` | `rich_text` ❌ |
| **`Eliminar`** | `checkbox` | `Eliminar` | `checkbox` |

**Solución aplicada:**
* Corregimos todos los mapeos de nombres en `notion_sync.py`.
* Implementamos un parsedor numérico robusto (`_parse_salary_to_num`) en `notion_sync.py` para extraer y enviar los salarios como números válidos en Notion, omitiendo el valor si no puede ser parseado (enviando `None`).
* Transformamos el stack tecnológico para enviarse como un string separado por comas tipo `rich_text`.

### B. Extracción de Salario Inteligente con IA
Los scrapers públicos (LinkedIn, InfoJobs) no siempre proveen un campo estructurado de salario en sus feeds públicos.
**Solución aplicada:**
* Modificamos el modelo estructurado de la IA (`OfferMatch`) en `utils/gemini_client.py` agregando la propiedad `estimated_salary`.
* Gemini ahora lee la descripción del empleo completa y extrae de forma autónoma el salario anual estimado (calculando la media o límite inferior si se ofrece en rango). Esto garantiza que el campo **Salario** en tu Notion se llene de manera inteligente.

### C. Filtro de Compatibilidad e IA real
Anteriormente se subían todos los trabajos recolectados (incluyendo "Operario de cementerios" o similares no relacionados).
**Solución de IA y Filtros aplicada:**
* **Bypass de Test (`MOCK_GEMINI=true`):** Al usar esta bandera de entorno, se inyectan respuestas pre-baked estáticas para validar que los endpoints de Notion e integraciones funcionen rápido sin agotar cuotas.
* **IA Real (Ejecución Normal):** Al ejecutar el script sin esa bandera, la IA evaluará de forma real y dinámica tu CV contra cada oferta.
* **Filtro de puntuación mínima:** Añadimos un filtro en `main.py` para que solo se suban a Notion ofertas que tengan un **Match Score mínimo de 50%**. Ofertas con menor afinidad (como operarios, reponedores, etc.) son descartadas automáticamente.
* **Respeto a Rate Limits:** Añadimos un retardo inteligente de **4 segundos** entre llamadas a la API de Gemini para evitar el error de cuota `429 (Too Many Requests)` en cuentas gratis (límite de 15 RPM).
* **Límite de procesamiento:** Limitamos la ejecución a un máximo de **15 ofertas nuevas analizadas por tanda**, previniendo que se encolen llamadas excesivas y asegurando ejecuciones estables en segundo plano.

### D. Uso del Endpoint de Data Sources (Synced Database)
Tu base de datos es una base de datos sincronizada/enlazada ("Data Source"), lo cual impedía realizar consultas directas mediante el endpoint tradicional `/v1/databases/{id}/query` (devolvía error `Invalid request URL`).
**Solución aplicada:**
* Detectamos si la base de datos tiene `data_sources` activos.
* Modificamos la función de consulta en `notion_sync.py` para que busque a través de `notion.data_sources.query` utilizando el ID del Data Source cuando esté presente.

### E. Normalización de Enlaces
Algunos scrapers (como InfoJobs) extraían enlaces en formato relativo al protocolo (ej. `//www.infojobs.net/...`), lo que hacía fallar la validación de URLs de Notion.
**Solución aplicada:**
* Añadimos normalización automática en `check_if_job_exists` y `add_job_to_notion` para anteponer `https:` si el enlace empieza por `//`.

---

## 2. Dockerización Optimizada

Originalmente el archivo `Dockerfile` usaba una imagen base `python:3.10-alpine` que requería compilar librerías en C como `selectolax`, ralentizando drásticamente la compilación de la imagen en sistemas locales o entornos CI/CD.

**Solución aplicada:**
* Cambiamos la imagen base a `python:3.10-slim`.
* Eliminamos la necesidad de instalar dependencias como `gcc` o `musl-dev`, ya que `python:3.10-slim` descarga directamente las wheels (binarios compilados) de las librerías del proyecto. El tiempo de construcción del contenedor ahora es casi instantáneo.

---

## 3. GitHub Actions con Cron Job Dockerizado

Hemos actualizado el flujo de trabajo de GitHub Actions en `.github/workflows/scraper.yml` para que:
1. Construya la imagen de Docker a partir del `Dockerfile` en el repositorio.
2. Ejecute el script scraper dentro del contenedor de Docker pasando todos los secretos necesarios de forma segura.

### Flujo de trabajo configurado:
* **Ejecución automática:** Configurado como un Cron Job para ejecutarse todos los días a las 8:00 y a las 20:00 UTC (modificable en la propiedad `on.schedule.cron`).
* **Ejecución manual:** Soporta `workflow_dispatch` desde la pestaña Actions de GitHub con inputs personalizables de ubicaciones, experiencia y salario.

---

## 🚀 Pasos para subirlo a tu GitHub

Si el proyecto aún no está inicializado con git ni subido a GitHub, puedes seguir estos comandos en tu terminal local:

1. **Inicializar git y realizar el primer commit:**
   ```bash
   git init
   git add .
   git commit -m "feat: correccion de Notion, Dockerfile y workflow en Actions"
   ```

2. **Crear el repositorio en GitHub y subir el código:**
   *(Crea primero un repositorio vacío en tu cuenta de GitHub, ej: `job_scraper_ai`)*
   ```bash
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/job_scraper_ai.git
   git push -u origin main
   ```

3. **Configurar los Secretos en GitHub:**
   Ve a la página de tu repositorio en GitHub y dirígete a:
   **Settings > Secrets and variables > Actions > New repository secret**

   Añade los siguientes secretos:
   * `GEMINI_API_KEY`: Tu clave de Gemini.
   * `NOTION_TOKEN`: Tu token de integración (`ntn_...`).
   * `NOTION_DATABASE_ID`: El ID de tu base de datos Notion (`39edd...`).
   * `RAPIDAPI_KEY` *(Opcional)*: Clave de RapidAPI para búsquedas de respaldo.

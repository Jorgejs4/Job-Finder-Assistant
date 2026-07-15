# Asistente Inteligente de Empleo con IA y Notion

Recopila automáticamente ofertas de empleo de **8 plataformas**, analiza la compatibilidad con tu currículum usando **Gemini IA**, y sincroniza todo en **Notion** con un resumen por email.

Funciona **100% gratis** con **GitHub Actions** (dos veces al día), o de forma local con Docker.

---

## Plataformas activas

| Plataforma | Tipo | Modalidad |
|------------|------|-----------|
| InfoJobs | Scraping HTML | España |
| LinkedIn | API pública guest | Global |
| Indeed | Scraping HTML | España |
| RemoteOK | API JSON | Remoto |
| Remotive | API JSON | Remoto |
| TecnoEmpleo | Scraping HTML | España |
| Jobfluent | Scraping HTML | Global |
| Glassdoor | Scraping HTML | Global |

---

## Características

1. **Análisis de Perfil:** Lee tu CV (PDF, DOCX, TXT o JSON) y extrae roles recomendados y habilidades clave.
2. **Scraping en 8 fuentes:** Con curl_cffi para evadir anti-bot (Cloudflare, Distil Networks).
3. **Scoring IA:** Gemini calcula match %, stack tecnológico, salario estimado y consejos personalizados.
4. **Notion Sync:** Sube ofertas evitando duplicadas, con borrado automático si marcas "Eliminar".
5. **Email de resumen:** Recibe un email HTML con estadísticas por plataforma, top ofertas y errores.
6. **Resultados persistentes:** Cada ejecución guarda JSON + CSV con métricas por scraper.
7. **Dashboard interactivo:** Streamlit con KPIs, gráficos, filtros y exportación CSV.
8. **Tests automatizados:** Verifican que todos los scrapers responden correctamente.

---

## Configuración de credenciales

Sigue la guía en `configuracion_credenciales.md` para crear tu base de datos de Notion y obtener la API key de Gemini.

---

## Ejecución local

### Python nativo
```bash
pip install -r requirements.txt
cp .env.example .env  # Rellena tus claves
# Guarda tu CV como cv.pdf en la raíz
python main.py
```

### Docker
```bash
# Rellena .env y coloca cv.pdf
docker-compose up --build
```

---

## Dashboard

El dashboard es una aplicación local con **Streamlit** que visualiza los resultados de las ejecuciones.

### Cómo lanzarlo

```bash
streamlit run dashboard.py
```

Abrir **http://localhost:8501** en el navegador.

### Qué muestra

- **KPIs:** Ofertas encontradas, añadidas a Notion, analizadas por IA, scrapers OK/fallidos
- **Gráficos:** Evolución de ofertas por ejecución, scrapers OK vs fallidos
- **Tabla de scrapers:** Estado de cada plataforma (OK, vacío, fallido) y número de ofertas
- **Ofertas:** Tabla con todos los resultados, filtrable por fuente, match mínimo y modalidad
- **Exportación:** Botón para descargar el CSV filtrado

### Cómo alimentar el dashboard con datos de GitHub Actions

1. Ve a **Actions** en tu repositorio de GitHub
2. Clic en la ejecución que quieras visualizar
3. Baja hasta **Artifacts** (al final de la página)
4. Descarga `scraper-results-XXXX`
5. Descomprime y copia la carpeta `results/` a la raíz de tu proyecto local
6. Lanza el dashboard: `streamlit run dashboard.py`

---

## Tests automatizados

Los tests verifican que los 8 scrapers responden correctamente. Se ejecutan automáticamente en GitHub Actions antes de cada run del scraper.

### Ejecutar tests localmente

```bash
# Ejecuta los tests con Gemini en modo mock (sin gastar cuota)
MOCK_GEMINI=true python tests/test_scrapers.py
```

### Qué verifican

- Cada scraper puede conectarse y devolver ofertas
- Detección de scrapers caídos o bloqueados
- Límite de 50 ofertas por plataforma
- Detección de duplicados dentro de un mismo scraper
- Genera `results/test_report.json` con el reporte completo

---

## GitHub Actions

### Secrets a configurar

En **Settings > Secrets and variables > Actions** de tu repositorio:

| Secret | Requerido | Descripción |
|--------|-----------|-------------|
| `GEMINI_API_KEY` | Sí | API Key de Google AI Studio |
| `NOTION_TOKEN` | Sí | Token de integración de Notion |
| `NOTION_DATABASE_ID` | Sí | ID de la base de datos de Notion |
| `RAPIDAPI_KEY` | No | Fallback JSearch (solo resultados US/UK) |
| `DESIRED_LOCATIONS` | No | Ubicaciones por defecto (ej: `Sevilla,Remoto`) |
| `YEARS_OF_EXPERIENCE` | No | Años de experiencia (ej: `3`) |
| `MIN_SALARY` | No | Salario mínimo anual (ej: `35000`) |
| `SMTP_GMAIL_USER` | No | Email de Gmail para notificaciones |
| `SMTP_GMAIL_PASSWORD` | No | Contraseña de aplicación de Gmail |
| `NOTIFY_EMAIL` | No | Email destino del resumen |

### Configurar email (Gmail)

1. Activa **Verificación en 2 pasos** en https://myaccount.google.com/security
2. Ve a https://myaccount.google.com/apppasswords
3. Selecciona **Otra (nombre personalizado)** → escribe "Job Scraper"
4. Click en **Crear**
5. Google te dará un código de 16 caracteres tipo: `abcd efgh ijkl mnop`
6. Ese código es tu `SMTP_GMAIL_PASSWORD` (guárdalo sin espacios)

> **Nota:** La contraseña de aplicación es distinta a tu contraseña normal de Gmail. Es una clave especial que permite enviar emails sin exponer tu contraseña principal.

### Probar que el email funciona

1. Ve a **Actions** > **Job Scraper and Notion Sync** > **Run workflow**
2. Asegúrate de que los 3 secrets de email están configurados
3. Espera a que termine la ejecución (3-5 minutos)
4. Revisa tu bandeja de entrada (y spam) por un email con asunto "[Job Scraper] Resumen ..."

### Cómo ver los resultados de cada ejecución

1. Ve a la pestaña **Actions** de tu repositorio
2. Haz clic en la ejecución que quieras revisar
3. En la sección **Artifacts** (abajo) encontrarás:
   - `scraper-results-XXXX` — JSON, CSV e histórico de la ejecución
   - `scraper-test-report` — Reporte de tests de scrapers
4. Haz clic en el artifact para descargarlo (formato .zip)
5. Descomprime y abre el CSV en Excel/Google Sheets o el JSON en un visor de texto

### Flujo de ejecución

El workflow se ejecuta **dos veces al día (8:00 y 20:00 UTC)**:

1. **Tests** → Verifica que los scrapers responden (con Gemini mock)
2. **Scraper** → Ejecuta el pipeline completo (scraping → IA → Notion → email)
3. **Artifacts** → Guarda resultados JSON/CSV por 90 días

También puedes ejecutarlo manualmente desde **Actions > Job Scraper and Notion Sync > Run workflow**.

---

## Resultados

Cada ejecución genera en `results/`:

| Archivo | Descripción |
|---------|-------------|
| `run_YYYYMMDD_HHMMSS.json` | Datos completos de la ejecución (scrapers, ofertas, errores) |
| `run_YYYYMMDD_HHMMSS.csv` | Ofertas en formato tabular (title, company, source, match_score...) |
| `history.csv` | Histórico aggregate: una fila por ejecución con métricas |
| `test_report.json` | Último reporte de tests de scrapers |

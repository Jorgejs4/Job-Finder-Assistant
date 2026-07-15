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

### Dashboard
```bash
streamlit run dashboard.py
# Abrir http://localhost:8501
```

El dashboard muestra:
- KPIs de la última ejecución (ofertas, scrapers OK/fallidos)
- Gráficos de historial de ejecuciones
- Filtros por fuente, match mínimo y modalidad
- Exportación a CSV

### Tests de scrapers
```bash
# Ejecuta los tests con Gemini en modo mock
MOCK_GEMINI=true python tests/test_scrapers.py
```

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
3. Crea una contraseña para "Otra (nombre personalizado)" → "Job Scraper"
4. Copia los 16 caracteres y guárdalos como `SMTP_GMAIL_PASSWORD`

### Flujo de ejecución

El workflow se ejecuta **dos veces al día (8:00 y 20:00 UTC)**:

1. **Tests** → Verifica que los scrapers responden (con Gemini mock)
2. **Scraper** → Ejecuta el pipeline completo
3. **Artifacts** → Guarda resultados JSON/CSV por 90 días

También puedes ejecutarlo manualmente desde **Actions > Job Scraper and Notion Sync > Run workflow**.

---

## Resultados

Cada ejecución genera en `results/`:
- `run_YYYYMMDD_HHMMSS.json` — Datos completos de la ejecución
- `run_YYYYMMDD_HHMMSS.csv` — Ofertas en formato tabular
- `history.csv` — Histórico aggregate de todas las ejecuciones
- `test_report.json` — Último reporte de tests de scrapers

### Cómo ver los resultados en GitHub Actions

1. Ve a la pestaña **Actions** de tu repositorio
2. Haz clic en la ejecución que quieras revisar
3. En la sección **Artifacts** (abajo) descarga:
   - `scraper-results-XXXX` — Contiene el JSON, CSV e historial
   - `scraper-test-report` — Reporte de tests de scrapers
4. Descomprime y abre el CSV en Excel o el JSON en un visor de texto

### Cómo ver el dashboard con los resultados

1. Descarga el artifact `scraper-results-XXXX` desde GitHub Actions
2. Descomprime la carpeta `results/` en la raíz de tu proyecto local
3. Ejecuta:
   ```bash
   streamlit run dashboard.py
   ```
4. Abre http://localhost:8501 en tu navegador

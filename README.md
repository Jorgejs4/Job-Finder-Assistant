# Asistente Inteligente de Empleo con IA y Notion

Recopila automáticamente ofertas de empleo de **9 plataformas**, analiza la compatibilidad con tu currículum usando **Gemini IA**, genera **CVs personalizados con foto**, y sincroniza todo en **Notion** con un resumen por email.

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
| Jooble | API/HTML | Global (agregador) |
| GetOnBoard | Scraping HTML | LATAM (remoto) |

---

## Características principales

### Pipeline completo
1. **Análisis de Perfil:** Lee tu CV (PDF, DOCX, TXT o JSON) y extrae roles recomendados y habilidades clave.
2. **Scraping en 9 fuentes:** Con curl_cffi para evadir anti-bot (Cloudflare, Distil Networks).
3. **Scoring IA:** Gemini calcula match %, stack tecnológico, salario estimado, carta de presentación y CV personalizado en **una sola llamada** (ahorra cuota).
4. **CV personalizado:** Genera PDF + HTML con foto del CV original, skills agrupadas por categoría, experience con métricas cuantificadas, ATS-compatible.
5. **Notion Sync:** Sube ofertas evitando duplicadas, con borrado automático si marcas "Eliminar".
6. **Email de resumen:** Recibe un email HTML con estadísticas por plataforma, top ofertas, errores y comparación con ejecución anterior.
7. **Feedback de CVs:** Formulario en dashboard para pedir modificaciones al CV. Se regenera automáticamente en la próxima ejecución.
8. **Dedup fuzzy matching:** Detecta duplicados cross-scraper con bucketing por título+empresa (O(n×k) en vez de O(n×m)).
9. **Filtro pre-IA:** 83 keywords no-tech eliminadas antes de llamar a Gemini (ahorra cuota).
10. **Inteligencia salarial:** MIN_SALARY + YEARS_OF_EXPERIENCE filtran antes del análisis IA.

### Análisis IA
11. **Carta de presentación IA:** Genera cartas personalizadas por oferta (150-250 palabras).
12. **Skills gap analysis:** Detecta qué habilidades faltan en tu CV vs demanda del mercado.
13. **Informe de mercado:** Tendencias de tech, salarios, empresas que contratan.
14. **Análisis paralelo:** 3 workers Gemini con `ThreadPoolExecutor` y `stop_event` para parada inmediata en 429.

### Dashboard
15. **Preview HTML del CV:** Visualiza el CV generado directamente en el dashboard (con foto) antes de descargar.
16. **Descarga PDF:** Botón para descargar el CV en PDF ATS-compatible.
17. **Formulario de feedback:** Escribe qué cambiar del CV y se regenera automáticamente.
18. **Panel de gestión (4 tabs):** Mis Ofertas (filtrado avanzado), Pipeline, Estadísticas, Ejecuciones.

### Infraestructura
19. **Rotación de API keys:** Múltiples keys de Gemini con failover automático. Si una key recibe 429, rota a la siguiente automáticamente. Thread-safe con `KeyPool`.
20. **Parada en 429:** Si se agotan TODAS las API keys, el programa PARA inmediatamente y envía email de aviso.
21. **Rate limiter adaptativo:** 10s base entre llamadas Gemini, backoff en 429 (x4 hasta 120s), recuperación lenta (x0.7).
22. **Tests automatizados:** 19 tests unitarios verificando scrapers, Gemini, CV generator y feedback manager.
23. **GitHub Actions:** CI/CD con 120min timeout, git pull --rebase para evitar conflictos de data.json.

---

## Configuración de credenciales

Sigue la guía en `configuracion_credenciales.md` para crear tu base de datos de Notion y obtener la API key de Gemini.

### API Key de Jooble (opcional)

Jooble es un agregador de empleo. Para mejores resultados:

1. Ve a https://jooble.org/api/about
2. Regístrate (gratis, toma 1 minuto)
3. Copia la API key que te generan
4. Añádela como secret en GitHub: `JOOBLE_API_KEY`
5. Sin API key, Jooble puede no devolver resultados (Cloudflare)

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

## Scripts útiles

### Skills Gap Analysis
```bash
# Analiza las últimas 25 ofertas y muestra qué skills faltan
python skills_gap.py

# Analizar más ofertas
python skills_gap.py --top 50

# Guardar informe en archivo
python skills_gap.py --output skills_gap.md
```

### Market Report
```bash
# Genera informe de mercado en HTML
python market_report.py

# Guardar en archivo
python market_report.py --output report.html

# Enviar por email
python market_report.py --email
```

### Rellenar CVs y cartas en Notion
```bash
# Rellena todos los campos vacíos (cartas + CVs)
python fill_empty_fields.py

# Solo cartas de presentación
python fill_empty_fields.py --only-cartas

# Solo CVs personalizados
python fill_empty_fields.py --only-cvs

# Modo dry-run (sin cambios)
python fill_empty_fields.py --dry-run
```

---

## Dashboard

Dashboard interactivo con **Streamlit**, reimaginado como panel de gestión de ofertas:

### 4 Tabs

- **💼 Mis Ofertas** — Todas las ofertas de todas las ejecuciones, deduplicadas por URL. 7 filtros: fuente, modalidad, estado, match %, rango salarial, tech stack y búsqueda por texto. Cada oferta es expandible: carta de presentación, CV preview HTML con foto, descarga PDF y formulario de feedback. Exportación CSV.
- **🔄 Pipeline** — Funnel visual de estados (Nuevo → Rechazado) con barra de colores y métricas. Ofertas agrupadas por estado.
- **📊 Estadísticas** — Inteligencia salarial completa (promedio, mediana, min, max + desglose por modalidad y plataforma). Skills gap analysis (skills que tienes vs las que faltan). Resumen del mercado (distribución por modalidad, plataforma, % remoto).
- **📈 Ejecuciones** — KPIs de la última ejecución, tabla de scrapers OK/fallidos, historial con gráficos de evolución.

### Dashboard Online

El dashboard está desplegado en **Streamlit Community Cloud** y se actualiza automáticamente con cada ejecución del scraper:

👉 **https://job-finder-assistant.streamlit.app**

### Cómo funciona

El dashboard lee los datos directamente desde el repositorio en GitHub (archivo `results/data.json`). Agrega TODAS las ofertas de TODAS las ejecuciones y las deduplica por URL (conserva la versión más reciente).

### Lanzarlo localmente

```bash
~/proyectos/job_scraper_ai/venv/bin/streamlit run dashboard.py
```

Abrir **http://localhost:8501** en el navegador.

---

## Sistema de CVs personalizados

### Cómo funciona el flujo

```
cv.pdf (foto extraída) + Gemini (contenido mejorado) + Template HTML
        ↓                                           ↓
   photo.png                              cv_{hash}.html (preview en dashboard)
        ↓                                           ↓
   fpdf2 + photo                          st.components.v1.html() → visualización
        ↓                                           ↓
   cv_{hash}.pdf (descarga)              Feedback form → feedback.json
        ↓                                           ↓
   Notion "CV" URL property              Próxima ejecución: regenera con feedback
```

### Calidad del CV

El CV generado sigue **10 reglas de un CV técnico profesional**:

1. **Legibilidad en 30-60 segundos** — títulos claros, buen espacio en blanco.
2. **Perfil técnico claro** — cargo objetivo + años + especialización + tech principal.
3. **Skills agrupadas por categoría** — Backend, Cloud, CI/CD (no lista plana mixta).
4. **Logros cuantificados** — métricas con %, tiempo, usuarios, volumen.
5. **Conocimientos profundos** — no solo "Java + Spring", sino arquitectura completa.
6. **Proyectos relevantes** — no CRUD básico, sino apps completas y open source.
7. **Adaptado a la oferta** — tecnologías de la oferta destacadas.
8. **ATS-compatible** — texto plano, títulos estándar, keywords de la oferta.
9. **Evolución profesional** — muestra progresión en complejidad técnica.
10. **Foto incluida** — extraída del CV original con PyMuPDF.

### Feedback循环

1. Abres el dashboard y ves el CV en HTML (preview con foto).
2. Si no te gusta, escribes qué cambiar en el formulario de feedback.
3. La próxima ejecución del cron, Gemini regenera el CV con tu feedback.
4. Notion se actualiza con la nueva URL del PDF.

---

## Tests automatizados

19 tests unitarios verifican:

- Scrapers (9 plataformas)
- Gemini models (OfferMatch, ProfileAnalysis, CVContent)
- Gemini mock (match_offer, analyze_cv)
- CV Generator (generate_from_data con HTML + PDF)
- Results Manager (save/load)
- Feedback Manager (save/retrieve, mark_done, has_pending)

### Ejecutar tests localmente

```bash
# Todos los tests
python -m pytest tests/test_unit.py -v

# Tests de scrapers (sin gastar cuota de Gemini)
MOCK_GEMINI=true python tests/test_scrapers.py
```

---

## GitHub Actions

### Secrets a configurar

En **Settings > Secrets and variables > Actions** de tu repositorio:

| Secret | Requerido | Descripción |
|--------|-----------|-------------|
| `GEMINI_API_KEY` | Sí | API Key de Google AI Studio |
| `GEMINI_API_KEYS` | No | Múltiples keys separadas por coma para failover automático (ej: `key1,key2,key3`). Si se configura, `GEMINI_API_KEY` se usa como fallback. |
| `NOTION_TOKEN` | Sí | Token de integración de Notion |
| `NOTION_DATABASE_ID` | Sí | ID de la base de datos de Notion |
| `RAPIDAPI_KEY` | No | Fallback JSearch (solo resultados US/UK) |
| `JOOBLE_API_KEY` | No | API key de Jooble (mejora resultados) |
| `DESIRED_LOCATIONS` | No | Ubicaciones por defecto (ej: `Sevilla,Remoto`) |
| `YEARS_OF_EXPERIENCE` | No | Años de experiencia (ej: `3`) |
| `MIN_SALARY` | No | Salario mínimo anual (ej: `35000`) |
| `SMTP_GMAIL_USER` | No | Email de Gmail para notificaciones |
| `SMTP_GMAIL_PASSWORD` | No | Contraseña de aplicación de Gmail (16 chars) |
| `NOTIFY_EMAIL` | No | Email destino del resumen |
| `WEBHOOK_URL` | No | URL de webhook (Slack, Discord o genérico) |
| `WEBHOOK_MIN_MATCH` | No | Match mínimo para webhook (default: 80) |

### Configurar email (Gmail)

1. Activa **Verificación en 2 pasos** en https://myaccount.google.com/security
2. Ve a https://myaccount.google.com/apppasswords
3. Selecciona **Otra (nombre personalizado)** → escribe "Job Scraper"
4. Click en **Crear**
5. Google te dará un código de 16 caracteres tipo: `abcdefghijklmnop`
6. Ese código es tu `SMTP_GMAIL_PASSWORD` (guárdalo **sin espacios**)

### Configurar webhooks (opcional)

1. **Slack:** Ve a Incoming Webhooks → crea un webhook → copia la URL
2. **Discord:** Server Settings → Integrations → Webhooks → crea uno → copia la URL
3. **Genérica:** Cualquier URL que acepte POST con JSON
4. Añade `WEBHOOK_URL` como secret en GitHub
5. Opcional: `WEBHOOK_MIN_MATCH=80` (default) para filtrar por match score

### Rotación de API keys de Gemini (recomendado)

Si tienes múltiples API keys de Google AI Studio, puedes configurarlas para failover automático:

1. Crea varias keys en https://aistudio.google.com/apikey
2. Añade `GEMINI_API_KEYS=key1,key2,key3` como secret en GitHub (separadas por coma)
3. Cuando una key agote su cuota (429), el sistema rota automáticamente a la siguiente
4. Si se agotan todas las keys, el pipeline para y envía email de aviso

**Fallback:** Si solo configuras `GEMINI_API_KEY` (una sola key), funciona igual que antes. `GEMINI_API_KEYS` es opcional pero recomendado para mayor disponibilidad.

### Campos opcionales en Notion

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `Estado` | Select | Pipeline: Nuevo, Revisado, Interesado, Aplicado, Entrevista, Oferta, Rechazado |
| `Carta Presentación` | Rich text | Carta de presentación generada por IA |
| `CV` | URL | Enlace al PDF del CV personalizado |
| `Exp` | Number | Años de experiencia requeridos |
| `Origen Salario` | Select | "Estimado (IA)" o "Directo" |

### Flujo de ejecución

El workflow se ejecuta **dos veces al día (9:00 y 21:00 hora española)**:

1. **Tests** → Verifica que los scrapers responden (con Gemini mock)
2. **Feedback** → Procesa feedback pendiente de CVs anteriores
3. **Scraping** → Ejecuta los 9 scrapers en paralelo (8 workers HTTP)
4. **Dedup fuzzy** → Elimina duplicados cross-scraper con bucketing por título+empresa
5. **Filtro keywords** → Elimina ofertas no-tech (83 keywords)
6. **Análisis IA** → Gemini analiza ofertas con 3 workers paralelos + rate limiter
7. **CV generation** → Genera HTML + PDF con foto y prompt de 10 reglas
8. **Notion sync** → Sube ofertas + cartas + CVs
9. **Email** → Resumen HTML con top ofertas y comparación con ejecución anterior
10. **Commit** → Actualiza `results/data.json` y `results/cvs/` en el repositorio

Si Gemini devuelve 429 (cuota agotada), el programa **intenta rotar a la siguiente API key** automáticamente. Si se agotan TODAS las keys, PARA inmediatamente y envía email de aviso.

También puedes ejecutarlo manualmente desde **Actions > Job Scraper and Notion Sync > Run workflow**.

---

## Dependencias

```
google-generativeai    # Gemini IA
notion-client          # API de Notion
beautifulsoup4         # HTML parsing
httpx                  # HTTP client
pydantic               # Data models
python-dotenv          # Environment variables
pypdf                  # PDF text extraction
python-docx            # DOCX extraction
selectolax             # Fast HTML parsing
curl_cffi              # Anti-bot HTTP
streamlit              # Dashboard
pandas                 # Data analysis
thefuzz                # Fuzzy matching
python-Levenshtein     # Fast fuzzy
fpdf2                  # PDF generation
PyMuPDF                # Photo extraction from CV
Pillow                 # Image processing
Jinja2                 # HTML templates
```

---

## Resultados

Cada ejecución acumula datos en `results/data.json` (único archivo, máx. 100 ejecuciones):

| Campo | Descripción |
|-------|-------------|
| `runs[].run_id` | ID de la ejecución (YYYYMMDD_HHMMSS) |
| `runs[].timestamp` | Fecha/hora ISO de la ejecución |
| `runs[].scraper_stats` | Ofertas por plataforma, estado OK/fallido |
| `runs[].jobs` | Todas las ofertas encontradas con match, salario, stack, cover_letter, custom_cv_url... |
| `runs[].errors` | Errores durante la ejecución |
| `results/cvs/` | CVs generados (HTML + PDF + foto) |
| `results/feedback.json` | Feedback pendiente de procesar |

---

## Estructura del proyecto

```
job_scraper_ai/
├── main.py                    # Pipeline principal
├── dashboard.py               # Dashboard Streamlit
├── config.py                  # Configuración y preferencias
├── notion_sync.py             # Sync con Notion
├── fill_empty_fields.py       # Backfill de CVs y cartas
├── skills_gap.py              # Análisis de skills faltantes
├── market_report.py           # Informe de mercado
├── cv.pdf                     # Tu CV original (para extraer foto + texto)
├── templates/
│   └── cv_template.html       # Template HTML del CV (Jinja2)
├── scrapers/                  # 9 scrapers de plataformas
│   ├── infojobs_scraper.py
│   ├── linkedin_scraper.py
│   ├── indeed_scraper.py
│   ├── remoteok_scraper.py
│   ├── remotive_scraper.py
│   ├── tecnobs_scraper.py
│   ├── jobfluent_scraper.py
│   ├── jooble_scraper.py
│   └── getonbrd_scraper.py
├── utils/
│   ├── gemini_client.py       # Cliente Gemini (match, CV, cover letter)
│   ├── cv_generator.py        # Generador de CV (HTML + PDF + foto)
│   ├── cv_parser.py           # Parser de CV (PDF, DOCX, TXT)
│   ├── photo_extractor.py     # Extracción de foto del CV con PyMuPDF
│   ├── feedback_manager.py    # Gestión de feedback de CVs
│   ├── results.py             # Gestión de resultados (data.json)
│   ├── notifications.py       # Email notifications
│   └── webhooks.py            # Webhook notifications
├── tests/
│   ├── test_unit.py           # 19 tests unitarios
│   └── test_scrapers.py       # Tests de scrapers
├── results/
│   ├── data.json              # Datos acumulados (dashboard)
│   ├── cvs/                   # CVs generados (HTML + PDF + foto)
│   └── feedback.json          # Feedback pendiente
└── .github/workflows/
    └── scraper.yml            # CI/CD (cron 2x/día)
```

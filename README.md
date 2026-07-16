# Asistente Inteligente de Empleo con IA y Notion

Recopila automáticamente ofertas de empleo de **9 plataformas**, analiza la compatibilidad con tu currículum usando **Gemini IA**, y sincroniza todo en **Notion** con un resumen por email.

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

## Características

1. **Análisis de Perfil:** Lee tu CV (PDF, DOCX, TXT o JSON) y extrae roles recomendados y habilidades clave.
2. **Scraping en 9 fuentes:** Con curl_cffi para evadir anti-bot (Cloudflare, Distil Networks).
3. **Scoring IA:** Gemini calcula match %, stack tecnológico, salario estimado y consejos personalizados.
4. **Notion Sync:** Sube ofertas evitando duplicadas, con borrado automático si marcas "Eliminar".
5. **Email de resumen:** Recibe un email HTML con estadísticas por plataforma, top ofertas y errores.
6. **Resultados persistentes:** Cada ejecución guarda JSON + CSV con métricas por scraper.
7. **Dashboard interactivo:** Streamlit con KPIs, gráficos, filtros, comparador y exportación CSV.
8. **Tests automatizados:** Verifican que todos los scrapers responden correctamente.
9. **Búsqueda multilingüe:** Busca automáticamente en español (InfoJobs, TecnoEmpleo) e inglés (LinkedIn, RemoteOK).
10. **Dedup fuzzy matching:** Detecta duplicados cross-scraper con similitud de texto (no solo URL exacta).
11. **Tracker de aplicaciones:** Pipeline en Notion: Nuevo → Revisado → Interesado → Aplicado → Entrevista → Oferta → Rechazado.
12. **Carta de presentación IA:** Genera cartas personalizadas por oferta con Gemini.
13. **Skills gap analysis:** Detecta qué habilidades faltan en tu CV vs demanda del mercado.
14. **Informe de mercado:** Tendencias de tech, salarios, empresas que contratan.
15. **Inteligencia salarial:** Estadísticas de salario por modalidad y plataforma en el dashboard.
16. **Comparador de ofertas:** Compara 2-3 ofertas lado a lado en el dashboard.
17. **Webhooks:** Notificaciones en tiempo real a Slack, Discord o URL genérica para ofertas de alto match.

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

---

## Dashboard

Dashboard público desplegado en **Streamlit Cloud**:

🔗 **https://jorgejs4-job-finder-assistant-dashboard-xxxxx.streamlit.app**

> Si el enlace no funciona, desplégalo tú mismo: ve a [share.streamlit.io](https://share.streamlit.io), conecta el repo `Jorgejs4/Job-Finder-Assistant`, selecciona `dashboard.py` como archivo principal y haz click en "Deploy".

### Qué muestra

- **KPIs:** Ofertas encontradas, añadidas a Notion, analizadas por IA, scrapers OK/fallidos
- **Pipeline de aplicaciones:** Funnel visual del estado de cada oferta (7 colores)
- **Inteligencia salarial:** Promedio, mediana, min, max + desglose por modalidad y plataforma
- **Comparador de ofertas:** Selecciona 2-3 ofertas y compáralas lado a lado con tabla + consejos
- **Gráficos:** Evolución de ofertas por ejecución, scrapers OK vs fallidos
- **Tabla de scrapers:** Estado de cada plataforma (OK, vacío, fallido) y número de ofertas
- **Ofertas:** Tabla con todos los resultados, filtrable por fuente, match, modalidad y estado
- **Exportación:** Botón para descargar el CSV filtrado

### Cómo funciona

El dashboard lee los datos directamente desde el repositorio en GitHub (archivo `results/data.json`). Cada ejecución del scraper actualiza este archivo automáticamente, así que el dashboard siempre muestra los datos más recientes sin necesidad de redesplegar.

### Lanzarlo localmente

```bash
~/proyectos/job_scraper_ai/venv/bin/streamlit run dashboard.py
```

Abrir **http://localhost:8501** en el navegador.

---

## Tests automatizados

Los tests verifican que los 9 scrapers y todas las features responden correctamente. Se ejecutan automáticamente en GitHub Actions antes de cada run del scraper.

### Ejecutar tests localmente

```bash
# Tests de scrapers (sin gastar cuota de Gemini)
MOCK_GEMINI=true python tests/test_scrapers.py

# Test de conexión Gemini (gasta 1 llamada)
python test_gemini.py
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
| `JOOBLE_API_KEY` | No | API key de Jooble (mejora resultados) |
| `DESIRED_LOCATIONS` | No | Ubicaciones por defecto (ej: `Sevilla,Remoto`) |
| `YEARS_OF_EXPERIENCE` | No | Años de experiencia (ej: `3`) |
| `MIN_SALARY` | No | Salario mínimo anual (ej: `35000`) |
| `SMTP_GMAIL_USER` | No | Email de Gmail para notificaciones |
| `SMTP_GMAIL_PASSWORD` | No | Contraseña de aplicación de Gmail |
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

### Campos opcionales en Notion

Para usar las funciones avanzadas, añade estos campos a tu base de datos:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `Estado` | Select | Pipeline: Nuevo, Revisado, Interesado, Aplicado, Entrevista, Oferta, Rechazado |
| `Carta Presentación` | Rich text | Carta de presentación generada por IA para cada oferta |
| `Exp` | Number | Años de experiencia requeridos |
| `Origen Salario` | Select | "Estimado (IA)" o "Directo" |

### Flujo de ejecución

El workflow se ejecuta **dos veces al día (8:00 y 20:00 UTC)**:

1. **Tests** → Verifica que los scrapers responden (con Gemini mock)
2. **Scraper** → Ejecuta el pipeline completo (scraping → IA → Notion → email → webhooks)
3. **Artifacts** → Guarda resultados JSON por 90 días
4. **Commit** → Actualiza `results/data.json` en el repositorio (para el dashboard)

También puedes ejecutarlo manualmente desde **Actions > Job Scraper and Notion Sync > Run workflow**.

---

## Resultados

Cada ejecución acumula datos en `results/data.json` (único archivo, máx. 100 ejecuciones):

| Campo | Descripción |
|-------|-------------|
| `runs[].run_id` | ID de la ejecución (YYYYMMDD_HHMMSS) |
| `runs[].timestamp` | Fecha/hora ISO de la ejecución |
| `runs[].scraper_stats` | Ofertas por plataforma, estado OK/fallido |
| `runs[].jobs` | Todas las ofertas encontradas con match, salario, stack... |
| `runs[].errors` | Errores durante la ejecución |

El archivo se actualiza automáticamente tras cada ejecución en GitHub Actions.

# Configuración multiusuario con Supabase

La base multiusuario usa Supabase como fuente principal. Ejecuta `migrations/001_multitenant.sql` en el SQL Editor de Supabase antes de usarla.

## Variables

Configura en el entorno del servidor o en `st.secrets`:

```text
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<publishable-or-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<server-only-secret>
```

`create_browser_client()` solo usa la clave anon/publishable. `create_server_client()` exige `SUPABASE_SERVICE_ROLE_KEY`; nunca expongas esa clave en el navegador ni la pongas en GitHub Actions logs.

El dashboard permite configurar por usuario las ubicaciones, salario, experiencia, fuentes, límites de ofertas, workers Gemini, modo headless, frecuencia y límites de reanálisis. Esos valores se validan con `WorkflowConfig`, se guardan en `user_profiles.preferences` y se envían al workflow como JSON validado.

## Google OIDC en Streamlit

Registra una aplicación web en Google Cloud y añade el callback de Streamlit en los URI autorizados. En `.streamlit/secrets.toml` usa:

```toml
[auth]
redirect_uri = "https://<tu-app>.streamlit.app/oauth2callback"
cookie_secret = "<secreto-largo-aleatorio>"
client_id = "<google-client-id>"
client_secret = "<google-client-secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

También se aceptan variables `STREAMLIT_AUTH_REDIRECT_URI`, `STREAMLIT_AUTH_COOKIE_SECRET`, `STREAMLIT_AUTH_CLIENT_ID`, `STREAMLIT_AUTH_CLIENT_SECRET` y `STREAMLIT_AUTH_SERVER_METADATA_URL` para detección/configuración externa. La app llama a `st.login("google")`, `st.user` y `st.logout()` mediante `utils.auth`.

## Relación OIDC y RLS

El OIDC nativo de Streamlit identifica al usuario en la sesión de Streamlit, pero no crea automáticamente una sesión JWT de Supabase. Para consultas directas desde browser, establece una sesión de Supabase Auth y usa el cliente anon, de forma que `auth.uid()` aplique RLS. Para procesos de servidor, usa el service-role únicamente dentro de backend y crea `TenantRepository(client, user_id)` con el identificador interno UUID de Supabase; el repositorio vuelve a filtrar cada operación por `user_id`.

Si se mantiene solo Google OIDC sin enlazarlo a un usuario de Supabase, el fallback debe mostrarse como "autenticación configurada pero persistencia Supabase no enlazada" y no se debe inventar un UUID a partir del `sub` de Google.

El pipeline heredado todavía puede generar archivos localmente para compatibilidad con datos históricos, pero los workflows ya no los añaden al repositorio ni a sus artifacts. La conexión del pipeline a `CVStorage` y la migración de URLs históricas son pasos posteriores y requieren un `auth.users.id` por usuario.

## CVs privados

La migración crea el bucket privado `cv-files`. `utils.cv_storage.CVStorage` genera rutas `<user_id>/<random>.<ext>` y URLs firmadas con expiración. No uses `custom_cv_url` apuntando a GitHub para CVs nuevos y no subas CVs originales a `results/` ni al repositorio. Los CVs históricos del flujo SQLite/GitHub requieren una migración explícita posterior, no automática.

## Scheduler y workflows

Activa el workflow `.github/workflows/tenant-scheduler.yml` y configura los secretos `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `GEMINI_API_KEYS` y `GITHUB_TOKEN`. El scheduler consulta `workflow_schedules` cada 15 minutos y reclama usuarios con `FOR UPDATE SKIP LOCKED`. El dashboard puede iniciar scraping o reanálisis bajo demanda mediante los workflows tenant.

## Ejemplo de uso

```python
from utils.auth import current_user
from utils.cv_storage import CVStorage
from utils.supabase_client import create_server_client
from utils.tenant_repository import TenantRepository

user = current_user()
if user is not None:
    # user.user_id debe estar enlazado a auth.users.id antes de persistir.
    repository = TenantRepository(create_server_client(), user.user_id)
    storage = CVStorage(repository.client)
```

Los tests `tests/test_multitenant.py` usan dobles en memoria y no hacen llamadas de red ni escriben datos reales.

## Workflows por usuario

`utils.workflow_config.WorkflowConfig` valida los parámetros permitidos y aplica sus defaults. La aplicación servidor despacha `tenant-scrape.yml` o `tenant-reanalyze.yml` con `user_id` y un `config_json`; el token de GitHub se obtiene exclusivamente de `os.environ` en `utils.workflow_dispatch`.

Los workflows tienen `contents: read`, reciben únicamente inputs tipados como texto y usan `SUPABASE_SERVICE_ROLE_KEY` y Gemini desde GitHub Secrets. No suben artifacts, CVs, `data.json` ni hacen commits.

El scheduler debe ejecutarse como proceso backend con `Scheduler(create_server_client(), dispatch_workflow)`. La función `claim_due_workflows` de la migración reclama filas con `FOR UPDATE SKIP LOCKED` y un lease, evitando que dos instancias despachen al mismo usuario.

El punto de integración del worker es `TenantWorker`: inyecta scrapers y analizador para producción o tests, y limita toda lectura/escritura a `TenantRepository(client, user_id)`. La caché exige `content_hash` y `analysis_hash`; el worker nunca usa el pipeline SQLite/GitHub legado.

# Configuración de variables

La aplicación tiene dos superficies: el dashboard de Streamlit y los workers de GitHub Actions. Usa siempre secretos; no los escribas en `README.md`, `data.json`, commits ni capturas.

## 1. Crear Supabase

1. Crea un proyecto en [Supabase](https://supabase.com/dashboard).
2. Abre `SQL Editor` y ejecuta `migrations/001_multitenant.sql`.
3. En `Project Settings > API` copia:
   - `Project URL` como `SUPABASE_URL`.
   - `Publishable key` o `anon key` como `SUPABASE_ANON_KEY`.
   - `service_role` como `SUPABASE_SERVICE_ROLE_KEY`.
4. La `service_role` omite RLS. Solo debe existir en Streamlit server-side y GitHub Actions, nunca en código del navegador.

## 2. Configurar Google OAuth para Streamlit

1. En [Google Cloud Console](https://console.cloud.google.com/) crea o selecciona un proyecto.
2. En `APIs & Services > OAuth consent screen`, configura la aplicación.
3. En `Credentials > Create credentials > OAuth client ID`, selecciona `Web application`.
4. Añade como callback autorizado:

```text
https://TU_APP.streamlit.app/oauth2callback
```

5. Guarda el client ID y el client secret.
6. Genera un secreto aleatorio largo para `cookie_secret`.
7. En Streamlit Cloud, abre `Settings > Secrets` y añade:

```toml
SUPABASE_URL = "https://TU_PROYECTO.supabase.co"
SUPABASE_ANON_KEY = "TU_ANON_O_PUBLISHABLE_KEY"
SUPABASE_SERVICE_ROLE_KEY = "TU_SERVICE_ROLE_KEY"
GITHUB_TOKEN = "TU_TOKEN_SERVER_SIDE"
GITHUB_REPO = "Jorgejs4/Job-Finder-Assistant"

[auth]
redirect_uri = "https://TU_APP.streamlit.app/oauth2callback"
cookie_secret = "SECRETO_ALEATORIO_LARGO"
client_id = "TU_GOOGLE_CLIENT_ID"
client_secret = "TU_GOOGLE_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

`SUPABASE_ANON_KEY` es la única clave potencialmente publicable. En esta versión el dashboard usa operaciones server-side para resolver el usuario, por lo que `SUPABASE_SERVICE_ROLE_KEY` y `GITHUB_TOKEN` deben permanecer en Secrets y nunca mostrarse en pantalla.

## 3. Configurar GitHub Actions

En `Settings > Secrets and variables > Actions > New repository secret`, crea:

| Secreto | Uso |
|---|---|
| `SUPABASE_URL` | Conexión al proyecto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Worker y scheduler server-side |
| `GEMINI_API_KEY` | Análisis Gemini |
| `GEMINI_API_KEYS` | Rotación opcional de claves Gemini, separadas por comas |

El scheduler usa el `GITHUB_TOKEN` automático del workflow y necesita `actions: write`, ya incluido en `tenant-scheduler.yml`.

Activa manualmente `Tenant workflow scheduler` una vez para comprobar la configuración. Después comprobará cada 15 minutos los usuarios cuyo horario haya vencido.

## 4. Ejecutar la migración legacy

Antes de migrar, crea una copia de seguridad de `results/data.json`, `results/jobs.db` y del CV original. Desde la raíz del proyecto:

```bash
set MIGRATION_USER_ID=UUID_DE_AUTH_USERS
python scripts/migrate_legacy_to_supabase.py --user-id "%MIGRATION_USER_ID%"
```

En PowerShell:

```powershell
$env:MIGRATION_USER_ID = "UUID_DE_AUTH_USERS"
python scripts/migrate_legacy_to_supabase.py --user-id $env:MIGRATION_USER_ID
```

El UUID debe pertenecer a `Authentication > Users` en Supabase. La primera entrada de Google OAuth lo crea automáticamente; también se puede obtener después del primer login.

La migración:

- Importa ofertas deduplicadas por URL canónica.
- Importa ejecuciones e historial.
- Conserva estados, archivado y análisis existentes.
- Importa feedback pendiente.
- Sube el CV original y los artefactos CV referenciados al bucket privado.
- No importa tokens de Notion globales.
- Ignora ejecuciones y ofertas de prueba.

## 5. Notion por usuario

Notion es opcional. Cada usuario debe conectar su propio `database_id` y token desde una futura pantalla de conexión segura. No reutilices el `NOTION_TOKEN` global anterior entre usuarios.

## 6. Rotación de secretos expuestos

Si una clave se ha guardado en un archivo, commit, log o captura:

1. Revócala en el proveedor inmediatamente.
2. Genera una nueva.
3. Actualiza Streamlit Secrets y GitHub Actions Secrets.
4. Elimina el secreto del historial Git si llegó a publicarse.

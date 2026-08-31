# Job Finder Assistant Web

Frontend Next.js para Vercel. La aplicación Streamlit y los workers Python se mantienen en la raíz del repositorio durante la migración.

## Desarrollo

```bash
cp .env.example .env.local
npm install
npm run dev
```

Configura en `.env.local` las variables públicas de Supabase. `SUPABASE_SERVICE_ROLE_KEY` y `GITHUB_TOKEN` son exclusivamente server-side y no se usan en el navegador.

## Vercel

Configura el Root Directory como `web`, añade las variables de entorno para Preview y Production, y establece en Supabase Auth las URLs de redirección:

```text
https://TU_DOMINIO/auth/callback
http://localhost:3000/auth/callback
```

El endpoint `POST /api/workflows` solo acepta `tenant-scrape.yml` o `tenant-reanalyze.yml` y obtiene el `user_id` de la sesión Supabase, nunca del cliente.

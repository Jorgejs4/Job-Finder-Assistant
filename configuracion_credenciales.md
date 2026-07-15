# Guía de Configuración de Credenciales y Notion

Para que tu aplicación gratuita funcione, necesitamos conectar tres servicios clave: **Google AI Studio (Gemini)**, **Notion** y opcionalmente **RapidAPI (JSearch)** para el fallback de empleo. Sigue estos pasos para obtener las claves necesarias.

---

## 1. Obtener la API Key de Google AI Studio (Gemini API)

La API de Gemini es la que usaremos para analizar tu CV, puntuar las ofertas y darte consejos. En su plan gratuito, no te cobrará nada.

1. Entra en [Google AI Studio](https://aistudio.google.com/).
2. Inicia sesión con tu cuenta de Google.
3. Haz clic en el botón **"Get API key"** (Obtener clave de API) en la esquina superior izquierda.
4. Selecciona **"Create API key"** (Crear clave de API).
5. Selecciona la opción para crear la clave en un proyecto nuevo o existente.
6. Copia la clave generada (empieza por `AIzaSy...`) y guárdala en un lugar seguro.

---

## 2. Configurar Notion (Base de Datos e Integración)

Crearemos la base de datos donde se guardarán las ofertas y una "integración" para que el script pueda escribir en ella.

> [!NOTE]
> **Sobre el Token de Notion:** Es completamente normal que tu token empiece por `ntn_` (del inglés *Notion*). Notion actualizó recientemente el formato de sus tokens de integración para nuevas cuentas. Los tokens antiguos empezaban por `secret_`, pero los nuevos empiezan por `ntn_`. Ambos funcionan exactamente igual.

### Paso A: Crear la Base de Datos en Notion
1. Abre Notion y crea una **nueva página** vacía.
2. Escribe `/database` y selecciona **Base de datos - Completa** (Database - Full page) o **Base de datos - En línea** (Database - Inline). Nómbrala como quieras (ej. "Ofertas de Empleo").
3. Crea las siguientes columnas (propiedades) con sus respectivos tipos de datos exactos:

| Nombre de la columna | Tipo de propiedad | Descripción |
| :--- | :--- | :--- |
| **Puesto** | `Title` (Título) | El nombre de la oferta de trabajo |
| **Empresa** | `Select` (Selección) | Nombre de la empresa |
| **Ubicación** | `Text` (Texto) | Ciudad, País, Remoto, Híbrido, etc. |
| **Salario** | `Text` (Texto) | Rango salarial (opcional, puede estar vacío) |
| **Match Score** | `Number` (Número) | Porcentaje de compatibilidad (0 a 100) |
| **Stack Tecnológico**| `Multi-select` | Tecnologías requeridas (Python, React, etc.) |
| **Fecha Publicación**| `Date` (Fecha) | Cuándo se publicó la oferta |
| **Fecha Detección**  | `Date` (Fecha) | Cuándo la encontró nuestro script |
| **Enlace Oferta**    | `URL` | Enlace directo para aplicar |
| **Consejos CV**      | `Text` (Texto) | Recomendaciones personalizadas de Gemini |
| **Eliminar**         | `Checkbox` (Casilla) | Actívalo para borrar ofertas caducadas/malas |

### Paso B: Crear la Integración de Notion y obtener el Token
1. Entra en [Notion Integrations](https://www.notion.so/my-integrations).
2. Haz clic en **"+ New integration"** (+ Nueva integración).
3. Ponle un nombre (ej. "Scraper de Empleo") y asegúrate de que esté asociada a tu espacio de trabajo actual.
4. En la pestaña **Capabilities** (Capacidades), asegúrate de que tenga permisos de:
   * **Read content** (Leer contenido)
   * **Update content** (Actualizar contenido)
   * **Insert content** (Insertar contenido)
5. Haz clic en **Submit** (Enviar).
6. Copia el **Internal Integration Token** (Token de integración secreto, empieza por `ntn_`) y guárdalo.

### Paso C: Conectar la Integración a tu Base de Datos
1. Ve a la página de Notion donde creaste la base de datos de ofertas de empleo.
2. En la esquina superior derecha, haz clic en los **tres puntos (`...`)**.
3. Baja hasta la opción **"Connect to"** (Conectar a) o **"Add connections"** (Añadir conexiones).
4. Busca el nombre de tu integración ("Scraper de Empleo") y selecciónala.
5. Confirma los accesos. ¡Listo! Tu script ya puede leer y escribir aquí.

### Paso D: Obtener el ID de la Base de Datos
1. Copia la URL de tu base de datos de Notion desde el navegador. La URL tendrá un formato similar a este:
   `https://www.notion.so/mi-espacio/854238e945c249a5b3d683a1b023de9b?v=...`
2. El **ID de la base de datos** es el código de 32 caracteres que está justo después del nombre del espacio y antes del signo de interrogación (`?`).
   * En el ejemplo anterior, el ID es: `854238e945c249a5b3d683a1b023de9b`. Guárdalo también.

---

## 3. Obtener la Key de RapidAPI (Para Fallback JSearch)

Si los scrapers propios fallan o son bloqueados por Cloudflare, el script usará la API de JSearch como plan de contingencia. Ofrece un plan gratuito de hasta 100 peticiones mensuales.

1. Regístrate o inicia sesión en [RapidAPI](https://rapidapi.com/) (puedes usar tu cuenta de GitHub o Google).
2. Ve a la página de la API de [JSearch en RapidAPI](https://rapidapi.com/letscrape-it-letscrape-it-default/api/jsearch).
3. Haz clic en el botón **"Subscribe to Test"** (Suscribirse para probar).
4. Elige el **Plan Gratuito (Basic)** de $0/mes que incluye 100 peticiones de búsqueda al mes.
5. Vuelve a la pestaña **Endpoints**.
6. En la parte derecha, en el código de ejemplo o en los parámetros de cabecera, busca el valor de la cabecera `x-rapidapi-key`. Es una cadena alfanumérica de unos 50 caracteres.
7. Copia esta clave y guárdala como `RAPIDAPI_KEY` en tu `.env` o secretos de GitHub.

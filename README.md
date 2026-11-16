# PlanificA+ · Control de obra

Aplicación web para controlar el programa de una obra de subestación eléctrica:

- **Login** con usuario y contraseña, y **perfiles** (Administrador de contrato, Oficina técnica, Terreno, Solo lectura). Cada perfil solo modifica las etapas de su área.
- **Carta Gantt** con dependencias, atrasos de inicio y plantilla de 15 etapas típicas (o proyecto en blanco).
- **Línea base**: «Poner en marcha» congela el programa. Cada cambio posterior exige causa y justificación y queda registrado con ID (`CHG-0001`).
- **Avance plan vs real**: el plan se calcula solo con las fechas de la Gantt; el real lo informa cada área en %. Semáforo: 🟢 hasta 5 pp de atraso · 🟡 de 6 a 10 · 🔴 desde 11. Al llegar a 100 % la etapa se cierra con fecha real (`AV-0001`).
- **KPI**: desviación del término, % de etapas cerradas en plazo, desviación promedio al cierre, días por causa, evolución de la fecha de término y cambios por área.
- **Exportación a Excel** del programa, los cambios y el registro de avance.
- **Asistente IA** (Gemini o Claude) que responde solo sobre el proyecto: resumen, etapas en riesgo, reporte semanal y extracción de hitos desde las bases.
- **Seguridad de claves**: las claves que asigna el administrador son temporales (el usuario crea la suya al entrar), cada usuario puede cambiar su clave y la recuperación de contraseña pasa por el dueño de la app (`APP_OWNER`).

Proyecto A+S · AIEP Santiago Norte · Ingeniería Industrial · INU603 — Leslie Vera, Christopher Iturriaga, Andrés Molina.

---

## Usuarios de demostración

| Usuario | Perfil | Puede editar |
|---|---|---|
| `alberto` | Administrador de contrato | Todo: proyectos, usuarios, línea base y las tres áreas |
| `oficina` | Jefe de oficina técnica | Etapas de Oficina técnica |
| `terreno` | Jefe de terreno | Etapas de Terreno |
| `visita` | Solo lectura | Nada (para el profesor o visitas) |

Contraseña inicial de todos: la que definas en `DEMO_PASSWORD` (si no defines nada: `planifica2026`).
**Cámbiala** desde la pestaña Administración apenas publiques la app.

---

## Probar en tu computador

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`. Los datos se guardan en el archivo `planificaplus.db` (SQLite). Para volver al ejemplo inicial, borra ese archivo.

---

## Publicar gratis en internet

### 1 · Base de datos permanente (Supabase, gratis)

Streamlit Cloud **borra los archivos locales** cada vez que la app se reinicia, por eso los datos deben vivir en una base externa.

1. Crea una cuenta en [supabase.com](https://supabase.com) → **New project** (elige región São Paulo).
2. En el proyecto: **Connect** → copia la cadena de conexión del **Session pooler** (empieza con `postgresql://postgres.xxxx:...@aws-...pooler.supabase.com:5432/postgres`) y reemplaza `[YOUR-PASSWORD]` por la contraseña del proyecto.
   Usa el *pooler* y no la conexión directa: Streamlit Cloud necesita conexión IPv4.
3. No hace falta crear tablas: la app las crea sola la primera vez.

> En el plan gratis, Supabase **pausa el proyecto tras 7 días sin uso**. Si pasa, entra a Supabase y pulsa *Restore*.

### 2 · Subir el código a GitHub

1. Crea una cuenta en [github.com](https://github.com) y un repositorio nuevo, por ejemplo `planificaplus`.
2. Sube todos los archivos de esta carpeta (botón **Add file → Upload files**). **No** subas `planificaplus.db` ni `secrets.toml`.

### 3 · Publicar en Streamlit Community Cloud

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub → **Create app**.
2. Repositorio: `tu-usuario/planificaplus` · Rama: `main` · Archivo: `app.py`.
3. En **Advanced settings → Secrets** pega (con tus datos):

   ```toml
   DATABASE_URL = "postgresql://postgres.xxxx:TU_CLAVE@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
   DEMO_PASSWORD = "una-clave-segura"
   APP_OWNER = "christopher"          # dueño: resuelve recuperaciones de clave
   GEMINI_API_KEY = "tu-api-key"       # opcional: activa el Asistente IA (aistudio.google.com)
   ```

4. **Deploy**. En 2–3 minutos tendrás una URL tipo `https://planificaplus.streamlit.app` para compartir.

> La app gratis "se duerme" tras 12 horas sin visitas; la primera carga después demora unos segundos.
> Si el repositorio es público, el código queda visible, pero los **datos y claves no**: viven en Supabase y en Secrets.

---

## Estructura

| Archivo | Contenido |
|---|---|
| `app.py` | Interfaz (Streamlit): login, Gantt, avance, etapas, historial, KPI y administración |
| `logic.py` | Cálculos: programación por dependencias, avance plan, semáforo, diferencias entre versiones |
| `db.py` | Base de datos (SQLAlchemy), usuarios con contraseña cifrada (bcrypt) y proyecto de ejemplo |
| `.streamlit/config.toml` | Colores de la app |
| `.streamlit/secrets.toml.example` | Ejemplo de configuración de secretos |

## Limitaciones conocidas del prototipo

- Si dos personas guardan al mismo tiempo, gana la última (la edición del programa sí está bloqueada para un usuario a la vez).
- El avance plan es lineal entre el inicio y el fin de cada etapa.
- Las fechas no consideran feriados ni días no laborables.

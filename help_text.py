"""Textos de la ayuda de PlanificA+ (botón ❓ Ayuda)."""

SECTIONS = {
    "🚀 Primeros pasos": """
**PlanificA+ controla el programa de una obra: lo planificas, lo congelas como línea base y mides el avance real contra el plan.**

1. **Crear el proyecto** · *Administración → Proyectos*: nombre, fecha de inicio y punto de partida (plantilla de subestación o en blanco). Queda en **Borrador**.
2. **Armar el programa** · pestaña *🧩 Programa*: escribe las tareas fila por fila o **importa la plantilla Excel**.
3. **Poner en marcha** · botón arriba: el programa se congela como **línea base v1**.
4. **Informar avance** · pestaña *✅ Avance real*: cada responsable registra su % y la fecha de cierre.
5. **Controlar** · *📊 Carta Gantt*, *📈 KPI* y *🤖 Asistente IA* muestran desviaciones, ruta crítica y riesgos.
6. **Cambiar el programa** · botón *Editar programa*: cada cambio pide causa y justificación y queda con ID (`CHG-0001`).

**Estados del proyecto:** 🔵 Borrador (se arma libremente) · 🟢 En marcha (se mide avance) · 🟠 Editando (un usuario modifica el programa).
""",
    "🧩 Programa (Gantt)": """
**Cómo escribir el programa** (pestaña *🧩 Programa*, perfiles Administrador y PMO):

| Columna | Qué va |
|---|---|
| **EDT** | `1` = tarea global · `1.1` = subtarea · `1.1.1` = tarea |
| **Tipo** | *Tarea* · *Hito* (duración 0, se dibuja ◆) · *Resumen* (agrupa; fechas y avance se calculan solos) |
| **Área / Responsable** | Quién puede informar el avance de esa tarea |
| **Duración / Atraso** | En días (corridos u hábiles, según el calendario del proyecto) |
| **Inicio fijo** | Opcional: "no empieza antes de" esta fecha |
| **Predecesoras** | De qué tareas depende (ver abajo) |

**Predecesoras (igual que en MS Project):**
- `2.1.1` → empieza cuando **termina** la 2.1.1 (fin-comienzo, FC)
- `2.1.1CC+3` → empieza **3 días después de que empieza** la 2.1.1 (comienzo-comienzo)
- `5.2FF-2` → **termina 2 días antes** que la 5.2 (fin-fin) · `CF` = comienzo-fin
- Varias: `2.1.1, 3.1`

**Ruta crítica:** tareas sin holgura (borde rojo 🔴). Si se atrasan, se atrasa el término del proyecto.
**Calendario:** *días corridos* o *días hábiles* (sin fines de semana ni feriados de Chile). Se elige en Borrador.
**Excel:** *Descargar en Excel* entrega el programa en formato plantilla; *Importar* lo carga (solo en Borrador) y avisa la fila exacta si algo está mal.
""",
    "✅ Avance y semáforo": """
- **Avance plan**: lo calcula la app según las fechas de la Gantt y la **fecha de corte** (barra lateral).
- **Avance real**: lo informa cada responsable en *✅ Avance real* (con el interruptor *Solo mis tareas* ves solo lo tuyo).
- Al llegar a **100 %** la tarea se cierra con su fecha real y se mide la desviación contra la línea base.
- Cada registro queda con ID (`AV-0001`) en *🧾 Historial*.

**Semáforo** (atraso del real frente al plan):
🟢 hasta 5 pp · 🟡 de 6 a 10 pp · 🔴 desde 11 pp.

Los avances del proyecto y de las tareas resumen se ponderan por la duración de cada tarea.
""",
    "🧾 Cambios y línea base": """
- **Poner en marcha** congela el programa como **línea base** (barra gris en la Gantt).
- Para modificarlo: **Editar programa** → haces los cambios → **Guardar cambio…** → eliges la **causa** y escribes la justificación.
- Se registra como `CHG-0001`, `CHG-0002`… con versión, usuario, fecha e **impacto en días** sobre el término.
- *Cancelar edición* deshace todo lo que no se guardó.
- Mientras alguien edita, el programa queda bloqueado para los demás.
- *📈 KPI* muestra días de atraso por causa, evolución del término por versión y cierres en plazo.
""",
    "👤 Usuarios y seguridad": """
**Perfiles:** Administrador de contrato (todo) · PMO (arma el programa) · Jefe de oficina técnica · Jefe de terreno · Solo lectura.

- La **clave inicial es temporal**: al primer ingreso la app obliga a crear una propia.
- Una cuenta nueva que **no entra en 5 días** se desactiva sola.
- **5 intentos fallidos** bloquean la cuenta 15 minutos.
- La sesión se cierra tras **30 minutos** sin actividad.
- ¿Olvidaste la clave? Usa *¿Olvidaste tu contraseña?* en el ingreso: la solicitud llega al **dueño de la app**, que entrega una clave temporal.
- Cambia tu clave cuando quieras en *Cambiar mi contraseña* (barra lateral).
""",
    "🤖 Asistente IA": """
El asistente responde **solo sobre el proyecto cargado y el uso de PlanificA+**.

- Botones rápidos: *Resumen del estado*, *Etapas en riesgo*, *Reporte semanal*.
- Puedes pedirle una nota al libro de obra, un acta o un resumen para la ITO.
- *Extraer hitos y multas*: pega el texto de las bases de licitación y te lista plazos y obligaciones.
- Preguntas fuera del proyecto reciben: *"Esa consulta no aplica para PlanificA+"*.
""",
}

"""PlanificA+ · Control de obra — Streamlit."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

import db
import logic
from logic import AREAS, ROLES, CAUSES, TOL_OK, TOL_HIGH

st.set_page_config(page_title="PlanificA+ · Control de obra", page_icon="📐", layout="wide")

ACCENT, WARN, OK, BAD, BASE, INK = "#0E5E52", "#C98A12", "#2F7A3A", "#AE2A21", "#A9B3AE", "#17201D"
st.markdown("""<style>
.block-container{padding-top:1.6rem}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:.82rem}
.p-draft{background:#E2E9F4;color:#3E5A86}.p-live{background:#E3F1E4;color:#2F7A3A}.p-edit{background:#FBEFD6;color:#9A6408}
.brand{font-size:2rem;font-weight:700;letter-spacing:.01em}.brand b{color:#0E5E52}
</style>""", unsafe_allow_html=True)

try:
    DEMO_PW = st.secrets["DEMO_PASSWORD"]
except Exception:
    DEMO_PW = "planifica2026"


@st.cache_resource
def _init():
    db.init_db(DEMO_PW)
    return True


_init()


# ---------------------------------------------------------------- sesión
def login_view():
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="brand">Planific<b>A+</b></div>', unsafe_allow_html=True)
        st.caption("Control de obra · Línea base, avance real y control de cambios")
        with st.form("login"):
            u = st.text_input("Usuario")
            pw = st.text_input("Contraseña", type="password")
            ok = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if ok:
            with db.Session() as s:
                user = s.scalar(select(db.User).where(db.User.username == u.strip().lower(), db.User.active == 1))
            if user and db.check_pw(pw, user.pw_hash):
                st.session_state.uid = user.id
                st.rerun()
            st.error("Usuario o contraseña incorrectos.")
        st.caption("Prototipo A+S · AIEP Santiago Norte · Leslie Vera, Christopher Iturriaga, Andrés Molina")


if "uid" not in st.session_state:
    login_view()
    st.stop()

with db.Session() as s:
    USER = s.get(db.User, st.session_state.uid)
if USER is None:
    st.session_state.clear()
    st.rerun()
ROLE_NAME, MY_AREAS = ROLES[USER.role]
IS_ADMIN = USER.role == "admin"
can = lambda area: area in MY_AREAS

# ---------------------------------------------------------------- barra lateral
with db.Session() as s:
    projects = s.scalars(select(db.Project).order_by(db.Project.id)).all()
with st.sidebar:
    st.markdown('<div class="brand">Planific<b>A+</b></div>', unsafe_allow_html=True)
    st.write(f"**{USER.name}**  \n{ROLE_NAME}")
    st.caption("Edita: " + (", ".join(AREAS[a] for a in MY_AREAS) or "nada (solo lectura)"))
    if not projects:
        st.warning("No hay proyectos.")
        PID = None
    else:
        ids = [p.id for p in projects]
        default = st.session_state.get("pid", ids[0])
        PID = st.selectbox("Proyecto", ids, index=ids.index(default) if default in ids else 0,
                           format_func=lambda i: next(p.name for p in projects if p.id == i))
        st.session_state.pid = PID
    CORTE = st.date_input("Fecha de corte", value=date.today(), help="Fecha usada para calcular el avance plan. Por defecto, hoy.")
    if st.button("Cerrar sesión", width="stretch"):
        st.session_state.clear()
        st.rerun()

if PID is None:
    st.info("Crea un proyecto desde Administración.")
    st.stop()


def load() -> db.Project:
    with db.Session() as s:
        return s.get(db.Project, PID)


P = load()
TASKS, BASEL = P.tasks, P.baseline
CUR = logic.schedule(P.start, TASKS)
BAS = logic.schedule(P.start, BASEL)
IN_BASE = {t["code"] for t in BASEL}
DRAFT, LIVE, EDIT = P.status == "draft", P.status == "live", P.status == "edit"
I_EDIT = EDIT and (P.edit_by == USER.name)


def fmt(d: date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


def mutate(fn):
    """Aplica fn(session, project) y guarda."""
    with db.Session() as s:
        p = s.get(db.Project, PID)
        fn(s, p)
        s.commit()


# ---------------------------------------------------------------- encabezado
dev_end = (CUR["end"] - BAS["end"]).days
pill = {"draft": ("Borrador", "p-draft"), "live": ("En marcha", "p-live"), "edit": ("Editando", "p-edit")}[P.status]
st.markdown(f'### {P.name} <span class="pill {pill[1]}">{pill[0]}</span>', unsafe_allow_html=True)
st.caption(f"Inicio {fmt(P.start)} · versión v{P.version}" +
           (f" · línea base aprobada por {P.baseline_by} el {fmt(P.baseline_at)}" if not DRAFT else " · sin línea base")
           + (f" · en edición por {P.edit_by}" if EDIT else ""))

pct_plan = {t["code"]: logic.pct_at(CUR["at"].get(t["code"]), t["dur"], CORTE) for t in TASKS}
pct_real = {t["code"]: int(t.get("real_pct") or 0) for t in TASKS}
p_plan, p_real = logic.weighted(TASKS, pct_plan), logic.weighted(TASKS, pct_real)
p_orig = logic.weighted(BASEL, {t["code"]: logic.pct_at(BAS["at"].get(t["code"]), t["dur"], CORTE) for t in BASEL})
lvl, lbl = logic.semaforo(p_plan - p_real)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Fin línea base", "—" if DRAFT else fmt(BAS["end"]))
c2.metric("Fin actual", fmt(CUR["end"]), None if DRAFT else f"{dev_end:+d} días", delta_color="inverse")
c3.metric("Avance plan", f"{p_plan}%")
c4.metric("Avance real", f"{p_real}%")
c5.metric("Desviación (real − plan)", f"{p_real - p_plan:+d} pp")
st.caption(f"Semáforo del proyecto: { {'verde': '🟢', 'amarillo': '🟡', 'rojo': '🔴'}[lvl]} {lbl}"
           + ("" if DRAFT or p_plan == p_orig else f" · Plan modificado: el plan original a esta fecha era {p_orig}%")
           + " · Avances ponderados por la duración de cada etapa")


# ---------------------------------------------------------------- acciones de estado
@st.dialog("Poner en marcha")
def dlg_go():
    st.write(f"El programa actual ({len(TASKS)} etapas, término **{fmt(CUR['end'])}**) quedará congelado como **línea base v1**. "
             "Desde ahí cada cambio exigirá causa y justificación.")
    if st.button("Aprobar y poner en marcha", type="primary"):
        def f(s, p):
            p.baseline, p.status, p.version = p.tasks, "live", 1
            p.baseline_by, p.baseline_at = USER.name, date.today()
        mutate(f)
        st.rerun()


@st.dialog("Registrar cambio al programa")
def dlg_save():
    items = logic.diff_tasks(P.snapshot, TASKS)
    if not items:
        st.info("No hay cambios: modifica, agrega o elimina una etapa primero.")
        return
    e0 = logic.schedule(P.start, P.snapshot)["end"]
    imp = (CUR["end"] - e0).days
    for it in items:
        st.write("• " + logic.change_text(it))
    st.write(f"Impacto en el término: **{imp:+d} días** (nuevo término {fmt(CUR['end'])}).")
    cause = st.selectbox("Causa", [""] + CAUSES, format_func=lambda c: c or "Elige una causa…")
    reason = st.text_area("Explica el cambio", placeholder="Qué pasó, quién lo informó y qué se hará para recuperar el plazo")
    if st.button("Guardar cambio", type="primary"):
        if not cause or len(reason.strip()) < 15:
            st.error("Elige la causa y escribe al menos una frase (15 caracteres) explicando el cambio.")
            return
        def f(s, p):
            ch = db.record_change(s, p, p.snapshot, p.tasks, USER.name, cause, reason.strip())
            p.status, p.snapshot, p.edit_by = "live", [], ""
            st.session_state.toast = f"{ch.code} guardado en el historial"
        mutate(f)
        st.rerun()


a1, a2, a3, _ = st.columns([1.2, 1.2, 1.2, 4])
if DRAFT and IS_ADMIN:
    if a1.button("Poner en marcha", type="primary"):
        dlg_go()
elif LIVE and MY_AREAS:
    if a1.button("Editar programa"):
        def f(s, p):
            p.status, p.snapshot, p.edit_by = "edit", p.tasks, USER.name
        mutate(f)
        st.rerun()
elif EDIT and (I_EDIT or IS_ADMIN):
    if a1.button("Guardar cambio…", type="primary"):
        dlg_save()
    if a2.button("Cancelar edición"):
        def f(s, p):
            p.tasks, p.status, p.snapshot, p.edit_by = p.snapshot, "live", [], ""
        mutate(f)
        st.rerun()
if EDIT and not I_EDIT:
    st.warning(f"{P.edit_by} está editando el programa. Podrás editar cuando guarde o cancele.")
if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"))

# ---------------------------------------------------------------- tablas base
num = {t["code"]: i + 1 for i, t in enumerate(TASKS)}
touched = set()
with db.Session() as s:
    CHANGES = s.scalars(select(db.Change).where(db.Change.project_id == PID).order_by(db.Change.id)).all()
    LOGS = s.scalars(select(db.Progress).where(db.Progress.project_id == PID).order_by(db.Progress.id)).all()
for c in CHANGES:
    touched |= {it["code"] for it in c.items if it["type"] != "add"}


def close_dev(t) -> int | None:
    if not t.get("real_end") or t["code"] not in IN_BASE:
        return None
    return (date.fromisoformat(t["real_end"]) - BAS["at"][t["code"]][1]).days


def row(t, i):
    s_, e_ = CUR["at"][t["code"]]
    plan, real = pct_plan[t["code"]], pct_real[t["code"]]
    dev = plan - real
    note = ""
    if not DRAFT:
        if t["code"] not in IN_BASE:
            note = "Etapa nueva: sin plan original"
        else:
            bt = next(b for b in BASEL if b["code"] == t["code"])
            orig = logic.pct_at(BAS["at"][t["code"]], bt["dur"], CORTE)
            if orig != plan:
                note = f"Plan modificado · original {orig}%"
    if t.get("real_end"):
        cd = close_dev(t)
        sem = f"✅ Cerrada {t['real_end'][8:10]}-{t['real_end'][5:7]}" + ("" if cd is None else f" ({cd:+d} d)")
    elif plan == 0 and real == 0:
        sem = "⚪ Por iniciar"
    else:
        lv, lb = logic.semaforo(dev)
        sem = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}[lv] + " " + lb
    vs = None if DRAFT or t["code"] not in IN_BASE else (e_ - BAS["at"][t["code"]][1]).days
    return {"#": i + 1, "Etapa": t["name"], "Área": AREAS[t["area"]],
            "Depende de": ", ".join(str(num[d]) for d in t["deps"] if d in num) or "—",
            "Duración (d)": t["dur"], "Atraso (d)": t["lag"], "Inicio": s_, "Fin": e_, "vs base (d)": vs,
            "Avance plan %": plan, "Avance real %": real, "Desv. (pp)": real - plan, "Semáforo": sem, "Nota": note}


DF = pd.DataFrame([row(t, i) for i, t in enumerate(TASKS)])

tabs = ["📊 Carta Gantt", "✅ Avance real", "🛠️ Etapas", "🧾 Historial", "📈 KPI"] + (["⚙️ Administración"] if IS_ADMIN else [])
T = st.tabs(tabs)

# ---------------------------------------------------------------- Gantt
with T[0]:
    if not TASKS:
        st.info("El proyecto no tiene etapas. Agrega la primera en la pestaña Etapas.")
    else:
        labels = [f"{i + 1:02d} · {t['name'][:42]}" for i, t in enumerate(TASKS)]
        fig = go.Figure()
        ms = lambda d: d * 86400000
        if not DRAFT:
            bx = [(lab, BAS["at"][t["code"]]) for lab, t in zip(labels, TASKS) if t["code"] in IN_BASE]
            fig.add_bar(y=[b[0] for b in bx], base=[b[1][0].isoformat() for b in bx],
                        x=[ms(max((b[1][1] - b[1][0]).days, 0.6)) for b in bx], orientation="h",
                        marker_color=BASE, width=0.18, offset=0.2, name="Línea base", hoverinfo="skip")
        cols = []
        for t in TASKS:
            new = not DRAFT and t["code"] not in IN_BASE
            snap = {x["code"]: x for x in P.snapshot} if EDIT else {}
            chg = t["code"] in touched or (EDIT and t["code"] in snap and (snap[t["code"]]["dur"] != t["dur"] or snap[t["code"]]["lag"] != t["lag"]))
            cols.append(OK if new else WARN if chg else ACCENT)
        fig.add_bar(y=labels, base=[CUR["at"][t["code"]][0].isoformat() for t in TASKS],
                    x=[ms(max(t["dur"], 0.6)) for t in TASKS], orientation="h", marker_color=cols, width=0.45,
                    offset=-0.3, name="Programa actual",
                    customdata=[[fmt(CUR["at"][t["code"]][0]), fmt(CUR["at"][t["code"]][1]), pct_plan[t["code"]], pct_real[t["code"]]] for t in TASKS],
                    hovertemplate="%{y}<br>%{customdata[0]} → %{customdata[1]}<br>Plan %{customdata[2]}% · Real %{customdata[3]}%<extra></extra>")
        fig.add_bar(y=labels, base=[CUR["at"][t["code"]][0].isoformat() for t in TASKS],
                    x=[ms(max(t["dur"], 0.6) * pct_real[t["code"]] / 100) for t in TASKS], orientation="h",
                    marker_color=INK, width=0.14, offset=-0.14, name="Avance real", hoverinfo="skip")
        fig.add_shape(type="line", x0=CORTE.isoformat(), x1=CORTE.isoformat(), y0=0, y1=1, yref="paper",
                      line=dict(color=BAD, width=2, dash="dot"))
        fig.add_annotation(x=CORTE.isoformat(), y=1.02, yref="paper", text="corte", showarrow=False, font=dict(color=BAD))
        fig.update_layout(barmode="overlay", height=max(320, 34 * len(TASKS) + 90), margin=dict(l=10, r=10, t=30, b=10),
                          xaxis=dict(type="date", gridcolor="#E4E8E5"),
                          yaxis=dict(autorange="reversed", categoryorder="array", categoryarray=labels),
                          legend=dict(orientation="h", y=-0.08), plot_bgcolor="white")
        st.plotly_chart(fig, width="stretch")
        st.caption("Verde oscuro: programa actual · Gris: línea base · Amarillo: etapa con cambios · Verde: etapa agregada · Línea negra: avance real")
        st.dataframe(DF, hide_index=True, width="stretch",
                     column_config={"Inicio": st.column_config.DateColumn(format="DD-MM-YYYY"),
                                    "Fin": st.column_config.DateColumn(format="DD-MM-YYYY"),
                                    "Avance plan %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                                    "Avance real %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%")})

# ---------------------------------------------------------------- Avance real
with T[1]:
    st.markdown(f"**Semáforo:** 🟢 hasta {TOL_OK} pp de atraso · 🟡 de {TOL_OK + 1} a {TOL_HIGH} pp · 🔴 desde {TOL_HIGH + 1} pp. "
                "El avance plan se calcula solo con las fechas de la Gantt; el avance real lo informa cada área.")
    if not LIVE:
        st.info("El avance real se informa con el programa **En marcha** (no en borrador ni durante una edición).")
    else:
        mine = [t for t in TASKS if can(t["area"]) and not t.get("real_end")]
        if not mine:
            st.info("No tienes etapas abiertas de tu área.")
        else:
            code = st.selectbox("Etapa", [t["code"] for t in mine], format_func=lambda c: f"{num[c]}. {next(t['name'] for t in TASKS if t['code'] == c)}")
            t = next(x for x in TASKS if x["code"] == code)
            cc1, cc2 = st.columns(2)
            cc1.metric("Avance plan a la fecha de corte", f"{pct_plan[code]}%")
            cc2.metric("Avance real registrado", f"{pct_real[code]}%")
            st.caption(f"Plan vigente: {fmt(CUR['at'][code][0])} → {fmt(CUR['at'][code][1])}")
            with st.form(f"av-{code}"):
                v = st.slider("Nuevo avance real (%)", 0, 100, pct_real[code], step=1)
                f1, f2 = st.columns(2)
                rs = f1.date_input("Fecha real de inicio", value=date.fromisoformat(t["real_start"]) if t.get("real_start") else min(CUR["at"][code][0], date.today()),
                                   max_value=date.today(), disabled=bool(t.get("real_start")))
                re_ = f2.date_input("Fecha real de cierre (solo si llega a 100%)", value=date.today(), max_value=date.today())
                com = st.text_input("Comentario (opcional)")
                sent = st.form_submit_button("Registrar avance", type="primary")
            if sent:
                if v == pct_real[code] and v != 100:
                    st.warning("El avance no cambió.")
                elif v == 100 and re_ < rs:
                    st.error("El cierre no puede ser anterior al inicio.")
                elif rs < P.start:
                    st.error("El inicio no puede ser anterior al inicio del proyecto.")
                else:
                    def f(s, p):
                        ts = p.tasks
                        tt = next(x for x in ts if x["code"] == code)
                        if not tt.get("real_start") and v > 0:
                            tt["real_start"] = rs.isoformat()
                            db.log_progress(s, p, tt, "inicio", rs, USER.name, "")
                        if v == 100:
                            tt["real_pct"], tt["real_end"] = 100, re_.isoformat()
                            db.log_progress(s, p, tt, "cierre", re_, USER.name, com)
                        else:
                            tt["real_pct"] = v
                            db.log_progress(s, p, tt, "avance", date.today(), USER.name, com, pct=v, plan_pct=pct_plan[code])
                        p.tasks = ts
                    mutate(f)
                    st.session_state.toast = "Etapa cerrada" if v == 100 else f"Avance {v}% registrado"
                    st.rerun()
    st.dataframe(DF[["#", "Etapa", "Área", "Avance plan %", "Avance real %", "Desv. (pp)", "Semáforo", "Nota"]], hide_index=True,
                 width="stretch",
                 column_config={"Avance plan %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                                "Avance real %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%")})

# ---------------------------------------------------------------- Etapas
with T[2]:
    editable = DRAFT or I_EDIT
    if LIVE:
        st.info("Para modificar etapas pulsa **Editar programa**. Cada cambio quedará registrado con ID, causa y justificación.")
    elif EDIT and not I_EDIT:
        st.info(f"{P.edit_by} está editando el programa.")
    elif DRAFT and not MY_AREAS:
        st.info("Tu perfil es de solo lectura.")
    if editable and MY_AREAS:
        st.caption("Solo puedes modificar etapas de tu área. La ubicación ordena la lista; las dependencias definen las fechas.")
        mode = st.radio("Acción", ["Agregar etapa", "Editar etapa", "Eliminar etapa"], horizontal=True)
        own = [t for t in TASKS if can(t["area"])]
        if mode == "Agregar etapa" or own:
            t0 = None
            if mode != "Agregar etapa":
                c0 = st.selectbox("Etapa", [t["code"] for t in own], format_func=lambda c: f"{num[c]}. {next(t['name'] for t in TASKS if t['code'] == c)}")
                t0 = next(t for t in TASKS if t["code"] == c0)
            if mode == "Eliminar etapa":
                deps = [t["name"] for t in TASKS if t0["code"] in t["deps"]]
                if t0.get("real_start"):
                    st.error("No se puede eliminar una etapa con avance real registrado.")
                elif deps:
                    st.error(f"No se puede eliminar: «{deps[0]}» depende de esta etapa.")
                elif st.button("Eliminar etapa", type="primary"):
                    def f(s, p):
                        p.tasks = [x for x in p.tasks if x["code"] != t0["code"]]
                    mutate(f)
                    st.rerun()
            else:
                banned = logic.descendants(TASKS, t0["code"]) if t0 else set()
                others = [t for t in TASKS if not t0 or t["code"] != t0["code"]]
                with st.form("stage"):
                    name = st.text_input("Nombre de la etapa", value=t0["name"] if t0 else "")
                    g1, g2, g3 = st.columns(3)
                    area = g1.selectbox("Área responsable", [t0["area"]] if t0 else MY_AREAS, format_func=AREAS.get, disabled=bool(t0))
                    dur = g2.number_input("Duración (días)", 0, 1000, int(t0["dur"]) if t0 else 14)
                    lag = g3.number_input("Atraso de inicio (días)", 0, 365, int(t0["lag"]) if t0 else 0)
                    dep_opts = [t["code"] for t in others if t["code"] not in banned]
                    deps = st.multiselect("Empieza cuando terminen (dependencias)", dep_opts, placeholder="Elige una o más etapas (vacío = inicio del proyecto)",
                                          default=[d for d in (t0["deps"] if t0 else []) if d in dep_opts],
                                          format_func=lambda c: f"{num[c]}. {next(t['name'] for t in TASKS if t['code'] == c)}")
                    pos_opts = ["__first"] + [t["code"] for t in others]
                    if t0:
                        idx = TASKS.index(t0)
                        pos_def = "__first" if idx == 0 else TASKS[idx - 1]["code"]
                    else:
                        pos_def = others[-1]["code"] if others else "__first"
                    pos = st.selectbox("Ubicación en el proceso", pos_opts, index=pos_opts.index(pos_def),
                                       format_func=lambda c: "Al comienzo de la lista" if c == "__first" else f"Después de {num[c]}. {next(t['name'] for t in TASKS if t['code'] == c)}")
                    go_ = st.form_submit_button("Guardar etapa" if t0 else "Agregar etapa", type="primary")
                if go_:
                    if len(name.strip()) < 3:
                        st.error("Escribe el nombre de la etapa.")
                    else:
                        def f(s, p):
                            ts = p.tasks
                            if t0:
                                cur = next(x for x in ts if x["code"] == t0["code"])
                                ts.remove(cur)
                                cur.update(name=name.strip(), dur=int(dur), lag=int(lag), deps=deps)
                            else:
                                allc = [x["code"] for x in ts + p.baseline + p.snapshot]
                                cur = {"code": logic.next_code(allc), "name": name.strip(), "area": area, "dur": int(dur), "lag": int(lag), "deps": deps}
                            at = 0 if pos == "__first" else next(i for i, x in enumerate(ts) if x["code"] == pos) + 1
                            ts.insert(at, cur)
                            p.tasks = ts
                        mutate(f)
                        st.session_state.toast = "Listo. Guarda el cambio para registrarlo." if EDIT else "Etapa guardada en el borrador."
                        st.rerun()
        else:
            st.info("No hay etapas de tu área todavía. Usa «Agregar etapa».")

# ---------------------------------------------------------------- Historial
with T[3]:
    st.subheader("Cambios al programa")
    if CHANGES:
        st.dataframe(pd.DataFrame([{"ID": c.code, "Fecha": c.date, "Usuario": c.user, "Versión": f"v{c.version - 1} → v{c.version}",
                                    "Cambios": " | ".join(logic.change_text(i) for i in c.items), "Impacto (d)": c.impact,
                                    "Causa": c.cause, "Motivo": c.reason} for c in reversed(CHANGES)]),
                     hide_index=True, width="stretch",
                     column_config={"Fecha": st.column_config.DateColumn(format="DD-MM-YYYY")})
    else:
        st.caption("Aún no hay cambios registrados.")
    st.subheader("Registro de avance real")
    if LOGS:
        def ev(l):
            if l.kind == "avance":
                d = (l.plan_pct or 0) - (l.pct or 0)
                lv, lb = logic.semaforo(d)
                return f"Avance {l.pct}%", f"plan {l.plan_pct}%", f"{-d:+d} pp · {lb}"
            return ("Inicio" if l.kind == "inicio" else "Cierre"), fmt(l.base_date), ("nueva" if l.dev_days is None else f"{l.dev_days:+d} d")
        st.dataframe(pd.DataFrame([{"ID": l.code, "Registrado": l.reg, "Usuario": l.user, "Etapa": l.task_name,
                                    "Evento": ev(l)[0], "Fecha real": l.fecha, "Línea base / plan": ev(l)[1],
                                    "Desviación": ev(l)[2], "Comentario": l.comment} for l in reversed(LOGS)]),
                     hide_index=True, width="stretch",
                     column_config={"Registrado": st.column_config.DateColumn(format="DD-MM-YYYY"),
                                    "Fecha real": st.column_config.DateColumn(format="DD-MM-YYYY")})
    else:
        st.caption("Aún no hay avance registrado.")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        DF.to_excel(xw, sheet_name="Programa", index=False)
        pd.DataFrame([{"ID": c.code, "Fecha": c.date, "Usuario": c.user, "Versión": c.version, "Impacto (d)": c.impact,
                       "Causa": c.cause, "Motivo": c.reason, "Cambios": " | ".join(logic.change_text(i) for i in c.items)} for c in CHANGES]).to_excel(xw, sheet_name="Cambios", index=False)
        pd.DataFrame([{"ID": l.code, "Registrado": l.reg, "Usuario": l.user, "Etapa": l.task_name, "Evento": l.kind, "Fecha": l.fecha,
                       "Fecha base": l.base_date, "Desv. días": l.dev_days, "Real %": l.pct, "Plan %": l.plan_pct, "Comentario": l.comment} for l in LOGS]).to_excel(xw, sheet_name="Avance", index=False)
    st.download_button("Descargar en Excel", buf.getvalue(), file_name=f"planificaplus_{PID}_{date.today()}.xlsx")

# ---------------------------------------------------------------- KPI
with T[4]:
    closed = [t for t in TASKS if t.get("real_end")]
    meas = [(t, close_dev(t)) for t in closed if close_dev(t) is not None]
    on_time = sum(1 for _, d in meas if d <= 0)
    added = sum(c.impact for c in CHANGES if c.impact > 0)
    rec = -sum(c.impact for c in CHANGES if c.impact < 0)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Etapas cerradas en plazo", f"{round(on_time / len(meas) * 100) if meas else 0}%", help=f"{on_time} de {len(meas)} cierres comparables con la línea base")
    k2.metric("Desviación promedio al cierre", f"{round(sum(d for _, d in meas) / len(meas)) if meas else 0:+d} d")
    k3.metric("Cambios aprobados", len(CHANGES), help=f"+{added} días agregados / −{rec} días recuperados en el término")
    cnt = {"verde": 0, "amarillo": 0, "rojo": 0}
    for t in TASKS:
        if t.get("real_end") or (pct_plan[t["code"]] == 0 and pct_real[t["code"]] == 0):
            continue
        cnt[logic.semaforo(pct_plan[t["code"]] - pct_real[t["code"]])[0]] += 1
    k4.metric("Etapas abiertas 🟢 / 🟡 / 🔴", f"{cnt['verde']} / {cnt['amarillo']} / {cnt['rojo']}")

    def hbar(title, labels_, vals, colors=None):
        f = go.Figure(go.Bar(y=labels_, x=vals, orientation="h", text=[f"{v:+d}" if isinstance(v, int) else v for v in vals],
                             textposition="outside", cliponaxis=False, marker_color=colors or [BAD if v > 0 else OK for v in vals]))
        f.update_layout(title=title, height=max(220, 40 * len(labels_) + 90), margin=dict(l=10, r=70, t=50, b=10),
                        yaxis=dict(autorange="reversed"), plot_bgcolor="white", xaxis=dict(gridcolor="#E4E8E5", zerolinecolor="#58645F"))
        return f
    g1, g2 = st.columns(2)
    by = {}
    for c in CHANGES:
        by[c.cause] = by.get(c.cause, 0) + c.impact
    if by:
        it = sorted(by.items(), key=lambda x: -x[1])
        g1.plotly_chart(hbar("Días de atraso por causa", [k for k, _ in it], [v for _, v in it]), width="stretch")
    if not DRAFT:
        pts = [("v1", BAS["end"])] + [(f"v{c.version}", c.end_after) for c in CHANGES]
        fv = go.Figure(go.Scatter(x=[p_[0] for p_ in pts], y=[p_[1] for p_ in pts], mode="lines+markers", line=dict(color=ACCENT, width=3)))
        fv.add_hline(y=BAS["end"], line_dash="dot", line_color=BASE)
        fv.update_layout(title="Fecha de término por versión", height=300, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white",
                         yaxis=dict(gridcolor="#E4E8E5"))
        g2.plotly_chart(fv, width="stretch")
    if meas:
        meas.sort(key=lambda x: -x[1])
        st.plotly_chart(hbar("Desviación al cierre por etapa (días vs línea base)", [t["name"][:45] for t, _ in meas], [d for _, d in meas]),
                        width="stretch")
    ar = {a: 0 for a in AREAS}
    for c in CHANGES:
        for a in {i["area"] for i in c.items}:
            ar[a] += 1
    st.plotly_chart(hbar("Cambios por área", [AREAS[a] for a in ar], list(ar.values()), ["#3E5A86"] * 3), width="stretch")

# ---------------------------------------------------------------- Administración
if IS_ADMIN:
    with T[5]:
        st.subheader("Usuarios")
        with db.Session() as s:
            users = s.scalars(select(db.User).order_by(db.User.id)).all()
        st.dataframe(pd.DataFrame([{"Usuario": u.username, "Nombre": u.name, "Perfil": ROLES[u.role][0],
                                    "Activo": "Sí" if u.active else "No"} for u in users]), hide_index=True, width="stretch")
        u1, u2 = st.columns(2)
        with u1.form("newuser", clear_on_submit=True):
            st.markdown("**Crear usuario**")
            nu = st.text_input("Usuario (sin espacios)")
            nn = st.text_input("Nombre")
            nr = st.selectbox("Perfil", list(ROLES), format_func=lambda r: ROLES[r][0])
            npw = st.text_input("Contraseña inicial", type="password")
            if st.form_submit_button("Crear"):
                uname = nu.strip().lower()
                if not uname or " " in uname or len(npw) < 8 or not nn.strip():
                    st.error("Completa usuario sin espacios, nombre y una contraseña de al menos 8 caracteres.")
                else:
                    with db.Session() as s:
                        if s.scalar(select(db.User).where(db.User.username == uname)):
                            st.error("Ese usuario ya existe.")
                        else:
                            s.add(db.User(username=uname, name=nn.strip(), role=nr, pw_hash=db.hash_pw(npw)))
                            s.commit()
                            st.session_state.toast = "Usuario creado"
                            st.rerun()
        with u2.form("pw", clear_on_submit=True):
            st.markdown("**Cambiar contraseña / desactivar**")
            who = st.selectbox("Usuario", [u.username for u in users])
            pw2 = st.text_input("Nueva contraseña (vacío = no cambiar)", type="password")
            act = st.checkbox("Activo", value=True)
            if st.form_submit_button("Guardar"):
                if pw2 and len(pw2) < 8:
                    st.error("La contraseña debe tener al menos 8 caracteres.")
                elif who == USER.username and not act:
                    st.error("No puedes desactivar tu propio usuario.")
                else:
                    with db.Session() as s:
                        u = s.scalar(select(db.User).where(db.User.username == who))
                        if pw2:
                            u.pw_hash = db.hash_pw(pw2)
                        u.active = 1 if act else 0
                        s.commit()
                    st.session_state.toast = "Usuario actualizado"
                    st.rerun()

        st.subheader("Proyectos")
        with st.form("newproj"):
            pn = st.text_input("Nombre de la obra", value="Ampliación S/E (nueva)")
            ps = st.date_input("Fecha de inicio (firma de contrato)", value=date.today())
            pt = st.radio("Punto de partida", ["Plantilla de subestación (15 etapas)", "En blanco"], horizontal=True)
            if st.form_submit_button("Crear proyecto en borrador"):
                with db.Session() as s:
                    tasks = logic.template_tasks() if pt.startswith("Plantilla") else []
                    np_ = db.Project(name=pn.strip() or "Proyecto sin nombre", start=ps, status="draft", version=0)
                    np_.tasks, np_.baseline = tasks, tasks
                    s.add(np_)
                    s.commit()
                    st.session_state.pid = np_.id
                st.rerun()
        with st.expander("Restaurar el proyecto de ejemplo"):
            st.write("Reemplaza el proyecto seleccionado por el ejemplo inicial, con su historial. No se puede deshacer.")
            sure = st.checkbox("Entiendo que se perderán los datos de este proyecto")
            if st.button("Restaurar ejemplo", disabled=not sure):
                st.session_state.pid = db.reset_demo(PID)
                st.rerun()

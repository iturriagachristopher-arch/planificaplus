"""PlanificA+ · Control de obra — Streamlit."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

import db
import ia
import mailer
import planner
import help_text
import logic
from logic import AREAS, ROLES, CAUSES, TOL_OK, TOL_HIGH

st.set_page_config(page_title="PlanificA+ · Control de obra", page_icon="icon.png" if __import__("os").path.exists("icon.png") else "📐", layout="wide")

ACCENT, WARN, OK, BAD, BASE, INK = "#1F4E8C", "#D99A1E", "#1FA38A", "#C0392B", "#AEB8C4", "#14213D"
st.markdown("""<style>
.block-container{padding-top:3.2rem}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:.82rem}
.p-draft{background:#E2E9F4;color:#3E5A86}.p-live{background:#DDF3EE;color:#13806C}.p-edit{background:#FBEFD6;color:#9A6408}
.brand{font-size:2rem;font-weight:700;letter-spacing:.01em}.brand b{color:#1F4E8C}
</style>""", unsafe_allow_html=True)


def brand(width: int = 260):
    """Logo de PlanificA+ (logo.webp); si no está, el nombre en texto."""
    import os
    if os.path.exists("logo.webp"):
        st.image("logo.webp", width=width)
    else:
        st.markdown('<div class="brand">Planific<b>A+</b></div>', unsafe_allow_html=True)

try:
    DEMO_PW = st.secrets["DEMO_PASSWORD"]
except Exception:
    DEMO_PW = "planifica2026"
try:
    INITIAL_PW = str(st.secrets["INITIAL_PASSWORD"])
except Exception:
    INITIAL_PW = None  # sin INITIAL_PASSWORD en Secrets hay que escribir la clave inicial a mano
try:
    OWNER = str(st.secrets["APP_OWNER"]).strip().lower()
except Exception:
    OWNER = "christopher"  # dueño de la app: el único que resuelve recuperaciones de clave


try:
    APP_URL = str(st.secrets["APP_URL"]).strip()
except Exception:
    APP_URL = "https://planificaplus.streamlit.app"
SESSION_MIN = 30  # minutos sin actividad antes de cerrar la sesión


@st.cache_resource
def _init(schema: int):  # cambiar SCHEMA en db.py fuerza a correr de nuevo las migraciones
    db.init_db(DEMO_PW)
    return True


_init(db.SCHEMA)


# ---------------------------------------------------------------- sesión
def login_view():
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        brand(280)
        st.caption("Control de obra · Línea base, avance real y control de cambios")
        with st.form("login"):
            u = st.text_input("Usuario")
            pw = st.text_input("Contraseña", type="password")
            ok = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if st.session_state.pop("expired", False):
            st.info(f"Tu sesión se cerró tras {SESSION_MIN} minutos sin actividad. Vuelve a ingresar.")
        if ok:
            db.sweep_inactive()
            now = datetime.utcnow()
            with db.Session() as s:
                user = s.scalar(select(db.User).where(db.User.username == u.strip().lower()))
                if user and user.locked_until and user.locked_until > now:
                    mins = int((user.locked_until - now).total_seconds() // 60) + 1
                    st.error(f"Cuenta bloqueada por intentos fallidos. Intenta de nuevo en {mins} min o pide ayuda al administrador.")
                elif user and db.check_pw(pw, user.pw_hash):
                    if not user.active:
                        st.error("Tu cuenta está desactivada" + (f" ({user.deact_reason.lower()})" if user.deact_reason else "")
                                 + ". Contacta al administrador para reactivarla.")
                    else:
                        user.failed, user.locked_until, user.last_login = 0, None, now
                        s.commit()
                        st.session_state.uid, st.session_state.seen = user.id, now
                        st.rerun()
                else:
                    if user:
                        user.failed = (user.failed or 0) + 1
                        if user.failed >= db.MAX_FAILED:
                            user.failed, user.locked_until = 0, now + timedelta(minutes=db.LOCK_MIN)
                        s.commit()
                    # Mismo mensaje exista o no el usuario.
                    st.error(f"Usuario o contraseña incorrectos. Tras {db.MAX_FAILED} intentos fallidos la cuenta se bloquea {db.LOCK_MIN} minutos.")
        with st.expander("¿Olvidaste tu contraseña?"):
            st.caption("Tu solicitud llega al administrador de la app. Él te entregará una clave temporal "
                       "por un canal directo (WhatsApp o correo) y al entrar deberás crear una nueva.")
            with st.form("forgot", clear_on_submit=True):
                fu = st.text_input("Tu usuario")
                fn = st.text_input("¿Cómo te contactamos? (opcional)", placeholder="Ej: WhatsApp o correo")
                sent = st.form_submit_button("Enviar solicitud")
            if sent:
                name = fu.strip().lower()
                if not name:
                    st.error("Escribe tu usuario.")
                else:
                    with db.Session() as s:
                        exists = s.scalar(select(db.User).where(db.User.username == name, db.User.active == 1))
                        pending = s.scalar(select(db.PasswordRequest).where(db.PasswordRequest.username == name,
                                                                           db.PasswordRequest.status == "pendiente"))
                        if exists and not pending:
                            s.add(db.PasswordRequest(username=name, note=fn.strip()[:200]))
                            s.commit()
                    # Mismo mensaje exista o no el usuario, para no revelar qué usuarios hay.
                    st.success("Solicitud enviada. El administrador te contactará con una clave temporal.")
        st.caption("Prototipo A+S · AIEP Santiago Norte · Leslie Vera, Christopher Iturriaga, Andrés Molina")


def make_username(full_name: str) -> str:
    """Primera letra del nombre + primer apellido, sin tildes ni espacios (Christopher Iturriaga → citurriaga)."""
    import unicodedata
    clean = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode().lower()
    w = ["".join(ch for ch in x if ch.isalnum()) for x in clean.split()]
    w = [x for x in w if x]
    if len(w) < 2:
        return w[0] if w else ""
    ap = w[-2] if len(w) >= 4 else w[1]  # Nombre1 Nombre2 Apellido1 Apellido2 → Apellido1
    return w[0][0] + ap


def free_username(s, base: str) -> str:
    """Primer nombre de usuario libre agregando un número al final: citurriaga2, citurriaga3…"""
    n = 2
    while s.scalar(select(db.User).where(db.User.username == f"{base}{n}")):
        n += 1
    return f"{base}{n}"


def pw_form(key: str, need_current: bool, user) -> None:
    """Formulario para que el usuario defina su propia contraseña."""
    with st.form(key, clear_on_submit=True):
        cur = st.text_input("Contraseña actual (la temporal)" if not need_current else "Contraseña actual", type="password")
        n1 = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
        n2 = st.text_input("Repite la nueva contraseña", type="password")
        go = st.form_submit_button("Guardar contraseña", type="primary")
    if go:
        if not db.check_pw(cur, user.pw_hash):
            st.error("La contraseña actual no es correcta.")
        elif len(n1) < 8:
            st.error("La nueva contraseña debe tener al menos 8 caracteres.")
        elif n1 != n2:
            st.error("Las contraseñas nuevas no coinciden.")
        elif n1 == cur:
            st.error("La nueva contraseña debe ser distinta de la actual.")
        elif INITIAL_PW and n1 == INITIAL_PW:
            st.error("No puedes usar la clave inicial estándar como tu contraseña.")
        else:
            with db.Session() as s:
                u_ = s.get(db.User, user.id)
                u_.pw_hash, u_.must_change = db.hash_pw(n1), 0
                s.commit()
            st.session_state.toast = "Contraseña actualizada"
            st.rerun()


if "uid" not in st.session_state:
    login_view()
    st.stop()

_now = datetime.utcnow()
if _now - st.session_state.get("seen", _now) > timedelta(minutes=SESSION_MIN):
    st.session_state.clear()
    st.session_state.expired = True
    st.rerun()
st.session_state.seen = _now

with db.Session() as s:
    USER = s.get(db.User, st.session_state.uid)
if USER is None or not USER.active:
    st.session_state.clear()
    st.rerun()
ROLE_NAME, MY_AREAS = ROLES[USER.role]
IS_ADMIN = USER.role == "admin"
IS_OWNER = IS_ADMIN and USER.username == OWNER
can = lambda area: area in MY_AREAS

if USER.must_change:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        brand(280)
        st.subheader(f"Hola, {USER.name}")
        st.info("Estás usando una contraseña temporal. Crea una propia para continuar.")
        pw_form("first_pw", False, USER)
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()
    st.stop()

# ---------------------------------------------------------------- barra lateral
with db.Session() as s:
    projects = s.scalars(select(db.Project).order_by(db.Project.id)).all()
with st.sidebar:
    brand(170)
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
    if IS_OWNER:
        with db.Session() as s:
            n_req = len(s.scalars(select(db.PasswordRequest).where(db.PasswordRequest.status == "pendiente")).all())
        if n_req:
            st.warning(f"🔑 {n_req} solicitud(es) de recuperación de contraseña. Revísalas en Administración.")
    with st.expander("Cambiar mi contraseña"):
        pw_form("my_pw", True, USER)
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
CAL = P.calendar or "corridos"
TASKS, BASEL = logic.ensure_wbs(P.tasks), logic.ensure_wbs(P.baseline)
CUR = logic.schedule(P.start, TASKS, CAL)
BAS = logic.schedule(P.start, BASEL, CAL)
SUMM = CUR["summ"]
LEAVES = [t for t in TASKS if t["code"] not in SUMM]
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
@st.dialog("❓ Ayuda de PlanificA+", width="large")
def dlg_help():
    ht = st.tabs(list(help_text.SECTIONS))
    for tab_, body in zip(ht, help_text.SECTIONS.values()):
        tab_.markdown(body)


_h1, _h2 = st.columns([8, 1])
_h1.markdown(f'### {P.name} <span class="pill {pill[1]}">{pill[0]}</span>', unsafe_allow_html=True)
if _h2.button("❓ Ayuda", width="stretch"):
    dlg_help()
st.caption(f"Inicio {fmt(P.start)} · versión v{P.version}" +
           (f" · línea base aprobada por {P.baseline_by} el {fmt(P.baseline_at)}" if not DRAFT else " · sin línea base")
           + (f" · en edición por {P.edit_by}" if EDIT else ""))

pct_plan = {t["code"]: logic.pct_at(CUR["at"].get(t["code"]), t["dur"], CORTE) for t in TASKS}
pct_real = {t["code"]: int(t.get("real_pct") or 0) for t in TASKS}
WBS_OF = {t["code"]: str(t["wbs"]) for t in TASKS}
for _c in SUMM:  # avance de un resumen = promedio ponderado de sus tareas
    _sub = [t for t in LEAVES if WBS_OF[t["code"]].startswith(WBS_OF[_c] + ".")]
    pct_plan[_c], pct_real[_c] = logic.weighted(_sub, pct_plan), logic.weighted(_sub, pct_real)
USERS_ALL = {}
with db.Session() as _s:
    USERS_ALL = {u.username: u.name for u in _s.scalars(select(db.User).where(db.User.active == 1)).all()}
p_plan, p_real = logic.weighted(TASKS, pct_plan), logic.weighted(TASKS, pct_real)
p_orig = logic.weighted(BASEL, {t["code"]: logic.pct_at(BAS["at"].get(t["code"]), t["dur"], CORTE) for t in BASEL})
lvl, lbl = logic.semaforo(p_plan - p_real)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Fin línea base", "—" if DRAFT else BAS["end"].strftime("%d-%m-%y"))
c2.metric("Fin actual", CUR["end"].strftime("%d-%m-%y"), None if DRAFT else f"{dev_end:+d} días", delta_color="inverse")
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
    e0 = logic.schedule(P.start, P.snapshot, CAL)["end"]
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
num = {t["code"]: str(t["wbs"]) for t in TASKS}
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
    is_s = t["code"] in SUMM
    kind = "Resumen" if is_s else (t.get("kind") or "Tarea")
    lvl = str(t["wbs"]).count(".")
    return {"#": str(t["wbs"]), "Etapa": "\u2003" * lvl + ("▸ " if is_s else "◆ " if kind == "Hito" else "") + t["name"],
            "Tipo": kind, "Área": AREAS[t["area"]], "Responsable": USERS_ALL.get(t.get("resp") or "", t.get("resp") or "—"),
            "Depende de": logic.preds_text(t, WBS_OF) or "—",
            "Duración (d)": (e_ - s_).days if is_s else (0 if kind == "Hito" else t["dur"]), "Atraso (d)": t["lag"],
            "Inicio": s_, "Fin": e_, "Holgura (d)": None if is_s else CUR["slack"].get(t["code"]),
            "Crítica": "🔴" if t["code"] in CUR["crit"] else "", "vs base (d)": vs,
            "Avance plan %": plan, "Avance real %": real, "Desv. (pp)": real - plan, "Semáforo": sem, "Nota": note}


DF = pd.DataFrame([row(t, i) for i, t in enumerate(TASKS)])

tabs = ["📊 Carta Gantt", "✅ Avance real", "🧩 Programa", "🧾 Historial", "📈 KPI", "🤖 Asistente IA"] + (["⚙️ Administración"] if IS_ADMIN else [])
T = st.tabs(tabs)

# ---------------------------------------------------------------- Gantt
with T[0]:
    if not TASKS:
        st.info("El proyecto no tiene etapas. Agrega la primera en la pestaña Etapas.")
    else:
        f1, f2, f3 = st.columns([1.2, 1.6, 2])
        only_crit = f1.toggle("Solo ruta crítica", key="g_crit")
        resp_opts = ["Todos"] + sorted({t.get("resp") for t in TASKS if t.get("resp")})
        f_resp = f2.selectbox("Responsable", resp_opts, key="g_resp",
                              format_func=lambda u: u if u == "Todos" else USERS_ALL.get(u, u))
        f3.caption(f"Calendario: **{logic.CALENDARS[CAL]}** · Ruta crítica: tareas sin holgura (🔴)")
        VIEW = [t for t in TASKS if (not only_crit or t["code"] in CUR["crit"] or t["code"] in SUMM)
                and (f_resp == "Todos" or t.get("resp") == f_resp or t["code"] in SUMM)]
        span = lambda c: (CUR["at"][c][1] - CUR["at"][c][0]).days
        labels = [(lambda x: f"<b>{x}</b>" if t["code"] in SUMM else x)(f"{t['wbs']} · " + t["name"][:42]) for t in VIEW]
        fig = go.Figure()
        ms = lambda d: d * 86400000
        if not DRAFT:
            bx = [(lab, BAS["at"][t["code"]]) for lab, t in zip(labels, VIEW) if t["code"] in IN_BASE and t["code"] in BAS["at"]]
            fig.add_bar(y=[b[0] for b in bx], base=[b[1][0].isoformat() for b in bx],
                        x=[ms(max((b[1][1] - b[1][0]).days, 0.6)) for b in bx], orientation="h",
                        marker_color=BASE, width=0.18, offset=0.2, name="Línea base", hoverinfo="skip")
        snap = {x["code"]: x for x in P.snapshot} if EDIT else {}
        rows_t = [(lab, t) for lab, t in zip(labels, VIEW) if t["code"] not in SUMM and t.get("kind") != "Hito"]
        cols, lines = [], []
        for _, t in rows_t:
            new = not DRAFT and t["code"] not in IN_BASE
            chg = t["code"] in touched or (EDIT and t["code"] in snap and (snap[t["code"]]["dur"] != t["dur"] or snap[t["code"]]["lag"] != t["lag"]))
            cols.append(OK if new else WARN if chg else ACCENT)
            lines.append(BAD if t["code"] in CUR["crit"] else "rgba(0,0,0,0)")
        cd = lambda t: [fmt(CUR["at"][t["code"]][0]), fmt(CUR["at"][t["code"]][1]), pct_plan[t["code"]], pct_real[t["code"]],
                        USERS_ALL.get(t.get("resp") or "", t.get("resp") or "—"), CUR["slack"].get(t["code"], "—")]
        hov = "%{y}<br>%{customdata[0]} → %{customdata[1]}<br>Plan %{customdata[2]}% · Real %{customdata[3]}%<br>Responsable: %{customdata[4]} · Holgura: %{customdata[5]} d<extra></extra>"
        fig.add_bar(y=[l for l, _ in rows_t], base=[CUR["at"][t["code"]][0].isoformat() for _, t in rows_t],
                    x=[ms(max(span(t["code"]), 0.6)) for _, t in rows_t], orientation="h", marker_color=cols,
                    marker_line=dict(color=lines, width=2), width=0.45, offset=-0.3, name="Tarea",
                    customdata=[cd(t) for _, t in rows_t], hovertemplate=hov)
        fig.add_bar(y=[l for l, _ in rows_t], base=[CUR["at"][t["code"]][0].isoformat() for _, t in rows_t],
                    x=[ms(max(span(t["code"]), 0.6) * pct_real[t["code"]] / 100) for _, t in rows_t], orientation="h",
                    marker_color=INK, width=0.14, offset=-0.14, name="Avance real", hoverinfo="skip")
        rows_s = [(lab, t) for lab, t in zip(labels, VIEW) if t["code"] in SUMM]
        if rows_s:
            fig.add_bar(y=[l for l, _ in rows_s], base=[CUR["at"][t["code"]][0].isoformat() for _, t in rows_s],
                        x=[ms(max(span(t["code"]), 0.6)) for _, t in rows_s], orientation="h", marker_color=INK,
                        width=0.16, offset=-0.08, name="Resumen", customdata=[cd(t) for _, t in rows_s], hovertemplate=hov)
        rows_m = [(lab, t) for lab, t in zip(labels, VIEW) if t.get("kind") == "Hito" and t["code"] not in SUMM]
        if rows_m:
            fig.add_scatter(y=[l for l, _ in rows_m], x=[CUR["at"][t["code"]][0].isoformat() for _, t in rows_m], mode="markers",
                            marker=dict(symbol="diamond", size=14, color=[BAD if t["code"] in CUR["crit"] else INK for _, t in rows_m]),
                            name="Hito", customdata=[cd(t) for _, t in rows_m], hovertemplate=hov)
        fig.add_shape(type="line", x0=CORTE.isoformat(), x1=CORTE.isoformat(), y0=0, y1=1, yref="paper",
                      line=dict(color=BAD, width=2, dash="dot"))
        fig.add_annotation(x=CORTE.isoformat(), y=1.02, yref="paper", text="corte", showarrow=False, font=dict(color=BAD))
        fig.update_layout(barmode="overlay", height=max(320, 30 * len(VIEW) + 90), margin=dict(l=10, r=10, t=30, b=10),
                          xaxis=dict(type="date", gridcolor="#E3E9F0"),
                          yaxis=dict(autorange="reversed", categoryorder="array", categoryarray=labels),
                          legend=dict(orientation="h", y=-0.08), plot_bgcolor="white")
        st.plotly_chart(fig, width="stretch")
        st.caption("Azul: tarea · Borde rojo: ruta crítica · Barra oscura delgada: resumen · ◆ Hito · Gris: línea base · "
                   "Amarillo: tarea con cambios · Turquesa: tarea agregada · Línea oscura interior: avance real")
        st.dataframe(DF[DF["#"].isin([str(t["wbs"]) for t in VIEW])], hide_index=True, width="stretch",
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
        only_mine = st.toggle("👤 Solo mis tareas (donde soy responsable)", key="av_mine")
        mine = [t for t in LEAVES if (t.get("resp") == USER.username if only_mine else (can(t["area"]) or t.get("resp") == USER.username))
                and not t.get("real_end")]
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

# ---------------------------------------------------------------- Programa (tipo MS Project)
with T[2]:
    editable = DRAFT or I_EDIT
    CAN_PLAN = USER.role in ("admin", "pmo")
    if LIVE:
        st.info("Para modificar el programa pulsa **Editar programa**. Cada cambio quedará registrado con ID, causa y justificación.")
    elif EDIT and not I_EDIT:
        st.info(f"{P.edit_by} está editando el programa.")
    elif DRAFT and not MY_AREAS:
        st.info("Tu perfil es de solo lectura.")

    if editable and CAN_PLAN:
        st.markdown("#### 🧩 Programa del proyecto")
        st.caption("Escribe fila por fila como en una planilla. **EDT**: 1 = tarea global · 1.1 = subtarea · 1.1.1 = tarea. "
                   "**Predecesoras**: `2.1.1` (fin-comienzo) · `2.1.1CC+3` (comienzo-comienzo con 3 días de desfase) · "
                   "`5.2FF-2` · varias separadas por coma. Las tareas **Resumen** calculan solas sus fechas y avance.")
        if DRAFT:
            cal_new = st.radio("Calendario", list(logic.CALENDARS), index=list(logic.CALENDARS).index(CAL),
                               format_func=logic.CALENDARS.get, horizontal=True, key="cal_sel")
        else:
            cal_new = CAL
            st.caption(f"Calendario: {logic.CALENDARS[CAL]} (se elige antes de poner en marcha).")
        grid = st.data_editor(
            planner.tasks_to_rows(TASKS), key=f"grid_{PID}_{P.version}_{P.status}", num_rows="dynamic", hide_index=True,
            width="stretch", height=min(700, 38 * (len(TASKS) + 3)),
            column_order=planner.COLS,
            column_config={
                "EDT": st.column_config.TextColumn("EDT", width="small", help="1 · 1.1 · 1.1.1"),
                "Nombre": st.column_config.TextColumn("Nombre", width="large"),
                "Tipo": st.column_config.SelectboxColumn("Tipo", options=logic.KINDS, default="Tarea", width="small"),
                "Área": st.column_config.SelectboxColumn("Área", options=list(logic.AREAS.values()), default="Oficina técnica"),
                "Responsable": st.column_config.SelectboxColumn("Responsable", options=sorted(USERS_ALL),
                                                                help="Usuario de la app que informa el avance"),
                "Duración (días)": st.column_config.NumberColumn("Duración (d)", min_value=0, step=1, default=5),
                "Atraso (días)": st.column_config.NumberColumn("Atraso (d)", min_value=0, step=1, default=0),
                "Inicio (opcional)": st.column_config.DateColumn("Inicio fijo", format="DD-MM-YYYY",
                                                                 help="Vacío = se calcula por predecesoras"),
                "Predecesoras": st.column_config.TextColumn("Predecesoras", help="Ej.: 2.1.1, 2.1.2CC+3"),
                "Notas": st.column_config.TextColumn("Notas"),
            })
        g1, g2, _ = st.columns([1.3, 1.6, 3])
        if g1.button("💾 Guardar programa", type="primary"):
            new_tasks, errs, warns = planner.rows_to_tasks(grid, TASKS, set(USERS_ALL))
            lost = [t["name"] for t in TASKS if t.get("real_start") and t["code"] not in {x["code"] for x in new_tasks}]
            if lost:
                errs.append("No puedes eliminar tareas con avance real registrado: " + ", ".join(lost[:3]))
            if errs:
                st.error("Revisa estos puntos antes de guardar:\n\n" + "\n".join(f"- {e}" for e in errs[:12]))
            else:
                def f(s, p):
                    p.tasks = new_tasks
                    if p.status == "draft":
                        p.baseline, p.calendar = new_tasks, cal_new
                mutate(f)
                st.session_state.toast = ("Programa guardado. Pulsa «Guardar cambio…» para registrarlo." if EDIT else "Programa guardado.")
                st.session_state.plan_warns = warns
                st.rerun()
        g2.download_button("📥 Descargar en Excel (plantilla)", planner.to_excel(TASKS or logic.template_tasks(), P.name, P.start),
                           file_name=f"programa_{PID}.xlsx", help="El mismo formato sirve para importar")
        for w in st.session_state.pop("plan_warns", []):
            st.warning(w)

        if DRAFT:
            with st.expander("📤 Importar programa desde Excel (plantilla PlanificA+ o exportado de MS Project)"):
                st.caption("Usa la plantilla (hoja «Programa», encabezados en la fila 2). Reemplaza el programa del borrador. "
                           "La fecha «Inicio del proyecto» de la celda G1, si existe, actualiza el inicio.")
                up = st.file_uploader("Archivo .xlsx", type=["xlsx"], key=f"up_{PID}")
                if up is not None:
                    try:
                        idf, istart = planner.read_excel(up)
                        new_tasks, errs, warns = planner.rows_to_tasks(idf, [], set(USERS_ALL))
                    except Exception as e:  # archivo dañado o formato distinto
                        new_tasks, errs, warns, istart = [], [f"No pude leer el archivo: {e}"], [], None
                    if errs:
                        st.error("El archivo tiene errores:\n\n" + "\n".join(f"- {e}" for e in errs[:15]))
                    else:
                        sch = logic.schedule(istart or P.start, new_tasks, cal_new)
                        st.success(f"Archivo correcto: {len(new_tasks)} filas · término calculado {fmt(sch['end'])}"
                                   + (f" · inicio {fmt(istart)}" if istart else ""))
                        for w in warns[:8]:
                            st.warning(w)
                        st.dataframe(planner.tasks_to_rows(new_tasks).drop(columns=["_code"]).head(12), hide_index=True)
                        if st.button("Importar y reemplazar el programa", type="primary"):
                            def f(s, p):
                                p.tasks = p.baseline = new_tasks
                                p.calendar = cal_new
                                if istart:
                                    p.start = istart
                            mutate(f)
                            st.session_state.toast = f"Programa importado ({len(new_tasks)} filas)"
                            st.rerun()

    elif editable and MY_AREAS:
        st.caption("La estructura del programa la arma el PMO o el administrador. Tú puedes ajustar duración y atraso de las tareas de tu área.")
        own = [t for t in LEAVES if can(t["area"]) and t.get("kind") != "Hito"]
        if not own:
            st.info("No hay tareas de tu área.")
        else:
            c0 = st.selectbox("Tarea", [t["code"] for t in own], format_func=lambda c: f"{num[c]} · {next(t['name'] for t in TASKS if t['code'] == c)}")
            t0 = next(t for t in TASKS if t["code"] == c0)
            with st.form("stage"):
                h1, h2 = st.columns(2)
                dur = h1.number_input("Duración (días)", 0, 2000, int(t0["dur"]))
                lag = h2.number_input("Atraso de inicio (días)", 0, 365, int(t0["lag"]))
                go_ = st.form_submit_button("Guardar", type="primary")
            if go_:
                def f(s, p):
                    ts = p.tasks
                    cur = next(x for x in ts if x["code"] == c0)
                    cur.update(dur=int(dur), lag=int(lag))
                    p.tasks = ts
                    if p.status == "draft":
                        p.baseline = ts
                mutate(f)
                st.session_state.toast = "Listo. Guarda el cambio para registrarlo." if EDIT else "Tarea actualizada en el borrador."
                st.rerun()

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
    for t in LEAVES:
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

# ---------------------------------------------------------------- Asistente IA
def project_context() -> str:
    lines = [f"Proyecto: {P.name}", f"Estado: {pill[0]} · versión v{P.version} · inicio {fmt(P.start)}",
             f"Fecha de corte: {fmt(CORTE)}",
             f"Término línea base: {'sin línea base' if DRAFT else fmt(BAS['end'])} · término actual: {fmt(CUR['end'])} · desviación: {dev_end:+d} días",
             f"Avance plan {p_plan}% · avance real {p_real}% · desviación {p_real - p_plan:+d} pp · semáforo {lvl} ({lbl})",
             "", "ETAPAS (tabla CSV):", DF.drop(columns=["Depende de"]).to_csv(index=False)]
    if CHANGES:
        lines += ["", "CAMBIOS APROBADOS:"] + [f"{c.code} | {fmt(c.date)} | {c.user} | v{c.version} | impacto {c.impact:+d} d | {c.cause} | {c.reason} | "
                                               + "; ".join(logic.change_text(i) for i in c.items) for c in CHANGES[-30:]]
    if LOGS:
        lines += ["", "REGISTRO DE AVANCE (últimos 40):"] + [f"{l.code} | {fmt(l.fecha)} | {l.user} | {l.task_name} | {l.kind}"
                                                              + (f" {l.pct}% (plan {l.plan_pct}%)" if l.kind == "avance" else "")
                                                              + ("" if l.dev_days is None else f" | desv {l.dev_days:+d} d") + (f" | {l.comment}" if l.comment else "")
                                                              for l in LOGS[-40:]]
    return "\n".join(lines)


with T[5]:
    try:
        prov = ia.provider(st.secrets)
    except Exception:
        prov = None
    st.caption("El asistente responde solo sobre este proyecto y el uso de PlanificA+. Revisa siempre sus respuestas antes de enviarlas.")
    if prov is None:
        st.info("El asistente no está activado. El dueño de la app debe agregar `GEMINI_API_KEY` (o `ANTHROPIC_API_KEY`) en los Secrets de Streamlit.")
    else:
        hist_key = f"chat_{PID}"
        st.session_state.setdefault(hist_key, [])
        st.session_state.setdefault("ia_count", 0)
        quick = {"📋 Resumen del estado": "Resume el estado del proyecto a la fecha de corte: avance plan vs real, semáforo, desviación del término y las 3 etapas que más preocupan.",
                 "🚨 Etapas en riesgo": "¿Qué etapas abiertas están en amarillo o rojo, o pueden atrasar el término? Indica para cada una la desviación y una acción sugerida.",
                 "📝 Reporte semanal": "Redacta el reporte semanal para la ITO y el mandante: resumen, avance, etapas en riesgo, cambios recientes y próximos pasos. Máximo 300 palabras."}
        qc = st.columns(len(quick) + 1)
        pick = None
        for i, (lbl_, q_) in enumerate(quick.items()):
            if qc[i].button(lbl_, width="stretch"):
                pick = q_
        if qc[-1].button("🗑️ Limpiar chat", width="stretch"):
            st.session_state[hist_key] = []
            st.rerun()
        with st.expander("📄 Extraer hitos y multas desde las bases"):
            bases = st.text_area("Pega aquí el texto de las bases (solo el capítulo de plazos y multas)", height=160)
            if st.button("Extraer hitos"):
                if len(bases.strip()) < 40:
                    st.error("Pega un texto más largo de las bases.")
                else:
                    pick = ("Del siguiente texto de bases extrae TODAS las obligaciones con plazo, hito o multa en una tabla: "
                            "Punto | Obligación | Plazo | Multa | Responsable sugerido. No inventes datos.\n\nBASES:\n" + bases[:ia.MAX_Q * 4])
        for m in st.session_state[hist_key]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"] if m["role"] == "assistant" or len(m["content"]) < 600 else m["content"][:600] + "…")
        typed = st.chat_input("Pregunta sobre el proyecto o pide un texto de trabajo")
        q = pick or typed
        if q:
            if st.session_state.ia_count >= 30:
                st.warning("Llegaste al máximo de 30 consultas por sesión. Cierra sesión y vuelve a entrar para continuar.")
            else:
                st.session_state.ia_count += 1
                with st.chat_message("user"):
                    st.markdown(q if len(q) < 600 else q[:600] + "…")
                with st.chat_message("assistant"):
                    with st.spinner("Pensando…"):
                        try:
                            ans = ia.ask(prov, project_context(), st.session_state[hist_key], q)
                        except Exception as e:
                            ans = f"⚠️ {e}" if isinstance(e, RuntimeError) else "⚠️ No se pudo conectar con el asistente. Intenta de nuevo."
                    st.markdown(ans)
                if not ans.startswith("⚠️"):
                    st.session_state[hist_key] += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]

# ---------------------------------------------------------------- Administración
if IS_ADMIN:
    with T[6]:
        st.subheader("Usuarios")
        db.sweep_inactive()
        if "user_msg" in st.session_state:
            st.info(st.session_state.pop("user_msg"))
        with db.Session() as s:
            users = s.scalars(select(db.User).order_by(db.User.id)).all()
        from zoneinfo import ZoneInfo
        _cl = lambda d: d.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Santiago")) if d else None
        _nowu = datetime.utcnow()

        def u_row(u):
            ref = u.last_login or u.created_at
            days = (_nowu - ref).days if ref else None
            if not u.active:
                state = "🔴 Desactivada" + (f" · {u.deact_reason}" if u.deact_reason else "")
            elif u.locked_until and u.locked_until > _nowu:
                state = "🔒 Bloqueada (intentos)"
            elif u.last_login is None and u.must_change:
                left = db.FIRST_LOGIN_DAYS - days if days is not None else db.FIRST_LOGIN_DAYS
                state = f"⏳ Sin primer ingreso · quedan {max(left, 0)} d"
            elif days is not None and days >= 15:
                state = f"🟡 {days} días sin entrar"
            else:
                state = "🟢 Activa"
            return {"Usuario": u.username, "Nombre": u.name, "Perfil": ROLES[u.role][0] + (" · dueño" if u.username == OWNER else ""),
                    "Estado": state, "Correo": u.email or "—",
                    "Clave": "Temporal" if u.must_change else "Propia",
                    "Último ingreso": _cl(u.last_login), "Creado": _cl(u.created_at),
                    "Días sin entrar": None if u.last_login is None else (_nowu - u.last_login).days}
        st.dataframe(pd.DataFrame([u_row(u) for u in users]), hide_index=True, width="stretch",
                     column_config={"Último ingreso": st.column_config.DatetimeColumn(format="DD-MM-YY HH:mm"),
                                    "Creado": st.column_config.DatetimeColumn(format="DD-MM-YY HH:mm")})
        st.caption(f"Las claves que asigna el administrador son temporales. Una cuenta nueva que no entra en {db.FIRST_LOGIN_DAYS} días "
                   f"se desactiva sola · 🟡 = 15 días o más sin entrar · {db.MAX_FAILED} intentos fallidos bloquean la cuenta {db.LOCK_MIN} min.")

        if IS_OWNER:
            st.markdown("**🧭 Panel del dueño · activar, desactivar y desbloquear cuentas**")
            others = [u for u in users if u.username != OWNER]
            if others:
                p1, p2, p3, p4 = st.columns([2.2, 1, 1.5, 1])
                tgt_name = p1.selectbox("Cuenta", [u.username for u in others], key="own_tgt",
                                        format_func=lambda n: f"{n} · {u_row(next(x for x in others if x.username == n))['Estado']}")
                tgt = next(u for u in others if u.username == tgt_name)
                p2.write("")
                p3.write("")
                p4.write("")
                if tgt.active and p2.button("Desactivar", key="own_off"):
                    with db.Session() as s:
                        u = s.get(db.User, tgt.id)
                        u.active, u.deact_reason = 0, f"Desactivada por {USER.name}"
                        s.commit()
                    st.session_state.user_msg = f"Cuenta «{tgt.username}» desactivada."
                    st.rerun()
                if not tgt.active and p3.button("Reactivar y enviar acceso", key="own_on", type="primary"):
                    tmp = INITIAL_PW or db.temp_password()
                    with db.Session() as s:
                        u = s.get(db.User, tgt.id)
                        u.active, u.deact_reason, u.must_change = 1, "", 1
                        u.pw_hash, u.created_at, u.failed, u.locked_until = db.hash_pw(tmp), datetime.utcnow(), 0, None
                        s.commit()
                    msg = f"Cuenta «{tgt.username}» reactivada con clave temporal."
                    if tgt.email:
                        subj, body = mailer.welcome_text(tgt.name, tgt.username, tmp, APP_URL, f"Reactivada por {USER.name}.", reactivated=True)
                        msg += " " + mailer.send(st.secrets, tgt.email, subj, body)[1]
                    elif not INITIAL_PW:
                        st.session_state.new_temp = (tgt.username, tmp)
                    st.session_state.user_msg = msg
                    st.rerun()
                if tgt.locked_until and tgt.locked_until > _nowu and p4.button("Desbloquear", key="own_unlock"):
                    with db.Session() as s:
                        u = s.get(db.User, tgt.id)
                        u.locked_until, u.failed = None, 0
                        s.commit()
                    st.session_state.user_msg = f"Cuenta «{tgt.username}» desbloqueada."
                    st.rerun()
            if not mailer.configured(st.secrets):
                st.caption("📧 El envío de correos está apagado: agrega SMTP_USER y SMTP_PASSWORD en los Secrets para activarlo.")

        if IS_OWNER:
            st.markdown("**🔑 Solicitudes de recuperación de contraseña**")
            with db.Session() as s:
                reqs = s.scalars(select(db.PasswordRequest).order_by(db.PasswordRequest.id.desc())).all()
            pend = [r for r in reqs if r.status == "pendiente"]
            if "new_temp" in st.session_state:
                who_, tmp_ = st.session_state.new_temp
                st.success(f"Clave temporal para **{who_}**: `{tmp_}` — entrégasela por un canal directo. "
                           "No se volverá a mostrar; al entrar deberá crear una propia.")
                if st.button("Ya la entregué, ocultar"):
                    del st.session_state.new_temp
                    st.rerun()
            if not pend:
                st.caption("No hay solicitudes pendientes.")
            for r in pend:
                c1_, c2_, c3_ = st.columns([3, 1.3, 1])
                c1_.write(f"**{r.username}** · {r.created_at:%d-%m-%Y %H:%M} UTC" + (f" · contacto: {r.note}" if r.note else ""))
                if c2_.button("Generar clave temporal", key=f"ok{r.id}", type="primary"):
                    tmp = db.temp_password()
                    with db.Session() as s:
                        u_ = s.scalar(select(db.User).where(db.User.username == r.username))
                        rr = s.get(db.PasswordRequest, r.id)
                        if u_:
                            u_.pw_hash, u_.must_change = db.hash_pw(tmp), 1
                        rr.status, rr.resolved_by, rr.resolved_at = "resuelta", USER.name, datetime.utcnow()
                        s.commit()
                    st.session_state.new_temp = (r.username, tmp)
                    st.rerun()
                if c3_.button("Rechazar", key=f"no{r.id}"):
                    with db.Session() as s:
                        rr = s.get(db.PasswordRequest, r.id)
                        rr.status, rr.resolved_by, rr.resolved_at = "rechazada", USER.name, datetime.utcnow()
                        s.commit()
                    st.rerun()
            done = [r for r in reqs if r.status != "pendiente"][:10]
            if done:
                with st.expander("Historial de solicitudes"):
                    st.dataframe(pd.DataFrame([{"Usuario": r.username, "Solicitada (UTC)": r.created_at, "Estado": r.status,
                                                "Resuelta por": r.resolved_by} for r in done]), hide_index=True, width="stretch")
        u1, u2 = st.columns(2)
        with u1.form("newuser", clear_on_submit=True):
            st.markdown("**Crear usuario**")
            nu = st.text_input("Usuario (vacío = primera letra del nombre + primer apellido)")
            nn = st.text_input("Nombre y apellidos")
            nm = st.text_input("Correo (para enviarle su acceso)")
            nr = st.selectbox("Perfil", list(ROLES), format_func=lambda r: ROLES[r][0])
            npw = st.text_input("Contraseña inicial" + (" (vacío = clave inicial estándar)" if INITIAL_PW else ""), type="password")
            st.caption(("Si la dejas vacía se asigna la clave inicial estándar. " if INITIAL_PW else "")
                       + f"El usuario debe cambiarla al entrar y tiene {db.FIRST_LOGIN_DAYS} días para hacerlo.")
            if st.form_submit_button("Crear"):
                uname = nu.strip().lower() or make_username(nn)
                npw = npw or INITIAL_PW or ""
                mail = nm.strip().lower()
                if not uname or " " in uname or len(npw) < 8 or not nn.strip():
                    st.error("Completa usuario sin espacios, nombre y una contraseña de al menos 8 caracteres.")
                elif mail and ("@" not in mail or "." not in mail.split("@")[-1]):
                    st.error("El correo no parece válido.")
                else:
                    with db.Session() as s:
                        if s.scalar(select(db.User).where(db.User.username == uname)):
                            st.error(f"El usuario «{uname}» ya existe. Agrégale un número al final, por ejemplo «{free_username(s, uname)}», y vuelve a crear.")
                        else:
                            s.add(db.User(username=uname, name=nn.strip(), role=nr, pw_hash=db.hash_pw(npw), must_change=1,
                                          email=mail, created_at=datetime.utcnow()))
                            s.commit()
                            msg = f"Usuario «{uname}» creado."
                            if mail:
                                subj, body = mailer.welcome_text(nn.strip(), uname, npw, APP_URL, f"Cualquier duda, escríbele a {USER.name}.")
                                sent_ok, info = mailer.send(st.secrets, mail, subj, body)
                                msg += " " + info
                            st.session_state.user_msg = msg
                            st.rerun()
        with u2.form("pw", clear_on_submit=True):
            st.markdown("**Cambiar contraseña / desactivar**")
            who = st.selectbox("Usuario", [u.username for u in users])
            pw2 = st.text_input("Nueva contraseña (vacío = no cambiar)", type="password")
            em2 = st.text_input("Correo (vacío = no cambiar)")
            rst = st.checkbox("Restablecer a la clave inicial estándar", disabled=not INITIAL_PW)
            act = st.checkbox("Activo", value=True)
            if st.form_submit_button("Guardar"):
                if rst:
                    pw2 = INITIAL_PW
                if pw2 and len(pw2) < 8:
                    st.error("La contraseña debe tener al menos 8 caracteres.")
                elif who == USER.username and not act:
                    st.error("No puedes desactivar tu propio usuario.")
                elif who == OWNER and not IS_OWNER:
                    st.error("Solo el dueño de la app puede modificar su propio usuario.")
                else:
                    with db.Session() as s:
                        u = s.scalar(select(db.User).where(db.User.username == who))
                        if pw2:
                            u.pw_hash = db.hash_pw(pw2)
                            u.must_change = 0 if who == USER.username else 1
                            u.locked_until, u.failed = None, 0
                        if em2.strip():
                            u.email = em2.strip().lower()
                        if act and not u.active:
                            u.created_at, u.deact_reason = datetime.utcnow(), ""  # nuevo plazo de primer ingreso
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

"""Base de datos de PlanificA+ (SQLAlchemy). SQLite local por defecto; Postgres (p. ej. Supabase) vía DATABASE_URL."""
from __future__ import annotations

import json
import os
from datetime import date, datetime

import bcrypt
from sqlalchemy import (Column, Date, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select)
from sqlalchemy.orm import declarative_base, sessionmaker

import logic

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False)  # admin | ot | te | lectura
    pw_hash = Column(String(100), nullable=False)
    active = Column(Integer, default=1)
    must_change = Column(Integer, default=0)  # 1 = clave temporal: debe cambiarla al entrar
    email = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)               # None = nunca ha entrado
    failed = Column(Integer, default=0)         # intentos fallidos seguidos
    locked_until = Column(DateTime)             # bloqueo temporal por intentos fallidos
    deact_reason = Column(String(80), default="")


class PasswordRequest(Base):
    """Solicitud de recuperación de contraseña; la resuelve el dueño de la app."""
    __tablename__ = "password_requests"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False)
    note = Column(Text, default="")
    status = Column(String(12), default="pendiente")  # pendiente | resuelta | rechazada
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_by = Column(String(120), default="")
    resolved_at = Column(DateTime)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    start = Column(Date, nullable=False)
    status = Column(String(10), default="draft")  # draft | live | edit
    version = Column(Integer, default=0)
    tasks_json = Column(Text, default="[]")
    baseline_json = Column(Text, default="[]")
    snapshot_json = Column(Text, default="[]")
    edit_by = Column(String(120), default="")
    baseline_by = Column(String(120), default="")
    baseline_at = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def tasks(self) -> list[dict]:
        return json.loads(self.tasks_json or "[]")

    @tasks.setter
    def tasks(self, v: list[dict]):
        self.tasks_json = json.dumps(v, ensure_ascii=False)

    @property
    def baseline(self) -> list[dict]:
        return json.loads(self.baseline_json or "[]")

    @baseline.setter
    def baseline(self, v: list[dict]):
        self.baseline_json = json.dumps(v, ensure_ascii=False)

    @property
    def snapshot(self) -> list[dict]:
        return json.loads(self.snapshot_json or "[]")

    @snapshot.setter
    def snapshot(self, v: list[dict]):
        self.snapshot_json = json.dumps(v, ensure_ascii=False)


class Change(Base):
    __tablename__ = "changes"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    code = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    user = Column(String(120), nullable=False)
    version = Column(Integer, nullable=False)
    items_json = Column(Text, nullable=False)
    impact = Column(Integer, nullable=False)
    cause = Column(String(60), nullable=False)
    reason = Column(Text, nullable=False)
    end_after = Column(Date, nullable=False)

    @property
    def items(self):
        return json.loads(self.items_json)


class Progress(Base):
    __tablename__ = "progress_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    code = Column(String(20), nullable=False)
    reg = Column(Date, nullable=False)
    user = Column(String(120), nullable=False)
    task_code = Column(String(10), nullable=False)
    task_name = Column(String(200), nullable=False)
    area = Column(String(5), nullable=False)
    kind = Column(String(10), nullable=False)  # inicio | avance | cierre
    fecha = Column(Date, nullable=False)
    base_date = Column(Date)
    dev_days = Column(Integer)
    pct = Column(Integer)
    plan_pct = Column(Integer)
    comment = Column(Text, default="")


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    try:
        import streamlit as st
        url = st.secrets.get("DATABASE_URL", url)
    except Exception:
        pass
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url or "sqlite:///planificaplus.db"


ENGINE = create_engine(_url(), pool_pre_ping=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except ValueError:
        return False


def next_code(s, model, project_id: int, prefix: str) -> str:
    n = s.scalar(select(func.count()).select_from(model).where(model.project_id == project_id)) or 0
    return f"{prefix}-{n + 1:04d}"


def log_progress(s, p: Project, t: dict, kind: str, fecha: date, user: str, comment: str = "",
                 reg: date | None = None, pct: int | None = None, plan_pct: int | None = None):
    base = logic.schedule(p.start, p.baseline)["at"]
    in_base = any(b["code"] == t["code"] for b in p.baseline)
    base_date = None
    if kind != "avance" and in_base and t["code"] in base:
        base_date = base[t["code"]][0] if kind == "inicio" else base[t["code"]][1]
    s.add(Progress(project_id=p.id, code=next_code(s, Progress, p.id, "AV"), reg=reg or date.today(), user=user,
                   task_code=t["code"], task_name=t["name"], area=t["area"], kind=kind, fecha=fecha,
                   base_date=base_date, dev_days=(fecha - base_date).days if base_date else None,
                   pct=pct, plan_pct=plan_pct, comment=comment))
    s.flush()


def record_change(s, p: Project, before: list[dict], after: list[dict], user: str, cause: str, reason: str,
                  when: date | None = None) -> Change:
    e0 = logic.schedule(p.start, before)["end"]
    e1 = logic.schedule(p.start, after)["end"]
    p.version += 1
    ch = Change(project_id=p.id, code=next_code(s, Change, p.id, "CHG"), date=when or date.today(), user=user,
                version=p.version, items_json=json.dumps(logic.diff_tasks(before, after), ensure_ascii=False),
                impact=(e1 - e0).days, cause=cause, reason=reason, end_after=e1)
    s.add(ch)
    s.flush()
    return ch


def seed_demo_project(s) -> Project:
    """Proyecto de ejemplo construido con los datos de la entrevista al socio comunitario."""
    p = Project(name="Ampliación S/E Las Cabras (ejemplo)", start=date(2026, 3, 2), status="live", version=1,
                baseline_by="Alberto Martino", baseline_at=date(2026, 3, 2))
    base = logic.template_tasks()
    p.baseline = base
    p.tasks = base
    s.add(p)
    s.flush()

    def change(when, user, fn, cause, reason):
        before = p.tasks
        after = [dict(t) for t in before]
        fn(after)
        p.tasks = after
        record_change(s, p, before, after, user, cause, reason, when)

    T = lambda ts, c: next(t for t in ts if t["code"] == c)
    change(date(2026, 5, 14), "Jefe de oficina técnica", lambda ts: T(ts, "T03").update(dur=105), "Mandante / ITO",
           "El mandante devolvió la ingeniería de detalle con observaciones en el paño de 66 kV; se suman 21 días de corrección.")
    change(date(2026, 6, 18), "Jefe de terreno",
           lambda ts: ts.insert(next(i for i, t in enumerate(ts) if t["code"] == "T07") + 1,
                                {"code": "T16", "name": "Malla de puesta a tierra adicional", "area": "te", "dur": 21, "lag": 0, "deps": ["T07"]}),
           "Alcance adicional", "La ITO exige ampliar la malla de puesta a tierra; se agrega la etapa en paralelo a fundaciones.")
    change(date(2026, 7, 22), "Jefe de terreno", lambda ts: T(ts, "T12").update(dur=30), "Recuperación de plazo",
           "Se contrata segunda cuadrilla de control y protección y turno de sábado para recuperar la curva.")
    change(date(2026, 9, 10), "Jefe de oficina técnica", lambda ts: T(ts, "T06").update(dur=210), "Proveedor",
           "El fabricante de interruptores informa 28 días de retraso en fábrica; el envío aéreo no fue viable por costo.")
    change(date(2026, 10, 28), "Jefe de oficina técnica", lambda ts: T(ts, "T02").update(lag=10), "Permisos",
           "La municipalidad pidió antecedentes adicionales del PAS; el inicio del trámite se corre 10 días.")

    tasks = p.tasks
    real = [("T01", "2026-03-02", "2026-03-10", "Alberto Martino", ""),
            ("T03", "2026-03-10", "2026-06-24", "Jefe de oficina técnica", "Aprobada tras dos rondas de observaciones"),
            ("T02", "2026-03-20", "2026-05-22", "Jefe de oficina técnica", "Resolución del PAS recibida"),
            ("T04", "2026-06-25", "2026-07-21", "Alberto Martino", ""),
            ("T05", "2026-07-24", "2026-07-24", "Jefe de oficina técnica", "OC emitidas a 3 proveedores"),
            ("T07", "2026-07-27", "2026-08-21", "Jefe de terreno", ""),
            ("T09", "2026-07-27", "2026-10-16", "Jefe de oficina técnica", "Estructura recibida con certificado de galvanizado"),
            ("T16", "2026-08-24", "2026-09-18", "Jefe de terreno", "Malla medida y aprobada por la ITO"),
            ("T06", "2026-07-27", None, "Jefe de oficina técnica", ""),
            ("T08", "2026-08-24", None, "Jefe de terreno", "")]
    events = []
    for code, rs, re_, u, com in real:
        t = T(tasks, code)
        t["real_start"], t["real_pct"] = rs, 0
        events.append((rs, 0, code, "inicio", u, ""))
        if re_:
            t["real_end"], t["real_pct"] = re_, 100
            events.append((re_, 1, code, "cierre", u, com))
    p.tasks = tasks
    for f, _, code, kind, u, com in sorted(events):
        d = date.fromisoformat(f)
        log_progress(s, p, T(tasks, code), kind, d, u, com, reg=d)
    sch = logic.schedule(p.start, tasks)["at"]
    for code, v, u, com in [("T06", 34, "Jefe de oficina técnica", "Proveedor de interruptores aún en fábrica"),
                            ("T08", 66, "Jefe de terreno", "Faltan 4 fundaciones del paño de transformador")]:
        t = T(tasks, code)
        t["real_pct"] = v
        when = date(2026, 11, 2)
        log_progress(s, p, t, "avance", when, u, com, reg=when, pct=v, plan_pct=logic.pct_at(sch[code], t["dur"], when))
    p.tasks = tasks
    return p


def _migrate():
    """Agrega columnas nuevas a tablas ya existentes (create_all no modifica tablas)."""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(ENGINE).get_columns("users")}
    ts = "TIMESTAMP" if ENGINE.dialect.name == "postgresql" else "DATETIME"
    add = {"must_change": "INTEGER DEFAULT 0", "email": "VARCHAR(120) DEFAULT ''", "created_at": ts,
           "last_login": ts, "failed": "INTEGER DEFAULT 0", "locked_until": ts, "deact_reason": "VARCHAR(80) DEFAULT ''"}
    with ENGINE.begin() as con:
        for name, typ in add.items():
            if name not in cols:
                con.execute(text(f"ALTER TABLE users ADD COLUMN {name} {typ}"))
        # Usuarios anteriores a esta versión: se cuentan como creados ahora (no se desactivan de golpe).
        con.execute(text("UPDATE users SET created_at = :n WHERE created_at IS NULL"), {"n": datetime.utcnow()})


FIRST_LOGIN_DAYS = 5      # días para el primer ingreso antes de desactivar la cuenta
MAX_FAILED, LOCK_MIN = 5, 15  # intentos fallidos permitidos y minutos de bloqueo


def sweep_inactive() -> int:
    """Desactiva cuentas que nunca entraron dentro de FIRST_LOGIN_DAYS. Devuelve cuántas desactivó."""
    from datetime import timedelta
    lim = datetime.utcnow() - timedelta(days=FIRST_LOGIN_DAYS)
    with Session() as s:
        us = s.scalars(select(User).where(User.active == 1, User.must_change == 1, User.last_login.is_(None), User.created_at < lim)).all()
        for u in us:
            u.active, u.deact_reason = 0, f"Sin primer ingreso en {FIRST_LOGIN_DAYS} días"
        s.commit()
        return len(us)


def temp_password() -> str:
    """Clave temporal legible: sin caracteres que se confundan (0/O, 1/l)."""
    import secrets
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def init_db(demo_password: str):
    Base.metadata.create_all(ENGINE)
    _migrate()
    with Session() as s:
        if not s.scalar(select(func.count()).select_from(User)):
            for u, n, r in [("alberto", "Alberto Martino", "admin"), ("oficina", "Jefe de oficina técnica", "ot"),
                            ("terreno", "Jefe de terreno", "te"), ("visita", "Visita (solo lectura)", "lectura")]:
                s.add(User(username=u, name=n, role=r, pw_hash=hash_pw(demo_password)))
        if not s.scalar(select(func.count()).select_from(Project)):
            seed_demo_project(s)
        s.commit()


def reset_demo(project_id: int | None):
    with Session() as s:
        if project_id:
            for m in (Change, Progress):
                s.query(m).filter(m.project_id == project_id).delete()
            s.query(Project).filter(Project.id == project_id).delete()
        p = seed_demo_project(s)
        s.commit()
        return p.id

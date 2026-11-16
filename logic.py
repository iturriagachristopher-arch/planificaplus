"""Lógica de negocio de PlanificA+: programación, avance plan vs real, semáforo y diferencias."""
from __future__ import annotations

from datetime import date, timedelta

AREAS = {"adm": "Administración", "ot": "Oficina técnica", "te": "Terreno"}
ROLES = {
    "admin": ("Administrador de contrato", ["adm", "ot", "te"]),
    "ot": ("Jefe de oficina técnica", ["ot"]),
    "te": ("Jefe de terreno", ["te"]),
    "lectura": ("Solo lectura", []),
}
CAUSES = ["Proveedor", "Ingeniería", "Permisos", "Mandante / ITO", "Clima", "Subcontrato",
          "Recuperación de plazo", "Alcance adicional", "Otro"]
TOL_OK, TOL_HIGH = 5, 10  # puntos porcentuales

# Plantilla: código, nombre, área, duración (días), dependencias
TEMPLATE = [
    ("T01", "Firma de contrato y kick-off", "adm", 7, []),
    ("T02", "Permisos administrativos y ambientales (PAS)", "ot", 56, ["T01"]),
    ("T03", "Ingeniería de detalle", "ot", 84, ["T01"]),
    ("T04", "Revisión y aprobación de ingeniería (mandante)", "adm", 28, ["T03"]),
    ("T05", "Emisión de OC de equipos primarios", "ot", 0, ["T04"]),
    ("T06", "Fabricación y transporte de equipos (barco)", "ot", 182, ["T05"]),
    ("T07", "Movimiento de tierra", "te", 28, ["T02", "T04"]),
    ("T08", "Fundaciones y pernos de anclaje", "te", 112, ["T07"]),
    ("T09", "Fabricación estructura metálica galvanizada", "ot", 84, ["T04"]),
    ("T10", "Montaje de estructuras", "te", 28, ["T08", "T09"]),
    ("T11", "Montaje de equipos (con vendor)", "te", 42, ["T06", "T10"]),
    ("T12", "Conexionado control y protección", "te", 42, ["T11"]),
    ("T13", "Pruebas y protocolos", "ot", 28, ["T12"]),
    ("T14", "Puesta en servicio", "adm", 14, ["T13"]),
    ("T15", "Marcha blanca", "adm", 28, ["T14"]),
]


def template_tasks() -> list[dict]:
    return [{"code": c, "name": n, "area": a, "dur": d, "lag": 0, "deps": list(p)} for c, n, a, d, p in TEMPLATE]


def schedule(start: date, tasks: list[dict]) -> dict:
    """Calcula inicio y fin de cada etapa según dependencias (fin-inicio) y atraso de inicio."""
    by = {t["code"]: t for t in tasks}
    memo: dict[str, tuple[date, date]] = {}

    def calc(code: str, stack: frozenset = frozenset()) -> tuple[date, date]:
        if code in memo:
            return memo[code]
        t = by.get(code)
        if t is None or code in stack:
            return (start, start)
        preds = [calc(p, stack | {code})[1] for p in t["deps"] if p in by]
        s = max([start] + preds) + timedelta(days=int(t.get("lag") or 0))
        e = s + timedelta(days=int(t.get("dur") or 0))
        memo[code] = (s, e)
        return memo[code]

    for t in tasks:
        calc(t["code"])
    end = max([e for _, e in memo.values()], default=start)
    return {"at": memo, "end": end}


def pct_at(span: tuple[date, date] | None, dur: int, when: date) -> int:
    """Avance plan (%) lineal según la fecha de corte."""
    if not span:
        return 0
    s, e = span
    if dur == 0 or e <= s:
        return 100 if when >= e else 0
    frac = (when - s).days / (e - s).days
    return round(max(0.0, min(1.0, frac)) * 100)


def semaforo(dev_pp: int) -> tuple[str, str]:
    """dev_pp = plan − real. Devuelve (nivel, etiqueta)."""
    if dev_pp <= TOL_OK:
        return ("verde", "Adelantada" if dev_pp < 0 else "Mínima")
    if dev_pp <= TOL_HIGH:
        return ("amarillo", "Alta")
    return ("rojo", "Crítica")


def descendants(tasks: list[dict], code: str) -> set[str]:
    out = {code}
    grew = True
    while grew:
        grew = False
        for t in tasks:
            if t["code"] not in out and any(p in out for p in t["deps"]):
                out.add(t["code"])
                grew = True
    return out


def next_code(codes: list[str]) -> str:
    nums = [int(c[1:]) for c in codes if c[1:].isdigit()]
    return f"T{(max(nums) if nums else 0) + 1:02d}"


def diff_tasks(before: list[dict], after: list[dict]) -> list[dict]:
    """Lista de cambios entre dos versiones del programa."""
    b = {t["code"]: t for t in before}
    a = {t["code"]: t for t in after}
    names = {**{c: t["name"] for c, t in b.items()}, **{c: t["name"] for c, t in a.items()}}
    dep_txt = lambda ds: ", ".join(names.get(x, x) for x in ds) or "inicio del proyecto"
    items = []
    for t in after:
        o = b.get(t["code"])
        base = {"code": t["code"], "name": t["name"], "area": t["area"]}
        if o is None:
            items.append({**base, "type": "add", "after": t["dur"]})
            continue
        if o["dur"] != t["dur"]:
            items.append({**base, "type": "dur", "before": o["dur"], "after": t["dur"]})
        if o["lag"] != t["lag"]:
            items.append({**base, "type": "lag", "before": o["lag"], "after": t["lag"]})
        if o["name"] != t["name"]:
            items.append({**base, "type": "name", "before": o["name"], "after": t["name"]})
        if sorted(o["deps"]) != sorted(t["deps"]):
            items.append({**base, "type": "deps", "before": dep_txt(o["deps"]), "after": dep_txt(t["deps"])})
    for t in before:
        if t["code"] not in a:
            items.append({"code": t["code"], "name": t["name"], "area": t["area"], "type": "del", "before": t["dur"]})
    return items


def change_text(it: dict) -> str:
    k = it["type"]
    if k == "add":
        return f"+ Etapa nueva: {it['name']} ({AREAS[it['area']]}, {it['after']} días)"
    if k == "del":
        return f"− Etapa eliminada: {it['name']}"
    if k == "name":
        return f"Renombrada: «{it['before']}» → «{it['after']}»"
    if k == "deps":
        return f"{it['name']}: ahora empieza después de {it['after']} (antes: {it['before']})"
    campo = "duración" if k == "dur" else "atraso de inicio"
    return f"{it['name']}: {campo} {it['before']} → {it['after']} días"


def weighted(tasks: list[dict], values: dict[str, float]) -> int:
    w = {t["code"]: max(1, int(t["dur"])) for t in tasks}
    tot = sum(w.values()) or 1
    return round(sum(w[c] * values.get(c, 0) for c in w) / tot)

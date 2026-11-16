"""Lógica de negocio de PlanificA+: programación, avance plan vs real, semáforo y diferencias."""
from __future__ import annotations

import re
from datetime import date, timedelta

AREAS = {"adm": "Administración", "ot": "Oficina técnica", "te": "Terreno"}
ROLES = {
    "admin": ("Administrador de contrato", ["adm", "ot", "te"]),
    "ot": ("Jefe de oficina técnica", ["ot"]),
    "te": ("Jefe de terreno", ["te"]),
    "pmo": ("PMO / Control de proyectos", ["adm", "ot", "te"]),
    "lectura": ("Solo lectura", []),
}
CAUSES = ["Proveedor", "Ingeniería", "Permisos", "Mandante / ITO", "Clima", "Subcontrato",
          "Recuperación de plazo", "Alcance adicional", "Otro"]
TOL_OK, TOL_HIGH = 5, 10  # puntos porcentuales
KINDS = ["Tarea", "Hito", "Resumen"]
LINK_TYPES = ["FC", "CC", "FF", "CF"]  # fin-comienzo, comienzo-comienzo, fin-fin, comienzo-fin
CALENDARS = {"corridos": "Días corridos", "habiles": "Días hábiles (sin fines de semana ni feriados)"}

# Feriados nacionales de Chile (fechas oficiales 2026-2028; los trasladables según calendario publicado).
HOLIDAYS = {date.fromisoformat(d) for d in """
2026-01-01 2026-04-03 2026-04-04 2026-05-01 2026-05-21 2026-06-21 2026-06-29 2026-07-16 2026-08-15
2026-09-18 2026-09-19 2026-10-12 2026-10-31 2026-11-01 2026-12-08 2026-12-25
2027-01-01 2027-03-26 2027-03-27 2027-05-01 2027-05-21 2027-06-21 2027-06-28 2027-07-16 2027-08-15
2027-09-17 2027-09-18 2027-09-19 2027-10-11 2027-10-31 2027-11-01 2027-12-08 2027-12-25
2028-01-01 2028-04-14 2028-04-15 2028-05-01 2028-05-21 2028-06-20 2028-06-26 2028-07-16 2028-08-15
2028-09-18 2028-09-19 2028-10-12 2028-10-31 2028-11-01 2028-12-08 2028-12-25""".split()}

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


def is_workday(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def add_days(d: date, n: int, cal: str = "corridos") -> date:
    """Suma n días (corridos u hábiles). En hábiles, n=0 lleva al siguiente día hábil."""
    if cal != "habiles":
        return d + timedelta(days=n)
    step = 1 if n >= 0 else -1
    while not is_workday(d):
        d += timedelta(days=1)
    for _ in range(abs(n)):
        d += timedelta(days=step)
        while not is_workday(d):
            d += timedelta(days=step)
    return d


def links_of(t: dict) -> list[dict]:
    """Vínculos de la tarea: [{'c': código, 't': 'FC'|'CC'|'FF'|'CF', 'l': desfase}]. Compatibilidad con 'deps'."""
    if t.get("links"):
        return t["links"]
    return [{"c": d, "t": "FC", "l": 0} for d in t.get("deps", [])]


def summaries(tasks: list[dict]) -> set[str]:
    """Códigos de tareas resumen: marcadas como Resumen o con hijas en el EDT."""
    wbs = {t["code"]: str(t.get("wbs") or "") for t in tasks}
    out = {t["code"] for t in tasks if t.get("kind") == "Resumen"}
    for c, w in wbs.items():
        if w and any(o.startswith(w + ".") for o in wbs.values()):
            out.add(c)
    return out


def children(tasks: list[dict], code: str) -> list[str]:
    """Hijas directas (por EDT) de una tarea resumen."""
    w = next((str(t.get("wbs") or "") for t in tasks if t["code"] == code), "")
    if not w:
        return []
    return [t["code"] for t in tasks if str(t.get("wbs") or "").startswith(w + ".")
            and str(t["wbs"]).count(".") == w.count(".") + 1]


def schedule(start: date, tasks: list[dict], cal: str = "corridos") -> dict:
    """Programa hacia adelante con vínculos FC/CC/FF/CF y desfases; resúmenes = mín inicio / máx fin de sus hijas.
    Luego programa hacia atrás para obtener holgura total y ruta crítica (tareas con holgura 0)."""
    by = {t["code"]: t for t in tasks}
    summ = summaries(tasks)
    kids = {c: children(tasks, c) for c in summ}
    memo: dict[str, tuple[date, date]] = {}
    start = add_days(start, 0, cal)

    def calc(code: str, stack: frozenset = frozenset()) -> tuple[date, date]:
        if code in memo:
            return memo[code]
        t = by.get(code)
        if t is None or code in stack:
            return (start, start)
        if code in summ and kids.get(code):
            spans = [calc(k, stack | {code}) for k in kids[code]]
            memo[code] = (min(s_ for s_, _ in spans), max(e_ for _, e_ in spans))
            return memo[code]
        dur = 0 if t.get("kind") == "Hito" else int(t.get("dur") or 0)
        cand = [start]
        if t.get("start"):
            cand.append(add_days(date.fromisoformat(t["start"]), 0, cal))
        for lk in links_of(t):
            if lk["c"] not in by:
                continue
            ps, pe = calc(lk["c"], stack | {code})
            l, k = int(lk.get("l") or 0), lk.get("t", "FC")
            if k == "FC":
                cand.append(add_days(pe, l, cal))
            elif k == "CC":
                cand.append(add_days(ps, l, cal))
            elif k == "FF":
                cand.append(add_days(add_days(pe, l, cal), -dur, cal))
            elif k == "CF":
                cand.append(add_days(add_days(ps, l, cal), -dur, cal))
        s = add_days(max(cand), int(t.get("lag") or 0), cal)
        memo[code] = (s, add_days(s, dur, cal))
        return memo[code]

    for t in tasks:
        calc(t["code"])
    end = max([e for _, e in memo.values()], default=start)

    # Programación hacia atrás → holgura total (en la misma unidad del calendario)
    def net(a: date, b: date) -> int:  # días (hábiles o corridos) entre a y b
        if cal != "habiles":
            return (b - a).days
        return sum(1 for i in range((b - a).days) if is_workday(a + timedelta(days=i)))

    leaves = [t for t in tasks if t["code"] not in summ]
    dw = {t["code"]: net(*memo[t["code"]]) for t in leaves}
    lf = {t["code"]: end for t in leaves}
    for _ in range(len(leaves) + 1):
        changed = False
        for t in leaves:
            c = t["code"]
            ls = add_days(lf[c], -dw[c], cal)
            for lk in links_of(t):
                pc = lk["c"]
                if pc not in lf:
                    continue
                l, k = int(lk.get("l") or 0), lk.get("t", "FC")
                if k == "FC":
                    lim = add_days(ls, -l, cal)
                elif k == "CC":
                    lim = add_days(add_days(ls, -l, cal), dw[pc], cal)
                elif k == "FF":
                    lim = add_days(lf[c], -l, cal)
                else:
                    lim = add_days(add_days(lf[c], -l, cal), dw[pc], cal)
                if lim < lf[pc]:
                    lf[pc], changed = lim, True
        if not changed:
            break
    slack = {c: max(0, net(memo[c][1], lf[c])) for c in lf}
    crit = {c for c, v in slack.items() if v == 0}
    return {"at": memo, "end": end, "slack": slack, "crit": crit, "summ": summ}


PRED_RE = re.compile(r"^\s*([0-9A-Za-z.]+?)\s*(FC|CC|FF|CF)?\s*([+-]\s*\d+)?\s*(d|días|dias)?\s*$", re.I)


def parse_preds(text: str) -> list[tuple[str, str, int]] | None:
    """'2.1.1, 2.1.2CC+3' → [('2.1.1','FC',0), ('2.1.2','CC',3)]. None si el formato no es válido."""
    out = []
    for part in [p for p in re.split(r"[;,]", str(text or "")) if p.strip()]:
        m = PRED_RE.match(part)
        if not m:
            return None
        out.append((m.group(1).strip(". "), (m.group(2) or "FC").upper(), int((m.group(3) or "0").replace(" ", ""))))
    return out


def preds_text(t: dict, wbs_of: dict[str, str]) -> str:
    parts = []
    for lk in links_of(t):
        if lk["c"] not in wbs_of:
            continue
        txt = wbs_of[lk["c"]] + ("" if lk.get("t", "FC") == "FC" else lk["t"])
        l = int(lk.get("l") or 0)
        parts.append(txt + (f"{l:+d}" if l else ""))
    return ", ".join(parts)


def wbs_key(w: str):
    return [int(x) if x.isdigit() else x for x in str(w).split(".")]


def ensure_wbs(tasks: list[dict]) -> list[dict]:
    """Proyectos antiguos sin EDT: numeración 1, 2, 3… en el orden actual."""
    if all(t.get("wbs") for t in tasks):
        return tasks
    return [{**t, "wbs": t.get("wbs") or str(i + 1)} for i, t in enumerate(tasks)]


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
            if t["code"] not in out and any(lk["c"] in out for lk in links_of(t)):
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
        lt = lambda x: sorted((lk["c"], lk.get("t", "FC"), int(lk.get("l") or 0)) for lk in links_of(x))
        if lt(o) != lt(t):
            fmt_ = lambda x: ", ".join(names.get(lk["c"], lk["c"]) + ("" if lk.get("t", "FC") == "FC" else f" ({lk['t']})")
                                       + (f" {int(lk['l']):+d} d" if int(lk.get("l") or 0) else "") for lk in links_of(x)) or "inicio del proyecto"
            items.append({**base, "type": "deps", "before": fmt_(o), "after": fmt_(t)})
        if (o.get("start") or "") != (t.get("start") or ""):
            items.append({**base, "type": "start", "before": o.get("start") or "automático", "after": t.get("start") or "automático"})
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
    if k == "start":
        return f"{it['name']}: inicio fijo {it['before']} → {it['after']}"
    campo = "duración" if k == "dur" else "atraso de inicio"
    return f"{it['name']}: {campo} {it['before']} → {it['after']} días"


def weighted(tasks: list[dict], values: dict[str, float]) -> int:
    """Promedio ponderado por duración, solo con tareas (sin resúmenes ni hitos)."""
    summ = summaries(tasks)
    w = {t["code"]: max(1, int(t["dur"] or 0)) for t in tasks if t["code"] not in summ and t.get("kind") != "Hito"}
    tot = sum(w.values()) or 1
    return round(sum(w[c] * values.get(c, 0) for c in w) / tot) if w else 0

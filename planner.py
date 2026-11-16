"""Programa tipo MS Project: tabla editable ⇄ tareas, importación/exportación Excel y validaciones."""
from __future__ import annotations

import io
import re
from datetime import date, datetime

import pandas as pd

import logic

COLS = ["EDT", "Nombre", "Tipo", "Área", "Responsable", "Duración (días)", "Atraso (días)", "Inicio (opcional)",
        "Predecesoras", "Notas"]
EDT_RE = re.compile(r"^\d+(\.\d+)*$")
AREA_BY_NAME = {v.lower(): k for k, v in logic.AREAS.items()}


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _int(v, default=0):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
            return default
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "NaT"):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date() if hasattr(v, "date") else v
    if isinstance(v, date):
        return v
    for f in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(str(v).strip(), f).date()
        except ValueError:
            pass
    return "error"


def tasks_to_rows(tasks: list[dict]) -> pd.DataFrame:
    tasks = logic.ensure_wbs(tasks)
    wbs_of = {t["code"]: str(t["wbs"]) for t in tasks}
    summ = logic.summaries(tasks)
    rows = [{"EDT": str(t["wbs"]), "Nombre": t["name"],
             "Tipo": "Resumen" if t["code"] in summ else (t.get("kind") or "Tarea"),
             "Área": logic.AREAS.get(t["area"], t["area"]), "Responsable": t.get("resp") or None,
             "Duración (días)": int(t.get("dur") or 0), "Atraso (días)": int(t.get("lag") or 0),
             "Inicio (opcional)": date.fromisoformat(t["start"]) if t.get("start") else None,
             "Predecesoras": logic.preds_text(t, wbs_of), "Notas": t.get("notes") or "", "_code": t["code"]}
            for t in sorted(tasks, key=lambda x: logic.wbs_key(x["wbs"]))]
    return pd.DataFrame(rows, columns=COLS + ["_code"])


def rows_to_tasks(df: pd.DataFrame, old: list[dict], users: set[str]) -> tuple[list[dict], list[str], list[str]]:
    """Convierte la tabla (o el Excel) en tareas. Devuelve (tareas, errores, avisos)."""
    errors, warns = [], []
    old_by = {t["code"]: t for t in old}
    used_codes = set(old_by)
    raw = []
    for i, r in enumerate(df.to_dict("records")):
        edt, name = _txt(r.get("EDT")).rstrip("."), _txt(r.get("Nombre"))
        if not edt and not name:
            continue
        fila = f"Fila {i + 1}" + (f" (EDT {edt})" if edt else "")
        if not edt or not EDT_RE.match(edt):
            errors.append(f"{fila}: el EDT debe ser como 1, 1.2 o 1.2.3.")
            continue
        if not name:
            errors.append(f"{fila}: falta el nombre.")
        kind = _txt(r.get("Tipo")).capitalize() or "Tarea"
        if kind not in logic.KINDS:
            errors.append(f"{fila}: tipo «{kind}» no válido (Tarea, Hito o Resumen).")
            kind = "Tarea"
        area = AREA_BY_NAME.get(_txt(r.get("Área")).lower()) or (_txt(r.get("Área")) if _txt(r.get("Área")) in logic.AREAS else None)
        if not area:
            errors.append(f"{fila}: área «{_txt(r.get('Área'))}» no válida (Oficina técnica, Terreno o Administración).")
            area = "ot"
        dur = _int(r.get("Duración (días)"), 0)
        lag = _int(r.get("Atraso (días)"), 0)
        if dur is None or dur < 0:
            errors.append(f"{fila}: la duración debe ser un número de días (0 o más).")
            dur = 0
        if lag is None or lag < 0:
            errors.append(f"{fila}: el atraso debe ser un número de días (0 o más).")
            lag = 0
        if kind == "Hito":
            dur = 0
        start = _date(r.get("Inicio (opcional)"))
        if start == "error":
            errors.append(f"{fila}: fecha de inicio no válida (usa dd-mm-aaaa).")
            start = None
        resp = _txt(r.get("Responsable")).lower()
        if resp and resp not in users:
            warns.append(f"{fila}: el responsable «{resp}» no es un usuario de la app; la tarea queda sin responsable.")
            resp = ""
        preds = logic.parse_preds(_txt(r.get("Predecesoras")))
        if preds is None:
            errors.append(f"{fila}: predecesoras con formato no válido (ej.: 2.1.1, 2.1.2CC+3).")
            preds = []
        code = _txt(r.get("_code"))
        if not code or code not in old_by or any(x["code"] == code for x in raw):
            code = logic.next_code(list(used_codes))
            used_codes.add(code)
        raw.append({"code": code, "wbs": edt, "name": name, "area": area, "dur": dur, "lag": lag, "kind": kind,
                    "resp": resp, "start": start.isoformat() if start else None, "notes": _txt(r.get("Notas")),
                    "_preds": preds})
    by_wbs = {}
    for t in raw:
        if t["wbs"] in by_wbs:
            errors.append(f"EDT {t['wbs']} repetido: cada tarea necesita un EDT único.")
        by_wbs[t["wbs"]] = t
    for t in raw:
        if "." in t["wbs"] and t["wbs"].rsplit(".", 1)[0] not in by_wbs:
            errors.append(f"EDT {t['wbs']}: no existe su tarea superior {t['wbs'].rsplit('.', 1)[0]}.")
        links = []
        for w, k, l in t.pop("_preds"):
            p = by_wbs.get(w)
            if not p:
                errors.append(f"EDT {t['wbs']}: la predecesora {w} no existe.")
            elif p is t or t["wbs"].startswith(w + ".") or w.startswith(t["wbs"] + "."):
                errors.append(f"EDT {t['wbs']}: no puede depender de sí misma ni de su propia tarea superior o inferior.")
            else:
                links.append({"c": p["code"], "t": k, "l": l})
        t["links"], t["deps"] = links, [lk["c"] for lk in links]
        o = old_by.get(t["code"])
        if o:
            for f in ("real_start", "real_end", "real_pct"):
                if o.get(f) is not None:
                    t[f] = o[f]
    tasks = sorted(raw, key=lambda x: logic.wbs_key(x["wbs"]))
    cyc = find_cycle(tasks)
    if cyc:
        errors.append("Dependencia circular entre: " + " → ".join(cyc) + ". Revisa las predecesoras.")
    if not tasks:
        errors.append("El programa no tiene tareas.")
    return tasks, errors, warns


def find_cycle(tasks: list[dict]) -> list[str] | None:
    """Busca un ciclo en los vínculos (contando que un resumen depende de sus hijas). Devuelve los EDT del ciclo."""
    wbs = {t["code"]: str(t["wbs"]) for t in tasks}
    graph = {t["code"]: [lk["c"] for lk in logic.links_of(t) if lk["c"] in wbs] for t in tasks}
    for c, w in wbs.items():  # el resumen "espera" a sus hijas
        graph[c] = graph[c] + [k for k, kw in wbs.items() if kw.startswith(w + ".")]
    color, path = {}, []

    def dfs(u):
        color[u] = 1
        path.append(u)
        for v in graph.get(u, []):
            if color.get(v) == 1:
                return path[path.index(v):] + [v]
            if not color.get(v):
                r = dfs(v)
                if r:
                    return r
        color[u] = 2
        path.pop()
        return None

    for c in graph:
        if not color.get(c):
            r = dfs(c)
            if r:
                return [wbs[x] for x in r]
    return None


def read_excel(file) -> tuple[pd.DataFrame, date | None]:
    """Lee la hoja «Programa» de la plantilla (encabezados en la fila 2). Devuelve (tabla, inicio del proyecto)."""
    xl = pd.ExcelFile(file)
    sheet = "Programa" if "Programa" in xl.sheet_names else xl.sheet_names[0]
    head = pd.read_excel(xl, sheet_name=sheet, header=None, nrows=1)
    start = None
    for v in head.iloc[0].tolist():
        d = _date(v) if isinstance(v, (datetime, pd.Timestamp, date)) else None
        if d and d != "error":
            start = d
    df = pd.read_excel(xl, sheet_name=sheet, header=1, dtype={"EDT": str})
    df.columns = [str(c).strip() for c in df.columns]
    if "EDT" not in df.columns:
        raise ValueError("No encontré la columna «EDT» en la fila 2. Usa la plantilla de PlanificA+.")
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    return df[COLS], start


def to_excel(tasks: list[dict], project_name: str, start: date) -> bytes:
    """Programa en el formato de la plantilla (sirve como plantilla para importar)."""
    from openpyxl.styles import Alignment, Font, PatternFill
    df = tasks_to_rows(tasks).drop(columns=["_code"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Programa", index=False, startrow=1)
        ws = xw.sheets["Programa"]
        ws["A1"], ws["B1"], ws["E1"], ws["G1"] = "Proyecto:", project_name, "Inicio del proyecto:", start
        ws["G1"].number_format = "dd-mm-yyyy"
        for c in ws[2]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E8C")
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for col, w in zip("ABCDEFGHIJ", [9, 46, 11, 17, 14, 11, 11, 14, 18, 36]):
            ws.column_dimensions[col].width = w
        for r in range(3, ws.max_row + 1):
            ws[f"H{r}"].number_format = "dd-mm-yyyy"
            lvl = str(ws[f"A{r}"].value or "").count(".")
            ws[f"B{r}"].alignment = Alignment(indent=lvl * 2)
            if ws[f"C{r}"].value == "Resumen":
                for c in ws[r]:
                    c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="E3EFEC")
        ws.freeze_panes = "A3"
    return buf.getvalue()

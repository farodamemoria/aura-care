"""KAN-81 — Genera el plan de reparto de tareas (Markdown) desde el JSON.

Uso:
    python scripts/kan81_generar_plan.py

El JSON `docs/kan81-delegacion.json` es la fuente de verdad; este script
produce `docs/kan81-delegacion-ia.md` de forma determinista (mismo JSON,
mismo Markdown), para que los tests puedan compararlos.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "docs" / "kan81-delegacion.json"
SALIDA_PATH = ROOT / "docs" / "kan81-delegacion-ia.md"
ORDEN_PRIORIDAD = {"Highest": 0, "High": 1, "Medium": 2, "Low": 3, "Lowest": 4}


def cargar_plan(ruta: Path = PLAN_PATH) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def ordenar_tareas(tareas: list[dict]) -> list[dict]:
    return sorted(
        tareas,
        key=lambda tarea: (
            ORDEN_PRIORIDAD.get(tarea["prioridad"], 9),
            tarea["creada"],
            tarea["clave"],
        ),
    )


def nombre_herramienta(plan: dict, herramienta_id: str) -> str:
    for herramienta in plan["herramientas"]:
        if herramienta["id"] == herramienta_id:
            return herramienta["nombre"]
    return herramienta_id


def celda(texto: str) -> str:
    return str(texto).replace("|", "\\|")


def generar_markdown(plan: dict) -> str:
    lineas: list[str] = []
    lineas.append("# KAN-81 — Reparto de tareas entre asistentes de IA")
    lineas.append("")
    lineas.append(f"> Actualizado: {plan['actualizado']} · Fuente: {plan['fuente']}")
    lineas.append("")
    lineas.append(plan["objetivo"])
    lineas.append("")

    lineas.append("## Herramientas y accesos")
    lineas.append("")
    for herramienta in plan["herramientas"]:
        lineas.append(f"### {herramienta['nombre']}")
        lineas.append("")
        lineas.append(f"- **Fortaleza:** {herramienta['fortaleza']}")
        lineas.append(f"- **Acceso:** {herramienta['acceso']}")
        lineas.append("")

    tareas = ordenar_tareas(plan["tareas"])
    lineas.append("## Resumen del reparto")
    lineas.append("")
    lineas.append("| Clave | Prioridad | Creada | Tarea | Responsable |")
    lineas.append("| --- | --- | --- | --- | --- |")
    for tarea in tareas:
        lineas.append(
            "| {clave} | {prioridad} | {creada} | {titulo} | {responsable} |".format(
                clave=tarea["clave"],
                prioridad=tarea["prioridad"],
                creada=tarea["creada"],
                titulo=celda(tarea["titulo"]),
                responsable=nombre_herramienta(plan, tarea["responsable"]),
            )
        )
    lineas.append("")

    lineas.append("## Briefs por herramienta")
    lineas.append("")
    lineas.append("Copiar el brief de cada tarea en la herramienta correspondiente.")
    lineas.append("")
    for herramienta in plan["herramientas"]:
        propias = [t for t in tareas if t["responsable"] == herramienta["id"]]
        lineas.append(f"### {herramienta['nombre']}")
        lineas.append("")
        if not propias:
            lineas.append("(Sin tareas asignadas por ahora.)")
            lineas.append("")
            continue
        for tarea in propias:
            lineas.append(f"#### {tarea['clave']} — {tarea['titulo']}")
            lineas.append("")
            lineas.append(tarea["brief"])
            lineas.append("")

    lineas.append("## Tareas no delegadas ahora")
    lineas.append("")
    lineas.append("| Clave | Estado | Motivo |")
    lineas.append("| --- | --- | --- |")
    for tarea in plan["no_delegadas"]:
        lineas.append(
            "| {clave} | {estado} | {motivo} |".format(
                clave=tarea["clave"],
                estado=celda(tarea["estado"]),
                motivo=celda(tarea["motivo"]),
            )
        )
    lineas.append("")

    lineas.append("## Flujo de trabajo")
    lineas.append("")
    for regla in plan["flujo"]:
        lineas.append(f"- {regla}")
    lineas.append("")

    lineas.append("## Cómo mantener este plan")
    lineas.append("")
    lineas.append("1. Editar `docs/kan81-delegacion.json` (tareas, responsables o briefs).")
    lineas.append("2. Regenerar el Markdown: `python scripts/kan81_generar_plan.py`.")
    lineas.append(
        "3. Ejecutar `python -m pytest tests/test_kan81_delegacion.py` para validar "
        "que el plan sigue completo y que el Markdown coincide."
    )
    lineas.append("")

    return "\n".join(lineas)


def main() -> int:
    plan = cargar_plan()
    SALIDA_PATH.write_text(generar_markdown(plan), encoding="utf-8")
    print(f"Plan generado: {SALIDA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

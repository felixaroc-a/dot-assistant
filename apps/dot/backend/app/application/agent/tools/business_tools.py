"""Business tools para el Agent Runtime — Finanzas, Investigacion, Contenido.

15 handlers: finance (6), research (4), content (5).
Cada handler usa ToolResult y routea via route_chat o bridge local segun corresponda.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.business")


# ═══════════════════════════════════════════════════════════════════
# FINANCE — 6 handlers
# ═══════════════════════════════════════════════════════════════════


def finance_parse_invoice(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae datos estructurados de una factura (PDF/imagen).

    Lee el archivo via bridge, lo parsea con read_document/parseDocument,
    y envia el texto a route_chat para extraer campos clave en JSON.

    Args:
        arguments:
            path (str): ruta absoluta al PDF o imagen de la factura
    """
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        from app.services.provider_router import route_chat

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="finance_parse_invoice requiere path del archivo.")

        ext = Path(path).suffix.lower()
        supported = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif"}
        if ext not in supported:
            return ToolResult(
                ok=False, output="",
                error=f"Formato no soportado: {ext}. Usa PDF, PNG, JPG, WEBP o TIFF.",
            )

        # Leer el documento via bridge (parseDocument maneja PDF e imagenes)
        raw = execute_local_tool_via_bridge("parseDocument", path=path)
        content_text = ""

        if raw.get("ok"):
            content_text = str(raw.get("text", raw.get("content", "")))
        else:
            # Fallback: intentar readFile para archivos de texto
            raw2 = execute_local_tool_via_bridge("readFile", path=path)
            if raw2.get("ok"):
                content_text = str(raw2.get("content", ""))

        if not content_text.strip():
            return ToolResult(
                ok=False, output="",
                error="No se pudo extraer texto de la factura. Verifica que el archivo sea legible.",
            )

        # Limitar a 8000 caracteres para no saturar la IA
        body = content_text[:8000]

        prompt = (
            "Extrae de esta factura los siguientes campos en JSON valido (solo el JSON, sin markdown):\n"
            '{\n'
            '  "monto_total": float,\n'
            '  "fecha": "YYYY-MM-DD",\n'
            '  "proveedor": "nombre del emisor",\n'
            '  "iva": float (monto del IVA o 0 si no aplica),\n'
            '  "concepto": "descripcion breve de lo facturado",\n'
            '  "moneda": "codigo ISO de 3 letras (USD/VES/EUR/etc.)",\n'
            '  "numero_factura": "numero o codigo de la factura si aparece"\n'
            '}\n\n'
            f"Texto de la factura:\n{body}"
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un contador experto en extraccion de datos de facturas. Responde SOLO con JSON valido, sin explicaciones ni markdown.",
            include_document_action_prompt=False,
        )

        # Intentar parsear el JSON resultante
        try:
            parsed = json.loads(result.strip().removeprefix("```json").removesuffix("```").strip())
            return ToolResult(
                ok=True,
                output=json.dumps(parsed, indent=2, ensure_ascii=False),
                artifacts=[{"type": "invoice_parsed", "path": path, "data": parsed}],
            )
        except json.JSONDecodeError:
            # Si la IA no devuelve JSON puro, devolvemos el texto como esta
            return ToolResult(
                ok=True,
                output=result.strip(),
                artifacts=[{"type": "invoice_parsed", "path": path, "raw_text": result.strip()[:3000]}],
            )

    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"Dependencia faltante: {e}")
    except Exception as e:
        log.exception("finance_parse_invoice error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al procesar factura: {e}")


def finance_categorize_expense(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Categoriza un gasto en una de 8 categorias predefinidas usando IA.

    Args:
        arguments:
            text (str): descripcion del gasto a categorizar
    """
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="finance_categorize_expense requiere text del gasto.")

        prompt = (
            "Categoriza este gasto en UNA SOLA de estas categorias:\n"
            "alquiler, nomina, insumos, servicios, marketing, impuestos, viajes, otros\n\n"
            f"Texto del gasto: {text}\n\n"
            "Responde SOLO con la categoria (1 palabra), sin explicaciones ni puntuacion."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un clasificador de gastos empresariales. Responde solo con la categoria exacta.",
            include_document_action_prompt=False,
        )

        category = result.strip().lower().rstrip(".,;:!?")
        valid = {"alquiler", "nomina", "insumos", "servicios", "marketing", "impuestos", "viajes", "otros"}
        if category not in valid:
            # Si la IA responde algo no esperado, intentar mapearlo
            for v in valid:
                if v in category:
                    category = v
                    break
            else:
                category = "otros"

        return ToolResult(ok=True, output=category)

    except Exception as e:
        log.exception("finance_categorize_expense error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al categorizar gasto: {e}")


def finance_monthly_report(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un reporte mensual de gastos desde un CSV.

    Lee el CSV, calcula totales por categoria, y usa IA para generar
    un resumen ejecutivo con recomendaciones.

    Args:
        arguments:
            path (str): ruta al archivo CSV de gastos
            month (str, opcional): mes a reportar (ej: "2026-07")
    """
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        from app.services.provider_router import route_chat

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="finance_monthly_report requiere path del CSV.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error al leer CSV: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines()))
        if not rows:
            return ToolResult(ok=True, output="El archivo CSV esta vacio o no tiene datos validos.")

        month_filter = str(arguments.get("month") or "").strip()

        # Calcular totales por categoria
        totals: dict[str, float] = {}
        row_count = 0
        skipped = 0

        for r in rows:
            # Si hay filtro de mes, intentar matchear columna fecha
            if month_filter:
                fecha = str(r.get("fecha", r.get("date", r.get("Fecha", "")))).strip()
                if fecha and not fecha.startswith(month_filter):
                    skipped += 1
                    continue

            cat = str(r.get("categoria", r.get("category", r.get("Categoria", "otros")))).strip().lower() or "otros"
            # Mapear a categorias validas
            valid_cats = {"alquiler", "nomina", "insumos", "servicios", "marketing", "impuestos", "viajes", "otros"}
            if cat not in valid_cats:
                cat = "otros"

            monto_str = str(r.get("monto", r.get("amount", r.get("Monto", r.get("total", "0"))))).strip()
            try:
                monto = float(monto_str.replace(",", "."))
            except (ValueError, TypeError):
                monto = 0.0

            totals[cat] = totals.get(cat, 0.0) + monto
            row_count += 1

        if not totals:
            return ToolResult(ok=True, output="No se encontraron gastos para el periodo especificado.")

        total_general = sum(totals.values())

        # Construir resumen para la IA
        cat_lines = [f"  - {cat}: ${monto:,.2f}" for cat, monto in sorted(totals.items(), key=lambda x: x[1], reverse=True)]
        cat_text = "\n".join(cat_lines)

        prompt = (
            f"Genera un resumen ejecutivo de gastos mensuales basado en estos datos:\n\n"
            f"Total general: ${total_general:,.2f}\n"
            f"Gastos por categoria:\n{cat_text}\n"
            f"Total de transacciones procesadas: {row_count}\n\n"
            f"Instrucciones:\n"
            f"1. Identifica la categoria de mayor gasto\n"
            f"2. Senala si hay categorias que exceden el 40% del total\n"
            f"3. Da 2-3 recomendaciones concretas de optimizacion\n"
            f"4. Responde en espanol, tono ejecutivo, maximo 250 palabras"
        )

        summary = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un analista financiero senior. Responde en espanol con datos concretos y recomendaciones accionables.",
            include_document_action_prompt=False,
        )

        lines = [
            f"REPORTE MENSUAL DE GASTOS",
            f"{'=' * 40}",
            f"Periodo: {month_filter or 'Todos los datos'}",
            f"Transacciones: {row_count}",
            f"Total: ${total_general:,.2f}",
            f"",
            f"DISTRIBUCION POR CATEGORIA:",
        ]
        for cat, monto in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            pct = (monto / total_general * 100) if total_general > 0 else 0
            bar = "█" * int(pct / 2)
            lines.append(f"  {cat:<14} ${monto:>10,.2f}  ({pct:5.1f}%) {bar}")
        lines.append("")
        lines.append("RESUMEN EJECUTIVO IA:")
        lines.append(summary.strip())

        return ToolResult(
            ok=True,
            output="\n".join(lines),
            artifacts=[{"type": "monthly_report", "totals": totals, "row_count": row_count, "skipped": skipped}],
        )

    except Exception as e:
        log.exception("finance_monthly_report error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al generar reporte mensual: {e}")


def finance_budget_alert(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica si una categoria de gastos excede su presupuesto.

    Lee un CSV de gastos, filtra por categoria, suma totales, y compara
    contra budget_limit. Retorna alerta si se excede.

    Args:
        arguments:
            path (str): ruta al CSV de gastos
            budget_limit (float): limite de presupuesto
            category (str): categoria a verificar
    """
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="finance_budget_alert requiere path del CSV.")

        budget_limit_str = str(arguments.get("budget_limit") or arguments.get("limit") or "").strip()
        if not budget_limit_str:
            return ToolResult(ok=False, output="", error="finance_budget_alert requiere budget_limit (numero).")

        try:
            budget_limit = float(budget_limit_str.replace(",", "."))
        except (ValueError, TypeError):
            return ToolResult(ok=False, output="", error=f"budget_limit invalido: {budget_limit_str}")

        category = str(arguments.get("category") or "").strip().lower()
        if not category:
            return ToolResult(ok=False, output="", error="finance_budget_alert requiere category.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error al leer CSV: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines()))
        if not rows:
            return ToolResult(ok=True, output="El archivo CSV esta vacio.")

        total = 0.0
        count = 0
        for r in rows:
            cat_col = str(r.get("categoria", r.get("category", r.get("Categoria", "")))).strip().lower()
            if cat_col == category or category in cat_col:
                monto_str = str(r.get("monto", r.get("amount", r.get("Monto", r.get("total", "0"))))).strip()
                try:
                    monto = float(monto_str.replace(",", "."))
                except (ValueError, TypeError):
                    monto = 0.0
                total += monto
                count += 1

        pct = (total / budget_limit * 100) if budget_limit > 0 else 0
        excedido = total > budget_limit

        if excedido:
            output = (
                f"ALERTA DE PRESUPUESTO EXCEDIDO\n"
                f"{'=' * 40}\n"
                f"Categoria: {category}\n"
                f"Gastado: ${total:,.2f}\n"
                f"Limite: ${budget_limit:,.2f}\n"
                f"Excedente: ${total - budget_limit:,.2f} ({pct - 100:.1f}% sobre el limite)\n"
                f"Transacciones: {count}\n"
            )
        else:
            restante = budget_limit - total
            output = (
                f"Presupuesto bajo control\n"
                f"{'=' * 40}\n"
                f"Categoria: {category}\n"
                f"Gastado: ${total:,.2f}\n"
                f"Limite: ${budget_limit:,.2f}\n"
                f"Restante: ${restante:,.2f} ({100 - pct:.1f}% disponible)\n"
                f"Transacciones: {count}\n"
            )

        return ToolResult(
            ok=True,
            output=output,
            artifacts=[{
                "type": "budget_alert",
                "category": category,
                "spent": total,
                "limit": budget_limit,
                "exceeded": excedido,
                "percentage": round(pct, 1),
            }],
        )

    except Exception as e:
        log.exception("finance_budget_alert error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al verificar presupuesto: {e}")


def finance_generate_invoice(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera una factura en DOCX o como texto estructurado.

    Usa generate_document si esta disponible; si no, route_chat genera
    texto formateado de factura. Si se pide writeFile, guarda resultado.

    Args:
        arguments:
            cliente (dict): datos del cliente {nombre, rif/cedula, direccion, telefono}
            items (list[dict]): lineas de la factura [{descripcion, cantidad, precio_unitario}]
            numero (str, opcional): numero de factura
            fecha (str, opcional): fecha (default: hoy)
            iva_rate (float, opcional): tasa de IVA (default 16.0)
    """
    try:
        from app.services.provider_router import route_chat

        cliente = arguments.get("cliente")
        if not cliente or not isinstance(cliente, dict):
            return ToolResult(ok=False, output="", error="finance_generate_invoice requiere cliente (dict con nombre, rif, direccion).")

        items = arguments.get("items")
        if not items or not isinstance(items, list) or not items:
            return ToolResult(ok=False, output="", error="finance_generate_invoice requiere items (lista de dicts con descripcion, cantidad, precio_unitario).")

        numero = str(arguments.get("numero") or arguments.get("number") or "").strip()
        fecha_str = str(arguments.get("fecha") or arguments.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
        iva_rate = float(arguments.get("iva_rate") or arguments.get("iva") or 16.0)

        nombre_cliente = str(cliente.get("nombre", cliente.get("name", "Cliente"))).strip()
        rif = str(cliente.get("rif", cliente.get("cedula", cliente.get("tax_id", "")))).strip()
        direccion = str(cliente.get("direccion", cliente.get("address", ""))).strip()
        telefono = str(cliente.get("telefono", cliente.get("phone", ""))).strip()

        # Calcular subtotales
        items_data: list[dict] = []
        subtotal = 0.0
        for item in items:
            if not isinstance(item, dict):
                continue
            desc = str(item.get("descripcion", item.get("description", "Item"))).strip()
            try:
                cant = float(str(item.get("cantidad", item.get("quantity", 1))).replace(",", "."))
            except (ValueError, TypeError):
                cant = 1.0
            try:
                pu = float(str(item.get("precio_unitario", item.get("price", item.get("unit_price", 0))).replace(",", ".")))
            except (ValueError, TypeError):
                pu = 0.0
            total_linea = cant * pu
            subtotal += total_linea
            items_data.append({
                "descripcion": desc,
                "cantidad": cant,
                "precio_unitario": pu,
                "total": total_linea,
            })

        iva = subtotal * (iva_rate / 100.0)
        total_factura = subtotal + iva

        # Intentar generar DOCX via generate_document
        doc_generated = False
        docx_path = ""
        docx_filename = ""
        try:
            from app.services.document_image_service import create_docx_with_images

            # Construir contenido markdown para el DOCX
            lines_md = [
                f"# FACTURA",
                f"",
                f"**N°:** {numero or 'S/N'}",
                f"**Fecha:** {fecha_str}",
                f"",
                f"## Datos del Cliente",
                f"- **Nombre:** {nombre_cliente}",
            ]
            if rif:
                lines_md.append(f"- **RIF/Cedula:** {rif}")
            if direccion:
                lines_md.append(f"- **Direccion:** {direccion}")
            if telefono:
                lines_md.append(f"- **Telefono:** {telefono}")

            lines_md.append("")
            lines_md.append("## Detalle")
            lines_md.append("")
            lines_md.append("| Descripcion | Cantidad | Precio Unit. | Total |")
            lines_md.append("|------------|----------|-------------|-------|")
            for it in items_data:
                lines_md.append(f"| {it['descripcion']} | {it['cantidad']} | ${it['precio_unitario']:,.2f} | ${it['total']:,.2f} |")

            lines_md.append("")
            lines_md.append(f"**Subtotal:** ${subtotal:,.2f}")
            lines_md.append(f"**IVA ({iva_rate:.0f}%):** ${iva:,.2f}")
            lines_md.append(f"**TOTAL:** ${total_factura:,.2f}")

            safe_title = f"Factura_{nombre_cliente.replace(' ', '_')}_{numero or 'SN'}".replace("/", "_")[:200]
            result = create_docx_with_images(
                title=safe_title,
                content="\n".join(lines_md),
                image_paths=None,
                folder=None,
            )

            if result.get("ok"):
                docx_path = str(result.get("path", ""))
                docx_filename = str(result.get("filename", ""))
                doc_generated = True
        except ImportError:
            log.debug("document_image_service no disponible, generando factura como texto.")
        except Exception as exc:
            log.warning("Error al generar DOCX de factura: %s", exc)

        if doc_generated:
            output = (
                f"Factura generada como documento DOCX:\n"
                f"  Archivo: {docx_filename}\n"
                f"  Ruta: {docx_path}\n"
                f"  Cliente: {nombre_cliente}\n"
                f"  Subtotal: ${subtotal:,.2f}\n"
                f"  IVA ({iva_rate:.0f}%): ${iva:,.2f}\n"
                f"  TOTAL: ${total_factura:,.2f}"
            )
            return ToolResult(
                ok=True,
                output=output,
                artifacts=[{
                    "type": "invoice_generated",
                    "format": "docx",
                    "path": docx_path,
                    "cliente": nombre_cliente,
                    "total": total_factura,
                }],
            )

        # Fallback: generar factura como texto via IA y guardar si se pide
        prompt = (
            f"Genera una factura formateada con estos datos:\n\n"
            f"Datos del emisor: DOT Asistente IA\n"
            f"Cliente: {nombre_cliente}\n"
            f"{'RIF: ' + rif if rif else ''}\n"
            f"{'Direccion: ' + direccion if direccion else ''}\n"
            f"{'Telefono: ' + telefono if telefono else ''}\n"
            f"Fecha: {fecha_str}\n"
            f"Numero: {numero or 'S/N'}\n\n"
            f"Items:\n"
        )
        for it in items_data:
            prompt += f"  - {it['descripcion']}: {it['cantidad']} x ${it['precio_unitario']:,.2f} = ${it['total']:,.2f}\n"
        prompt += (
            f"\nSubtotal: ${subtotal:,.2f}\n"
            f"IVA ({iva_rate:.0f}%): ${iva:,.2f}\n"
            f"TOTAL: ${total_factura:,.2f}\n\n"
            f"Formatea como factura profesional en texto plano. "
            f"Incluye encabezado, cuerpo y pie con totales."
        )

        factura_texto = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un facturador profesional. Genera facturas claras y bien formateadas en texto plano.",
            include_document_action_prompt=False,
        )

        # Si el usuario pidio guardar, escribir archivo
        file_path = str(arguments.get("save_path") or arguments.get("output") or "").strip()
        if file_path:
            from app.application.agent.tools.local_files import execute_local_tool_via_bridge
            write_res = execute_local_tool_via_bridge("writeFile", path=file_path, content=factura_texto.strip())
            if write_res.get("ok"):
                return ToolResult(
                    ok=True,
                    output=f"Factura guardada en {file_path}.\nTOTAL: ${total_factura:,.2f}",
                    artifacts=[{"type": "invoice_generated", "format": "txt", "path": file_path, "total": total_factura}],
                )

        return ToolResult(
            ok=True,
            output=factura_texto.strip(),
            artifacts=[{"type": "invoice_generated", "format": "text", "total": total_factura}],
        )

    except Exception as e:
        log.exception("finance_generate_invoice error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al generar factura: {e}")


def finance_calc_vat(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Calcula IVA y total a partir de un monto base.

    Args:
        arguments:
            amount (float): monto base
            rate (float, opcional): tasa de IVA en porcentaje (default 16.0)
    """
    try:
        amount_str = str(arguments.get("amount") or "").strip()
        if not amount_str:
            return ToolResult(ok=False, output="", error="finance_calc_vat requiere amount (monto base).")

        try:
            amount = float(amount_str.replace(",", "."))
        except (ValueError, TypeError):
            return ToolResult(ok=False, output="", error=f"Monto invalido: {amount_str}")

        rate = float(arguments.get("rate") or 16.0)
        if rate < 0 or rate > 100:
            return ToolResult(ok=False, output="", error=f"Tasa de IVA fuera de rango: {rate}%. Debe estar entre 0 y 100.")

        iva = amount * (rate / 100.0)
        total = amount + iva

        output = (
            f"CALCULO DE IVA\n"
            f"{'=' * 30}\n"
            f"Monto base: ${amount:,.2f}\n"
            f"Tasa IVA:   {rate}%\n"
            f"IVA:        ${iva:,.2f}\n"
            f"{'-' * 30}\n"
            f"TOTAL:      ${total:,.2f}\n"
        )

        return ToolResult(
            ok=True,
            output=output,
            artifacts=[{"type": "vat_calc", "amount": amount, "rate": rate, "iva": round(iva, 2), "total": round(total, 2)}],
        )

    except Exception as e:
        log.exception("finance_calc_vat error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al calcular IVA: {e}")


# ═══════════════════════════════════════════════════════════════════
# RESEARCH — 4 handlers
# ═══════════════════════════════════════════════════════════════════


def research_topic_deep(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Investigacion profunda sobre un tema usando IA.

    Genera un analisis estructurado con contexto, datos clave,
    tendencias, actores principales y conclusiones.

    Args:
        arguments:
            topic (str): tema a investigar
            depth (str, opcional): "breve", "normal" o "profundo" (default: "normal")
    """
    try:
        from app.services.provider_router import route_chat

        topic = str(arguments.get("topic") or "").strip()
        if not topic:
            return ToolResult(ok=False, output="", error="research_topic_deep requiere topic.")

        depth = str(arguments.get("depth") or "normal").strip().lower()
        depth_config = {
            "breve": ("maximo 300 palabras", "breve"),
            "normal": ("maximo 600 palabras", "detallado"),
            "profundo": ("maximo 1200 palabras", "exhaustivo"),
        }
        word_limit, detail_level = depth_config.get(depth, depth_config["normal"])

        prompt = (
            f"Realiza una investigacion {detail_level} sobre el siguiente tema. "
            f"Responde en espanol con estructura clara ({word_limit}):\n\n"
            f"TEMA: {topic}\n\n"
            f"Estructura requerida:\n"
            f"1. CONTEXTO Y ANTECEDENTES — origen y situacion actual\n"
            f"2. DATOS CLAVE — cifras, estadisticas, hechos relevantes\n"
            f"3. TENDENCIAS — hacia donde va el tema\n"
            f"4. ACTORES PRINCIPALES — personas, empresas, paises involucrados\n"
            f"5. IMPLICACIONES — impacto economico, social, tecnologico\n"
            f"6. CONCLUSIONES Y RECOMENDACIONES\n\n"
            f"Se objetivo, cita fuentes cuando sea posible, y destaca lo mas importante."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un investigador senior. Responde en espanol con analisis profundo, datos verificables y estructura clara.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "research_topic", "topic": topic, "depth": depth}],
        )

    except Exception as e:
        log.exception("research_topic_deep error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en investigacion: {e}")


def research_fact_check(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica una afirmacion contra conocimiento y fuentes disponibles.

    Args:
        arguments:
            statement (str): afirmacion a verificar
    """
    try:
        from app.services.provider_router import route_chat

        statement = str(arguments.get("statement") or arguments.get("claim") or "").strip()
        if not statement:
            return ToolResult(ok=False, output="", error="research_fact_check requiere statement (afirmacion a verificar).")

        prompt = (
            f"Verifica la siguiente afirmacion. Analizala criticamente y determina si es:\n"
            f"- VERDADERO (respaldada por hechos/evidencia)\n"
            f"- FALSO (contradicha por hechos/evidencia)\n"
            f"- NO VERIFICABLE (no hay suficiente informacion para determinarlo)\n\n"
            f"AFIRMACION: {statement}\n\n"
            f"Formato de respuesta REQUERIDO:\n"
            f"VEREDICTO: [VERDADERO/FALSO/NO_VERIFICABLE]\n"
            f"EXPLICACION: [2-4 oraciones explicando el razonamiento]\n"
            f"FUENTE: [fuente o razonamiento que respalda tu veredicto]"
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un verificador de datos riguroso. Responde con veredicto claro, explicacion y fuente. Se esceptico y objetivo.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "fact_check", "statement": statement[:300]}],
        )

    except Exception as e:
        log.exception("research_fact_check error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al verificar afirmacion: {e}")


def research_competitor(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un perfil detallado de un competidor.

    Args:
        arguments:
            name (str): nombre de la empresa competidora
            industry (str, opcional): industria o sector para contexto
    """
    try:
        from app.services.provider_router import route_chat

        name = str(arguments.get("name") or arguments.get("competitor") or "").strip()
        if not name:
            return ToolResult(ok=False, output="", error="research_competitor requiere name del competidor.")

        industry = str(arguments.get("industry") or arguments.get("sector") or "").strip()

        prompt = (
            f"Genera un perfil competitivo detallado de la empresa '{name}'"
            + (f" en la industria {industry}" if industry else "")
            + ".\n\n"
            f"Estructura requerida:\n"
            f"1. DESCRIPCION GENERAL — que hace, tamano, presencia geografica\n"
            f"2. PRODUCTOS Y SERVICIOS — oferta principal\n"
            f"3. FORTALEZAS — ventajas competitivas\n"
            f"4. DEBILIDADES — puntos debiles conocidos\n"
            f"5. ESTRATEGIA — modelo de negocio, diferenciacion\n"
            f"6. CLIENTES OBJETIVO — a quien venden\n"
            f"7. PRECIOS APROXIMADOS — rango si se conoce\n"
            f"8. PRESENCIA DIGITAL — web, redes sociales, reputacion online\n\n"
            f"Responde en espanol, maximo 800 palabras. Se objetivo y factual."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un analista de inteligencia competitiva. Generas perfiles detallados, objetivos y accionables de empresas competidoras.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "competitor_profile", "name": name, "industry": industry}],
        )

    except Exception as e:
        log.exception("research_competitor error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al investigar competidor: {e}")


def research_company_profile(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un perfil detallado de una empresa.

    Args:
        arguments:
            name (str): nombre de la empresa
            country (str, opcional): pais de origen/operacion
    """
    try:
        from app.services.provider_router import route_chat

        name = str(arguments.get("name") or arguments.get("company") or "").strip()
        if not name:
            return ToolResult(ok=False, output="", error="research_company_profile requiere name de la empresa.")

        country = str(arguments.get("country") or "").strip()

        prompt = (
            f"Genera un perfil corporativo completo de '{name}'"
            + (f" (pais: {country})" if country else "")
            + ".\n\n"
            f"Estructura requerida:\n"
            f"1. DATOS BASICOS — nombre legal, fundacion, sede, CEO, empleados\n"
            f"2. SECTOR E INDUSTRIA — clasificacion y posicion en el mercado\n"
            f"3. PRODUCTOS Y SERVICIOS — catalogo principal\n"
            f"4. INGRESOS Y TAMANO — facturacion aproximada, capitalizacion si aplica\n"
            f"5. PRESENCIA GEOGRAFICA — paises donde opera\n"
            f"6. COMPETIDORES PRINCIPALES — competencia directa\n"
            f"7. HITOS RECIENTES — noticias, adquisiciones, lanzamientos recientes\n"
            f"8. REPUTACION Y CONTROVERSIAS — si las hay\n\n"
            f"Responde en espanol, maximo 600 palabras. Se factual y objetivo."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un analista de inteligencia de negocios. Generas perfiles corporativos precisos, objetivos y bien estructurados.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "company_profile", "name": name, "country": country}],
        )

    except Exception as e:
        log.exception("research_company_profile error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al investigar empresa: {e}")


# ═══════════════════════════════════════════════════════════════════
# CONTENT — 5 handlers
# ═══════════════════════════════════════════════════════════════════


def content_write_draft(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Redacta un borrador de email, carta, propuesta u otro tipo de documento.

    Args:
        arguments:
            type (str): tipo de documento — "email", "carta", "propuesta", "informe", "memo"
            data (dict): datos para personalizar el documento
                Para email: {to, subject, context, tone}
                Para carta: {destinatario, asunto, cuerpo}
                Para propuesta: {cliente, proyecto, alcance, presupuesto}
                Para informe: {titulo, hallazgos, conclusiones}
    """
    try:
        from app.services.provider_router import route_chat

        doc_type = str(arguments.get("type") or arguments.get("tipo") or "").strip().lower()
        valid_types = {"email", "carta", "propuesta", "informe", "memo"}
        if doc_type not in valid_types:
            return ToolResult(
                ok=False, output="",
                error=f"Tipo de documento no soportado: {doc_type}. Usa: {', '.join(sorted(valid_types))}.",
            )

        data = arguments.get("data") or arguments.get("datos") or {}
        if not isinstance(data, dict):
            return ToolResult(ok=False, output="", error="content_write_draft requiere data como dict con los datos del documento.")

        # Construir prompt segun tipo
        if doc_type == "email":
            to = str(data.get("to", data.get("destinatario", ""))).strip()
            subject = str(data.get("subject", data.get("asunto", ""))).strip()
            context = str(data.get("context", data.get("contexto", ""))).strip()
            tone = str(data.get("tone", data.get("tono", "profesional"))).strip()
            if not context:
                return ToolResult(ok=False, output="", error="Para email se requiere data.context con el contenido/contexto.")

            prompt = (
                f"Redacta un correo electronico con las siguientes caracteristicas:\n\n"
                f"Para: {to or '[destinatario]'}\n"
                f"Asunto: {subject or '[generar asunto apropiado]'}\n"
                f"Tono: {tone}\n"
                f"Contexto: {context}\n\n"
                f"El correo debe incluir saludo, cuerpo (2-3 parrafos) y despedida. Responde solo con el correo completo."
            )

        elif doc_type == "carta":
            destinatario = str(data.get("destinatario", data.get("to", ""))).strip()
            asunto = str(data.get("asunto", data.get("subject", ""))).strip()
            cuerpo = str(data.get("cuerpo", data.get("body", data.get("contexto", "")))).strip()
            if not cuerpo:
                return ToolResult(ok=False, output="", error="Para carta se requiere data.cuerpo con el contenido.")

            prompt = (
                f"Redacta una carta formal:\n\n"
                f"Destinatario: {destinatario or '[nombre]'}\n"
                f"Asunto: {asunto or '[asunto]'}\n"
                f"Contenido a desarrollar: {cuerpo}\n\n"
                f"Incluye lugar, fecha, saludo formal, cuerpo (2-3 parrafos), despedida y firma. Responde solo con la carta completa."
            )

        elif doc_type == "propuesta":
            cliente = str(data.get("cliente", data.get("client", ""))).strip()
            proyecto = str(data.get("proyecto", data.get("project", ""))).strip()
            alcance = str(data.get("alcance", data.get("scope", ""))).strip()
            presupuesto = str(data.get("presupuesto", data.get("budget", ""))).strip()
            if not proyecto:
                return ToolResult(ok=False, output="", error="Para propuesta se requiere data.proyecto con el nombre del proyecto.")

            prompt = (
                f"Redacta una propuesta comercial/profesional:\n\n"
                f"Cliente: {cliente or '[cliente]'}\n"
                f"Proyecto: {proyecto}\n"
                f"Alcance: {alcance or '[describir alcance]'}\n"
                f"Presupuesto: {presupuesto or '[indicar presupuesto]'}\n\n"
                f"Estructura: 1) Introduccion y contexto, 2) Objetivos, 3) Alcance detallado, "
                f"4) Metodologia, 5) Cronograma, 6) Presupuesto, 7) Terminos y condiciones.\n"
                f"Responde solo con la propuesta completa en espanol."
            )

        elif doc_type == "informe":
            titulo = str(data.get("titulo", data.get("title", ""))).strip()
            hallazgos = str(data.get("hallazgos", data.get("findings", ""))).strip()
            conclusiones = str(data.get("conclusiones", data.get("conclusions", ""))).strip()
            if not titulo:
                return ToolResult(ok=False, output="", error="Para informe se requiere data.titulo.")

            prompt = (
                f"Redacta un informe profesional:\n\n"
                f"Titulo: {titulo}\n"
                f"Hallazgos: {hallazgos or '[por desarrollar]'}\n"
                f"Conclusiones: {conclusiones or '[por desarrollar]'}\n\n"
                f"Estructura: 1) Resumen ejecutivo, 2) Introduccion, 3) Metodologia, "
                f"4) Hallazgos principales, 5) Analisis, 6) Conclusiones, 7) Recomendaciones.\n"
                f"Responde solo con el informe completo en espanol."
            )

        else:  # memo
            to = str(data.get("to", data.get("para", ""))).strip()
            from_ = str(data.get("from", data.get("de", ""))).strip()
            subject = str(data.get("subject", data.get("asunto", ""))).strip()
            body = str(data.get("body", data.get("cuerpo", data.get("mensaje", ""))).strip())
            if not body:
                return ToolResult(ok=False, output="", error="Para memo se requiere data.body con el mensaje.")

            prompt = (
                f"Redacta un memorandum interno:\n\n"
                f"Para: {to or '[destinatario]'}\n"
                f"De: {from_ or '[remitente]'}\n"
                f"Asunto: {subject or '[asunto]'}\n"
                f"Mensaje: {body}\n\n"
                f"Formato de memorandum tradicional con encabezado y cuerpo en espanol. Responde solo con el memo completo."
            )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt=f"Eres un redactor profesional experto en {doc_type}. Redactas documentos claros, bien estructurados y en espanol correcto.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "draft", "doc_type": doc_type, "length": len(result)}],
        )

    except Exception as e:
        log.exception("content_write_draft error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al redactar borrador: {e}")


def content_improve(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Mejora claridad, tono y gramatica de un texto manteniendo el mensaje original.

    Args:
        arguments:
            text (str): texto a mejorar
            aspect (str, opcional): aspecto a enfocar — "claridad", "tono", "gramatica", "todo" (default: "todo")
    """
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="content_improve requiere text.")

        aspect = str(arguments.get("aspect") or "todo").strip().lower()
        aspect_map = {
            "claridad": "claridad y legibilidad",
            "tono": "tono profesional y adecuado",
            "gramatica": "gramatica, ortografia y puntuacion",
            "concision": "concision y eliminacion de redundancias",
            "todo": "claridad, tono, gramatica y concision",
        }
        focus = aspect_map.get(aspect, aspect_map["todo"])

        prompt = (
            f"Mejora este texto enfocandote en {focus}. "
            f"Manten el mensaje y la intencion original, pero mejora la redaccion:\n\n"
            f"{text[:6000]}\n\n"
            f"Devuelve SOLO el texto mejorado, sin explicaciones ni comentarios adicionales."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un editor profesional. Mejoras textos manteniendo el mensaje original. Responde solo con el texto mejorado.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "text_improved", "aspect": aspect, "original_length": len(text), "improved_length": len(result)}],
        )

    except Exception as e:
        log.exception("content_improve error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al mejorar texto: {e}")


def content_summarize_long(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Resume un texto largo a N palabras.

    Args:
        arguments:
            text (str): texto a resumir
            words (int, opcional): numero maximo de palabras (default 100)
            style (str, opcional): "breve", "ejecutivo", "academico" (default: "breve")
    """
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="content_summarize_long requiere text.")

        words = int(arguments.get("words") or arguments.get("max_words") or 100)
        if words < 20:
            words = 20
        if words > 2000:
            words = 2000

        style = str(arguments.get("style") or "breve").strip().lower()
        style_config = {
            "breve": "Resume en forma de parrafo directo",
            "ejecutivo": "Resume en formato ejecutivo con bullets de ideas clave",
            "academico": "Resume preservando el rigor y la estructura academica",
            "puntos": "Resume como lista de puntos clave numerados",
        }
        style_instruction = style_config.get(style, style_config["breve"])

        prompt = (
            f"{style_instruction} el siguiente texto en MAXIMO {words} palabras. "
            f"No excedas el limite de palabras bajo ninguna circunstancia:\n\n"
            f"{text[:10000]}\n\n"
            f"Responde solo con el resumen, sin introducciones ni comentarios."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un sintetizador experto. Resumes textos largos en resumenes precisos que capturan lo esencial.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "summary", "style": style, "target_words": words, "original_length": len(text)}],
        )

    except Exception as e:
        log.exception("content_summarize_long error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al resumir texto: {e}")


def content_rewrite_tone(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Reescribe un texto en un tono diferente.

    Args:
        arguments:
            text (str): texto a reescribir
            tone (str): tono deseado — "formal", "casual", "persuasivo", "empatico", "tecnico", "amigable"
    """
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="content_rewrite_tone requiere text.")

        tone = str(arguments.get("tone") or arguments.get("tono") or "formal").strip().lower()
        valid_tones = {
            "formal": "formal y profesional",
            "casual": "casual y coloquial",
            "persuasivo": "persuasivo y convincente",
            "empatico": "empatico y comprensivo",
            "tecnico": "tecnico y preciso",
            "amigable": "amigable y cercano",
            "urgente": "urgente e imperativo",
            "inspirador": "inspirador y motivacional",
        }
        tone_desc = valid_tones.get(tone, tone)

        prompt = (
            f"Reescribe el siguiente texto en un tono {tone_desc}. "
            f"Conserva el mensaje y las ideas principales, pero adapta el lenguaje, "
            f"vocabulario y estilo al tono solicitado:\n\n"
            f"{text[:6000]}\n\n"
            f"Responde SOLO con el texto reescrito, sin explicaciones ni comentarios."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt=f"Eres un redactor experto en adaptacion de tono. Reescribes textos manteniendo el mensaje pero ajustando el tono a {tone_desc}.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{"type": "text_rewritten", "tone": tone, "original_length": len(text), "rewritten_length": len(result)}],
        )

    except Exception as e:
        log.exception("content_rewrite_tone error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al reescribir texto: {e}")


def content_social_post(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un post optimizado para una red social especifica.

    Args:
        arguments:
            platform (str): plataforma — "instagram", "facebook", "linkedin", "twitter", "tiktok", "whatsapp"
            topic (str): tema o mensaje del post
            tone (str, opcional): tono — "profesional", "casual", "motivacional", "divertido" (default: "profesional")
            include_hashtags (bool, opcional): incluir hashtags relevantes (default: True)
            max_chars (int, opcional): limite de caracteres (auto-detectado por plataforma si no se especifica)
    """
    try:
        from app.services.provider_router import route_chat

        platform = str(arguments.get("platform") or arguments.get("red") or "").strip().lower()
        topic = str(arguments.get("topic") or arguments.get("tema") or arguments.get("message") or "").strip()
        if not platform:
            return ToolResult(ok=False, output="", error="content_social_post requiere platform (instagram, facebook, linkedin, twitter, tiktok, whatsapp).")
        if not topic:
            return ToolResult(ok=False, output="", error="content_social_post requiere topic (tema o mensaje).")

        platform_config = {
            "instagram": {
                "name": "Instagram",
                "max_chars": 2200,
                "format": "Caption con emojis, hashtags al final, tono visual y atractivo. Opcional: sugerencia de call-to-action.",
                "hashtag_count": "8-12 hashtags relevantes",
            },
            "facebook": {
                "name": "Facebook",
                "max_chars": 5000,
                "format": "Post con titulo llamativo, cuerpo y call-to-action. Puede incluir enlace.",
                "hashtag_count": "2-3 hashtags",
            },
            "linkedin": {
                "name": "LinkedIn",
                "max_chars": 3000,
                "format": "Post profesional con hook, desarrollo de ideas, y cierre con pregunta o reflexion.",
                "hashtag_count": "3-5 hashtags profesionales",
            },
            "twitter": {
                "name": "Twitter/X",
                "max_chars": 280,
                "format": "Mensaje conciso y directo, maximo 280 caracteres. Incluir emojis si aplica.",
                "hashtag_count": "1-2 hashtags",
            },
            "tiktok": {
                "name": "TikTok",
                "max_chars": 4000,
                "format": "Descripcion corta y llamativa con emojis, hashtags y frase hook inicial.",
                "hashtag_count": "4-6 hashtags virales",
            },
            "whatsapp": {
                "name": "WhatsApp",
                "max_chars": 4096,
                "format": "Mensaje directo y personal. Formato de broadcast o mensaje uno a uno.",
                "hashtag_count": "0 hashtags (no se usan en WhatsApp generalmente)",
            },
        }

        config = platform_config.get(platform)
        if not config:
            return ToolResult(
                ok=False, output="",
                error=f"Plataforma no soportada: {platform}. Usa: instagram, facebook, linkedin, twitter, tiktok, whatsapp.",
            )

        tone = str(arguments.get("tone") or arguments.get("tono") or "profesional").strip().lower()
        include_hashtags = bool(arguments.get("include_hashtags", True))
        max_chars = int(arguments.get("max_chars") or config["max_chars"])

        hashtag_instruction = f"Incluye {config['hashtag_count']} al final." if include_hashtags else "NO incluyas hashtags."
        if platform == "whatsapp":
            hashtag_instruction = "No incluyas hashtags (WhatsApp no los usa)."

        prompt = (
            f"Genera un post optimizado para {config['name']} con las siguientes especificaciones:\n\n"
            f"Tema: {topic}\n"
            f"Tono: {tone}\n"
            f"Formato: {config['format']}\n"
            f"Limite maximo: {max_chars} caracteres\n"
            f"Hashtags: {hashtag_instruction}\n\n"
            f"El post debe ser nativo de {config['name']}, usando las mejores practicas de la plataforma.\n"
            f"Responde SOLO con el contenido del post listo para publicar."
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt=f"Eres un social media manager experto en {config['name']}. Creas posts optimizados, atractivos y con alto engagement.",
            include_document_action_prompt=False,
        )

        return ToolResult(
            ok=True,
            output=result.strip(),
            artifacts=[{
                "type": "social_post",
                "platform": platform,
                "tone": tone,
                "char_count": len(result),
                "hashtags_included": include_hashtags,
            }],
        )

    except Exception as e:
        log.exception("content_social_post error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al generar post: {e}")


# ═══════════════════════════════════════════════════════════════════
# Registro canónico de tools
# ═══════════════════════════════════════════════════════════════════

TOOLS: list[tuple[str, object]] = [
    # Finance
    # ⚠️ finance_parse_invoice → migrado a real_apis.py (bridge Electron + regex + IA)
    ("finance_categorize_expense", finance_categorize_expense),
    ("finance_monthly_report", finance_monthly_report),
    ("finance_budget_alert", finance_budget_alert),
    ("finance_generate_invoice", finance_generate_invoice),
    ("finance_calc_vat", finance_calc_vat),
    # Research
    # ⚠️ FAKE peligroso: research_topic_deep alucina investigación profunda sin fuentes reales
    # ("research_topic_deep", research_topic_deep),
    # ⚠️ FAKE peligroso: research_fact_check alucina verificación de hechos sin fuentes verificables
    # ("research_fact_check", research_fact_check),
    # ⚠️ FAKE peligroso: research_competitor alucina análisis de competidores sin datos reales
    # ("research_competitor", research_competitor),
    # ⚠️ FAKE peligroso: research_company_profile alucina perfiles empresariales sin fuentes verificables
    # ("research_company_profile", research_company_profile),
    # Content
    ("content_write_draft", content_write_draft),
    ("content_improve", content_improve),
    ("content_summarize_long", content_summarize_long),
    ("content_rewrite_tone", content_rewrite_tone),
    ("content_social_post", content_social_post),
]

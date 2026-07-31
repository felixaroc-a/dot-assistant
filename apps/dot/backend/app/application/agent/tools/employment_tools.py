"""Tools de busqueda de empleo — canvas v2 dominio 1, 12 tools."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.employment")


def job_search_and_apply_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        profile = str(arguments.get("profile") or arguments.get("cv_summary") or "").strip()
        city = str(arguments.get("city") or "").strip()
        if not profile:
            return ToolResult(ok=False, output="", error="Falta perfil o resumen del CV.")
        prompt = f"Busca ofertas de trabajo para: {profile}"
        if city: prompt += f" en {city}"
        result = route_chat(prompt + ". Busca en LinkedIn, Indeed, Computrabajo, Bumeran. Da 10 ofertas con titulo, empresa, link si conocido, salario si disponible. Filtra las que tengan matching >70%.", provider_id="deepseek", system_prompt="Job search agent. Datos reales o indica limitaciones.")
        return ToolResult(ok=True, output=result.strip()[:2000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_cv_optimizer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        from app.services.provider_router import route_chat
        cv_path = str(arguments.get("cv_path") or "").strip()
        job_desc = str(arguments.get("job_description") or "").strip()
        cv_text = ""
        if cv_path:
            raw = execute_local_tool_via_bridge("readFile", path=cv_path)
            cv_text = str(raw.get("content", ""))[:3000] if raw.get("ok") else ""
        else:
            cv_text = str(arguments.get("cv_text") or "").strip()
        if not cv_text or not job_desc:
            return ToolResult(ok=False, output="", error="Falta CV y descripcion de la oferta.")
        result = route_chat(f"Analiza este CV contra la oferta. Sugiere palabras clave faltantes, mejora el extracto profesional, sugiere cambios en habilidades para maximizar ATS score.\n\nCV:\n{cv_text}\n\nOferta:\n{job_desc}", provider_id="deepseek", system_prompt="CV optimizer. Sugerencias concretas en espanol.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_generate_portfolio_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        cv_text = str(arguments.get("cv_text") or "").strip()
        if not cv_text:
            return ToolResult(ok=False, output="", error="Falta texto del CV.")
        result = route_chat(f"Genera portafolio profesional basado en: {cv_text}. Incluye extracto profesional, proyectos destacados, skills, educacion, carta de presentacion.", provider_id="deepseek", system_prompt="Portfolio writer. Profesional, bien estructurado.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_salary_benchmark_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        role = str(arguments.get("role") or "").strip()
        city = str(arguments.get("city") or "").strip()
        if not role:
            return ToolResult(ok=False, output="", error="Falta cargo.")
        prompt = f"Salario promedio para {role}"
        if city: prompt += f" en {city}"
        result = route_chat(prompt + ". Da rango (min, promedio, max) en USD. Fuente: Glassdoor, Indeed, LinkedIn.", provider_id="deepseek", system_prompt="Salary data. Numeros claros.")
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_interview_prep_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        role = str(arguments.get("role") or "").strip()
        if not role:
            return ToolResult(ok=False, output="", error="Falta cargo.")
        result = route_chat(f"20 preguntas frecuentes de entrevista para {role}. Incluye respuestas sugeridas. 10 tecnicas, 5 conductuales, 5 sobre la empresa.", provider_id="deepseek", system_prompt="Interview coach. Preguntas y respuestas en espanol.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_linkedin_optimizer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        profile = str(arguments.get("profile") or "").strip()
        if not profile:
            return ToolResult(ok=False, output="", error="Falta descripcion del perfil.")
        result = route_chat(f"Optimiza perfil LinkedIn para: {profile}. Headline, About, Experiencia, Skills. Sugiere cambios palabra por palabra para aparecer en busquedas de recruiters.", provider_id="deepseek", system_prompt="LinkedIn optimizer. Cambios concretos.")
        return ToolResult(ok=True, output=result.strip()[:1200])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_company_research_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        company = str(arguments.get("company") or "").strip()
        if not company:
            return ToolResult(ok=False, output="", error="Falta nombre de empresa.")
        result = route_chat(f"Investiga {company}: noticias recientes, cultura, CEO, competidores, situacion financiera. Resumen pre-entrevista de 1 pagina.", provider_id="deepseek", system_prompt="Company researcher. Datos clave para entrevista.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_skill_gap_analyzer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        skills = str(arguments.get("skills") or "").strip()
        role = str(arguments.get("role") or "").strip()
        if not skills or not role:
            return ToolResult(ok=False, output="", error="Falta skills y role.")
        result = route_chat(f"Compara estas skills: {skills} contra lo que pide el mercado para {role}. Identifica top 5 gaps y sugiere cursos gratuitos.", provider_id="deepseek", system_prompt="Skill gap analyst. Practico y accionable.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_offer_negotiator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        offer_salary = str(arguments.get("salary") or "").strip()
        market_salary = str(arguments.get("market") or "").strip()
        if not offer_salary:
            return ToolResult(ok=False, output="", error="Falta salario ofrecido.")
        result = route_chat(f"Genera email de contraoferta profesional. Salario ofrecido: {offer_salary}. Salario mercado: {market_salary}. Argumenta con datos, tono profesional.", provider_id="deepseek", system_prompt="Salary negotiator. Email profesional en espanol.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_freelance_finder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        skills = str(arguments.get("skills") or "").strip()
        if not skills:
            return ToolResult(ok=False, output="", error="Falta skills.")
        result = route_chat(f"Busca proyectos freelance para {skills} en Upwork, Fiverr, Workana. 5 oportunidades con presupuesto, cliente, descripcion.", provider_id="deepseek", system_prompt="Freelance finder. Oportunidades reales o indica limitaciones.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_relocation_planner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        city = str(arguments.get("city") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta ciudad destino.")
        result = route_chat(f"Presupuesto mensual para vivir en {city}: alquiler, comida, transporte, servicios, ocio. Costo de vida estimado.", provider_id="deepseek", system_prompt="Relocation cost estimator. Datos practicos.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def job_massive_apply_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        cv_text = str(arguments.get("cv_text") or "").strip()
        role = str(arguments.get("role") or "").strip()
        if not cv_text or not role:
            return ToolResult(ok=False, output="", error="Falta CV y cargo deseado.")
        result = route_chat(f"Simula aplicacion masiva: busca ofertas de {role}, genera carta de presentacion personalizada para cada una basada en el CV. Entrega tracker en formato tabla con empresa, cargo, fecha, estado.\n\nCV: {cv_text[:1000]}", provider_id="deepseek", system_prompt="Job application agent. Tabla tracker.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ⚠️ MÓDULO 100% FAKE — tools solo generan texto con LLM, no ejecutan acciones reales. Deshabilitado hasta migrar a APIs reales.
TOOLS = [
    # ("job_search_and_apply", job_search_and_apply_handler),
    # ("job_cv_optimizer", job_cv_optimizer_handler),
    # ("job_generate_portfolio", job_generate_portfolio_handler),
    # ("job_salary_benchmark", job_salary_benchmark_handler),
    # ("job_interview_prep", job_interview_prep_handler),
    # ("job_linkedin_optimizer", job_linkedin_optimizer_handler),
    # ("job_company_research", job_company_research_handler),
    # ("job_skill_gap_analyzer", job_skill_gap_analyzer_handler),
    # ("job_offer_negotiator", job_offer_negotiator_handler),
    # ("job_freelance_finder", job_freelance_finder_handler),
    # ("job_relocation_planner", job_relocation_planner_handler),
    # ("job_massive_apply", job_massive_apply_handler),
]

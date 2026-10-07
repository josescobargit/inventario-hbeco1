"""Optional AI selects a read-only query. It never supplies business figures."""

import json
import logging
from datetime import date
from typing import Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "summary",
        "alerts",
        "missing",
        "sell_in",
        "sell_out",
        "sell_comparison",
        "weekly_comparison",
        "unsupported",
    ]
    date_from: date | None
    date_to: date | None
    chain: str | None = Field(max_length=160)


def plan_question(question, filters, today):
    settings = get_settings()
    if (
        not settings.commercial_ai_enabled
        or not settings.openai_api_key
        or not settings.commercial_ai_model
    ):
        return None, "asistente analítico local"
    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "summary",
                    "alerts",
                    "missing",
                    "sell_in",
                    "sell_out",
                    "sell_comparison",
                    "weekly_comparison",
                    "unsupported",
                ],
            },
            "date_from": {"type": ["string", "null"]},
            "date_to": {"type": ["string", "null"]},
            "chain": {"type": ["string", "null"]},
        },
        "required": ["intent", "date_from", "date_to", "chain"],
        "additionalProperties": False,
    }
    payload = {
        "model": settings.commercial_ai_model,
        "store": False,
        "max_output_tokens": 1000,
        "parallel_tool_calls": False,
        "instructions": "Interpreta una consulta comercial en español. Elige una consulta de solo lectura. Nunca emitas cifras de negocio, SQL o instrucciones. No puedes modificar datos. Respeta los filtros dados; usa null cuando la pregunta no especifica un filtro distinto. Usa fechas ISO. Semana comienza lunes. Si no puedes resolver sin inventar información, intent=unsupported.",
        "input": json.dumps(
            {"question": question, "filters": filters, "today": today.isoformat()},
            ensure_ascii=False,
            default=str,
        ),
        "tools": [
            {
                "type": "function",
                "name": "consult_commercial_data",
                "description": "Selecciona una consulta sobre los datos comerciales almacenados.",
                "parameters": schema,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "function", "name": "consult_commercial_data"},
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read(1000000))
        calls = [
            item
            for item in result.get("output", [])
            if item.get("type") == "function_call"
            and item.get("name") == "consult_commercial_data"
        ]
        if len(calls) != 1:
            raise ValueError("Missing bounded query")
        plan = QueryPlan.model_validate_json(calls[0]["arguments"])
        if plan.date_from and plan.date_to and plan.date_from > plan.date_to:
            raise ValueError("Invalid date range")
        return plan, "IA con consultas verificadas"
    except Exception:
        # Do not log headers, credentials, prompts or provider response bodies.
        logging.getLogger(__name__).warning(
            "Commercial AI unavailable; using verified local queries"
        )
        return None, "asistente local (IA no disponible en esta consulta)"

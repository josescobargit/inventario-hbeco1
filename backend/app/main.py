from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.api.router import api_router
from app.core.config import get_settings


settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Control y visualización del inventario operativo. "
            "La aplicación no emite facturas."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With", "Idempotency-Key"],
    )
    application.include_router(api_router, prefix=settings.api_prefix)

    @application.exception_handler(OperationalError)
    async def database_unavailable(
        _request: Request, _error: OperationalError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Estamos conectando con los datos. "
                    "El sistema tardó más de lo esperado; intenta nuevamente."
                )
            },
        )

    @application.get("/health", tags=["Sistema"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "inventario-operativo-api"}

    return application


app = create_app()

"""
Crisis management API entrypoint.
"""
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.incidents import router as incidents_router
from app.api.visualization import router as viz_router
from app.config import get_settings
from app.observability import get_phoenix_url, setup_phoenix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

OPENAPI_TAGS = [
    {
        "name": "Incidents",
        "description": "Incident ingestion, retrieval, and live load metrics.",
    },
    {
        "name": "Visualization",
        "description": "Realtime streaming and graph visualization endpoints.",
    },
    {
        "name": "System",
        "description": "System status and runtime diagnostics.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Phoenix tracing UI before graph initialization.
    setup_phoenix(port=6006)

    # Warm up graph once during startup.
    logger.info("Initializing CZK graph...")
    from app.agents.graph import get_graph
    get_graph()
    logger.info("CZK system ready.")
    logger.info(f"   -> FastAPI:  http://{settings.app_host}:{settings.app_port}")
    logger.info(f"   -> Phoenix:  {get_phoenix_url()}")
    logger.info(f"   -> Swagger:  http://{settings.app_host}:{settings.app_port}/docs")
    yield
    logger.info("Shutting down CZK system.")


app = FastAPI(
    title=settings.app_title,
    description=(
        "Multi-agent crisis management support system.\n\n"
        "**Flow:** Incident -> Supervisor -> Domain Verifier -> Cross-domain Correlator -> Priority -> Comms\n\n"
        "**Realtime viz:** `GET /` (dashboard) or `GET /viz/stream/{incident_id}` (SSE)"
    ),
    version="1.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (dashboard HTML)
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass  # static/ may be missing in some test environments

# Routers
app.include_router(incidents_router)
app.include_router(viz_router)


@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    description="Return runtime status, configured model endpoint, GPU diagnostics, and tracing URL.",
    responses={
        200: {"description": "Service is healthy and diagnostics are available."},
    },
)
async def health():
    from app.agents.cuda_utils import get_cuda_info
    model_routing = {
        "supervisor": settings.nvidia_model_supervisor or settings.nvidia_model,
        "domain_verifier": settings.nvidia_model_domain_verifier or settings.nvidia_model,
        "cross_domain_correlator": settings.nvidia_model_cross_domain_correlator or settings.nvidia_model,
        "priority_assessor": settings.nvidia_model_priority_assessor or settings.nvidia_model,
        "comms_generator": settings.nvidia_model_comms_generator or settings.nvidia_model,
    }
    return {
        "status": "ok",
        "system": settings.app_title,
        "nvidia_base_url": settings.nvidia_base_url,
        "nvidia_model": settings.nvidia_model,
        "nvidia_model_routing": model_routing,
        "gpu": get_cuda_info(),
        "tracing_ui": get_phoenix_url(),
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level="info",
    )

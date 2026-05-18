"""
Observability setup: Arize Phoenix + OpenTelemetry.

Phoenix runs a local UI server (default port 6006) with:
- trace waterfall per incident
- node-level latency for LangGraph chains
- prompt/response inspection
- token usage breakdown
- retries and failures

Instrumentation is enabled via OpenInference for LangChain/LangGraph.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_phoenix_session = None


def setup_phoenix(port: int = 6006) -> Optional[object]:
    """Initialize Phoenix tracing and LangChain OpenTelemetry instrumentation."""
    global _phoenix_session

    try:
        import phoenix as px
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk import trace as trace_sdk
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning(
            f"Phoenix/OpenTelemetry not available ({e}); tracing is disabled. "
            "Install: pip install arize-phoenix "
            "openinference-instrumentation-langchain opentelemetry-exporter-otlp-proto-http"
        )
        return None

    try:
        _phoenix_session = px.launch_app(port=port)
        phoenix_url = f"http://localhost:{port}"
        logger.info(f"Arize Phoenix UI: {phoenix_url}")

        tracer_provider = trace_sdk.TracerProvider(
            resource=Resource({"service.name": "CZK-Crisis-Management", "service.version": "1.0.0"})
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{phoenix_url}/v1/traces"))
        )
        trace_api.set_tracer_provider(tracer_provider)

        LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

        logger.info(f"OpenTelemetry + LangChain instrumentation active: {phoenix_url}")
        return _phoenix_session

    except Exception as exc:
        logger.warning(f"Phoenix startup failed: {exc}; continuing without tracing")
        return None


def get_phoenix_url(port: int = 6006) -> str:
    return f"http://localhost:{port}"

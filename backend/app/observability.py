from __future__ import annotations

import os

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

HTTP_REQUESTS = Counter("gocomet_http_requests_total", "HTTP requests", ("method", "route", "status"))
HTTP_DURATION = Histogram("gocomet_http_request_duration_seconds", "HTTP request duration", ("method", "route"))
BIDS = Counter("gocomet_bids_total", "Committed auction bids")
EXTENSIONS = Counter("gocomet_auction_extensions_total", "Auction extensions", ("trigger",))


def configure_telemetry(app) -> None:
    # A concrete route avoids a trailing-slash redirect being swallowed by the
    # SPA catch-all on container platforms.
    app.add_api_route(
        "/metrics",
        lambda: Response(generate_latest(), media_type=CONTENT_TYPE_LATEST),
        methods=["GET"],
        include_in_schema=False,
    )
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "gocomet-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="/metrics,/api/health")

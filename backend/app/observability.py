from __future__ import annotations

import os

from prometheus_client import Counter, Histogram, make_asgi_app

HTTP_REQUESTS = Counter("gocomet_http_requests_total", "HTTP requests", ("method", "route", "status"))
HTTP_DURATION = Histogram("gocomet_http_request_duration_seconds", "HTTP request duration", ("method", "route"))
BIDS = Counter("gocomet_bids_total", "Committed auction bids")
EXTENSIONS = Counter("gocomet_auction_extensions_total", "Auction extensions", ("trigger",))


def configure_telemetry(app) -> None:
    app.mount("/metrics", make_asgi_app())
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

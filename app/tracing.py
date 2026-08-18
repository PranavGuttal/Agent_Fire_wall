"""OpenTelemetry setup: one tracer for the whole service, exporting every
span to a local Jaeger instance (via OTLP/HTTP) and to the console.

Console export means traces are visible even if Jaeger isn't running;
Jaeger gives the actual visual waterfall (http://localhost:16686) once
`docker compose up -d` is running.
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

# Overridable so the containerized app can reach Jaeger by its Docker
# Compose service name ("jaeger") instead of localhost, which inside a
# container refers to the container itself, not the host or sibling containers.
OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://localhost:4318/v1/traces")


def setup_tracing() -> None:
    resource = Resource(attributes={SERVICE_NAME: "agent-runtime-firewall"})
    provider = TracerProvider(resource=resource)

    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT))
    )

    trace.set_tracer_provider(provider)


def get_tracer():
    return trace.get_tracer("agent-runtime-firewall")

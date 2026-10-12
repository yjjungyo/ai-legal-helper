from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
import typing

_tracer: typing.Optional[trace.Tracer] = None

def init_telemetry(service_name: str = "ai-legal-helper"):
    global _tracer
    
    # Create resource
    resource = Resource.create(attributes={
        "service.name": service_name
    })

    # Set up tracer provider
    provider = TracerProvider(resource=resource)
    
    # In P0 (development), we just output to console.
    # In future, this will be changed to JaegerExporter.
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

    # Register the provider globally
    trace.set_tracer_provider(provider)
    
    _tracer = trace.get_tracer(service_name)
    
def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        init_telemetry()
    return _tracer


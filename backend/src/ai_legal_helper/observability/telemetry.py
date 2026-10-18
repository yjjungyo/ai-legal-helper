# -*- coding: utf-8 -*-
"""
모듈명: telemetry.py

[모듈 개요]
OpenTelemetry 기반 트레이서(Tracer) 및 분산 추적 리소스를 초기화하는 모듈이다.
환경변수 `LANGFUSE_SYSTEM_NAME`을 기본 서비스명으로 연동하여 분산 환경 추적 일관성을 확보한다.
"""
import os
import typing
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

_tracer: typing.Optional[trace.Tracer] = None


def init_telemetry(service_name: typing.Optional[str] = None):
    """OpenTelemetry TracerProvider 및 Tracer를 초기화한다.

    Args:
        service_name: 서비스 식별자 (미지정 시 환경변수 LANGFUSE_SYSTEM_NAME 또는 'LegalAgent')
    """
    global _tracer

    if not service_name:
        service_name = os.getenv("LANGFUSE_SYSTEM_NAME", "LegalAgent")

    # Create resource
    resource = Resource.create(attributes={
        "service.name": service_name
    })

    # Set up tracer provider
    provider = TracerProvider(resource=resource)

    # 기본적으로 콘솔을 오염시키지 않도록 OTEL_CONSOLE_EXPORT=true 설정 시에만 콘솔로 스팬 덤프
    if os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true":
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)

    # Register the provider globally
    trace.set_tracer_provider(provider)

    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    """초기화된 전역 OpenTelemetry Tracer를 반환한다."""
    global _tracer
    if _tracer is None:
        init_telemetry()
    return _tracer



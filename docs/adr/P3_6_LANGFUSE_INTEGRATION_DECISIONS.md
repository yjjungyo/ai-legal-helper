# ADR: Langfuse Integration & Observability Strategy

## 1. 개요
* 대상: AI Legal Helper Langfuse 통합 (P3.6)
* 작성자: AI Agent
* 상태: Proposed -> Accepted

## 2. 배경 (Context)
P3.6에서는 기존 AOP(OpenTelemetry) 및 Gateway(LangChain) 기반의 추적 체계를 확장하여 Langfuse를 통합해야 합니다. 
주요 제약사항은 다음과 같습니다.
1. 기존 AOP 및 OpenTelemetry(`telemetry.py`), TokenTracker를 유지.
2. 동일 LLM 호출 중복 집계 방지.
3. **개인정보 및 Prompt/Response 원문을 절대 Langfuse에 전송하지 않음.**
4. Self-hosted 배포 지원 및 장애 격리(비동기 로깅 등).

## 3. 대안 비교 (Alternatives)

### 대안 A. OpenTelemetry (OTel) 기반 연동
- 장점: 기존 `telemetry.py`에 Exporter만 추가하면 됨.
- 단점: Langfuse의 고유 기능(토큰, 비용, Agent Flow 특화 뷰)을 100% 활용하기 어려울 수 있으며, LangChain 내부 LLM 메트릭을 OTel로 추출하는 추가 작업이 필요함.

### 대안 B. 공식 LangGraph/LangChain Callback Handler 기반 연동
- 장점: Langfuse에서 제공하는 `LangfuseCallbackHandler`를 사용하면 LangGraph 실행 흐름과 LLM 호출을 자동으로 추적할 수 있음.
- 단점: 공식 CallbackHandler는 기본적으로 프롬프트와 응답 원문을 모두 캡처하여 전송함. 이를 차단하기 위해 내부를 강하게 Hooking하거나 Masking 함수를 제공해야 함. (일부 버전에서 완벽한 차단이 어려움)

### 대안 C. Gateway 및 Decorator 중심 수동 계측 (Custom Instrumentation)
- 장점: `langfuse.client.Langfuse` 객체를 직접 호출하여 추적(Trace), 스팬(Span), 세대(Generation)를 명시적으로 생성함. 이때 `input`, `output` 인자에 원문을 아예 넘기지 않고 `None` 또는 `[MASKED]` 처리를 할 수 있어 **개인정보 통제가 100% 보장됨**. 기존 TokenTrackingCallbackHandler와 로직을 병합하여 중복 토큰 집계도 방지할 수 있음.
- 단점: LangChain 노드마다 수동으로 계측하거나, 기존 AOP Decorator(`decorators.py`)를 수정하여 Langfuse Span을 함께 열도록 해야 함.

## 4. 결정 (Decision)
**대안 C (Custom Instrumentation)와 일부 대안 B의 장점을 섞은 하이브리드 커스텀 콜백(Custom Callback) 방식을 채택한다.**

1. `LangfuseCallbackHandler`를 그대로 쓰지 않고, 보안이 최우선이므로 기존 `TokenTrackingCallbackHandler`를 확장한 `LangfuseSecureCallbackHandler`를 구현한다.
2. LLM 시작/종료 시점에 `langfuse.client.generation()`을 수동 호출하며, `input`과 `output`은 명시적으로 기록하지 않는다.
3. LangGraph 노드 추적은 기존 AOP `@trace` (`decorators.py`)에서 `telemetry.py`를 호출할 때 Langfuse Trace/Span도 병행해서 생성 및 관리하도록 연동한다.
4. Langfuse 클라이언트는 비동기 백그라운드 전송 기능을 기본 탑재하고 있어(장애 격리), `Langfuse(public_key, secret_key, host)` 인스턴스 하나를 글로벌하게 싱글톤으로 유지한다.

## 5. 결과 (Consequences)
- **보안/개인정보**: 어플리케이션 계층에서 원문 자체가 Langfuse Client로 넘어가지 않으므로 메모리 덤프나 네트워크 스니핑에서도 안전.
- **성능/장애 격리**: Langfuse API 장애 시 비동기 큐에서 버려지거나 Timeout 처리되며, 메인 스레드의 법률 분석 로직은 중단되지 않음.
- **유지보수성**: AOP Decorator와 Custom Callback을 통해 중복 코드를 최소화하고, 기존 `docker-compose.yml`과 분리된 `docker-compose.langfuse.yml`을 유지하여 인프라 분리 달성.


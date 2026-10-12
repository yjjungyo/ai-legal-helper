# P3.6 AI Master QA / Evaluation Answers

본 문서는 P3.6 단계 결과물에 대한 AI Master 관점의 평가 답변입니다.

## 1. Technical Depth & System Excellence

**Q: 분산 추적 구조는 어떻게 구현되었으며, 개인정보는 어떻게 보호되는가?**
A: 기존 `contextvars` 기반의 AOP Tracing(`@trace`) 레이어를 유지하면서 Langfuse SDK를 수동 계측 형태로 확장 결합했습니다. LangGraph Callback을 쓰지 않음으로써 LLM 호출 중복 집계를 방지했고, `[MASKED FOR PRIVACY]` 하드코딩과 `LANGFUSE_CAPTURE_CONTENT=false` 정책을 통해 메모리 레벨에서부터 PII 및 원본 본문이 외부로 유출되는 것을 차단했습니다.

**Q: Langfuse 서버 장애 시 AI 법률 시스템은 어떻게 격리되는가?**
A: Langfuse Python SDK는 내부적으로 백그라운드 스레드를 이용한 비동기 큐 전송 방식을 사용합니다. 메인 스레드(FastAPI)가 Langfuse 응답 지연으로 멈추지 않으며, 네트워크 단절 시 SDK 레벨에서 재시도 후 안전하게 이벤트를 드랍합니다. 이를 위해 `langfuse_client.py`는 `try-except` 블록과 옵셔널 클라이언트 패턴으로 감싸져 있습니다.

## 2. Problem Solving & Strategy

**Q: 기존 OTel 구조가 있었음에도 Langfuse를 도입한 목적과 도입 전후 비교는?**
A: OpenTelemetry는 시스템 레벨의 병목과 에러 추적에는 훌륭하나, LLM 애플리케이션 특성상 토큰 단위의 비용 산정, 프롬프트 체인, Multi-Agent 트리 뷰 분석에 한계가 있었습니다. Langfuse는 LLM Generation과 Token Metrics 중심의 UI를 제공하므로, 도입 후 각 Agent(Verification, Supervisor, FactExtractor)가 소모한 LLM 토큰과 지연 시간을 즉시 정량적으로 가시화할 수 있게 되었습니다.

## 3. Growth Potential & Communication

**Q: 실제 Agent Trace를 통해 향후 시스템을 어떻게 고도화할 계획인가?**
A: Trace를 통해 가장 병목이 심한 구간이 **Evidence GraphRAG**와 **Verification Agent**임을 관측할 수 있습니다. 특히 Verification Agent는 주장(Claim) 검증 시 토큰 소모가 큽니다. 추후 Langfuse에 쌓인 Trace 데이터셋을 활용해 Verification Agent의 프롬프트를 Few-Shot 최적화하거나, 가벼운 모델(GPT-4o-mini 등)로 교체하여 비용 대비 성능을 극대화할 계획입니다.


# Langfuse Trace JSON 내보내기

스크립트: `scripts/evaluation/export_langfuse_traces.py`

Langfuse(`localhost:3001`)에서 각 Trace의 원본 데이터와 모든 Observation을 조회하여 **Trace마다 JSON 1개**를 저장합니다. 기존 단건·CSV·25건 일괄 추출 기능은 그대로 유지합니다.

## 1. TXT 목록으로 순차 추출 (추가 기능)

UTF-8 텍스트 파일을 만들고 **Trace ID(UUID)를 한 줄에 하나씩** 적습니다. 빈 줄 및 `#`으로 시작하는 주석 줄은 무시합니다.

```text
# scripts/evaluation/my_trace_ids.txt
9a6ea3b1-5817-480d-a934-67eeb402ccab
3fe378fc-1ac5-4c90-adf6-0de614c0e65d
d049beb7-f807-403c-b288-3012d9359db2
```

위 세 ID는 프로젝트에 기록된 **SC-001 LegalAgent E2E V8 1~3차 상담**의 Trace ID입니다.

프로젝트 루트에서 실행:

```powershell
python scripts/evaluation/export_langfuse_traces.py --ids-file scripts/evaluation/my_trace_ids.txt --case-id SC-001 --service "LegalAgent E2E V8" --out artifacts/langfuse_trace_export --zip
```

- TXT의 순서대로 한 건씩 조회합니다. 중간 조회가 실패해도 기본적으로 나머지 ID를 계속 처리합니다.
- 한 건마다 `SC-001_step1_LegalAgent_E2E_V8_<trace-id>.json` 형식으로 개별 저장합니다. `--ids-file`은 `--case-id`, `--step`, `--service`를 **목록 전체에 공통 적용**합니다.
- `export_manifest.json`에 각 ID의 `OK/FAILED` 상태와 Observation 수, 실패 사유를 남깁니다.
- `--zip`을 지정하면 성공한 JSON과 결과 목록을 ZIP으로 묶습니다. 부분 실패가 있으면 종료 코드는 `1`입니다.
- 잘못된 ID는 해당 행의 `FAILED`로 기록합니다. **동일 ID 중복 기재 및 빈 TXT는 입력 오류**로 거부합니다.
- 실패 즉시 중단하려면 `--fail-fast` 옵션을 추가합니다.

## 2. 사건·단계·서비스명이 서로 다른 Trace 여러 건

**SC-001~SC-003의 여러 서비스**처럼 개별 Trace의 메타데이터가 다르면 기존 CSV 목록을 사용하세요.

```powershell
python scripts/evaluation/export_langfuse_traces.py --manifest scripts/evaluation/langfuse_trace_manifest_sc001_sc003.csv --out artifacts/langfuse_trace_export --zip
```

CSV 필수 헤더: `case_id,step,service,trace_id`.

프로젝트에 이미 기록된 SC-001~SC-003의 25개 비교 Trace를 한 번에 받으려면:

```powershell
python scripts/evaluation/export_langfuse_traces.py --all --zip
```

## 3. 단건 추출 (기존 방식)

```powershell
python scripts/evaluation/export_langfuse_traces.py --trace-id 9a6ea3b1-5817-480d-a934-67eeb402ccab --case-id SC-001 --step 1 --service "LegalAgent E2E V8" --zip
```

## 4. 연결 및 보안

기본 연결 주소는 `http://localhost:3001`이며, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 환경변수나 `backend/.env`에 설정합니다. 다른 위치의 환경 파일은 `--env-file <path>`로 지정합니다.

Trace JSON에는 상담 내용과 증거 원문 등 **개인정보가 포함될 수 있습니다**. 추출 파일과 ZIP은 외부에 공개하거나 저장소에 커밋하지 말고, 공유 전 비식별화 여부를 확인하세요. 스크립트는 인증 키를 JSON에 기록하지 않습니다.

## 5. 테스트

```powershell
python -m unittest discover -s scripts/evaluation -p test_export_langfuse_traces.py -v
```

이 테스트는 가짜 API 응답을 사용하므로 실제 Langfuse 서버와 연결하지 않습니다.

import pytest
from fastapi.testclient import TestClient
from ai_legal_helper.api.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_start_consultation():
    # Make sure we can trigger consultation without actually running the full legacy LLM mock if we don't want to, 
    # but the background task will try to run it. For unit testing, we might want to mock run_legacy_consultation,
    # but the prompt requires testing API input validation and running.
    # Since it's a background task, the API will return immediately.
    response = client.post(
        "/api/v1/consultations",
        json={"question": "근로기준법상 해고 예고 수당은 얼마인가요?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert data["status"] == "IN_PROGRESS"
    
    req_id = data["request_id"]
    
    # Check status endpoint
    status_response = client.get(f"/api/v1/consultations/{req_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] in ["IN_PROGRESS", "SUCCESS", "ERROR"]

    # Check full result endpoint
    result_response = client.get(f"/api/v1/consultations/{req_id}")
    assert result_response.status_code == 200
    res_data = result_response.json()
    assert res_data["request_id"] == req_id
    assert "trace_id" in res_data


def test_case_consultation_persistence():
    """사건 연계 상담이 DB에 영구 저장되고 사건별 상담 목록으로 조회되는지 검증한다."""
    # 1. 사건 생성
    case_res = client.post("/api/v1/cases", json={"title": "상담 저장 테스트 사건", "case_type": "주택임대차"})
    assert case_res.status_code == 200
    case_id = case_res.json()["id"]

    # 2. 해당 사건에 대한 상담 요청
    c_res = client.post(
        "/api/v1/consultations",
        json={"question": "보증금 반환 거부 시 어떻게 대처하나요?", "case_id": case_id}
    )
    assert c_res.status_code == 200
    req_id = c_res.json()["request_id"]

    # 3. 사건별 상담 내역 조회 API 검증
    list_res = client.get(f"/api/v1/cases/{case_id}/consultations")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert any(item["request_id"] == req_id for item in items)
    assert any(item["question"] == "보증금 반환 거부 시 어떻게 대처하나요?" for item in items)



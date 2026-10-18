import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import os

from ai_legal_helper.database.session import Base, get_db
from ai_legal_helper.database import models  # Import all models to register them
from ai_legal_helper.api.main import app

# Use the test DB URL
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ai_user:ai_password@127.0.0.1:5432/ai_legal_helper_test")
engine = create_engine(TEST_DB_URL)
Base.metadata.create_all(bind=engine)

def override_get_db():
    from sqlalchemy.orm import sessionmaker
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
import ai_legal_helper.api.routes.evidence
ai_legal_helper.api.routes.evidence.get_db = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import sessionmaker
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    user = models.User(id="test-user-id", email="test@example.com", display_name="Test User", password_hash="fakehash")
    db.add(user)
    db.commit()
    db.close()
    
    yield
    Base.metadata.drop_all(bind=engine)

def test_evidence_workflow():
    # 1. Create a case
    res = client.post("/api/v1/cases", json={"title": "Test Case", "case_type": "TEST"})
    assert res.status_code == 200
    case_id = res.json()["id"]

    # 2. Upload an evidence file
    # We will upload a simple text file
    test_content = b"This is a test evidence file content about returning 1,000,000 KRW deposit."
    
    # We use a tuple for files: (filename, fileobj, content_type)
    res = client.post(
        f"/api/v1/cases/{case_id}/evidence",
        files={"file": ("test_evidence.txt", test_content, "text/plain")}
    )
    assert res.status_code == 200
    doc = res.json()
    assert doc["status"] == "UPLOADED"
    evidence_id = doc["evidence_id"]

    # Background extraction is triggered automatically on upload.
    # Instead, we will simulate the extraction output manually in DB or just assume it works.
    # Let's check status right after. It might be EXTRACTING or REVIEW_REQUIRED.
    res = client.get(f"/api/v1/cases/{case_id}/evidence")
    docs = res.json()
    assert len(docs) == 1
    
    # Since the background extraction might be running or finished, we won't assert the exact final status here
    # but we can check the endpoint exists.
    res = client.get(f"/api/v1/cases/{case_id}/evidence/{evidence_id}/claims")
    assert res.status_code == 200

    # 3. 수동 추출(또는 재추출) 엔드포인트 호출 검증
    res_extract = client.post(f"/api/v1/cases/{case_id}/evidence/{evidence_id}/extract")
    assert res_extract.status_code == 200
    extract_data = res_extract.json()
    assert extract_data["status"] == "SUCCESS"
    assert extract_data["evidence_id"] == evidence_id

    # 존재하지 않는 증거 문서 추출 요청 시 404 반환 검증
    res_404 = client.post(f"/api/v1/cases/{case_id}/evidence/invalid-doc-id/extract")
    assert res_404.status_code == 404

    # 4. 증거 충돌(conflicts) 엔드포인트 호출 검증 (405가 아닌 200 OK와 conflicts 키 반환 확인)
    res_conflicts = client.get(f"/api/v1/cases/{case_id}/evidence/conflicts")
    assert res_conflicts.status_code == 200
    conflicts_data = res_conflicts.json()
    assert "conflicts" in conflicts_data
    assert isinstance(conflicts_data["conflicts"], list)


def test_claim_type_normalization_and_categories():
    """법률 도메인 9개 세분화 카테고리의 영문 코드 정규화 및 UI 한글 표기 규칙을 검증한다.

    DB 영문 코드:
        PROPERTY, RIGHT_DUTY, DOC_INFO, DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, GENERAL
    UI 한글 표기 (띄어쓰기 없음):
        목적물정보, 권리의무, 문서정보, 일자기한, 금액비용, 당사자정보, 법률행위, 계약조건, 일반서술
    """
    from ai_legal_helper.case_intelligence.evidence_extractor import normalize_claim_type, normalize_to_claim_code

    test_cases = [
        # (입력값, 기대 영문 코드, 기대 한글 라벨)
        ("PROPERTY", "PROPERTY", "목적물정보"),
        ("PROPERTY_INFO", "PROPERTY", "목적물정보"),
        ("부동산", "PROPERTY", "목적물정보"),
        ("목적물 정보", "PROPERTY", "목적물정보"),
        ("RIGHT_DUTY", "RIGHT_DUTY", "권리의무"),
        ("OBLIGATION", "RIGHT_DUTY", "권리의무"),
        ("권리 의무", "RIGHT_DUTY", "권리의무"),
        ("DOC_INFO", "DOC_INFO", "문서정보"),
        ("DOCUMENT", "DOC_INFO", "문서정보"),
        ("문서 정보", "DOC_INFO", "문서정보"),
        ("DATE", "DATE", "일자기한"),
        ("일자 기한", "DATE", "일자기한"),
        ("AMOUNT", "AMOUNT", "금액비용"),
        ("금액 비용", "AMOUNT", "금액비용"),
        ("PARTY_INFO", "PARTY_INFO", "당사자정보"),
        ("당사자 정보", "PARTY_INFO", "당사자정보"),
        ("ACTION", "ACTION", "법률행위"),
        ("법률 행위", "ACTION", "법률행위"),
        ("CONDITION", "CONDITION", "계약조건"),
        ("계약 조건", "CONDITION", "계약조건"),
        ("OTHER", "GENERAL", "일반서술"),
        ("GENERAL", "GENERAL", "일반서술"),
        ("기타 서술", "GENERAL", "일반서술"),
        (None, "GENERAL", "일반서술"),
        ("", "GENERAL", "일반서술"),
    ]

    for raw, expected_code, expected_label in test_cases:
        actual_code = normalize_to_claim_code(raw)
        assert actual_code == expected_code, f"Code failed for {raw}: expected {expected_code}, got {actual_code}"

        actual_label = normalize_claim_type(raw)
        assert actual_label == expected_label, f"Label failed for {raw}: expected {expected_label}, got {actual_label}"
        # 한글 표기 시 띄어쓰기가 없어야 하는 규칙 검증
        assert " " not in actual_label, f"Category '{actual_label}' must not contain spaces"


def test_evidence_delete_and_cascade_facts():
    """증거 문서 삭제 시 공식 승격(APPROVED)된 Fact 레코드까지 연쇄 삭제되는지 검증한다.

    1. 사건 생성 및 증거 문서 업로드
    2. 증거 문서에 속한 Claim 생성 (PROPERTY 카테고리)
    3. Claim 목록 조회 시 표준 영문 코드('PROPERTY')로 반환되는지 확인
    4. Claim을 승인(APPROVE)하여 사건의 공식 Fact로 승격 (Fact.fact_type도 PROPERTY로 보존)
    5. 증거 문서 DELETE 요청 수행
    6. 증거 문서 및 승격되었던 Fact 레코드가 모두 연쇄 삭제되었는지 확인
    """
    from sqlalchemy.orm import sessionmaker

    # 1. 사건 생성
    res = client.post("/api/v1/cases", json={"title": "Cascade Fact Test Case", "case_type": "TEST"})
    assert res.status_code == 200
    case_id = res.json()["id"]

    # 2. 증거 문서 업로드
    res_up = client.post(
        f"/api/v1/cases/{case_id}/evidence",
        files={"file": ("lease_contract.txt", b"Lease agreement for Seoul Apt 101.", "text/plain")}
    )
    assert res_up.status_code == 200
    evidence_id = res_up.json()["evidence_id"]

    # 3. 테스트용 Claim 직접 생성 (PROPERTY 카테고리)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    claim = models.EvidenceClaim(
        case_id=case_id,
        evidence_id=evidence_id,
        statement="서울시 마포구 아파트 101호 임대차 목적물",
        claim_type="PROPERTY",
        assertion_status="DOCUMENT_STATES",
        confidence=0.95,
        review_status="PENDING"
    )
    db.add(claim)
    db.commit()
    claim_id = claim.id
    db.close()

    # 4. Claim 목록 API 호출 시 표준 영문 코드 'PROPERTY'로 반환되는지 확인 (DB 저장은 영문)
    res_claims = client.get(f"/api/v1/cases/{case_id}/evidence/{evidence_id}/claims")
    assert res_claims.status_code == 200
    claims_list = res_claims.json()
    assert len(claims_list) >= 1
    target_claim = next(c for c in claims_list if c["id"] == claim_id)
    assert target_claim["claim_type"] == "PROPERTY"

    # 5. Claim 승인(APPROVE) -> 공식 Fact로 승격
    res_review = client.post(
        f"/api/v1/cases/{case_id}/evidence/{evidence_id}/claims/{claim_id}/review",
        json={"action": "APPROVE"}
    )
    assert res_review.status_code == 200

    # DB에서 Fact 생성 확인
    db = TestingSessionLocal()
    promoted_facts = db.query(models.Fact).filter_by(case_id=case_id).all()
    assert len(promoted_facts) >= 1
    assert any(f.source_ref == evidence_id for f in promoted_facts)
    db.close()

    # 6. 증거 문서 삭제 호출 (DELETE)
    res_del = client.delete(f"/api/v1/cases/{case_id}/evidence/{evidence_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "SUCCESS"

    # 7. 검증: 증거 문서 및 승격되었던 Fact가 모두 연쇄 삭제되었는지 확인
    db = TestingSessionLocal()
    doc_after = db.query(models.EvidenceDocument).filter_by(id=evidence_id).first()
    assert doc_after is None, "EvidenceDocument must be deleted"

    claims_after = db.query(models.EvidenceClaim).filter_by(evidence_id=evidence_id).all()
    assert len(claims_after) == 0, "Related EvidenceClaims must be cascade deleted"

    facts_after = db.query(models.Fact).filter(
        (models.Fact.case_id == case_id) & (models.Fact.source_ref == evidence_id)
    ).all()
    assert len(facts_after) == 0, "Promoted Fact from this evidence must be deleted"
    db.close()


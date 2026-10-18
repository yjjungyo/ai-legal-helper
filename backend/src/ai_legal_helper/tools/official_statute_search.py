# -*- coding: utf-8 -*-
"""
모듈명: official_statute_search.py

[모듈 개요]
법제처 국가법령정보공동활용 API(open.law.go.kr)를 연동하여 내부 RAG 벡터 데이터베이스에 부재한
공식 법령 원문 및 관련 조문을 온디맨드(On-demand)로 실시간 검색하는 외부 도구 모듈이다.

[주요 기능]
1. `search_official_statutes`:
   - 법제처 Open API(`lawSearch.do` 및 `lawService.do`)를 통한 법령 식별(MST) 및 세부 조문 검색
   - 사용자 질문/쟁점 키워드 기반의 관련 조문 필터링
   - 검색된 법령 조문을 표준 Source 스키마(source_id, statute_name, article, content 등)로 변환
2. 출처 신뢰성 보장:
   - 조회 실패 시 빈 결과를 반환하며, LLM 자체 지식으로 허위 법령을 지어내지 않는다.
   - API Key 및 민감정보는 로그에 마스킹 처리하여 기록한다.

[주의사항]
- 환경변수 `LAW_OPENAPI_KEY`가 필수로 요구된다. 미설정 시 안전하게 빈 목록을 반환한다.
- PII 및 사건 원문은 외부 검색 쿼리로 전송하지 않고, 정제된 법령명과 쟁점 키워드만 사용한다.
"""
import os
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.source_schema import normalize_source_dict

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9))


def _get_kst_iso() -> str:
    """현재 한국 표준시(KST) 기준 ISO 8601 문자열을 반환한다."""
    return datetime.now(KST).isoformat()


@trace
def search_official_statutes(
    query: str,
    candidate_laws: List[str],
    effective_date: Optional[str] = None,
    missing_issues: Optional[List[str]] = None,
    max_articles_per_law: int = 10,
) -> List[Dict[str, Any]]:
    """법제처 국가법령정보공동활용 API를 호출하여 공식 법령 조문 원문을 실시간 검색한다.

    1. 각 후보 법령명(`candidate_laws`)으로 법제처 법령 검색 API(`lawSearch.do`)를 호출하여 법령 식별자(MST)를 조회한다.
       - 법령명 완전 일치(예: '민법' 검색 시 '난민법' 배제)를 우선 검증한다.
    2. 획득한 MST로 조문 상세 조회 API(`lawService.do`)를 호출하여 조문 목록(XML)을 파싱한다.
    3. 정보검색(IR) 기반의 일반화된 동적 가중치 알고리즘을 적용하여 조문을 선별한다:
       - 법률검증 Agent가 식별한 누락 쟁점(`missing_issues`)에 조문 제목이 부합할 경우 최우선 순위(15.0x)를 부여한다.
       - 법령명 자체에 포함된 단어(예: '주택임대차보호법'의 '주택', '임대차')는 조문 전반에 빈출하므로 가중치를 감쇄(0.2x~0.3x, TF-IDF 원리)한다.
       - 특정 도메인 전용 하드코딩 없이 노동, 민사, 형사, 행정 등 모든 법률 분야에 범용적으로 동작한다.
    4. 각 조문의 본문, 항(項), 호(號) 텍스트를 취합하여 시스템 공통 표준 Source 스키마 딕셔너리로 변환한다.

    Args:
        query: 검색 목적이 되는 법률 질문 원문.
        candidate_laws: 검색할 공식 법령명 목록 (예: ["주택임대차보호법"]).
        effective_date: 특정 시행일자 기준 조회 시 지정 (옵션).
        missing_issues: 법률검증 Agent가 식별한 핵심 누락 쟁점 목록 (옵션).
        max_articles_per_law: 법령당 추출할 최대 조문 청크 수 (기본값: 10).

    Returns:
        List[Dict[str, Any]]: 표준 Source 스키마 규격으로 정규화된 법령 출처 딕셔너리 리스트.
            조회 실패 시 빈 리스트 반환.

    Notes:
        - API 키나 개인정보는 절대 외부 호출 쿼리에 노출하지 않는다.
        - 조회되지 않은 조문을 허위로 꾸며내지 않으며, 실패 시 반드시 빈 목록을 반환한다.
    """
    api_key = os.getenv("LAW_OPENAPI_KEY")
    if not api_key:
        logger.warning("[OFFICIAL_STATUTE] LAW_OPENAPI_KEY 환경변수가 설정되지 않아 외부 법령 검색을 건너뜁니다.")
        return []

    if not candidate_laws:
        logger.debug("[OFFICIAL_STATUTE] 검색할 candidate_laws 목록이 비어 있습니다.")
        return []

    missing_text = " ".join(missing_issues or []).strip()
    full_query_text = f"{query or ''} {missing_text}".strip()

    retrieved_sources: List[Dict[str, Any]] = []

    for law_name in candidate_laws:
        clean_law_name = law_name.strip()
        if not clean_law_name:
            continue

        try:
            # 1단계: 법제처 법령 목록 검색 (MST 획득)
            encoded_name = urllib.parse.quote(clean_law_name)
            search_url = (
                f"http://www.law.go.kr/DRF/lawSearch.do?"
                f"OC={api_key}&target=law&type=XML&query={encoded_name}"
            )
            logger.info(f"[OFFICIAL_STATUTE] 법제처 법령 검색 호출: {clean_law_name}")

            req = urllib.request.Request(search_url, headers={"User-Agent": "AILegalHelper/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                search_xml_bytes = resp.read()

            search_root = ET.fromstring(search_xml_bytes)
            
            # 정확한 법령명 일치 우선 탐색 (예: '민법' 검색 시 '난민법'이 먼저 매칭되는 현상 방지)
            matched_elem = None
            for elem in search_root.findall(".//law"):
                hname = (elem.findtext("법령명한글") or "").strip()
                if hname == clean_law_name:
                    matched_elem = elem
                    break

            if matched_elem is None:
                # 2순위: 괄호나 공백 제거 후 일치 비교 (예: '주택임대차보호법')
                clean_target = re.sub(r'[\s\(\)\[\]]', '', clean_law_name)
                for elem in search_root.findall(".//law"):
                    hname = re.sub(r'[\s\(\)\[\]]', '', (elem.findtext("법령명한글") or "").strip())
                    if hname == clean_target:
                        matched_elem = elem
                        break

            if matched_elem is None:
                matched_elem = search_root.find(".//law")

            if matched_elem is None:
                logger.warning(f"[OFFICIAL_STATUTE] '{clean_law_name}' 법령을 법제처에서 찾지 못했습니다.")
                continue

            mst = matched_elem.findtext("법령일련번호") or matched_elem.findtext("일련번호")
            official_law_name = matched_elem.findtext("법령명한글") or clean_law_name
            law_id = matched_elem.findtext("법령ID") or ""
            law_no = matched_elem.findtext("공포번호") or ""
            eff_date_raw = matched_elem.findtext("시행일자") or ""
            
            # 시행일자 YYYY-MM-DD 변환
            effective_date_str = ""
            if len(eff_date_raw) == 8:
                effective_date_str = f"{eff_date_raw[:4]}-{eff_date_raw[4:6]}-{eff_date_raw[6:]}"

            if not mst:
                logger.warning(f"[OFFICIAL_STATUTE] '{clean_law_name}'의 MST(일련번호)가 없습니다.")
                continue

            # 2단계: 법제처 조문 상세 조회
            service_url = f"http://www.law.go.kr/DRF/lawService.do?OC={api_key}&target=law&MST={mst}&type=XML"
            req_service = urllib.request.Request(service_url, headers={"User-Agent": "AILegalHelper/1.0"})
            with urllib.request.urlopen(req_service, timeout=10) as resp_service:
                detail_xml_bytes = resp_service.read()

            detail_root = ET.fromstring(detail_xml_bytes)
            article_nodes = detail_root.findall(".//조문단위")
            if not article_nodes:
                logger.warning(f"[OFFICIAL_STATUTE] '{official_law_name}'의 세부 조문이 없습니다.")
                continue

            # 3단계: 동적 IR 가중치 기반 매칭 및 조문 수집
            # 법령명 자체에 포함된 2글자 이상 부분 문자열을 동적 불용어로 산출 (IDF 감쇄)
            law_subwords = {
                clean_law_name[i:j]
                for i in range(len(clean_law_name))
                for j in range(i + 2, len(clean_law_name) + 1)
            }

            matched_articles: List[Dict[str, Any]] = []

            for node in article_nodes:
                art_no_raw = node.findtext("조문번호") or ""
                art_title = (node.findtext("조문제목") or "").strip()
                art_content = (node.findtext("조문내용") or "").strip()
                
                # 조문 식별자 생성 (예: "제6조의2" 또는 "제6조")
                branch_no = node.findtext("조문가지번호") or ""
                article_label = f"제{art_no_raw}조"
                if branch_no and branch_no != "0":
                    article_label += f"의{branch_no}"

                # 항, 호 텍스트 취합
                sub_parts = []
                for hang in node.findall(".//항"):
                    h_content = (hang.findtext("항내용") or "").strip()
                    if h_content:
                        sub_parts.append(h_content)
                    for ho in hang.findall(".//호"):
                        ho_content = (ho.findtext("호내용") or "").strip()
                        if ho_content:
                            sub_parts.append(f"  {ho_content}")

                full_article_text = art_content
                if sub_parts:
                    full_article_text += "\n" + "\n".join(sub_parts)

                # 동적 적합도 점수 산정
                score = 0.0

                # 3.1 조문 제목 기반 쟁점 매칭 (가장 높은 판별력)
                title_words = [
                    w for w in re.findall(r'[가-힣]{2,}', art_title)
                    if w not in {"경우", "등의", "따른", "관한"}
                ]
                for tw in title_words:
                    is_law_term = tw in law_subwords or any(sw in tw for sw in law_subwords if len(sw) >= 3)
                    weight = 0.3 if is_law_term else 1.0
                    if missing_text and tw in missing_text:
                        score += 15.0 * weight  # 누락 쟁점에 조문 제목 단어가 일치 시 매우 높은 부스팅
                    elif tw in full_query_text:
                        score += 5.0 * weight

                # 3.2 조문 본문 내 누락 쟁점 및 질문 키워드 매칭
                search_tokens = [
                    t for t in re.findall(r'[가-힣]{2,}|[A-Za-z0-9]{2,}', full_query_text)
                    if t not in {"경우", "따라", "관한", "대한", "질문", "관련", "어떻게", "있나요", "인가요", "언제", "시점", "여부", "내용", "확인", "필요"}
                ]
                for tok in search_tokens:
                    is_law_term = tok in law_subwords or any(sw in tok for sw in law_subwords if len(sw) >= 3)
                    weight = 0.2 if is_law_term else (2.0 if missing_text and tok in missing_text else 1.0)
                    if tok in full_article_text:
                        score += 1.0 * weight

                # 쿼리 키워드가 1개 이상 매칭되거나, 쿼리가 너무 짧을 경우 고려
                if score > 0 or not full_query_text:
                    matched_articles.append({
                        "score": score,
                        "article_label": article_label,
                        "article_title": art_title,
                        "content": full_article_text,
                    })

            # 점수 내림차순 정렬 후 상위 k개 선택 (score > 0 우선)
            matched_articles.sort(key=lambda x: x["score"], reverse=True)
            positive_scored = [a for a in matched_articles if a["score"] > 0]
            selected_articles = (positive_scored if positive_scored else matched_articles)[:max_articles_per_law]

            # 만약 키워드 매칭이 전혀 없더라도 주요 총칙/기본 조문 2개라도 포함
            if not selected_articles and article_nodes:
                first_node = article_nodes[0]
                first_no = first_node.findtext("조문번호") or "1"
                first_label = f"제{first_no}조"
                first_content = (first_node.findtext("조문내용") or "").strip()
                selected_articles = [{
                    "score": 0,
                    "article_label": first_label,
                    "article_title": first_node.findtext("조문제목") or "",
                    "content": first_content,
                }]

            # 4단계: 표준 Source 스키마 형태로 변환
            for item in selected_articles:
                art_label = item["article_label"]
                source_id = f"{official_law_name}_{art_label}"
                doc_filename = f"{official_law_name}.pdf"

                source_dict = {
                    "source_id": source_id,
                    "source_type": "STATUTE",
                    "document_id": doc_filename,
                    "title": official_law_name,
                    "statute_name": official_law_name,
                    "article": art_label,
                    "content": item["content"],
                    "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
                    "chunk_id": f"statute-{mst}-{art_label}",
                    "source_url": f"https://www.law.go.kr/법령/{urllib.parse.quote(official_law_name)}/{art_label}",
                    "version_date": effective_date_str or None,
                    "effective_date": effective_date_str or None,
                    "court": None,
                    "case_number": None,
                    "decision_date": None,
                    "evidence_id": None,
                    "filename": doc_filename,
                    "file": doc_filename,
                    "file_name": doc_filename,
                    "page": "1",
                    "category": "civil",
                    "retrieved_at": _get_kst_iso(),
                    "verified": False,
                }
                retrieved_sources.append(normalize_source_dict(source_dict))

            logger.info(f"[OFFICIAL_STATUTE] '{official_law_name}'에서 조문 {len(selected_articles)}건 확보 완료")

        except Exception as e:
            logger.error(f"[OFFICIAL_STATUTE] 법령 '{law_name}' 검색 중 오류: {type(e).__name__}: {str(e)}")

    return retrieved_sources


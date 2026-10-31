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
   - 법령명에 조문·제목·설명이 붙은 후보를 정규화하고 같은 법의 요청을 병합
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
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.source_schema import normalize_source_dict

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9))
_ARTICLE_REFERENCE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_LAW_ENDING = r"(?:법률|법|령|규칙|규정)"


@dataclass
class StatuteSearchTarget:
    """외부 조회용 법령명과 내부 선별용 조문·설명을 분리한 검색 대상.

    Attributes:
        law_name: 법령 목록 API에 전송할 정규화된 법령명.
        articles: 사용자가 명시한 정확한 조문 식별자. 비어 있으면 쟁점으로 선별한다.
        references: 제목 등 선별에 사용할 입력 표현. 외부 쿼리로 전송하지 않는다.
    """

    law_name: str
    articles: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)


def _article_references(text: str) -> List[str]:
    """띄어쓰기와 선행 0을 정리한 조문 식별자를 중복 없이 추출한다.

    Args:
        text: 법령 인용 또는 검색 목적 문구.

    Returns:
        제3조와 제3조의2 등을 서로 다른 값으로 유지한 조문 목록.
    """
    labels = []
    for match in _ARTICLE_REFERENCE.finditer(text):
        label = f"제{int(match.group(1))}조"
        if match.group(2) is not None:
            label += f"의{int(match.group(2))}"
        if label not in labels:
            labels.append(label)
    return labels


def _split_statute_reference(reference: str) -> Optional[StatuteSearchTarget]:
    """후보 표현에서 법령명과 명시 조문을 분리하고 설명을 이름에서 제거한다.

    Args:
        reference: 법령명 또는 법령명에 조문·제목·법령상 설명이 붙은 문자열.

    Returns:
        분리한 검색 대상. 법령명을 식별할 수 없으면 None을 반환한다.
    """
    if not isinstance(reference, str) or not reference.strip():
        return None
    text = re.sub(r"\s+", " ", reference.strip())
    first_article = _ARTICLE_REFERENCE.search(text)
    prefix = text[:first_article.start()] if first_article else text
    law_name = prefix.strip(" \t\r\n「」『』〈〉《》\"'")

    # '민법상 ...', '민법의 제6조' 같은 조사는 정식 법령명의 일부가 아니다.
    # 법령명 내부의 공백은 보존하여 '소송촉진 등에 관한 특례법' 등을 훼손하지 않는다.
    described = re.match(rf"^(.+?{_LAW_ENDING})(?:상의|상|의|에\s*따른)(?=\s|$)", law_name)
    if described:
        law_name = described.group(1)
    elif not re.search(rf"{_LAW_ENDING}$", law_name):
        described = re.match(rf"^(.+?{_LAW_ENDING})\s+(?:관련|일반|해석|검토)(?:\s|$)", law_name)
        if described:
            law_name = described.group(1)
    if not law_name or not re.search(rf"{_LAW_ENDING}$", law_name):
        return None

    # 다른 법까지 섞인 표현의 조문을 첫 법의 조문으로 잘못 배정하지 않는다.
    article_text = text[first_article.start():] if first_article else ""
    another_law = re.search(rf"\s+[^,;]*?{_LAW_ENDING}\s*제\s*\d+\s*조", article_text)
    if another_law:
        article_text = article_text[:another_law.start()]
    return StatuteSearchTarget(law_name, _article_references(article_text), [text])


def _prepare_search_targets(candidate_laws: List[str]) -> List[StatuteSearchTarget]:
    """같은 법의 여러 조문 요청을 합쳐 법령 목록·원문을 한 번씩 조회하게 한다.

    Args:
        candidate_laws: 검증기가 반환한 법령 후보 표현 목록.

    Returns:
        입력 순서를 유지하며 법령별 요청 조문을 합친 검색 대상 목록.
    """
    targets: Dict[str, StatuteSearchTarget] = {}
    for reference in candidate_laws:
        parsed = _split_statute_reference(reference)
        if parsed is None:
            logger.warning("[OFFICIAL_STATUTE] 법령명을 식별할 수 없는 후보 1건을 제외했습니다.")
            continue
        target = targets.setdefault(parsed.law_name, StatuteSearchTarget(parsed.law_name))
        for article in parsed.articles:
            if article not in target.articles:
                target.articles.append(article)
        if reference not in target.references:
            target.references.append(reference)
    return list(targets.values())


def _get_kst_iso() -> str:
    """현재 한국 표준시(KST) 기준 ISO 8601 문자열을 반환한다."""
    return datetime.now(KST).isoformat()


def mask_api_key(text: str, key: Optional[str] = None) -> str:
    """로그 및 URL에 포함된 법제처 Open API 키를 마스킹([MASKED]) 처리한다.

    Args:
        text: 원본 문자열 또는 URL.
        key: 마스킹할 API 키 문자열 (옵션).

    Returns:
        str: 민감정보가 마스킹된 문자열.
    """
    if not text:
        return ""
    if key and key in text:
        text = text.replace(key, "[MASKED]")
    return re.sub(r"OC=[^&]+", "OC=[MASKED]", text)


def _fetch_xml_with_retry(
    url: str,
    api_key: Optional[str] = None,
    timeout: int = 10,
    max_retries: int = 1,
    backoff_seconds: float = 1.0,
) -> Optional[bytes]:
    """HTTPS 요청을 수행하고 네트워크/타임아웃 오류 발생 시 1회 지수 백오프로 재시도한다.

    Args:
        url: 요청 대상 HTTPS URL.
        api_key: 마스킹할 API 키.
        timeout: 타임아웃 초 (기본값: 10초).
        max_retries: 최대 재시도 횟수 (기본값: 1회).
        backoff_seconds: 재시도 대기 시간 초 (기본값: 1.0초).

    Returns:
        Optional[bytes]: 응답 바이트 데이터. 실패 시 None 반환.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "AILegalHelper/1.0"})
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            masked_url = mask_api_key(url, api_key)
            if attempt < max_retries:
                logger.warning(
                    f"[OFFICIAL_STATUTE] 요청 실패({type(e).__name__}), {backoff_seconds}초 후 재시도... URL: {masked_url}"
                )
                time.sleep(backoff_seconds)
            else:
                logger.error(
                    f"[OFFICIAL_STATUTE] 최종 요청 실패({type(e).__name__}): {mask_api_key(str(e), api_key)} URL: {masked_url}"
                )
    return None


@trace
def search_official_statutes(
    query: str,
    candidate_laws: List[str],
    effective_date: Optional[str] = None,
    missing_issues: Optional[List[str]] = None,
    max_articles_per_law: int = 10,
) -> List[Dict[str, Any]]:
    """법제처 국가법령정보공동활용 API를 호출하여 공식 법령 조문 원문을 실시간 검색한다.

    1. 후보에서 법령명과 명시 조문을 분리한 뒤 법령명만으로 법령 식별자(MST)를 조회한다.
       - 법령명 완전 일치(예: '민법' 검색 시 '난민법' 배제)를 우선 검증한다.
       - 일치하는 법령이 없을 경우 첫 번째 법령을 임의 선택하지 않고 즉시 제외(None Fallback)한다.
    2. 획득한 MST로 조문 상세 조회 API(`lawService.do`)를 HTTPS로 호출하여 조문 목록(XML)을 파싱한다.
    3. 명시 조문이 있으면 해당 조문만 선택하고, 없으면 일반화된 동적 가중치로 선별한다:
       - 법률검증 Agent가 식별한 누락 쟁점(`missing_issues`)에 조문 제목이 부합할 경우 최우선 순위(15.0x)를 부여한다.
       - 법령명 자체에 포함된 단어(예: '주택임대차보호법'의 '주택', '임대차')는 조문 전반에 빈출하므로 가중치를 감쇄(0.2x~0.3x, TF-IDF 원리)한다.
       - 특정 도메인 전용 하드코딩 없이 노동, 민사, 형사, 행정 등 모든 법률 분야에 범용적으로 동작한다.
    4. 각 조문의 본문, 항(項), 호(號) 텍스트를 취합하여 시스템 공통 표준 Source 스키마 딕셔너리로 변환한다.

    Args:
        query: 검색 목적이 되는 법률 질문 원문.
        candidate_laws: 공식 법령 후보 목록. 조문·제목이 붙은 입력도 분리하여 처리한다.
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

    for target in _prepare_search_targets(candidate_laws):
        law_name = clean_law_name = target.law_name
        requested_articles = set(target.articles)
        # 후보에 붙은 조문·제목은 외부 법령명 쿼리에서 제외하되 내부 검색 목적은 보존한다.
        target_query_text = " ".join([full_query_text, *target.references]).strip()
        missing_article_ids = set(_article_references(missing_text))
        query_article_ids = set(_article_references(target_query_text))

        try:
            # 1단계: 법제처 법령 목록 검색 (MST 획득, HTTPS 강제)
            encoded_name = urllib.parse.quote(clean_law_name)
            search_url = (
                f"https://www.law.go.kr/DRF/lawSearch.do?"
                f"OC={api_key}&target=law&type=XML&query={encoded_name}"
            )
            logger.info(f"[OFFICIAL_STATUTE] 법제처 법령 검색 호출: {clean_law_name}")

            search_xml_bytes = _fetch_xml_with_retry(search_url, api_key=api_key)
            if not search_xml_bytes:
                logger.warning(f"[OFFICIAL_STATUTE] '{clean_law_name}' 검색 응답 수신 실패")
                continue

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

            # 임의 법령 채택 fallback 제거: 일치하지 않으면 임의 채택하지 않고 건너뜀
            if matched_elem is None:
                logger.warning(f"[OFFICIAL_STATUTE] '{clean_law_name}' 법령을 법제처 검색 결과에서 찾지 못했습니다.")
                continue

            mst = matched_elem.findtext("법령일련번호") or matched_elem.findtext("일련번호")
            official_law_name = matched_elem.findtext("법령명한글") or clean_law_name
            law_type_name = (matched_elem.findtext("법령구분명") or "").strip()
            law_id = matched_elem.findtext("법령ID") or ""
            law_no = (matched_elem.findtext("공포번호") or "").strip()
            law_no_disp = f"제{law_no}호" if (law_no and not law_no.startswith("제")) else law_no
            eff_date_raw = (matched_elem.findtext("시행일자") or "").strip()
            prom_date_raw = (matched_elem.findtext("공포일자") or "").strip()
            
            # 시행일자 및 공포일자 YYYY-MM-DD 변환
            effective_date_str = ""
            if len(eff_date_raw) == 8:
                effective_date_str = f"{eff_date_raw[:4]}-{eff_date_raw[4:6]}-{eff_date_raw[6:]}"
            promulgation_date_str = ""
            if len(prom_date_raw) == 8:
                promulgation_date_str = f"{prom_date_raw[:4]}-{prom_date_raw[4:6]}-{prom_date_raw[6:]}"

            if not mst:
                logger.warning(f"[OFFICIAL_STATUTE] '{clean_law_name}'의 MST(일련번호)가 없습니다.")
                continue

            # 2단계: 법제처 조문 상세 조회 (HTTPS 강제)
            service_url = f"https://www.law.go.kr/DRF/lawService.do?OC={api_key}&target=law&MST={mst}&type=XML"
            detail_xml_bytes = _fetch_xml_with_retry(service_url, api_key=api_key)
            if not detail_xml_bytes:
                logger.warning(f"[OFFICIAL_STATUTE] '{official_law_name}' 상세 조문 응답 수신 실패")
                continue

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
                if requested_articles and article_label not in requested_articles:
                    continue

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

                # 3.0 조문 번호(예: "제536조", "제6조의2")가 누락 쟁점 및 질의 텍스트에 직접 언급된 경우 최우선 부스팅
                if article_label in requested_articles:
                    score += 100.0
                elif article_label in missing_article_ids:
                    score += 50.0
                elif article_label in query_article_ids:
                    score += 20.0

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
                    elif tw in target_query_text:
                        score += 5.0 * weight

                # 3.2 조문 본문 내 누락 쟁점 및 질문 키워드 매칭
                search_tokens = [
                    t for t in re.findall(r'[가-힣]{2,}|[A-Za-z0-9]{2,}', target_query_text)
                    if t not in {"경우", "따라", "관한", "대한", "질문", "관련", "어떻게", "있나요", "인가요", "언제", "시점", "여부", "내용", "확인", "필요"}
                ]
                for tok in search_tokens:
                    is_law_term = tok in law_subwords or any(sw in tok for sw in law_subwords if len(sw) >= 3)
                    weight = 0.2 if is_law_term else (2.0 if missing_text and tok in missing_text else 1.0)
                    if tok in full_article_text:
                        score += 1.0 * weight

                # 쿼리 키워드가 1개 이상 매칭되거나, 쿼리가 너무 짧을 경우 고려
                if score > 0 or not target_query_text:
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
            if not selected_articles and article_nodes and not requested_articles:
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

            if requested_articles:
                missing_requested = requested_articles - {item["article_label"] for item in selected_articles}
                if missing_requested:
                    # 요청한 조문이 없을 때 총칙 등 다른 조문을 성공 결과처럼 대신 반환하지 않는다.
                    logger.warning("[OFFICIAL_STATUTE] '%s' 요청 조문 미확보: %s",
                                   official_law_name, ", ".join(sorted(missing_requested)))

            # 4단계: 표준 Source 스키마 형태로 변환 (조문 제목·공포번호·시행일·법령구분 등 전체 상세 정보 반영)
            for item in selected_articles:
                art_label = item["article_label"]
                art_title = (item.get("article_title") or "").strip()
                art_full = f"{art_label}({art_title})" if art_title else art_label
                if law_no_disp and eff_date_raw:
                    doc_filename = f"{official_law_name}({law_type_name or '법률'})({law_no_disp})({eff_date_raw}).pdf"
                else:
                    doc_filename = f"{official_law_name}.pdf"

                meta_parts = [
                    p for p in (
                        law_type_name,
                        law_no_disp,
                        f"시행 {effective_date_str}" if effective_date_str else "",
                    ) if p
                ]
                meta_suffix = f" [{', '.join(meta_parts)}]" if meta_parts else ""
                detailed_title = f"{official_law_name} {art_full}{meta_suffix}"
                source_id = detailed_title

                source_dict = {
                    "source_id": source_id,
                    "source_type": "STATUTE",
                    "document_id": doc_filename,
                    "title": detailed_title,
                    "statute_name": official_law_name,
                    "article": art_label,
                    "article_title": art_title or None,
                    "law_id": law_id or None,
                    "version_id": mst or None,
                    "promulgation_date": promulgation_date_str or None,
                    "promulgation_number": law_no_disp or None,
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
            masked_err = mask_api_key(f"{type(e).__name__}: {str(e)}", api_key)
            logger.error(f"[OFFICIAL_STATUTE] 법령 '{law_name}' 검색 중 오류: {masked_err}")

    return retrieved_sources


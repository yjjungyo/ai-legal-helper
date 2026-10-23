# -*- coding: utf-8 -*-
"""
모듈명: timeline.py

[모듈 개요]
사건의 확정 사실(Fact) 목록으로부터 날짜 및 기간 정보를 추출·검증하여
시계열 타임라인 이벤트(Event)를 생성하는 엔진 모듈이다.

[핵심 설계 원칙 (P0-02)]
1. 다중 날짜 소스 지원:
   - `Fact.occurred_at`에만 의존하지 않고 `Fact.statement` 본문에서 직접 날짜 및 기간을 추출한다.
   - `conflict_detector.extract_dates_with_validation`을 재사용하여 달력상 유효하지 않은 날짜
     (예: `2026년 2월 31일`)는 타임라인 생성에서 즉시 배제한다.
   - `Fact.occurred_at`과 `Fact.statement` 내 날짜가 상충하면 본문 날짜를 우선하되
     `occurrence_status = "NEEDS_VERIFICATION"`으로 표시한다.
   - 날짜가 전혀 없는 사실에는 임의 날짜를 부여하지 않는다.
2. 다중 날짜(기간) 분리:
   - `"임대차 기간은 2022년 3월 1일부터 2024년 2월 28일까지이다"`와 같이 시작일과 종료일이
     함께 포함된 문장은 `계약 시작(2022-03-01)`과 `계약 종료(2024-02-28)`의 별도 Event로 분리한다.
3. 이벤트 의미(event_type) 및 발생 성격(occurrence_status) 구분:
   - 실제 발생(`ACTUAL`), 예정/기일(`SCHEDULED`), 요청 기한(`REQUESTED`), 검증 필요(`NEEDS_VERIFICATION`)를 구분한다.
   - 계약 체결, 계약 시작, 계약 종료, 지급기일, 금원 지급, 인도 예정일, 목적물 인도,
     통지 발송, 통지 도달, 퇴거 예정, 실제 퇴거, 반환 요청 기한, 지급 약속, 법적 절차를 분류한다.
4. 동일 날짜 다중 이벤트 보존:
   - 동일 날짜라도 서로 다른 법적 행위(예: 잔금 지급기일 vs 임대차 시작 vs 주택 인도 예정일)는
     별도의 Event로 보존하며, 동일한 의미의 사건을 복수의 Fact가 지지하는 경우에만 병합한다.
"""

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Dict, List, Optional, Tuple

from ai_legal_helper.case_intelligence.conflict_detector import extract_dates_with_validation
from ai_legal_helper.case_intelligence.fact_semantics import extract_semantic_fact
from ai_legal_helper.database.models import Event, Fact
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 기간(범위) 표현 정규식: "YYYY년 M월 D일부터 YYYY년 M월 D일까지" 또는 "YYYY-MM-DD ~ YYYY-MM-DD"
_DATE_TOKEN_PATTERN = (
    r"(?:\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}\.?)"
)
_DATE_RANGE_REGEX = re.compile(
    rf"(?P<start>{_DATE_TOKEN_PATTERN})\s*(?:부터|에서|~|∼)\s*(?P<end>{_DATE_TOKEN_PATTERN})\s*(?:까지)?"
)

# 대략적 시기(연·월 + 초/중순/말/경) 정규식 (뒤에 '일' 숫자가 오지 않는 경우만 매칭)
_APPROX_YEAR_MONTH_REGEX = re.compile(
    r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(초순?|중순|말일?|말경?|경|무렵|쯤))?(?!\s*\d{1,2}\s*일)"
)

# 시각(HH:MM) 추출 정규식
_TIME_REGEX = re.compile(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)")


@dataclass
class _CandidateEventSpec:
    """단일 Fact에서 도출된 개별 이벤트 후보 명세."""

    event_date: str
    date_precision: str
    event_type: str
    occurrence_status: str
    semantic_key: str
    title: str
    statement: str
    fact_id: Optional[str] = None
    extra_fact_ids: List[str] = field(default_factory=list)


def _extract_approximate_dates(text: str) -> List[Tuple[str, str]]:
    """문장에서 '일(day)' 없이 연·월 또는 초/중순/말/경으로 표현된 대략적 시기를 추출한다.

    Args:
        text: 검사할 문장 문자열.

    Returns:
        List[Tuple[str, str]]: `(정규화된 event_date 문자열, 수식어)` 튜플 리스트.
    """
    if not text:
        return []
    results: List[Tuple[str, str]] = []
    for match in _APPROX_YEAR_MONTH_REGEX.finditer(text):
        year = int(match.group(1))
        month = int(match.group(2))
        qualifier = (match.group(3) or "").strip()
        if not (1900 <= year <= 2100 and 1 <= month <= 12):
            continue
        iso_ym = f"{year:04d}-{month:02d}"
        results.append((iso_ym, qualifier))
    return results


def _infer_period_subject_label(statement: str) -> str:
    """기간 범위 문장에서 어떤 기간인지(임대차 기간, 계약 기간, 근로 기간 등) 라벨을 추론한다."""
    stmt = (statement or "").strip()
    if "임대차" in stmt:
        return "임대차 기간"
    if "전세" in stmt:
        return "전세 계약 기간"
    if "근로" in stmt or "고용" in stmt:
        return "근로계약 기간"
    if "용역" in stmt or "도급" in stmt:
        return "계약 기간"
    return "계약 기간"


def _classify_clause_semantics(
    clause: str,
    full_statement: str,
    needs_verification: bool = False,
) -> List[Tuple[str, str, str, Optional[str]]]:
    """문장(또는 날짜 주변 절)의 법적 행위 의미(event_type), 발생 상태(occurrence_status), 병합 키를 분류한다.

    하나의 문장이 동일 날짜에 대해 '이사/퇴거 예정'과 '보증금 반환 요청'을 동시에 담고 있는 경우
    복수의 이벤트 명세를 반환할 수 있다.

    Args:
        clause: 날짜 주변 문맥 문자열.
        full_statement: Fact 전체 진술문.
        needs_verification: occurred_at과 본문 날짜 불일치 여부.

    Returns:
        List[Tuple[str, str, str, Optional[str]]]:
            `(event_type, occurrence_status, semantic_key, custom_title)` 리스트.
    """
    text = f"{clause} {full_statement}".strip()
    compact = re.sub(r"\s+", "", text)

    def _status(default_status: str) -> str:
        return "NEEDS_VERIFICATION" if needs_verification else default_status

    # 1. 퇴거/이사 예정 및 보증금 반환 요청 기한이 명시된 경우 (단, '시:분' 타임스탬프가 있는 메시지 발송 자체 기록은 제외)
    has_timestamp = bool(_TIME_REGEX.search(full_statement)) or bool(
        re.search(r"\d{1,2}\s*시\s*\d{1,2}\s*분", full_statement)
    )
    has_moveout_sched = any(
        kw in compact
        for kw in (
            "이사예정",
            "퇴거예정",
            "이사할예정",
            "퇴거할예정",
            "이사나가야",
            "퇴거해야",
            "퇴거일",
            "이사일",
        )
    )
    has_return_req = any(
        kw in compact
        for kw in (
            "반환을요청",
            "반환요청",
            "반환을요구",
            "반환요구",
            "반환해야한다고요구",
            "반환이가능한지",
            "돌려달라",
            "지급을요청",
            "반환해달라",
        )
    )
    if not has_timestamp and (has_moveout_sched or has_return_req):
        specs: List[Tuple[str, str, str, Optional[str]]] = []
        if has_moveout_sched and not (
            "퇴거일에맞춰" in compact and "이사예정" not in compact and "퇴거예정" not in compact
        ):
            specs.append(("퇴거 예정", _status("SCHEDULED"), "MOVEOUT_SCHEDULED", None))
        if has_return_req:
            specs.append(("반환 요청 기한", _status("REQUESTED"), "RETURN_REQUESTED", None))
        if specs:
            return specs

    # 2. 통지·메시지·문자·내용증명 발송
    if any(
        kw in compact
        for kw in (
            "메시지를보냈",
            "문자를보냈",
            "내용증명을발송",
            "통지서를발송",
            "발송하였다",
            "발송함",
            "통보하였다",
            "통지하였다",
        )
    ):
        time_match = _TIME_REGEX.search(full_statement)
        if time_match:
            time_key = time_match.group(1)
        else:
            hm_match = re.search(r"(\d{1,2})\s*시\s*(\d{1,2})\s*분", full_statement)
            time_key = f"{int(hm_match.group(1)):02d}:{int(hm_match.group(2)):02d}" if hm_match else ""
        actor_match = re.search(r"([가-힣]{2,4})(?:은|는|이|가)\s+", full_statement)
        actor_key = actor_match.group(1) if actor_match is not None else ""
        sem_key = f"NOTICE_SENT:{actor_key}:{time_key}" if (actor_key or time_key) else f"NOTICE_SENT:{compact[:20]}"
        return [("통지 발송", _status("ACTUAL"), sem_key, None)]

    # 3. 통지·내용증명 도달/수령
    if any(kw in compact for kw in ("도달하였다", "송달되었다", "내용증명을수령", "통지를수령")):
        return [("통지 도달", _status("ACTUAL"), "NOTICE_REACHED", None)]

    # 4. 지급기일 / 납부기일 / 변제기 (예정된 금원 지급 일정)
    if any(kw in compact for kw in ("지급기일", "지급예정일", "납부기일", "변제기", "지급하기로")):
        if "계약금" in compact:
            sub = "계약금"
        elif "중도금" in compact:
            sub = "중도금"
        elif "잔금" in compact:
            sub = "잔금"
        elif "보증금" in compact or "전세금" in compact:
            sub = "보증금"
        elif "차임" in compact or "월세" in compact:
            sub = "차임"
        else:
            sub = "일반"
        return [("지급기일", _status("SCHEDULED"), f"PAYMENT_DUE:{sub}", None)]

    # 5. 목적물 인도·입주 예정일
    if any(kw in compact for kw in ("인도예정일", "인도기일", "입주예정일", "명도예정일", "인도하기로")):
        return [("인도 예정일", _status("SCHEDULED"), "DELIVERY_SCHEDULED", None)]

    # 6. 지급/반환 약속
    if any(
        kw in compact
        for kw in ("지급하겠다고", "반환하겠다고", "돌려주겠다고", "변제하겠다고", "약속하였다", "약속함")
    ):
        return [("지급 약속", _status("SCHEDULED"), "PAYMENT_PROMISED", None)]

    # 7. 계약 체결 / 작성
    if any(
        kw in compact
        for kw in (
            "계약을체결",
            "계약체결",
            "체결된",
            "체결하였",
            "계약서를작성",
            "계약서작성",
            "합의하였다",
            "약정하였다",
        )
    ):
        occ = "SCHEDULED" if "예정" in compact else "ACTUAL"
        return [("계약 체결", _status(occ), "CONTRACT_SIGNED", None)]

    # 8. 계약 시작 / 종료 (단일 날짜 문장인 경우)
    if any(kw in compact for kw in ("임대차개시", "계약시작", "개시일")):
        return [("계약 시작", _status("SCHEDULED"), "PERIOD_START:계약 기간", None)]
    if any(kw in compact for kw in ("만료일", "계약종료", "임대차종료", "계약만기")):
        return [("계약 종료", _status("SCHEDULED"), "PERIOD_END:계약 기간", None)]

    # 9. 실제 금원 지급 / 입금 / 송금
    if any(
        kw in compact
        for kw in ("지급하였다", "지급함", "입금하였다", "송금하였다", "납부하였다", "이체하였다", "변제하였다")
    ):
        if "계약금" in compact:
            ev_type = "계약금 지급"
        elif "중도금" in compact:
            ev_type = "중도금 지급"
        elif "잔금" in compact:
            ev_type = "잔금 지급"
        elif "보증금" in compact:
            ev_type = "보증금 지급"
        else:
            ev_type = "실제 지급"
        return [(ev_type, _status("ACTUAL"), f"PAYMENT_ACTUAL:{ev_type}", None)]

    # 10. 실제 목적물 인도 / 입주 / 전입신고
    if any(kw in compact for kw in ("인도하였다", "인도받았다", "입주하였다", "전입신고", "확정일자")):
        return [("목적물 인도", _status("ACTUAL"), f"DELIVERY_ACTUAL:{compact[:16]}", None)]

    # 11. 실제 퇴거 / 이사 완료
    if any(kw in compact for kw in ("퇴거하였다", "이사하였다", "공실로", "명도하였다", "퇴거완료")):
        return [("실제 퇴거", _status("ACTUAL"), "MOVEOUT_ACTUAL", None)]

    # 12. 공통 Fact Semantics 기반 도메인 분류 (근로계약 입사/퇴사, 채권채무 대여/변제, 소송절차 등)
    sem = extract_semantic_fact(full_statement)
    if sem.event_type == "EMPLOYMENT" and sem.event_subtype in ("HIRE", "RESIGNATION"):
        ev_title = "입사" if sem.event_subtype == "HIRE" else "퇴사"
        return [(ev_title, _status(sem.occurrence_status), f"EMPLOYMENT:{sem.event_subtype}", None)]
    if sem.event_type == "LOAN" and sem.event_subtype in ("LOAN_ORIGINATION", "PARTIAL_REPAYMENT"):
        ev_title = "대여 발생" if sem.event_subtype == "LOAN_ORIGINATION" else "일부 변제"
        return [(ev_title, _status(sem.occurrence_status), f"LOAN:{sem.event_subtype}", None)]
    if sem.event_type == "LITIGATION" and sem.event_subtype in ("COMPLAINT_FILING", "COMPLAINT_SERVICE", "HEARING_DATE", "JUDGMENT_PRONOUNCEMENT"):
        ev_title = "소장 제출" if sem.event_subtype == "COMPLAINT_FILING" else ("소장 송달" if sem.event_subtype == "COMPLAINT_SERVICE" else ("변론기일" if sem.event_subtype == "HEARING_DATE" else "판결 선고"))
        return [(ev_title, _status(sem.occurrence_status), f"LITIGATION:{sem.event_subtype}", None)]

    # 13. 법적 절차 (소 제기, 지급명령, 임차권등기 등)
    if any(
        kw in compact
        for kw in ("소를제기", "소송제기", "지급명령", "임차권등기", "가압류", "가처분", "경매", "판결선고")
    ):
        occ = "SCHEDULED" if ("예정" in compact or "기일" in compact) else "ACTUAL"
        return [("법적 절차", _status(occ), f"LEGAL_PROCEEDING:{compact[:18]}", None)]

    # 14. 일반 사실 (예정/기일/요청 키워드 유무에 따라 occurrence_status 결정, 문장별 고유 키 부여로 오병합 방지)
    if any(kw in compact for kw in ("예정", "기일", "하기로")):
        occ = "SCHEDULED"
    elif any(kw in compact for kw in ("요청", "촉구", "최고")):
        occ = "REQUESTED"
    else:
        occ = "ACTUAL"
    return [("사실 발생", _status(occ), f"GENERAL_FACT:{compact}", None)]


def _format_event_title(statement: str, custom_title: Optional[str] = None) -> str:
    """이벤트 제목을 가독성 있게 생성한다."""
    if custom_title:
        return custom_title
    clean = (statement or "").strip()
    return clean if len(clean) <= 65 else clean[:62] + "..."


def extract_events_from_fact(fact: Fact) -> List[_CandidateEventSpec]:
    """단일 Fact 객체에서 날짜·기간을 추출 및 검증하여 0개 이상의 이벤트 후보 명세를 반환한다.

    Args:
        fact: 분석 대상 Fact ORM 인스턴스.

    Returns:
        List[_CandidateEventSpec]: 추출된 이벤트 후보 리스트. 유효한 날짜가 없으면 빈 리스트.
    """
    statement = (fact.statement or "").strip()
    if not statement:
        return []

    stmt_valid_dates, stmt_invalid_dates, _stmt_roles = extract_dates_with_validation(statement)
    occurred_raw = (fact.occurred_at or "").strip()
    occ_valid_dates, occ_invalid_dates, _occ_roles = (
        extract_dates_with_validation(occurred_raw) if occurred_raw else ([], [], {})
    )

    # 잘못된 달력 날짜(예: 2026년 2월 31일)만 존재하고 유효한 날짜가 전혀 없는 경우 생성 거부 (T08)
    if (stmt_invalid_dates or occ_invalid_dates) and not stmt_valid_dates and not occ_valid_dates:
        logger.warning(
            "Skipping timeline event generation for fact %s due to invalid calendar date.",
            getattr(fact, "id", None),
        )
        return []

    # occurred_at과 statement 본문 날짜의 일치 여부 검증
    needs_verification = False
    if occ_valid_dates and stmt_valid_dates:
        if not set(occ_valid_dates).intersection(set(stmt_valid_dates)):
            needs_verification = True

    candidates: List[_CandidateEventSpec] = []

    # 1. 기간 범위("YYYY년 M월 D일부터 YYYY년 M월 D일까지") 우선 처리 (T06)
    range_match = _DATE_RANGE_REGEX.search(statement)
    if range_match:
        start_valid, start_invalid, _ = extract_dates_with_validation(range_match.group("start"))
        end_valid, end_invalid, _ = extract_dates_with_validation(range_match.group("end"))
        if start_valid and end_valid and not start_invalid and not end_invalid:
            start_iso = start_valid[0]
            end_iso = end_valid[0]
            period_label = _infer_period_subject_label(statement)
            status = "NEEDS_VERIFICATION" if needs_verification else "SCHEDULED"

            candidates.append(
                _CandidateEventSpec(
                    event_date=start_iso,
                    date_precision="EXACT",
                    event_type="계약 시작",
                    occurrence_status=status,
                    semantic_key=f"PERIOD_START:{period_label}",
                    title=f"{period_label} 시작 ({start_iso})",
                    statement=statement,
                    fact_id=fact.id,
                )
            )
            candidates.append(
                _CandidateEventSpec(
                    event_date=end_iso,
                    date_precision="EXACT",
                    event_type="계약 종료",
                    occurrence_status=status,
                    semantic_key=f"PERIOD_END:{period_label}",
                    title=f"{period_label} 종료 ({end_iso})",
                    statement=statement,
                    fact_id=fact.id,
                )
            )
            return candidates

    # 2. 본문(statement) 또는 occurred_at에서 유효한 정확한 일자(YYYY-MM-DD)가 추출된 경우
    effective_exact_dates = stmt_valid_dates if stmt_valid_dates else occ_valid_dates
    if effective_exact_dates:
        # 한 문장에 통지 발송일과 향후 예정일이 함께 있더라도, 통지 발송 문장은 발송일(첫 날짜) 중심으로 처리
        sem_list = _classify_clause_semantics(statement, statement, needs_verification=needs_verification)
        if len(effective_exact_dates) == 1 or (sem_list and sem_list[0][0] == "통지 발송"):
            target_date = effective_exact_dates[0]
            for ev_type, occ_status, sem_key, custom_title in sem_list:
                candidates.append(
                    _CandidateEventSpec(
                        event_date=target_date,
                        date_precision="EXACT",
                        event_type=ev_type,
                        occurrence_status=occ_status,
                        semantic_key=sem_key,
                        title=_format_event_title(statement, custom_title),
                        statement=statement,
                        fact_id=fact.id,
                    )
                )
        else:
            # 복수의 날짜가 나열된 문장인 경우 각 날짜별로 이벤트 생성
            for target_date in effective_exact_dates:
                for ev_type, occ_status, sem_key, custom_title in sem_list:
                    candidates.append(
                        _CandidateEventSpec(
                            event_date=target_date,
                            date_precision="EXACT",
                            event_type=ev_type,
                            occurrence_status=occ_status,
                            semantic_key=f"{sem_key}:{target_date}",
                            title=_format_event_title(statement, custom_title),
                            statement=statement,
                            fact_id=fact.id,
                        )
                    )
        return candidates

    # 3. 정확한 일자(day)는 없으나 유효한 대략적 연·월(예: "2026년 9월 말", "2024년 3월경")이 있는 경우
    if not stmt_invalid_dates and not occ_invalid_dates:
        approx_dates = _extract_approximate_dates(statement)
        if not approx_dates and occurred_raw:
            approx_dates = _extract_approximate_dates(occurred_raw)
        if approx_dates:
            ym_str, _qual = approx_dates[0]
            sem_list = _classify_clause_semantics(statement, statement, needs_verification=needs_verification)
            for ev_type, occ_status, sem_key, custom_title in sem_list:
                candidates.append(
                    _CandidateEventSpec(
                        event_date=ym_str,
                        date_precision="APPROXIMATE",
                        event_type=ev_type,
                        occurrence_status=occ_status,
                        semantic_key=sem_key,
                        title=_format_event_title(statement, custom_title),
                        statement=statement,
                        fact_id=fact.id,
                    )
                )

    return candidates


@trace
def build_timeline_from_facts(facts: List[Fact]) -> List[Event]:
    """사실관계(Fact) 리스트를 분석하여 시계열 타임라인 이벤트(Event) 목록을 구축한다.

    [동작 방식]
    1. 각 Fact에서 `extract_events_from_fact(fact)`를 통해 날짜·기간 및 이벤트 의미를 추출한다.
    2. `(event_date, event_type, occurrence_status, semantic_key)`가 완전히 일치하는 후보만
       하나의 Event로 병합하고 `related_fact_ids`와 설명(`description`)을 합친다.
    3. 동일 날짜라도 법적 행위 의미(`event_type` / `semantic_key`)가 다른 이벤트는
       개별 Event로 보존하여 정보 손실을 방지한다 (T07).
    4. 날짜 오름차순으로 정렬하여 반환한다.

    Args:
        facts (List[Fact]): 사건에 속한 모든 사실관계 객체 목록.

    Returns:
        List[Event]: 생성될 Event ORM 객체 목록 (메모리 상태, `source_type="EVIDENCE_DERIVED"`).
    """
    grouped: Dict[Tuple[str, str, str, str], List[_CandidateEventSpec]] = {}

    for fact in facts:
        specs = extract_events_from_fact(fact)
        for spec in specs:
            group_key = (
                spec.event_date,
                spec.event_type,
                spec.occurrence_status,
                spec.semantic_key,
            )
            if group_key not in grouped:
                grouped[group_key] = []
            grouped[group_key].append(spec)

    events: List[Event] = []
    for (event_date, event_type, occ_status, _sem_key), specs in grouped.items():
        primary = specs[0]
        related_ids: List[str] = []
        seen_fids = set()
        statements: List[str] = []
        seen_stmts = set()

        for sp in specs:
            if sp.fact_id and sp.fact_id not in seen_fids:
                seen_fids.add(sp.fact_id)
                related_ids.append(sp.fact_id)
            norm_s = "".join(sp.statement.split())
            if norm_s and norm_s not in seen_stmts:
                seen_stmts.add(norm_s)
                statements.append(f"- {sp.statement}")

        description = "\n".join(statements)
        precision = "APPROXIMATE" if any(s.date_precision == "APPROXIMATE" for s in specs) else "EXACT"

        event = Event(
            title=primary.title,
            description=description,
            event_date=event_date,
            date_precision=precision,
            event_type=event_type,
            occurrence_status=occ_status,
            source_type="EVIDENCE_DERIVED",
            related_fact_ids=related_ids,
        )
        events.append(event)

    events.sort(key=lambda e: (e.event_date or "", e.event_type or "", e.title or ""))
    return events

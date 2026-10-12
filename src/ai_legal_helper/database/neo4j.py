# -*- coding: utf-8 -*-
"""
모듈명: neo4j.py

[모듈 개요]
P2.4 Evidence GraphRAG에서 사용하는 Neo4j 연결을 관리한다.
Neo4j는 PostgreSQL(Source of Truth)에서 파생된 관계 탐색 전용 저장소이다.

[주요 기능]
1. 환경변수 기반 Neo4j Driver 지연(lazy) 생성
2. 연결 가용성 확인 및 실패 시 None 반환(Fallback)
3. 그래프 노드별 고유 ID 제약조건 초기화
4. 테스트/종료 시 드라이버 정리

[처리 흐름]
get_neo4j_driver()
  → (최초 1회) 환경변수 로드 → Driver 생성 → verify_connectivity
  → 성공: Driver 반환 / 실패: None 반환 + 재시도 쿨다운

[주요 의존성]
- neo4j (공식 Python 드라이버)
- python-dotenv

[주의사항]
- 모듈 import 시점에는 절대 연결하지 않는다. Neo4j 장애가 FastAPI 기동이나
  기존 P0~P2.3 기능(사건 조회, 법령 RAG)을 막지 않아야 하기 때문이다.
- 비밀번호 등 인증정보를 로그에 남기지 않는다.
"""

import os
import time
import logging
import threading
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

load_dotenv()

# 연결 실패 후 재시도까지 대기하는 시간(초).
# 매 요청마다 타임아웃을 기다리면 상담 응답이 크게 지연되므로 쿨다운을 둔다.
_RETRY_COOLDOWN_SEC = 30.0

# 그래프 스키마(P2_4_GRAPH_SCHEMA.md)의 노드별 고유 ID 제약조건.
# MERGE 기반 멱등 동기화가 중복 노드를 만들지 않도록 보장하고, ID 조회 성능을 확보한다.
_CONSTRAINTS = [
    "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (n:Case) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT party_id IF NOT EXISTS FOR (n:Party) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT issue_id IF NOT EXISTS FOR (n:LegalIssue) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_doc_id IF NOT EXISTS FOR (n:EvidenceDocument) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_span_id IF NOT EXISTS FOR (n:EvidenceSpan) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_claim_id IF NOT EXISTS FOR (n:EvidenceClaim) REQUIRE n.id IS UNIQUE",
    # case_id 격리 조회 성능을 위한 보조 인덱스
    "CREATE INDEX fact_case IF NOT EXISTS FOR (n:Fact) ON (n.case_id)",
    "CREATE INDEX claim_case IF NOT EXISTS FOR (n:EvidenceClaim) ON (n.case_id)",
    "CREATE INDEX span_case IF NOT EXISTS FOR (n:EvidenceSpan) ON (n.case_id)",
]


class Neo4jConnectionManager:
    """Neo4j Driver의 생성·재사용·종료를 담당한다.

    프로세스 내에서 하나의 Driver를 공유한다(Driver는 내부적으로 커넥션 풀을 가진다).

    Attributes:
        _driver: 생성된 Driver. 미연결/장애 상태에서는 None.
        _last_failure: 마지막 연결 실패 시각(epoch). 쿨다운 판단에 사용.
        _schema_ready: 제약조건 초기화 완료 여부.
    """

    def __init__(self) -> None:
        self._driver: Optional[Driver] = None
        self._last_failure: float = 0.0
        self._schema_ready: bool = False
        self._lock = threading.Lock()

    def get_driver(self) -> Optional[Driver]:
        """사용 가능한 Driver를 반환하고, 불가하면 None을 반환한다.

        Returns:
            연결 검증된 Driver 또는 None(Neo4j 비활성/장애/쿨다운 중).

        Notes:
            예외를 던지지 않는다. 호출자는 None일 때 Graph 없이 진행(Fallback)해야 한다.
        """
        if self._driver is not None:
            return self._driver

        # NEO4J_ENABLED=false 로 명시적으로 그래프 기능을 끌 수 있다(테스트/경량 실행용).
        if os.getenv("NEO4J_ENABLED", "true").lower() in ("0", "false", "no"):
            return None

        # 최근 실패했다면 쿨다운 동안 재시도하지 않는다.
        if time.time() - self._last_failure < _RETRY_COOLDOWN_SEC:
            return None

        with self._lock:
            if self._driver is not None:
                return self._driver
            uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "")
            try:
                driver = GraphDatabase.driver(
                    uri, auth=(user, password), connection_timeout=3.0
                )
                driver.verify_connectivity()
                self._driver = driver
                logger.info("Neo4j 연결 성공")
            except Exception as e:  # 연결 거부, 인증 실패 등
                # 인증정보 노출 방지를 위해 예외 유형만 기록한다.
                logger.warning(f"Neo4j 연결 불가 - Graph 기능 비활성화(Fallback): {type(e).__name__}")
                self._last_failure = time.time()
                return None

        self._ensure_schema()
        return self._driver

    def _ensure_schema(self) -> None:
        """제약조건/인덱스를 1회 생성한다. 실패해도 연결 자체는 유지한다."""
        if self._schema_ready or self._driver is None:
            return
        try:
            with self._driver.session() as session:
                for q in _CONSTRAINTS:
                    session.run(q)
            self._schema_ready = True
        except Exception as e:
            logger.warning(f"Neo4j 스키마 초기화 실패: {type(e).__name__}")

    def close(self) -> None:
        """Driver를 종료하고 상태를 초기화한다(앱 종료/테스트 정리 시 호출)."""
        if self._driver is not None:
            try:
                self._driver.close()
            finally:
                self._driver = None
                self._schema_ready = False
                logger.info("Neo4j 연결 종료")


# 전역 매니저 인스턴스. 생성자는 연결을 시도하지 않는다.
neo4j_manager = Neo4jConnectionManager()


def get_neo4j_driver() -> Optional[Driver]:
    """전역 Neo4j Driver를 반환한다. 사용할 수 없으면 None."""
    return neo4j_manager.get_driver()

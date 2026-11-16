#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export Langfuse traces (including every observation) to reviewable JSON.

Works with self-hosted Langfuse v3 (legacy trace + v1 observations API)
and Langfuse v4 (v2 observations API). Uses Python's standard library only.
No Langfuse API credentials are included in exported files.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_HOST = "http://localhost:3001"
DEFAULT_PROJECT = "cmv56sw2u00063wm9ivtyrtdj"
HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "langfuse_trace_manifest_sc001_sc003.csv"
V2_FIELDS = "core,basic,time,io,metadata,model,usage,metrics,trace_context"
MAX_PAGES = 1000


class ApiError(RuntimeError):
    def __init__(self, status: int, path: str, message: str):
        self.status = status
        self.path = path
        super().__init__(f"HTTP {status} ({path}): {message}")


def load_local_env(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE lines without importing the whole application."""
    result: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[key.strip()] = value
    return result


def credentials(env_file: Path) -> tuple[str, str, str]:
    conf = load_local_env(env_file)
    # Environment variables take precedence. Never write or log key material.
    host = os.environ.get("LANGFUSE_HOST") or conf.get("LANGFUSE_HOST") or DEFAULT_HOST
    public = os.environ.get("LANGFUSE_PUBLIC_KEY") or conf.get("LANGFUSE_PUBLIC_KEY") or ""
    secret = os.environ.get("LANGFUSE_SECRET_KEY") or conf.get("LANGFUSE_SECRET_KEY") or ""
    if not public or not secret:
        raise ValueError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 설정이 필요합니다 (--env-file 참조).")
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("LANGFUSE_HOST는 http(s)://host:port 형식이어야 합니다.")
    return host.rstrip("/"), public, secret


class LangfuseReader:
    def __init__(self, host: str, public: str, secret: str, timeout: float = 30.0):
        self.host = host
        self.timeout = timeout
        basic = base64.b64encode(f"{public}:{secret}".encode("utf-8")).decode("ascii")
        self.headers = {"Authorization": f"Basic {basic}", "Accept": "application/json"}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(params or {})
        url = self.host + path + ("?" + query if query else "")
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError(f"API 응답이 JSON 객체가 아닙니다: {path}")
                return data
            except urllib.error.HTTPError as e:
                status = e.code
                if status in (429, 500, 502, 503, 504) and attempt < 3:
                    retry = e.headers.get("Retry-After")
                    try:
                        delay = min(15.0, max(0.1, float(retry))) if retry else 1.5 * (attempt + 1)
                    except ValueError:
                        delay = 1.5 * (attempt + 1)
                    time.sleep(delay)
                    continue
                # Avoid logging response body, which may contain private user data.
                raise ApiError(status, path, "API 요청 실패") from None
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ConnectionError(f"Langfuse 서버 연결 실패: {self.host} ({type(e.reason).__name__})") from None
        raise RuntimeError("요청 재시도 실패")

    @staticmethod
    def _validate_rows(rows: Any, trace_id: str, path: str) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            raise ValueError(f"Observations data 배열이 없습니다: {path}")
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Observation 객체 형식 오류: {path}")
            row_tid = row.get("traceId") or row.get("trace_id")
            if row_tid and row_tid != trace_id:
                raise ValueError(f"다른 Trace의 Observation이 혼합되었습니다: {path}")
            output.append(row)
        return output

    def observations_v1(self, trace_id: str) -> list[dict[str, Any]]:
        path = "/api/public/observations"
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while page <= MAX_PAGES:
            response = self.get(path, {"traceId": trace_id, "limit": 100, "page": page})
            rows = self._validate_rows(response.get("data"), trace_id, path)
            for obs in rows:
                oid = str(obs.get("id") or "")
                if oid and oid in seen:
                    continue
                if oid:
                    seen.add(oid)
                items.append(obs)
            meta = response.get("meta") or {}
            total_pages = meta.get("totalPages")
            if isinstance(total_pages, int) and total_pages > 0:
                if page >= total_pages:
                    return items
            elif len(rows) < 100:
                return items
            if rows and all(str(x.get("id") or "") in seen for x in rows) and page > 1:
                # No guard based on this condition: duplication can be legitimate
                # if the backend pages through overlapping data. MAX_PAGES bounds it.
                pass
            page += 1
        raise RuntimeError(f"Observation v1 페이지 수가 {MAX_PAGES}회를 초과했습니다: {trace_id}")

    def observations_v2(self, trace_id: str) -> list[dict[str, Any]]:
        path = "/api/public/v2/observations"
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"traceId": trace_id, "limit": 1000, "fields": V2_FIELDS}
            if cursor:
                params["cursor"] = cursor
            response = self.get(path, params)
            rows = self._validate_rows(response.get("data"), trace_id, path)
            for obs in rows:
                oid = str(obs.get("id") or "")
                if oid and oid in seen:
                    continue
                if oid:
                    seen.add(oid)
                items.append(obs)
            meta = response.get("meta") or {}
            next_cursor = meta.get("cursor")
            if not next_cursor:
                return items
            if not isinstance(next_cursor, str) or next_cursor in cursors:
                raise ValueError("Langfuse v2 cursor가 반복되거나 잘못되었습니다.")
            cursors.add(next_cursor)
            cursor = next_cursor
        raise RuntimeError(f"Observation v2 페이지 수가 {MAX_PAGES}회를 초과했습니다: {trace_id}")

    def export(self, trace_id: str) -> tuple[dict[str, Any], str, list[str]]:
        """Prefer legacy full trace on v3; fallback to observations v2 on v4."""
        warnings: list[str] = []
        raw_trace: dict[str, Any] | None = None
        try:
            raw_trace = self.get(f"/api/public/traces/{trace_id}")
        except ApiError as exc:
            if exc.status not in (404, 405, 410):
                raise

        if raw_trace:
            if raw_trace.get("id") and raw_trace["id"] != trace_id:
                raise ValueError("서버가 요청과 다른 Trace ID를 반환했습니다.")
            inline = self._validate_rows(raw_trace.get("observations") or [], trace_id, "trace.observations")
            try:
                paginated = self.observations_v1(trace_id)
                if len(paginated) >= len(inline):
                    observations = paginated
                else:
                    observations = inline
                    warnings.append("v1 API 조회 수가 Trace 내장 observations보다 적어 내장 데이터를 보존했습니다.")
            except ApiError as exc:
                if exc.status not in (404, 405, 410):
                    raise
                observations = inline
                warnings.append("v1 Observations API를 사용할 수 없어 Trace 내장 목록을 사용했습니다.")
            if not observations:
                # Legacy trace might not embed observations on some server versions.
                observations = self.observations_v2(trace_id)
                warnings.append("v1 데이터가 비어 v2 Observations API를 사용했습니다.")
            if not observations:
                raise ValueError("Observation이 0건입니다. 수집 지연 또는 Trace ID를 확인하세요.")
            raw_trace["observations"] = observations
            return raw_trace, "legacy_trace_v1_observations", warnings

        observations = self.observations_v2(trace_id)
        if not observations:
            raise ValueError("v2 Observations API가 0건을 반환했습니다. Trace ID / 적재 지연을 확인하세요.")
        # v4 does not have a legacy trace detail API. Preserve a familiar
        # langfuse_trace object so existing analysis scripts can read observations.
        return {"id": trace_id, "observations": observations}, "v2_observations", warnings


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    required = {"case_id", "step", "service", "trace_id"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Manifest CSV에는 case_id,step,service,trace_id 헤더와 1개 이상의 행이 필요합니다.")
    return [{key: str(value or "").strip() for key, value in row.items()} for row in rows]


def read_ids_file(path: Path, case_id: str, step: str, service: str) -> list[dict[str, str]]:
    """Read a UTF-8 text file with one Trace UUID per line, in input order.

    Empty lines and lines starting with '#' are ignored. Each requested ID
    remains an independent export task, so one invalid ID/API failure does
    not prevent later IDs from being processed by main().
    """
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        trace_id = raw.strip()
        if not trace_id or trace_id.startswith("#"):
            continue
        # Never overwrite a previous export because the same ID is listed twice.
        dedupe_key = trace_id.lower()
        if dedupe_key in seen:
            raise ValueError(f"{path}:{line_number}: 중복 Trace ID: {trace_id}")
        seen.add(dedupe_key)
        rows.append({"case_id": case_id, "step": step, "service": service, "trace_id": trace_id})
    if not rows:
        raise ValueError(f"Trace ID 목록 파일이 비어 있습니다: {path}")
    return rows


def safe_filename(row: dict[str, str]) -> str:
    def clean(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", s.strip()).strip("_")
    trace_id = str(uuid.UUID(row["trace_id"]))
    return f'{clean(row["case_id"])}_step{clean(row["step"])}_{clean(row["service"])}_{trace_id}.json'


def save_json(path: Path, payload: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Langfuse Trace ID별 JSON 일괄 추출")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--manifest", type=Path, help="case_id,step,service,trace_id CSV 파일")
    group.add_argument("--all", action="store_true", help="제공된 SC-001~SC-003 25건 일괄")
    group.add_argument("--trace-id", action="append", help="단일 ID 또는 여러 --trace-id")
    group.add_argument("--ids-file", type=Path, help="Trace ID를 한 줄씩 기록한 UTF-8 TXT 파일")
    parser.add_argument("--case-id", default="manual", help="--trace-id의 사건명")
    parser.add_argument("--step", default="1", help="--trace-id의 단계")
    parser.add_argument("--service", default="Manual", help="--trace-id의 서비스")
    parser.add_argument("--env-file", type=Path, default=Path("backend/.env"), help="인증정보 파일 (기본: backend/.env)")
    parser.add_argument("--host", help="Langfuse URL (미지정 시 환경변수/.env 사용)")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT)
    parser.add_argument("--out", type=Path, default=Path("artifacts/langfuse_trace_export"))
    parser.add_argument("--zip", action="store_true", help="성공한 JSON과 목록을 ZIP 파일로 묶음")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.2, help="Trace 간 요청 간격(초)")
    parser.add_argument("--fail-fast", action="store_true", help="첫 조회 실패 시 중단")
    args = parser.parse_args(argv)
    if args.host:
        os.environ["LANGFUSE_HOST"] = args.host
    try:
        host, public, secret = credentials(args.env_file)
        reader = LangfuseReader(host, public, secret, timeout=args.timeout)
        if args.all or args.manifest:
            rows = read_manifest(DEFAULT_MANIFEST if args.all else args.manifest)
        elif args.ids_file:
            rows = read_ids_file(args.ids_file, args.case_id, args.step, args.service)
        else:
            rows = [{"case_id": args.case_id, "step": args.step, "service": args.service, "trace_id": tid}
                    for tid in args.trace_id]
        args.out.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as exc:
        print(f"[설정 오류] {exc}", file=sys.stderr)
        return 2

    exported_at = datetime.now(timezone.utc).isoformat()
    catalog: list[dict[str, Any]] = []
    successful_paths: list[Path] = []
    for index, row in enumerate(rows, 1):
        try:
            filename = safe_filename(row)
            trace_id = str(uuid.UUID(row["trace_id"]))
            trace, api_mode, warnings = reader.export(trace_id)
            observations = trace.get("observations") or []
            project_id = trace.get("projectId")
            if project_id and args.project_id and project_id != args.project_id:
                raise ValueError("프로젝트 ID가 지정한 프로젝트와 다릅니다.")
            payload = {
                "export_metadata": {
                    **row,
                    "tag": f'step{row["step"]}',
                    "project_id": args.project_id,
                    "exported_at": exported_at,
                    "langfuse_fetched": True,
                    "api_mode": api_mode,
                    "observation_count": len(observations),
                    "warnings": warnings,
                },
                "langfuse_trace": trace,
            }
            path = args.out / filename
            save_json(path, payload)
            successful_paths.append(path)
            catalog.append({**row, "status": "OK", "file": filename,
                            "observations": len(observations), "api_mode": api_mode, "warnings": warnings})
            print(f"[{index}/{len(rows)}] OK   {row['case_id']} {row['step']} {row['service']}: {len(observations)} obs → {filename}")
        except (ApiError, ValueError, ConnectionError, RuntimeError, OSError) as exc:
            # Failures must be visible; do not write fake/success-looking JSON.
            message = str(exc)
            catalog.append({**row, "status": "FAILED", "error": message})
            print(f"[{index}/{len(rows)}] FAIL {row.get('trace_id')}: {message}", file=sys.stderr)
            if args.fail_fast:
                break
        if args.delay > 0:
            time.sleep(args.delay)

    summary = {"exported_at": exported_at, "source_host": host,
               "project_id": args.project_id, "requested": len(rows),
               "success": len(successful_paths), "failed": len(catalog) - len(successful_paths),
               "traces": catalog}
    summary_path = args.out / "export_manifest.json"
    save_json(summary_path, summary)
    if args.zip:
        archive = args.out.parent / (args.out.name + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in successful_paths + [summary_path]:
                z.write(p, arcname=p.name)
        print(f"ZIP: {archive}")
    print(f"완료: {len(successful_paths)}/{len(rows)} 성공, 결과 목록: {summary_path}")
    return 0 if len(successful_paths) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
모듈명: cli.py

[역할]
AI Legal Helper Evaluation Harness의 커맨드 라인 인터페이스(CLI).
개발지시서에 명시된 주요 명령어(validate-gold, run, compare 등)를 명령줄에서 바로 실행할 수 있도록 지원한다.

[지원 명령어]
1. `validate-gold`: 골드 정답 데이터셋의 스키마 및 무결성 검증
2. `run`: 평가 시나리오 일괄 실행 및 베이스라인 성적표 산출
3. `compare`: Baseline과 Candidate 간의 회귀 분석 및 지표 비교
4. `show-manifest`: 원문 증거 디렉토리와 DB 상태 매니페스트 출력
5. `list-scenarios`: 사용 가능한 시나리오 목록 조회
"""

import sys
import argparse
from pathlib import Path

# Windows 콘솔 인코딩 UTF-8 설정
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from evaluation_harness.config import config
from evaluation_harness.gold.gold_validator import GoldValidator
from evaluation_harness.datasets.loader import load_gold_case, load_evidence_manifest, list_scenarios
from evaluation_harness.runner import EvaluationRunner
from evaluation_harness.reporters.comparison_reporter import ComparisonReporter


def cmd_validate_gold(args):
    """골드 데이터셋 무결성을 검증한다."""
    scenarios = load_gold_case()
    print(f"\n[Gold Dataset 검증] 총 {len(scenarios)}개 시나리오 점검 중...")
    is_valid, errors = GoldValidator.validate_dataset(scenarios)

    if is_valid:
        print("[SUCCESS] 모든 골드 시나리오가 스키마 규격 및 안전성 규칙을 완벽히 통과했습니다.")
        sys.exit(0)
    else:
        print("[FAILED] 다음 시나리오에서 정합성 결함이 발견되었습니다:")
        for sc_id, errs in errors.items():
            print(f"  - [{sc_id}]:")
            for e in errs:
                print(f"      • {e}")
        sys.exit(1)


def cmd_run(args):
    """평가 러너를 실행한다."""
    print(f"\n[Evaluation Run] 데이터셋: {args.dataset}, 프로파일: {args.profile}")
    scenario_ids = [s.strip() for s in args.scenarios.split(",")] if args.scenarios else None

    runner = EvaluationRunner(case_id=args.case_id)
    summary = runner.run_evaluation(
        dataset_name=args.dataset,
        scenario_ids=scenario_ids,
        run_id=args.run_id,
        auto_approve_hilt=not args.no_auto_approve,
    )

    print("\n" + "=" * 60)
    print(f"[RUN FINISHED] Run ID: {summary.run_id}")
    print(f"소요 시간: {summary.duration_seconds}초")
    print(f"총 시나리오: {summary.total_scenarios}건 | 통과: {summary.passed_scenarios}건 ({summary.pass_rate}%)")
    print(f"치명적 결함(Critical Failures): {summary.critical_failures_count}건")
    print(f"종합 평균 점수: {summary.average_overall_score} / 1.000")
    print(f"산출물 저장 디렉토리: {summary.output_directory}")
    print("=" * 60 + "\n")


def cmd_compare(args):
    """두 평가 실행 결과를 비교한다."""
    baseline_dir = Path(args.baseline)
    candidate_dir = Path(args.candidate)

    if not baseline_dir.is_absolute():
        baseline_dir = config.results_dir / args.baseline
    if not candidate_dir.is_absolute():
        candidate_dir = config.results_dir / args.candidate

    print(f"\n[Run Comparison] 대조: {baseline_dir.name} vs {candidate_dir.name}")
    reporter = ComparisonReporter(baseline_dir=baseline_dir, candidate_dir=candidate_dir)
    diff = reporter.compare()
    md = reporter.generate_comparison_markdown(diff)

    print("\n" + md + "\n")


def cmd_show_manifest(args):
    """증거 매니페스트를 출력한다."""
    manifest = load_evidence_manifest(case_id=args.case_id)
    print(f"\n[Evidence Manifest] 사건: {manifest.case_name} (DB Case ID: {manifest.db_case_id})")
    print(f"원문 디렉토리: {manifest.source_dir}")
    print(f"원문 파일 수: {manifest.total_raw_files}건 | DB 등록 승인 건수: {manifest.db_registered_count}건\n")
    print("| 라벨 | 파일명 | 크기(Bytes) | SHA-256 (앞 10자리) | DB 등록 상태 |")
    print("|---|---|---|---|---|")
    for f in manifest.files:
        db_stat = f"[등록] {f.db_status}" if f.is_in_db else "[미등록]"
        print(f"| {f.label} | {f.filename} | {f.size_bytes} | {f.sha256[:10]}... | {db_stat} |")
    if manifest.missing_files_in_db:
        print(f"\nDB 미등록 파일 ({len(manifest.missing_files_in_db)}건): {', '.join(manifest.missing_files_in_db)}\n")


def cmd_list_scenarios(args):
    """시나리오 목록을 출력한다."""
    scenarios = load_gold_case()
    print(f"\n[Gold Scenarios] 총 {len(scenarios)}건\n")
    print("| ID | 구분 | 제목 |")
    print("|---|---|---|")
    for s in scenarios:
        category = "Core" if s.scenario_id.startswith("SC01-T") else "Variation"
        print(f"| {s.scenario_id} | {category} | {s.title} |")
    print("")


def main():
    parser = argparse.ArgumentParser(description="AI Legal Helper Evaluation Harness v1.0 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate-gold
    p_val = subparsers.add_parser("validate-gold", help="골드 데이터셋 스키마 및 무결성 검증")
    p_val.add_argument("--dataset", default="sc001_dev", help="데이터셋 이름")
    p_val.set_defaults(func=cmd_validate_gold)

    # run
    p_run = subparsers.add_parser("run", help="평가 시나리오 일괄 실행")
    p_run.add_argument("--dataset", default="sc001_dev", help="데이터셋 이름")
    p_run.add_argument("--case-id", default=config.default_case_id, help="사건 UUID")
    p_run.add_argument("--profile", default="isolated", choices=["isolated", "e2e"], help="실행 프로파일")
    p_run.add_argument("--scenarios", default=None, help="실행할 시나리오 ID 콤마 구분 (예: SC01-T01,SC01-T02)")
    p_run.add_argument("--run-id", default=None, help="평가 실행 ID")
    p_run.add_argument("--no-auto-approve", action="store_true", help="HILT 승인 요청 시 자동 승인 비활성화")
    p_run.set_defaults(func=cmd_run)

    # compare
    p_cmp = subparsers.add_parser("compare", help="두 평가 실행 결과 비교")
    p_cmp.add_argument("--baseline", required=True, help="베이스라인 디렉토리명")
    p_cmp.add_argument("--candidate", required=True, help="비교 대상 디렉토리명")
    p_cmp.set_defaults(func=cmd_compare)

    # show-manifest
    p_man = subparsers.add_parser("show-manifest", help="원문 증거 및 DB 정합성 매니페스트 확인")
    p_man.add_argument("--case-id", default=config.default_case_id, help="사건 UUID")
    p_man.set_defaults(func=cmd_show_manifest)

    # list-scenarios
    p_list = subparsers.add_parser("list-scenarios", help="사용 가능한 시나리오 목록 확인")
    p_list.set_defaults(func=cmd_list_scenarios)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

/**
 * @fileoverview 법률 상담 답변 내 증거 인용 태그([E01], [E02] 등) 컴포넌트
 * 답변 텍스트 중 증거 문서 식별자를 시각적으로 강조하며, 클릭 시 우측 슬라이드오버
 * 증거 원문 및 발췌 패널을 호출하여 사용자가 즉시 출처를 확인할 수 있도록 지원합니다.
 */

import React from 'react';

export interface EvidenceCitationProps {
  /** 증거 식별자 라벨 (예: "E01", "E02") */
  label: string;
  /** 클릭 시 호출되는 콜백 함수 */
  onClick?: (label: string) => void;
}

/**
 * 인라인 증거 번호 인용 뱃지 버튼 컴포넌트
 * @param props 증거 라벨 및 클릭 핸들러
 * @returns 클릭 가능한 인라인 증거 태그 JSX
 */
export const EvidenceCitation: React.FC<EvidenceCitationProps> = ({ label, onClick }) => {
  return (
    <button
      type="button"
      onClick={(e) => {
        // 부모 이벤트 전파 방지 및 출처 드로어 열기
        e.stopPropagation();
        onClick?.(label);
      }}
      className="chat-evidence-tag"
      title={`증거 [${label}] 원문 및 발췌 확인`}
      aria-label={`증거 ${label} 원문 보기`}
    >
      [{label}]
    </button>
  );
};


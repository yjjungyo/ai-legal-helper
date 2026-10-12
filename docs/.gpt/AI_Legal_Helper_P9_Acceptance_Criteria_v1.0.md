# P9 통합 검수기준


## 공통 승인 Gate
1. 설계/Scope 준수
2. 기존 구조 재사용 및 불필요한 중복 금지
3. Input/Output Contract 준수
4. 오류/UNKNOWN 처리
5. Traceability 유지
6. 자동 테스트 PASS
7. Regression 없음
8. 승인되지 않은 Architecture 변경 없음
9. 보안/민감정보 악화 없음
10. 다음 Phase가 사용할 수 있는 명확한 산출물

판정: `APPROVED / APPROVED WITH MINOR FIX / REJECTED / BLOCKED`

## P9 특별 Gate
`AI_Legal_Helper_P9_Evaluation_and_Test_Design_v1.0.md`의 DoD 및 핵심 원칙을 모두 검증한다. Phase의 핵심 기능이 Fixture/E2E 또는 자동 테스트로 증명되지 않으면 승인하지 않는다.

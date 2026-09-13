# StartupRadar 2.0

GFC 회원을 위한 창업 지원 공고 수집·조건 확인·추천 서비스입니다. K-Startup과 기업마당의 공식 API에서 공고와 첨부 근거를 수집하고, 팀 프로필에 따라 지원 조건과 추천 이유를 제공합니다.

## 사용 및 구조

- 회원 화면: https://www.gfc-startup.com/notice
- 기존 GFC React/Vercel 웹에서 Supabase 인증과 RPC를 사용합니다. 회원 여부와 팀 권한은 서버에서도 검증합니다.
- Python 배치는 GitHub Actions에서 수집·문서 분석·판정·추천·Telegram 알림을 처리합니다. 별도 상시 Python 웹 호스트는 필요하지 않습니다.
- 공유 GFC Supabase의 `startup_radar` 스키마에 출처, 원문, 문서, 버전, 판정과 알림 이력을 보존합니다.
- 프로필 변경은 계산 요청으로 저장되고 다음 배치에서 반영됩니다. 계산 중에는 이전 점수를 현재 결과처럼 표시하지 않습니다.

## 범위와 한계

현재 수집 범위는 두 공식 API의 제한된 최신 공고와 K-Startup의 주요 모집 공고군입니다. 전국·과거 공고 전수 수집을 보장하지 않습니다. 문서 파싱 실패와 확인되지 않은 자격 조건은 미확인으로 남기며, 약한 근거로 지원 가능이나 높은 확신의 알림을 만들지 않습니다. 추천은 선정 또는 최종 신청 자격을 보장하지 않습니다.

[운영 일정·설정·장애 복구·V1 롤백](docs/PRODUCTION-OPERATIONS.md), [배포 안내](docs/DEPLOYMENT.md), [구조와 한계](docs/ARCHITECTURE.md), [출처 추가](docs/SOURCES.md)를 참고하세요. 실제 자동 실행 여부는 저장소 변수와 운영 DB 설정이 기준입니다.

이전 구현과 감사 기록은 보존합니다. [V1 README와 이전 전환 기록](docs/LEGACY-V1-README.md)의 상태 설명은 작성 시점의 기록이며 현재 운영 상태를 의미하지 않습니다.

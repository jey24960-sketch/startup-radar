# StartupRadar V2 배포

웹은 기존 GFC Vercel 프로젝트, 인증·DB는 공유 Supabase `etvffzxqdgblvkfdikwl`, 배치는 StartupRadar 저장소의 `startup_radar_v2.yml`입니다. 두 저장소의 통합 변경은 main에 반영되어 있습니다. 별도 Python HTTP 서버는 필수가 아닙니다.

## 환경

GitHub Actions Secrets: `RADAR_DATABASE_URL`, `ANTHROPIC_API_KEY`, `KSTARTUP_API_KEY`, `BIZINFO_API_KEY`, `TELEGRAM_BOT_TOKEN`.

작업 환경에서는 DB 주소를 `DATABASE_URL`로 전달합니다. 로컬 `.env.worker`는 보존하되 버전 관리나 브라우저에 넣지 않습니다. GFC 웹에는 기존 공개 Supabase 설정만 사용하며 서버 키를 넣지 않습니다.

## 실행 및 수락

수동 실행은 `workflow_dispatch`의 INGEST, REFRESH, DIGEST, REMINDER, HIGH_FIT, TICK을 사용합니다. 수동 실행은 정기 실행 gate와 별개입니다. 실제 발송 여부는 `RADAR_V2_DELIVERY_ENABLED`가 결정합니다.

정기 실행에는 `RADAR_V2_ENABLED=true`와 DB scheduling 설정이 모두 필요합니다. 파일에 cron이 있다고 실제 운영 중인 것은 아닙니다. 실제 권한, 두 API 수집·저장, 회원의 실제 공고 조회, 실패 표시, 불확실한 근거 차단을 검증한 뒤 활성화합니다.

중단된 작업은 GitHub 실행이 실제 종료됐는지 확인한 다음 실행 소유 기록을 복구합니다. 타임아웃만으로 다른 작업을 시작하지 않습니다. 코드와 데이터는 보존하며, 수집 설정을 전체 재등록하지 않습니다.

정확한 일정과 제한, Telegram 0명 처리, 중단·복구 및 V1 롤백은 [운영 안내](PRODUCTION-OPERATIONS.md)를 따릅니다. 이전 단계의 상세 검증 기록은 해당 날짜의 감사 문서에 보존되어 있습니다.

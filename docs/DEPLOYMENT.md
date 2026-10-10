# StartupRadar V2 배포

웹은 기존 GFC Vercel 프로젝트, 인증·DB는 공유 Supabase `etvffzxqdgblvkfdikwl`, 배치는 StartupRadar 저장소의 `startup_radar_v2.yml`입니다. 두 저장소의 통합 변경은 main에 반영되어 있습니다. 별도 Python HTTP 서버는 필수가 아닙니다.

## 환경

GitHub Actions Secrets: `RADAR_DATABASE_URL`, `ANTHROPIC_API_KEY`, `KSTARTUP_API_KEY`, `BIZINFO_API_KEY`, `TELEGRAM_BOT_TOKEN`.

작업 환경에서는 DB 주소를 `DATABASE_URL`로 전달합니다. 로컬 `.env.worker`는 보존하되 버전 관리나 브라우저에 넣지 않습니다. GFC 웹에는 기존 공개 Supabase 설정만 사용하며 서버 키를 넣지 않습니다.

### AI 모델 선택과 비교

GitHub Actions repository variable `RADAR_EXTRACTION_MODEL`로 AI 추출 모델을 선택합니다.
V2의 수동 `INGEST`와 레거시 V1 분석 모두 이 값을 사용하며, 비어 있으면 코드 기본값을 사용합니다.
기본값은 `claude-sonnet-5-5`입니다. `claude-haiku-5-5`를 비교하려면 같은 변수로 명시적으로 선택합니다.
정기 `WEEKLY`는 `structured_only=True`로 실행하므로 이 설정과 관계없이 AI를 호출하지 않습니다.
모델 ID는 추출 캐시 키에 포함되어 서로 다른 모델의 결과를 재사용하지 않습니다.

`StartupRadar model comparison` 워크플로는 기존 `ANTHROPIC_API_KEY` Secret만 사용합니다.
공식 공고 발췌 10건과 합성 정상 사례 5건에 동일한 추출기를 적용해 Haiku 5.5와 Sonnet 5.5를 비교합니다.
DB, 실제 수집, 발행, Telegram은 사용하지 않습니다. 기본 30회 추출, 재시도를 포함해 최대 60회 API 요청입니다.
인증·서버·통신 오류는 비교 미완료로 처리하며 모델의 품질 차이로 판정하지 않습니다.
결과 JSON에는 실제 반환 모델, 토큰, 지연, 오류와 필수 정보 누락을 기록합니다.
짧은 발췌 사례의 통과만으로 전체 공고나 첨부문서에서의 품질 동등성을 보장하지 않습니다.
로컬 실행은 `python tools/evaluate_models.py --repo . --output work/model-comparison.json`이며,
`--list-cases`는 API 호출 없이 평가 기준만 출력합니다.

2026-10-10 [실제 API 비교](https://github.com/jey24960-sketch/startup-radar/actions/runs/38037324023)는
각 모델 15회씩 실행했으며, Sonnet 5.5는 15/15, Haiku 5.5는 13/15 사례를 통과했습니다.
두 모델 모두 스키마 오류나 이 평가에서 탐지된 잘못된 날짜·자격 확정은 없었습니다.
Haiku는 추가 자격 제한이 없다고 명시한 합성 정상 사례 2건도 `UNVERIFIABLE`로 남겼습니다.
이번 비교에서 필수 확인 항목을 모두 충족한 Sonnet을 기본값으로 선택했습니다.
이는 현재 프롬프트와 검증기를 적용한 작은 사례 집합의 1회 비교 결과이며, 전체 공고 품질의 보장은 아닙니다.

## 실행 및 수락

수동 실행은 `workflow_dispatch`의 INGEST, REFRESH, DIGEST, REMINDER, HIGH_FIT, TICK을 사용합니다. 수동 실행은 정기 실행 gate와 별개입니다. 실제 발송 여부는 `RADAR_V2_DELIVERY_ENABLED`가 결정합니다.

정기 실행에는 `RADAR_V2_ENABLED=true`와 DB scheduling 설정이 모두 필요합니다. 파일에 cron이 있다고 실제 운영 중인 것은 아닙니다. 실제 권한, 두 API 수집·저장, 회원의 실제 공고 조회, 실패 표시, 불확실한 근거 차단을 검증한 뒤 활성화합니다.

중단된 작업은 GitHub 실행이 실제 종료됐는지 확인한 다음 실행 소유 기록을 복구합니다. 타임아웃만으로 다른 작업을 시작하지 않습니다. 코드와 데이터는 보존하며, 수집 설정을 전체 재등록하지 않습니다.

정확한 일정과 제한, Telegram 0명 처리, 중단·복구 및 V1 롤백은 [운영 안내](PRODUCTION-OPERATIONS.md)를 따릅니다. 이전 단계의 상세 검증 기록은 해당 날짜의 감사 문서에 보존되어 있습니다.

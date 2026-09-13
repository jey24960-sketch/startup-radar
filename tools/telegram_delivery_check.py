"""Explicit one-message check to the existing configured recipient; no polling."""
import json
import os
import re
from pathlib import Path
from radar.notifications import TelegramTransport

TEXT=('StartupRadar 2.0 알림 연결 확인\n\n'
      '사용자 요청으로 기존 수신 대상에 보낸 검증용 메시지입니다.\n'
      'GFC 공고 수집 및 회원 화면 연결을 확인했으며, 자동 알림 운영 전 검증을 진행하고 있습니다.')


def check(environ,transport_factory=TelegramTransport):
    if environ.get('GITHUB_RUN_ATTEMPT')!='1':
        return {'state':'NOT_SENT','reason':'Only the first explicitly dispatched attempt may send'}
    if environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch':
        return {'state':'NOT_SENT','reason':'Explicit manual dispatch required'}
    token=environ.get('TELEGRAM_BOT_TOKEN','').strip()
    target=environ.get('TELEGRAM_CHAT_ID','').strip()
    if not token or not re.fullmatch(r'-?\d+|@[A-Za-z0-9_]+',target):
        return {'state':'NOT_SENT','reason':'Existing bot and single configured recipient required'}
    # Transport already treats ambiguous responses as UNCERTAIN and never retries.
    result=transport_factory(token).send(target,TEXT)
    return {**result,'kind':'CONNECTION_CHECK','automatic_retry':False,
            'recipient_source':'existing TELEGRAM_CHAT_ID','run_id':environ.get('GITHUB_RUN_ID')}


def main():
    result=check(os.environ)
    path=Path('work/telegram-delivery-check.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['state']=='DELIVERED' else 1


if __name__=='__main__':raise SystemExit(main())

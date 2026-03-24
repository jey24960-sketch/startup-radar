"""
kakao_auth.py
카카오 나에게 보내기용 액세스 토큰 발급 스크립트
최초 1회 실행 후 config.py에 토큰을 붙여넣으면 됩니다.

사용법:
  python kakao_auth.py

카카오 개발자 콘솔에서 앱 생성 후 REST API 키와 Redirect URI가 필요합니다.
"""

import webbrowser
import urllib.parse
import requests


# ── 여기에 카카오 앱 정보 입력 ────────────────────────────────
# https://developers.kakao.com 에서 앱 생성 후 확인
KAKAO_REST_API_KEY = "YOUR_KAKAO_REST_API_KEY"
REDIRECT_URI = "https://localhost"   # 앱 설정의 Redirect URI와 동일하게
# ────────────────────────────────────────────────────────────


def step1_get_auth_code():
    """1단계: 인증 코드 받기 (브라우저 열림)"""
    params = {
        "client_id": KAKAO_REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    }
    auth_url = "https://kauth.kakao.com/oauth/authorize?" + urllib.parse.urlencode(params)
    print("\n[1단계] 브라우저가 열립니다. 카카오 로그인 후 리다이렉트된 URL을 복사하세요.")
    print(f"URL: {auth_url}\n")
    webbrowser.open(auth_url)


def step2_exchange_token(code: str) -> str:
    """2단계: 인증 코드 → 액세스 토큰 교환"""
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": KAKAO_REST_API_KEY,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
    )
    data = resp.json()

    if "access_token" not in data:
        print(f"❌ 토큰 발급 실패: {data}")
        return ""

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")

    print("\n" + "=" * 50)
    print("✅ 토큰 발급 성공!")
    print(f"\naccess_token:\n{access_token}")
    print(f"\nrefresh_token (장기 갱신용, 안전하게 보관):\n{refresh_token}")
    print("\n" + "=" * 50)
    print("\n👉 config.py의 KAKAO_ACCESS_TOKEN에 위 access_token을 붙여넣으세요.")
    print("   액세스 토큰은 약 6시간 유효합니다.")
    print("   장기 사용을 위해 refresh_token도 따로 저장하세요.\n")

    return access_token


def refresh_access_token(refresh_token: str) -> str:
    """액세스 토큰 만료 시 갱신"""
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": KAKAO_REST_API_KEY,
            "refresh_token": refresh_token,
        },
    )
    data = resp.json()
    if "access_token" in data:
        print(f"✅ 토큰 갱신 성공: {data['access_token']}")
        return data["access_token"]
    else:
        print(f"❌ 갱신 실패: {data}")
        return ""


if __name__ == "__main__":
    print("=" * 50)
    print("  StartupRadar 카카오 인증 설정")
    print("=" * 50)
    print("\n준비사항:")
    print("  1. https://developers.kakao.com 접속")
    print("  2. '내 애플리케이션' → '애플리케이션 추가하기'")
    print("  3. 앱 이름: StartupRadar (자유롭게)")
    print("  4. '앱 키' 탭에서 REST API 키 복사 → KAKAO_REST_API_KEY에 입력")
    print("  5. '카카오 로그인' 활성화")
    print("  6. Redirect URI에 'https://localhost' 추가")
    print("  7. '동의항목'에서 카카오톡 메시지 전송 활성화")
    print("\n위 설정 완료 후 아무 키나 누르세요...")
    input()

    step1_get_auth_code()

    print("\n브라우저에서 로그인 후, 리다이렉트된 URL을 전체 복사하세요.")
    print("(예: https://localhost/?code=XXXXXX)")
    redirected = input("리다이렉트 URL 입력: ").strip()

    if "code=" in redirected:
        code = redirected.split("code=")[1].split("&")[0]
        step2_exchange_token(code)
    else:
        print("❌ URL에서 code를 찾을 수 없습니다.")

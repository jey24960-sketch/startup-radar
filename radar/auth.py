"""Supabase validates bearer tokens on its server before database impersonation."""
import os
from uuid import UUID
from fastapi import HTTPException,Request
from supabase import create_client


def authenticated_user(request:Request):
    authorization=request.headers.get('Authorization','')
    if not authorization.startswith('Bearer '):raise HTTPException(401,'로그인이 필요합니다.')
    token=authorization[7:]
    url=os.environ.get('SUPABASE_URL');key=os.environ.get('SUPABASE_PUBLISHABLE_KEY')
    if not url or not key:raise HTTPException(503,'Supabase 인증 설정이 필요합니다.')
    try:
        user=create_client(url,key).auth.get_user(token).user
        if user is None or getattr(user,'is_anonymous',False) or getattr(user,'deleted_at',None):
            raise HTTPException(401,'유효한 초대 계정으로 로그인하세요.')
        return UUID(user.id)
    except HTTPException:raise
    except Exception:raise HTTPException(401,'세션을 확인할 수 없습니다. 다시 로그인하세요.')

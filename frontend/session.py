"""Tarayıcı oturumuna özel durum (st.session_state) ve ortak yardımcılar.

Token ve sohbet geçmişi yalnızca bu oturumun durumunda tutulur. Kullanıcıya özel hiçbir veri
st.cache_data / st.cache_resource gibi paylaşılan önbelleklere konmaz: oralarda bir kullanıcının
cevabı başka bir kullanıcıya görünebilirdi.
"""

import os
from typing import Any, NoReturn

import streamlit as st

from frontend import api_client

API_URL = os.environ.get("KNOWVIA_API_URL", "http://127.0.0.1:8000")

TOKEN = "token"
USER = "user"
MESSAGES = "messages"
CONVERSATION_ID = "conversation_id"
PENDING_TICKET = "pending_ticket"  # modelin önerdiği, kullanıcının henüz onaylamadığı talep taslağı
NOTICE = "notice"


def client(token: str | None = None) -> api_client.KnowviaClient:
    # Sınıf her çağrıda modülden okunur; testler onu sahte bir istemciyle değiştirebilir.
    return api_client.KnowviaClient(API_URL, token or st.session_state.get(TOKEN))


def current_user() -> dict[str, Any]:
    return st.session_state[USER]


def is_admin() -> bool:
    return current_user()["role"] == "admin"


def sign_in(token: str, user: dict[str, Any]) -> None:
    st.session_state[TOKEN] = token
    st.session_state[USER] = user
    st.session_state[MESSAGES] = []
    st.session_state[CONVERSATION_ID] = None
    st.session_state[PENDING_TICKET] = None


def sign_out(notice: str | None = None) -> NoReturn:
    """Oturuma ait her şeyi siler ve giriş ekranına döner (st.rerun bu çalıştırmayı burada bitirir)."""
    st.session_state.clear()
    if notice:
        st.session_state[NOTICE] = notice
    st.rerun()


def show_notice() -> None:
    """Önceki çalıştırmadan kalan bilgi mesajını bir kez gösterir (ör. "oturum süresi doldu")."""
    notice = st.session_state.pop(NOTICE, None)
    if notice:
        st.info(notice)

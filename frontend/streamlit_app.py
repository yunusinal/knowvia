"""Knowvia arayüzü. Çalıştırma (API ayrı bir terminalde açık olmalı):
    uv run streamlit run frontend/streamlit_app.py
"""

import sys
from pathlib import Path

# `streamlit run` yalnızca betiğin klasörünü import yoluna ekler; `frontend` paketi için repo kökü gerekir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from frontend import session  # noqa: E402
from frontend.api_client import ApiError, SessionExpiredError  # noqa: E402

VIEWS = Path(__file__).resolve().parent / "views"


def login_screen() -> None:
    st.title("Knowvia")
    st.caption("Ask your team's knowledge base — with access-aware answers.")
    session.show_notice()

    with st.form("login"):
        email = st.text_input("E-posta")
        password = st.text_input("Parola", type="password")
        submitted = st.form_submit_button("Giriş yap", type="primary")

    if submitted:
        if not email or not password:
            st.error("E-posta ve parola gerekli.")
            return
        try:
            token = session.client().login(email, password)
            user = session.client(token).me()
        except ApiError as error:
            st.error(error.message)
            return
        session.sign_in(token, user)
        st.rerun()

    st.caption(
        "Yerel demo hesapları: admin@demo.local, it@demo.local, hr@demo.local, finance@demo.local "
        "(parola .env içindeki DEMO_USER_PASSWORD). Bu hesaplar yalnızca yerel demo içindir; "
        "uygulama kamuya açık bir sunucuya bu ayarlarla kurulmamalıdır."
    )


def sidebar() -> None:
    user = session.current_user()
    with st.sidebar:
        st.markdown(f"**{user['email']}**")
        st.caption(f"Rol: {user['role']} · Departman: {user['department'] or '—'}")
        try:
            documents = session.client().list_documents()
            st.caption(f"Erişebildiğiniz belge sayısı: {sum(d['status'] == 'active' for d in documents)}")
        except SessionExpiredError as error:
            session.sign_out(error.message)
        except ApiError as error:
            st.caption(error.message)
        if st.button("Çıkış yap"):
            session.sign_out("Çıkış yapıldı.")


st.set_page_config(page_title="Knowvia", page_icon="📚")

if session.TOKEN not in st.session_state:
    login_screen()
else:
    sidebar()
    navigation = st.navigation(
        [
            st.Page(VIEWS / "chat.py", title="Sohbet", icon="💬", default=True),
            st.Page(VIEWS / "documents.py", title="Belgeler", icon="📄"),
        ]
    )
    navigation.run()

"""Knowvia arayüzü. Çalıştırma (repo kökünden; API ayrı bir terminalde açık olmalı):
    uv run streamlit run frontend/streamlit_app.py
"""

import sys
from pathlib import Path

# `streamlit run` yalnızca betiğin klasörünü import yoluna ekler; `frontend` paketi için repo kökü gerekir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from frontend import labels, session  # noqa: E402
from frontend.api_client import ApiError, SessionExpiredError  # noqa: E402

VIEWS = Path(__file__).resolve().parent / "views"
# Tanıtım sayfasıyla (docs/index.html) aynı logo ve koyu tema.
ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = str(ASSETS / "logo.svg")
LOGO_MARK = str(ASSETS / "logo-mark.svg")
# Sekme simgesi: lacivert zeminli sürüm, açık ve koyu tarayıcı sekmesinde aynı netlikte görünür.
FAVICON = str(ASSETS / "favicon.svg")
# Tanıtım sayfasındaki kareli, geçişli zemin ve küçük stil düzeltmeleri; yalnız <style> olduğu için sayfada yer kaplamaz.
THEME_CSS = ASSETS / "theme.css"


def sidebar() -> None:
    user = session.current_user()
    role: str = user["role"]
    is_admin = role == "admin"
    with st.sidebar:
        st.caption("Belgelere sorun, kaynaklarıyla öğrenin.")
        with st.container(border=True):
            # Kod biçimi: düz e-posta Markdown'da mailto bağlantısına dönüşür.
            st.markdown(f"**`{user['email']}`**")
            with st.container(horizontal=True):
                st.badge(
                    labels.ROLE_LABELS.get(role, role),
                    icon=":material/shield_person:" if is_admin else ":material/person:",
                    color="violet" if is_admin else "blue",
                )
                if user["department"]:
                    st.badge(labels.department(user["department"]), icon=":material/apartment:", color="gray")
        if st.button("Çıkış yap", icon=":material/logout:", width="stretch"):
            session.sign_out("Çıkış yapıldı.")
        try:
            documents = session.client().list_documents()
        except SessionExpiredError as error:
            session.sign_out(error.message)
        except ApiError as error:
            st.caption(f"Belge sayısı alınamadı: {error.message}")
        else:
            active_count = sum(d["status"] == "active" for d in documents)
            st.caption(f":material/library_books: {active_count} aktif belge erişiminize açık.")


signed_in = session.TOKEN in st.session_state
st.set_page_config(
    page_title="Knowvia", page_icon=FAVICON,
    layout="centered" if signed_in else "wide",
)
st.html(THEME_CSS)
# Giriş ekranında logo zaten ortada; sol üstteki logo yalnız giriş yapınca görünür (yan panel kapanınca simge kalır).
if signed_in:
    st.logo(LOGO, icon_image=LOGO_MARK, size="large")

if session.TOKEN not in st.session_state:
    # Giriş yapılmamışken yalnızca landing page (giriş formu dahil) erişilebilir.
    navigation = st.navigation(
        [st.Page(VIEWS / "landing.py", title="Knowvia", default=True)],
        position="hidden",
    )
else:
    sidebar()
    navigation = st.navigation(
        [
            st.Page(VIEWS / "chat.py", title="Sohbet", icon=":material/chat:", default=True),
            st.Page(VIEWS / "documents.py", title="Belgeler", icon=":material/description:"),
            st.Page(VIEWS / "tickets.py", title="Destek talepleri", icon=":material/support_agent:"),
        ]
    )
if signed_in:
    navigation.run()
else:
    with st.container(horizontal_alignment="center"):
        with st.container(width=1100):
            navigation.run()

"""Giriş ekranı: kısa tanıtım ve giriş formu (giriş yapılmamışken görünen tek sayfa).

Projenin ayrıntılı, etkileşimli tanıtımı `docs/index.html`'dedir; sunucuda ana adreste yayınlanır ve
uygulama /app altında çalışır (ADR-12). Burada yalnızca giriş öne çıkar.
"""

import os
from pathlib import Path

import streamlit as st

from frontend import session
from frontend.api_client import ApiError

REPO_URL = "https://github.com/yunusinal/knowvia"
# Herkese açık demoda ziyaretçilere gösterilen üye parolası; admin hiçbir zaman listelenmez (ADR-12).
PUBLIC_DEMO_PASSWORD = os.environ.get("KNOWVIA_PUBLIC_DEMO_PASSWORD", "")
LOGO_MARK = str(Path(__file__).resolve().parents[1] / "assets" / "logo-mark.svg")

def login_form() -> None:
    with st.container(border=True):
        st.subheader("Giriş yap")
        session.show_notice()
        with st.form("login", border=False):
            email = st.text_input("E-posta", placeholder="it@demo.local")
            password = st.text_input("Parola", type="password")
            submitted = st.form_submit_button("Giriş yap", type="primary", width="stretch")
        if submitted:
            if not email or not password:
                st.error("E-posta ve parola gerekli.", icon=":material/error:")
                return
            try:
                token = session.client().login(email, password)
                user = session.client(token).me()
            except ApiError as error:
                st.error(error.message, icon=":material/error:")
                return
            session.sign_in(token, user)
            st.rerun()
        # E-postalar kod biçiminde: düz metin Markdown'da mailto bağlantısına dönüşür.
        if PUBLIC_DEMO_PASSWORD:
            st.caption(
                f"Demo hesapları: `it@demo.local`, `hr@demo.local`, `finance@demo.local`; parola `{PUBLIC_DEMO_PASSWORD}`. "
                "Aynı soruyu farklı hesaplarla sorup cevabın nasıl değiştiğini görün."
            )
        else:
            st.caption("Demo hesabı örneği `it@demo.local`; parola `.env` içindeki `DEMO_USER_PASSWORD` değeridir.")


hero, login = st.columns([3, 2], gap="large", vertical_alignment="center")
with hero:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.image(LOGO_MARK, width=56)
        st.title("Knowvia")
    # Tanıtım sayfasındaki başlıkla aynı söz.
    st.markdown("# Aynı soru. :green[Herkese _kendi_ cevabı.]")
    st.markdown(
        "Ekibinizin ya da kurumunuzun belgelerine doğal dille sorun. Her kullanıcı yalnızca **görmeye yetkili olduğu** belgelerden, "
        "**kaynak gösterilerek** cevap alır; yetkisi olmadığı bilgi cevaba hiç girmez."
    )
    st.link_button("Kaynak kodunu incele", REPO_URL, icon=":material/code:")
with login:
    login_form()

st.space("small")
st.caption("Demo, hayali bir şirketin sentetik belgeleriyle çalışır; gerçek kurum verisi içermez.")

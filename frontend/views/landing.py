"""Landing page: projeyi kısaca tanıtır ve giriş formunu sunar (giriş yapılmamışken görünen tek sayfa).

Tasarım `docs/index.html` tanıtım sayfasıyla aynı dili konuşur: aynı soruya iki kullanıcının aldığı
farklı cevap. Ayrıntılı hikâye o sayfada; burada giriş öne çıkar.
"""

import os

import streamlit as st

from frontend import session
from frontend.api_client import ApiError

REPO_URL = "https://github.com/yunusinal/knowvia"
# Herkese açık demoda ziyaretçilere gösterilen üye parolası; admin hiçbir zaman listelenmez (ADR-12).
PUBLIC_DEMO_PASSWORD = os.environ.get("KNOWVIA_PUBLIC_DEMO_PASSWORD", "")
QUESTION = "2026'da bulut altyapı harcamalarına yüzde kaç artış ayrıldı?"

GUARDS = [
    ("Tek tip ret", "\"Bilgi yok\" ve \"yetkiniz yok\" aynı mesajı alır; gizli bir belgenin varlığı ele verilmez."),
    ("Kaynaklı cevap", "Cevaplar yalnızca yetkili belgelerden gelir; dosya adı ve alıntıyla gösterilir."),
    ("Silince erişim anında kesilir", "Silinen belge bir sonraki sorudan itibaren hiçbir aramada çıkmaz."),
    ("Destek talebi onayla açılır", "Model yalnızca taslak önerir; kayıt siz onaylayınca oluşur."),
]


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
    st.title("Knowvia")
    st.markdown("# Aynı soru. :gray[Kimin sorduğuna göre farklı cevap.]")
    st.markdown(
        "Şirket belgelerine doğal dille sorun. Her kullanıcı yalnızca **erişebildiği** belgelerden, "
        "**kaynak gösterilerek** cevap alır; yetkisi olmadığı bilgi cevaba hiç girmez."
    )
    st.link_button("Kaynak kodunu incele", REPO_URL, icon=":material/code:")
with login:
    login_form()

st.space("medium")
st.header("Aynı soru, farklı cevap")
st.caption(QUESTION)
finance, it = st.columns(2)
with finance, st.container(border=True, height="stretch"):
    st.markdown("`finance@demo.local` :green-badge[Finans]")
    st.markdown("Bulut altyapı harcamalarına %20 artış ayrıldı. :yellow-background[**S1**]")
    st.caption("Kaynak: budget-plan-2026-confidential.md")
with it, st.container(border=True, height="stretch"):
    st.markdown("`it@demo.local` :gray-badge[IT]")
    st.markdown("Yetkiniz dahilindeki belgelerde bu soruya yeterli bilgi bulamadım.")
    st.caption("Bütçe belgesi bu kullanıcının aramasına hiç girmez.")

st.space("medium")
st.header("Sızdırmamak için yapılanlar")
for column, (title, text) in zip(st.columns(len(GUARDS)), GUARDS):
    with column:
        st.markdown(f"**{title}**")
        st.caption(text)

st.space("small")
st.caption("Sentetik demo belgeleriyle çalışan yerel bir portföy projesi; gerçek şirket verisi içermez.")

"""Landing page: projeyi tanıtır ve giriş formunu sunar (giriş yapılmamışken görünen tek sayfa)."""

import streamlit as st

from frontend import session
from frontend.api_client import ApiError

REPO_URL = "https://github.com/yunusinal/knowvia"

FEATURES = [
    (
        ":material/lock_person:",
        "Yetkiye duyarlı arama",
        "Sorularınız yalnızca erişim izniniz olan belgelerde aranır. Departmanınıza özel bilgiler "
        "kendi erişim sınırları içinde kalır.",
    ),
    (
        ":material/format_quote:",
        "Kaynaklı cevaplar",
        "Cevaplar yalnızca belgelerdeki bilgiye dayanır ve dosya adı, sayfa ve alıntıyla gösterilir. "
        "Bilgi yoksa cevap uydurulmaz.",
    ),
    (
        ":material/visibility_off:",
        "Sızıntısız ret",
        "\"Bilgi yok\" ile \"yetkiniz yok\" aynı cevabı alır; ret mesajı gizli bir belgenin varlığını ele vermez.",
    ),
    (
        ":material/auto_delete:",
        "Güncel belge erişimi",
        "Silinen belgeler yeni sorularda kaynak olarak kullanılmaz. Önceki cevaplar sohbet geçmişinde kalır.",
    ),
]

STEPS = [
    (":material/upload_file:", "Yükle", "Admin PDF, TXT veya MD belgesini departman ve görünürlükle yükler."),
    (":material/segment:", "İndeksle", "Metin paragraflara bölünür ve çok dilli bir modelle vektöre çevrilir."),
    (":material/manage_search:", "Yetkili ara", "Soru yalnızca kullanıcının yetkili olduğu belgelerde aranır."),
    (":material/chat:", "Kaynaklı cevap", "Dil modeli yalnızca bulunan parçalardan, kaynak göstererek cevap verir."),
]


def login_form() -> None:
    with st.container(border=True):
        st.subheader("Giriş yap", icon=":material/login:")
        session.show_notice()
        with st.form("login", border=False):
            email = st.text_input("E-posta", placeholder="it@demo.local")
            password = st.text_input("Parola", type="password")
            submitted = st.form_submit_button("Giriş yap", type="primary", icon=":material/arrow_forward:", width="stretch")
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


hero, login = st.columns([3, 2], gap="large", vertical_alignment="center")
with hero:
    st.title("Knowvia", icon=":material/menu_book:")
    st.subheader("Ekibinizin bilgisi, erişim sınırlarınız içinde.")
    st.markdown(
        "Şirket belgelerinizi doğal dille sorgulayın. Her kullanıcı yalnızca **yetkili olduğu** belgelerden, "
        "**kaynak gösterilerek** cevap alır."
    )
    st.badge("Yerel demo · sentetik belgeler", icon=":material/science:", color="gray")
    st.link_button("Kaynak kodu GitHub'da", REPO_URL, icon=":material/code:")
with login:
    login_form()

st.space("medium")
st.header("Neden Knowvia?")
for row in (FEATURES[:2], FEATURES[2:]):
    for column, (icon, title, text) in zip(st.columns(2), row):
        with column, st.container(border=True, height="stretch"):
            st.markdown(f"**{icon} {title}**")
            st.caption(text)

st.space("medium")
st.header("Nasıl çalışır?")
for column, (number, (icon, title, text)) in zip(st.columns(2), enumerate(STEPS[:2], start=1)):
    with column:
        st.markdown(f"**{icon} {number}. {title}**")
        st.caption(text)
for column, (number, (icon, title, text)) in zip(st.columns(2), enumerate(STEPS[2:], start=3)):
    with column:
        st.markdown(f"**{icon} {number}. {title}**")
        st.caption(text)

st.space("medium")
with st.expander("Demo hesapları", icon=":material/badge:"):
    st.markdown(
        "`admin@demo.local` · `it@demo.local` · `hr@demo.local` · `finance@demo.local`  \n"
        "Parola: `.env` içindeki `DEMO_USER_PASSWORD`. Aynı soruyu farklı rollerle sorup cevapların "
        "nasıl değiştiğini görebilirsiniz (ör. 2026 bütçesi yalnızca Finans ve admin için)."
    )
st.caption("Knowvia · Erişim yetkisine duyarlı bilgi asistanı · Yerel portföy prototipi")

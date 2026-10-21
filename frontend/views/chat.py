"""Sohbet sayfası: soru → yetkili belgelerden kaynaklı cevap veya açık "kanıt yok" mesajı."""

from typing import Any

import streamlit as st

from frontend import session
from frontend.api_client import ApiError, SessionExpiredError

AVATARS = {"user": ":material/person:", "assistant": ":material/menu_book:"}
# Boş sohbette gösterilen örnek sorular; cevap yetkiye göre değişir (ör. bütçe yalnız Finans ve admin için).
SUGGESTIONS = {
    ":violet[:material/vpn_key:] VPN hatası": "VPN 'sertifika doğrulanamadı' hatası veriyor, ne yapmalıyım?",
    ":blue[:material/beach_access:] Yıllık izin": "3 yıldır çalışıyorum, yıllık izin hakkım kaç gün?",
    ":green[:material/home_work:] Uzaktan çalışma": "Haftada kaç gün evden çalışabilirim?",
    ":orange[:material/savings:] 2026 bütçesi": "2026 yılında bulut altyapı harcamalarına yüzde kaç artış ayrıldı?",
}


def render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"], avatar=AVATARS[message["role"]]):
        if message.get("error"):
            st.error(message["error"], icon=":material/error:")
            return
        if message.get("no_evidence"):
            st.info(message["content"], icon=":material/search_off:")
        else:
            # st.markdown HTML'i varsayılan olarak çalıştırmaz; model çıktısı yalnızca metin olarak görünür.
            st.markdown(message["content"])

        sources = message.get("sources", [])
        if sources:
            with st.expander(f"Kaynaklar · {len(sources)}", icon=":material/library_books:", expanded=True):
                for source in sources:
                    with st.container(border=True):
                        with st.container(horizontal=True, vertical_alignment="center"):
                            st.markdown(f"**[{source['source_id']}] {source['filename']}**")
                            if source["page_number"] is not None:
                                st.badge(f"Sayfa {source['page_number']}", icon=":material/article:", color="gray")
                        st.text(source["snippet"])
        if "retrieval_ms" in message and message.get("response_type", "rag") != "canned":
            seconds = (message["retrieval_ms"] + message["generation_ms"]) / 1000
            st.caption(f"{seconds:.1f} sn · arama {message['retrieval_ms']} ms · dil modeli {message['generation_ms']} ms")


def ask(question: str) -> None:
    history = [
        message["content"]
        for message in st.session_state[session.MESSAGES]
        if message["role"] == "user"
    ][-4:]
    user_message = {"role": "user", "content": question}
    st.session_state[session.MESSAGES].append(user_message)
    render_message(user_message)

    try:
        with st.spinner("Cevap hazırlanıyor…"):
            result = session.client().chat(question, history)
        answer = {
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
            "no_evidence": result["no_evidence"],
            "retrieval_ms": result["retrieval_ms"],
            "generation_ms": result["generation_ms"],
            "response_type": result.get("response_type", "rag"),
        }
    except SessionExpiredError as error:
        session.sign_out(error.message)
    except ApiError as error:
        answer = {"role": "assistant", "error": error.message}

    st.session_state[session.MESSAGES].append(answer)
    render_message(answer)


st.title("Knowvia", icon=":material/menu_book:")
st.caption("Yalnızca erişim yetkiniz olan belgelerden, kaynak göstererek cevap verilir.")
st.caption("Takip soruları, bu oturumdaki son dört sorunuzu bağlam olarak kullanır.")

messages = st.session_state[session.MESSAGES]
for previous in messages:
    render_message(previous)

if not messages:
    st.subheader("Belgelerinize ne sormak istersiniz?")
    suggestion = st.pills("Örnek sorular", list(SUGGESTIONS))
    if suggestion:
        ask(SUGGESTIONS[suggestion])
        st.rerun()  # örnek sorular kaybolsun, sohbet geçmişi gösterilsin

if question := st.chat_input("Bir soru sorun", max_chars=1000, submit_mode="disable"):
    ask(question)

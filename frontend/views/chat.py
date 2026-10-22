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
    user_message = {"role": "user", "content": question}
    st.session_state[session.MESSAGES].append(user_message)
    render_message(user_message)

    try:
        with st.spinner("Cevap hazırlanıyor…"):
            result = session.client().chat(question, st.session_state.get(session.CONVERSATION_ID))
        st.session_state[session.CONVERSATION_ID] = result["conversation_id"]
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
st.caption("Takip sorularında önceki soru ve cevaplar, mevcut kaynaklara ayrılan yer ölçüsünde kullanılır.")

try:
    conversations = session.client().list_conversations()
    choices = {item["id"]: item["title"] for item in conversations}
    active_id = st.session_state.get(session.CONVERSATION_ID)
    if active_id is not None and active_id not in choices:
        active_id = None
        st.session_state[session.CONVERSATION_ID] = active_id
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.selectbox(
            "Sohbet", [None, *choices],
            index=[None, *choices].index(active_id),
            format_func=lambda value: "Yeni sohbet" if value is None else choices[value],
            key=f"conversation_picker_{active_id or 'new'}",
        )
        if st.button("Yeni sohbet", icon=":material/add:"):
            chosen = None
    if chosen != active_id:
        st.session_state[session.CONVERSATION_ID] = chosen
        st.session_state[session.MESSAGES] = []
    if chosen:
        st.session_state[session.MESSAGES] = session.client().get_conversation_messages(chosen)
except SessionExpiredError as error:
    session.sign_out(error.message)
except ApiError as error:
    st.error(error.message)

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

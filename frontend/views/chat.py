"""Sohbet sayfası: soru → yetkili belgelerden kaynaklı cevap veya açık "kanıt yok" mesajı."""

from typing import Any

import streamlit as st

from frontend import session
from frontend.api_client import ApiError, SessionExpiredError


def render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        if message.get("error"):
            st.error(message["error"])
        elif message.get("no_evidence"):
            st.info(message["content"])
        else:
            # st.markdown HTML'i varsayılan olarak çalıştırmaz; model çıktısı yalnızca metin olarak görünür.
            st.markdown(message["content"])
        for source in message.get("sources", []):
            with st.container(border=True):
                page = f" · sayfa {source['page_number']}" if source["page_number"] is not None else ""
                st.markdown(f"**[{source['source_id']}] {source['filename']}**{page}")
                st.text(source["snippet"])


st.title("Knowvia")
st.caption("Ask your team's knowledge base — with access-aware answers.")

for previous in st.session_state[session.MESSAGES]:
    render_message(previous)

if question := st.chat_input("Bir soru sorun", max_chars=1000, submit_mode="disable"):
    user_message = {"role": "user", "content": question}
    st.session_state[session.MESSAGES].append(user_message)
    render_message(user_message)

    try:
        with st.spinner("Belgeler aranıyor ve cevap hazırlanıyor…"):
            result = session.client().chat(question)
        answer = {
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
            "no_evidence": result["no_evidence"],
        }
    except SessionExpiredError as error:
        session.sign_out(error.message)
    except ApiError as error:
        answer = {"role": "assistant", "error": error.message}

    st.session_state[session.MESSAGES].append(answer)
    render_message(answer)

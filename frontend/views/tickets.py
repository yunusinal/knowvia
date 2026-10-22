"""Destek talepleri: üye kendi onayladığı talepleri, admin tüm talepleri görür (karar API'de verilir)."""

from datetime import datetime

import streamlit as st

from frontend import labels, session
from frontend.api_client import ApiError, SessionExpiredError

st.title("Destek talepleri", icon=":material/support_agent:")
st.caption(
    ("Tüm kullanıcıların talepleri." if session.is_admin() else "Onayladığınız destek talepleri.")
    + " Talepler bu demoda yerel olarak kaydedilir; gerçek bir yardım masasına gönderilmez."
)

try:
    tickets = session.client().list_tickets()
except SessionExpiredError as error:
    session.sign_out(error.message)
except ApiError as error:
    st.error(error.message, icon=":material/error:")
    st.stop()

if not tickets:
    st.info(
        "Henüz destek talebi yok. Belgelerdeki adımlar sorununuzu çözmediyse sohbette asistandan "
        "talep taslağı isteyebilirsiniz.",
        icon=":material/inbox:",
    )

for ticket in tickets:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{ticket['subject']}**")
            status: str = ticket["status"]
            is_open = status == "open"
            st.badge(
                labels.TICKET_STATUS_LABELS.get(status, status),
                icon=":material/radio_button_checked:" if is_open else ":material/check_circle:",
                color="green" if is_open else "gray",
            )
        created = datetime.fromisoformat(ticket["created_at"]).strftime("%d.%m.%Y %H:%M")
        owner = f" · {ticket['created_by_email']}" if session.is_admin() else ""
        st.caption(f"{created}{owner}")
        # Açıklama model taslağından gelebilir; st.text HTML/Markdown yorumlamaz.
        st.text(ticket["description"])

"""Belgeler sayfası: herkes erişebildiği belgeleri görür; admin yükler ve siler.

Yükleme/silme kontrollerini üyelerden gizlemek yalnızca kullanım kolaylığıdır; asıl engel
API'nin 403 cevabıdır (yetki her zaman backend'de).
"""

import streamlit as st

from frontend import session
from frontend.api_client import ApiError, SessionExpiredError

DEPARTMENTS = ["IT", "HR", "FINANCE"]
VISIBILITY_LABELS = {"company": "Şirket geneli", "department": "Yalnızca departman"}
DELETABLE = {"active", "failed", "cleanup_pending", "deleting"}

st.title("Belgeler")
session.show_notice()

try:
    documents = session.client().list_documents()
except SessionExpiredError as error:
    session.sign_out(error.message)
except ApiError as error:
    st.error(error.message)
    st.stop()

if documents:
    st.dataframe(
        [
            {
                "Dosya": d["filename"],
                "Departman": d["department"],
                "Görünürlük": VISIBILITY_LABELS.get(d["visibility"], d["visibility"]),
                "Durum": d["status"],
                "Chunk": d["chunk_count"],
                "Yüklenme": d["created_at"][:16].replace("T", " "),
            }
            for d in documents
        ],
        hide_index=True,
    )
else:
    st.info("Erişebildiğiniz belge yok.")

if session.is_admin():
    st.subheader("Belge yükle")
    with st.form("upload", clear_on_submit=True):
        uploaded = st.file_uploader("Belge (PDF, TXT, MD)", type=["pdf", "txt", "md"])
        department = st.selectbox("Departman", DEPARTMENTS)
        visibility = st.selectbox("Görünürlük", list(VISIBILITY_LABELS), format_func=VISIBILITY_LABELS.__getitem__)
        submitted = st.form_submit_button("Yükle", type="primary")
    if submitted:
        if uploaded is None:
            st.error("Önce bir dosya seçin.")
        else:
            try:
                with st.spinner("Belge doğrulanıyor ve indeksleniyor…"):
                    created = session.client().upload_document(
                        uploaded.name, uploaded.getvalue(), department, visibility
                    )
            except SessionExpiredError as error:
                session.sign_out(error.message)
            except ApiError as error:
                st.error(error.message)
            else:
                st.session_state[session.NOTICE] = (
                    f"{created['filename']} yüklendi ({created['chunk_count']} chunk)."
                )
                st.rerun()

    deletable = [d for d in documents if d["status"] in DELETABLE]
    if deletable:
        st.subheader("Belge sil")
        labels = {d["id"]: f"{d['filename']} ({d['department']}, {d['status']})" for d in deletable}
        with st.form("delete"):
            document_id = st.selectbox("Silinecek belge", list(labels), format_func=labels.__getitem__)
            confirmed = st.checkbox("Bu belgenin silineceğini ve kimsenin artık göremeyeceğini anlıyorum.")
            delete_clicked = st.form_submit_button("Sil")
        if delete_clicked:
            if not confirmed:
                st.error("Silmek için onay kutusunu işaretleyin.")
            elif document_id is None:
                st.error("Silinecek belgeyi seçin.")
            else:
                try:
                    result = session.client().delete_document(document_id)
                except SessionExpiredError as error:
                    session.sign_out(error.message)
                except ApiError as error:
                    st.error(error.message)
                else:
                    if result["status"] == "deleted":
                        st.session_state[session.NOTICE] = f"{result['filename']} silindi."
                    else:
                        st.session_state[session.NOTICE] = (
                            f"{result['filename']} erişime kapatıldı ama vektör temizliği tamamlanamadı; "
                            "silmeyi tekrar deneyin."
                        )
                    st.rerun()

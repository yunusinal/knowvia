"""Belgeler sayfası: herkes erişebildiği belgeleri görür; admin yükler ve siler.

Yükleme/silme kontrollerini üyelerden gizlemek yalnızca kullanım kolaylığıdır; asıl engel
API'nin 403 cevabıdır (yetki her zaman backend'de).
"""

import streamlit as st

from frontend import labels, session
from frontend.api_client import ApiError, SessionExpiredError

DELETABLE = {"active", "failed", "cleanup_pending", "deleting"}

st.title("Belgeler", icon=":material/description:")
session.show_notice()

try:
    documents = session.client().list_documents()
except SessionExpiredError as error:
    session.sign_out(error.message)
except ApiError as error:
    st.error(error.message, icon=":material/error:")
    st.stop()

if documents:
    st.caption(f"Erişebildiğiniz {len(documents)} belge.")
    st.dataframe(
        [
            {
                "Dosya": d["filename"],
                "Departman": labels.department(d["department"]),
                "Görünürlük": labels.VISIBILITY_LABELS.get(d["visibility"], d["visibility"]),
                "Durum": labels.STATUS_LABELS.get(d["status"], d["status"]),
                "Parça": d["chunk_count"],
                "Yüklenme": d["created_at"][:16].replace("T", " "),
            }
            for d in documents
        ],
        hide_index=True,
        column_config={
            "Dosya": st.column_config.TextColumn(width="large"),
            "Parça": st.column_config.NumberColumn(help="Belgenin arama için bölündüğü metin parçası sayısı"),
        },
        alt="Erişebildiğiniz belgeler",
    )
else:
    st.info("Erişebildiğiniz belge yok.", icon=":material/folder_off:")

if session.is_admin():
    upload_tab, delete_tab = st.tabs([":material/upload: Belge yükle", ":material/delete: Belge sil"])

    with upload_tab:
        st.caption("Şirket geneli belgeler tüm departmanlara; departman belgeleri yalnız ilgili departmana ve adminlere açıktır.")
        with st.form("upload", clear_on_submit=True, border=False):
            uploaded = st.file_uploader("Belge (PDF, TXT, MD)", type=["pdf", "txt", "md"])
            with st.container(horizontal=True):
                department = st.selectbox("Departman", labels.DEPARTMENTS, format_func=labels.department)
                visibility = st.selectbox(
                    "Görünürlük", list(labels.VISIBILITY_LABELS), format_func=labels.VISIBILITY_LABELS.__getitem__
                )
            submitted = st.form_submit_button("Yükle", type="primary", icon=":material/upload:")
        if submitted:
            if uploaded is None:
                st.error("Önce bir dosya seçin.", icon=":material/error:")
            else:
                try:
                    with st.spinner("Belge doğrulanıyor ve indeksleniyor…"):
                        created = session.client().upload_document(
                            uploaded.name, uploaded.getvalue(), department, visibility
                        )
                except SessionExpiredError as error:
                    session.sign_out(error.message)
                except ApiError as error:
                    st.error(error.message, icon=":material/error:")
                else:
                    st.session_state[session.NOTICE] = f"{created['filename']} yüklendi ({created['chunk_count']} parça)."
                    st.rerun()

    with delete_tab:
        deletable = [d for d in documents if d["status"] in DELETABLE]
        if not deletable:
            st.caption("Silinebilecek belge yok.")
        else:
            options = {
                d["id"]: f"{d['filename']} ({labels.department(d['department'])}, "
                f"{labels.STATUS_LABELS.get(d['status'], d['status'])})"
                for d in deletable
            }
            with st.form("delete", border=False):
                document_id = st.selectbox("Silinecek belge", list(options), format_func=options.__getitem__)
                confirmed = st.checkbox("Bu belgenin silineceğini ve kimsenin artık göremeyeceğini anlıyorum.")
                delete_clicked = st.form_submit_button("Sil", icon=":material/delete:")
            if delete_clicked:
                if not confirmed:
                    st.error("Silmek için onay kutusunu işaretleyin.", icon=":material/error:")
                elif document_id is None:
                    st.error("Silinecek belgeyi seçin.", icon=":material/error:")
                else:
                    try:
                        result = session.client().delete_document(document_id)
                    except SessionExpiredError as error:
                        session.sign_out(error.message)
                    except ApiError as error:
                        st.error(error.message, icon=":material/error:")
                    else:
                        if result["status"] == "deleted":
                            st.session_state[session.NOTICE] = f"{result['filename']} silindi."
                        else:
                            st.session_state[session.NOTICE] = (
                                f"{result['filename']} erişime kapatıldı ama vektör temizliği tamamlanamadı; "
                                "silmeyi tekrar deneyin."
                            )
                        st.rerun()

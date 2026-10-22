"""Arayüzde gösterilen Türkçe adlar; API değerleri (ör. "cleanup_pending") olduğu gibi kalır."""

DEPARTMENTS = ["IT", "HR", "FINANCE"]
DEPARTMENT_LABELS = {"IT": "IT", "HR": "İK", "FINANCE": "Finans"}
VISIBILITY_LABELS = {"company": "Şirket geneli", "department": "Yalnızca departman"}
STATUS_LABELS = {
    "active": "Aktif",
    "processing": "İşleniyor",
    "failed": "Başarısız",
    "deleting": "Siliniyor",
    "cleanup_pending": "Temizlik bekliyor",
    "deleted": "Silindi",
}
TICKET_STATUS_LABELS = {"open": "Açık", "closed": "Kapalı"}
ROLE_LABELS = {"admin": "Admin", "member": "Üye"}


def department(value: str | None) -> str:
    return DEPARTMENT_LABELS.get(value or "", "—")

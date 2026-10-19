from app.core.security import hash_password, verify_password


def test_hash_is_not_the_plain_password() -> None:
    hashed = hash_password("demo-password")

    assert hashed != "demo-password"
    assert hashed.startswith("$argon2")


def test_correct_password_is_verified() -> None:
    hashed = hash_password("demo-password")

    assert verify_password("demo-password", hashed) is True


def test_same_password_produces_different_hashes() -> None:
    # Rastgele salt sayesinde aynı parola her seferinde farklı hash üretir.
    assert hash_password("demo-password") != hash_password("demo-password")


def test_wrong_password_is_rejected() -> None:
    # 1) Bir parolayı hash'le
    hashed = hash_password("demo-password")

    # 2) FARKLI bir parolayla doğrulamayı dene; sonuç ne olmalı?
    assert verify_password("wrong-password", hashed) is False
from chatbi.auth.hashing import hash_password, verify_password


def test_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_accepts_the_right_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("Correct Horse Battery Staple", hashed) is False


def test_verify_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-hash") is False


def test_same_password_hashes_differently() -> None:
    assert hash_password("same") != hash_password("same")

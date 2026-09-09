from auth import accounts
from repository import display_url


def test_password_hashing_and_verification():
    password_hash = accounts.hash_password("a sufficiently long password")
    assert password_hash != "a sufficiently long password"
    assert accounts.verify_password("a sufficiently long password", password_hash)
    assert not accounts.verify_password("wrong password", password_hash)


def test_email_normalization_and_validation():
    assert accounts.normalize_email(" Analyst@Example.COM ") == "analyst@example.com"
    assert accounts.valid_email("analyst@example.com")
    assert not accounts.valid_email("not-an-email")


def test_evidence_urls_have_readable_labels_but_keep_unicode_path():
    url = "https://www.svmarina.com/bg/%D1%86%D0%B5%D0%BD%D0%BE%D1%80%D0%B0%D0%B7%D0%BF%D0%B8%D1%81"
    assert display_url(url) == "svmarina.com/bg/ценоразпис"

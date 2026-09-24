import pytest
import requests

import app


class Odpowiedz:
    def __init__(self, dane=None, status=200):
        self.dane, self.status_code = dane or {}, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def bez_czekania(monkeypatch):
    monkeypatch.setattr(app.time, "sleep", lambda s: None)


def test_extract_odpytuje_do_done_i_zwraca_extracted(monkeypatch):
    statusy = iter(["RUNNING", "RUNNING", "DONE"])
    monkeypatch.setattr(app.requests, "post", lambda *a, **k: Odpowiedz({"run_id": "r1"}))

    def get(url, **k):
        if url.endswith("/status"):
            return Odpowiedz({"job_status": next(statusy)})
        return Odpowiedz({"extracted": {"numer_umowy": "1"}})

    monkeypatch.setattr(app.requests, "get", get)
    assert app.wywolaj_extract_api("tekst", "t", "KHB1", {}) == {"numer_umowy": "1"}


def test_wygasly_token_w_trakcie_odpytywania_to_blad_http_a_nie_timeout(monkeypatch):
    monkeypatch.setattr(app.requests, "post", lambda *a, **k: Odpowiedz({"run_id": "r1"}))
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: Odpowiedz(status=401))

    with pytest.raises(requests.HTTPError):
        app.wywolaj_ocr_api(b"%PDF", "t", "KHB1")


def test_status_failed(monkeypatch):
    monkeypatch.setattr(app.requests, "post", lambda *a, **k: Odpowiedz({"run_id": "r1"}))
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: Odpowiedz({"job_status": "FAILED"}))

    with pytest.raises(RuntimeError, match="FAILED"):
        app.wywolaj_ocr_api(b"%PDF", "t", "KHB1")


def test_limit_czasu(monkeypatch):
    zegar = iter(range(0, 10_000, 100))
    monkeypatch.setattr(app.time, "monotonic", lambda: next(zegar))
    monkeypatch.setattr(app.requests, "post", lambda *a, **k: Odpowiedz({"run_id": "r1"}))
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: Odpowiedz({"job_status": "RUNNING"}))

    with pytest.raises(TimeoutError):
        app.wywolaj_ocr_api(b"%PDF", "t", "KHB1")


def test_token_z_pliku(tmp_path):
    plik = tmp_path / "token.txt"
    plik.write_text('{"access_token": "abc"}', encoding="utf-8")
    assert app.wczytaj_token_z_pliku(plik) == "abc"
    assert app.wczytaj_token_z_pliku(tmp_path / "brak.txt") is None

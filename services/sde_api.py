"""Endpointy OCR i Extract (sde_service): zlecenie zadania, odpytywanie, wynik."""

import json
import time

import requests

from ustawienia import (
    BASE_URL,
    CA_CERT,
    LIMIT_EKSTRAKCJI_S,
    LIMIT_OCR_S,
    ODSTEP_ODPYTYWANIA_S,
)


def _naglowki(token):
    return {"Authorization": f"Bearer {token}"}


def _czekaj_na_wynik(sciezka, run_id, token, limit_s, nazwa):
    """Odpytuje status zadania do DONE, potem pobiera wynik.

    Każda odpowiedź przechodzi przez raise_for_status: wygasły token (401)
    w trakcie odpytywania ma dać błąd autoryzacji, a nie mylący komunikat
    o przekroczonym czasie.
    """
    koniec = time.monotonic() + limit_s

    while True:
        odpowiedz = requests.get(
            f"{BASE_URL}/{sciezka}/{run_id}/status",
            headers=_naglowki(token),
            verify=CA_CERT,
            timeout=30,
        )
        odpowiedz.raise_for_status()
        status = odpowiedz.json().get("job_status")

        if status == "DONE":
            break
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"{nazwa} zakończona błędem (status={status})")
        if time.monotonic() > koniec:
            raise TimeoutError(f"Przekroczono limit oczekiwania na: {nazwa} ({limit_s} s).")

        time.sleep(ODSTEP_ODPYTYWANIA_S)

    odpowiedz = requests.get(
        f"{BASE_URL}/{sciezka}/{run_id}",
        headers=_naglowki(token),
        verify=CA_CERT,
        timeout=30,
    )
    odpowiedz.raise_for_status()
    return odpowiedz.json()


def wywolaj_ocr(plik_bajty, token, document_group_id):
    """POST /legal_analysis/ocr — zwraca tekst dokumentu ze znacznikami PageBreak."""
    odpowiedz = requests.post(
        f"{BASE_URL}/legal_analysis/ocr",
        headers={**_naglowki(token), "Content-Type": "application/octet-stream"},
        params={
            "document_group_id": document_group_id,
            "document_type": "umowa",
            "ocr_model": "prebuilt-layout",
        },
        data=plik_bajty,
        verify=CA_CERT,
        timeout=60,
    )
    odpowiedz.raise_for_status()
    run_id = odpowiedz.json()["run_id"]

    return _czekaj_na_wynik("legal_analysis/ocr", run_id, token, LIMIT_OCR_S, "OCR")


def wywolaj_extract(tekst, token, document_id, schema):
    """POST /legal_analysis/extract — zwraca słownik zgodny ze schematem."""
    odpowiedz = requests.post(
        f"{BASE_URL}/legal_analysis/extract",
        headers=_naglowki(token),
        json={
            "ocr_text": tekst,
            "schema": schema,
            "metadata": {"document_id": document_id},
        },
        verify=CA_CERT,
        timeout=60,
    )
    odpowiedz.raise_for_status()
    run_id = odpowiedz.json()["run_id"]

    wynik = _czekaj_na_wynik(
        "legal_analysis/extract", run_id, token, LIMIT_EKSTRAKCJI_S, "Ekstrakcja"
    )
    return wynik["extracted"]


def wczytaj_token(plik):
    """access_token z pliku JSON albo None."""
    try:
        with open(plik, "r", encoding="utf-8") as f:
            return json.load(f).get("access_token")
    except (FileNotFoundError, json.JSONDecodeError):
        return None

"""Przebieg analizy dokumentu: cache -> OCR -> ekstrakcja -> zapis do cache.

Bez Streamlita: postęp raportowany przez callback, źródła danych (hurtownia,
API) wstrzykiwane parametrem — dzięki temu całość da się przetestować.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from core.tekst import dodaj_markery_stron
from services.schemy import klucz_wersji, policz_hash_pdf, wczytaj_schema, zbuduj_prompt


@dataclass
class Analiza:
    """Wynik analizy jednego dokumentu w kontekście jednego wniosku."""
    pdf_hash: str
    nr_wniosku: str
    nazwa_pliku: str
    typ_dokumentu: str
    ocr_text: str
    wynik: dict
    zrodlo: str
    czas: str
    id_analizy: str
    ostrzezenia: list = field(default_factory=list)


def _bez_postepu(procent, opis):
    pass


def analizuj(
    plik_bajty,
    nazwa_pliku,
    nr_wniosku,
    token,
    dane_uniflow,
    typ_dokumentu,
    zrodla,
    wymus=False,
    postep=_bez_postepu,
):
    """Pełna analiza albo odczyt z cache. Zwraca Analiza.

    `zrodla` to obiekt z funkcjami get_document_cache, save_document_cache,
    wywolaj_ocr i wywolaj_extract (moduł services.zrodla albo atrapa w testach).

    Błąd OCR albo ekstrakcji przerywa analizę wyjątkiem. Błąd ZAPISU do cache
    już nie: OCR i model zadziałały, więc analityk dostaje wynik, a problem
    z zapisem trafia do `ostrzezenia`.
    """
    pdf_hash = policz_hash_pdf(plik_bajty)
    schema = wczytaj_schema(typ_dokumentu)
    klucz = klucz_wersji(schema, dane_uniflow)
    id_analizy = str(uuid.uuid4())

    def analiza(ocr_text, wynik, zrodlo, ostrzezenia=None):
        return Analiza(
            pdf_hash=pdf_hash,
            nr_wniosku=nr_wniosku,
            nazwa_pliku=nazwa_pliku,
            typ_dokumentu=typ_dokumentu,
            ocr_text=ocr_text,
            wynik=wynik,
            zrodlo=zrodlo,
            czas=datetime.now().strftime("%H:%M:%S"),
            id_analizy=id_analizy,
            ostrzezenia=ostrzezenia or [],
        )

    if not wymus:
        z_cache = zrodla.get_document_cache(
            pdf_hash=pdf_hash,
            nr_wniosku=nr_wniosku,
            hash_schematu=klucz,
        )
        if z_cache is not None:
            return analiza(z_cache["ocr_text"], z_cache["wynik"], "Cache Impala")

    postep(20, "Krok 1/2: OCR...")
    ocr_text = dodaj_markery_stron(zrodla.wywolaj_ocr(plik_bajty, token, nr_wniosku))

    postep(70, f"Krok 2/2: Ekstrakcja ({typ_dokumentu})...")
    wynik = zrodla.wywolaj_extract(
        zbuduj_prompt(dane_uniflow, ocr_text), token, nr_wniosku, schema
    )

    ostrzezenia = []
    try:
        zrodla.save_document_cache(
            pdf_hash=pdf_hash,
            nr_wniosku=nr_wniosku,
            hash_schematu=klucz,
            id_analizy=id_analizy,
            document_type=typ_dokumentu,
            # markery [STRONA_X] muszą trafić do cache — bez nich
            # szukajka i klik w pole nie wskażą strony
            ocr_text=ocr_text,
            extracted_data=wynik,
        )
    except Exception as blad:
        ostrzezenia.append(
            f"Wynik nie został zapisany do cache ({blad}). Analiza jest kompletna, "
            "ale przy następnym otwarciu dokumentu zostanie wykonana ponownie."
        )

    postep(100, "Analiza zakończona.")
    return analiza(ocr_text, wynik, getattr(zrodla, "NAZWA", "Prawdziwe API"), ostrzezenia)

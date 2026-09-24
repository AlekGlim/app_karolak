"""Atrapy hurtowni i API do pracy lokalnej (HIPOTEKA_OFFLINE=1).

Zastępują WYŁĄCZNIE wejście/wyjście. Cała logika (szukajka, rozbieżności,
ustalenia, widoki) działa na tych danych dokładnie tak jak na produkcyjnych,
więc nie powtarza się problem dawnego trybu demo, który dublował analizę
i rozjeżdżał się ze schematem.

Dane w katalogu dev/:
  wnioskodawcy.json               wiersze tabeli wnioskodawców (jak z hurtowni)
  wynik_umowa_deweloperska.json   odpowiedź endpointu Extract
  umowa_demo.pdf                  dokument pasujący do powyższych danych

OCR zwraca warstwę tekstową PDF, więc szukajka działa na prawdziwym tekście
wgranego pliku. Extract zwraca zawsze ten sam JSON, niezależnie od pliku.
"""

import json
import time

import pandas as pd

from ustawienia import KATALOG_DEV

NAZWA = "Offline (dev/)"

# Ten sam zapis znacznika, który zwraca endpoint OCR — core.tekst dzieli po nim strony.
ZNACZNIK_STRONY = "&lt;!-- PageBreak --&gt;"

_cache = {}


def _json(nazwa):
    with open(KATALOG_DEV / nazwa, "r", encoding="utf-8") as f:
        return json.load(f)


def load_wnioskodawcy(nr_wniosku):
    wiersze = [w for w in _json("wnioskodawcy.json") if w["NR_WNIOSKU"] == str(nr_wniosku).strip()]
    return pd.DataFrame(wiersze, columns=["NR_WNIOSKU", "IMIE", "NAZWISKO", "PESEL", "STAN_CYWILNY"])


def load_kwoty_kredytu(nr_wniosku):
    return None


def get_document_cache(pdf_hash, nr_wniosku, hash_schematu):
    return _cache.get((pdf_hash, nr_wniosku, hash_schematu))


def save_document_cache(pdf_hash, nr_wniosku, hash_schematu, id_analizy,
                        document_type, ocr_text, extracted_data):
    _cache[(pdf_hash, nr_wniosku, hash_schematu)] = {
        "wynik": extracted_data,
        "ocr_text": ocr_text,
    }


def wczytaj_token():
    return "offline"


def wywolaj_ocr(plik_bajty, token, document_group_id):
    import pypdfium2 as pdfium

    dokument = pdfium.PdfDocument(plik_bajty)
    try:
        strony = []
        for strona in dokument:
            tekst = strona.get_textpage()
            strony.append(tekst.get_text_range())
            tekst.close()
            strona.close()
    finally:
        dokument.close()

    time.sleep(0.5)
    return ZNACZNIK_STRONY.join(strony)


def wywolaj_extract(tekst, token, document_id, schema):
    time.sleep(0.5)
    return _json("wynik_umowa_deweloperska.json")

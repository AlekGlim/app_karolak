"""Wybór źródeł danych: prawdziwe (serwer) albo offline (dev/).

Aplikacja importuje hurtownię i API wyłącznie stąd, więc przełączenie trybu
nie dotyka żadnej logiki — zmienia się tylko to, skąd przychodzą dane.
"""

from ustawienia import OFFLINE, PLIK_TOKENU

__all__ = [
    "NAZWA",
    "get_document_cache",
    "load_kwoty_kredytu",
    "load_wnioskodawcy",
    "save_document_cache",
    "wczytaj_token",
    "wywolaj_extract",
    "wywolaj_ocr",
]

if OFFLINE:
    from services.offline import (
        NAZWA,
        get_document_cache,
        load_kwoty_kredytu,
        load_wnioskodawcy,
        save_document_cache,
        wczytaj_token,
        wywolaj_extract,
        wywolaj_ocr,
    )
else:
    from services.hurtownia import (
        get_document_cache,
        load_kwoty_kredytu,
        load_wnioskodawcy,
        save_document_cache,
    )
    from services.sde_api import wywolaj_extract, wywolaj_ocr
    from services.sde_api import wczytaj_token as _wczytaj_token_z_pliku

    NAZWA = "Prawdziwe API"

    def wczytaj_token():
        return _wczytaj_token_z_pliku(PLIK_TOKENU)

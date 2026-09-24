"""Schematy ekstrakcji, prompt i klucze cache."""

import hashlib
import json

from ustawienia import SCHEMY_DIR

# Typ dokumentu -> plik schematu w katalogu schemy/.
# Typ wybiera zakładka, w której analityk wgrał plik — nie nazwa pliku.
# Zgadywanie z nazwy kierowało np. "przedwstepna_skan.pdf" wgrany w zakładce
# umowy deweloperskiej na inny schemat.
SCHEMATY = {
    "umowa_deweloperska": "umowa_deweloperska",
    "umowa_przedwstepna": "umowa_przedwstepna",
    "umowa_rezerwacyjna": "umowa_rezerwacyjna",
    "prospekt": "prospekt",
    "oswiadczenie_zbywcy": "oswiadczenie_zbywcy",
}

# Treść przeniesiona 1:1 z wcześniejszego f-stringa (łącznie z wcięciami),
# żeby refaktor nie zmienił tego, co widzi model.
SZABLON_PROMPTU = """
        DANE KLIENTÓW Z SYSTEMU UNIFLOW:

        {tekst_uniflow}

        PONIŻEJ ZNAJDUJE SIĘ TREŚĆ DOKUMENTU.

        Porównuj dane klientów z UniFlow z danymi nabywców
        występującymi w dokumencie.

        TREŚĆ DOKUMENTU:

        {ocr_text}
        """


def wczytaj_schema(typ_dokumentu):
    if typ_dokumentu not in SCHEMATY:
        raise ValueError(f"Nieznany typ dokumentu: {typ_dokumentu}")

    with open(SCHEMY_DIR / f"{SCHEMATY[typ_dokumentu]}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def tekst_uniflow(dane_uniflow):
    return json.dumps(dane_uniflow or {}, ensure_ascii=False, indent=2, default=str)


def zbuduj_prompt(dane_uniflow, ocr_text):
    return SZABLON_PROMPTU.format(
        tekst_uniflow=tekst_uniflow(dane_uniflow),
        ocr_text=ocr_text,
    )


def policz_hash_pdf(plik_bajty):
    return hashlib.sha256(plik_bajty).hexdigest()


def klucz_wersji(schema, dane_uniflow):
    """Wersja zapytania do modelu — trafia do kolumny hash_schematu w cache.

    Obejmuje wszystko, co poza samym dokumentem zmienia wynik:
      schemat         — inne pola albo opisy to inne pytanie do modelu
      szablon promptu — jw.
      dane UniFlow    — z nich liczona jest weryfikacja_uniflow; dopisanie
                        wnioskodawcy albo poprawka PESEL w UniFlow musi
                        unieważnić stary wynik

    sort_keys: samo przestawienie pól w pliku schematu nie unieważnia cache.
    """
    tekst = json.dumps(
        {"schema": schema, "prompt": SZABLON_PROMPTU, "uniflow": dane_uniflow or {}},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()

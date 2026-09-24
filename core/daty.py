"""Daty w tekście OCR — w zapisie liczbowym i słownym ("22 marca 2000")."""

import re
from datetime import date

from core.tekst import DLUGOSC_KONTEKSTU, normalizuj_do_szukania, strona_dla_pozycji


# Polskie nazwy miesięcy w dopełniaczu, już bez diakrytyków — szukamy w tekście
# przepuszczonym przez normalizuj_do_szukania ("września" -> "wrzesnia").
NUMERY_MIESIECY = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "wrzesnia": 9, "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}


# Dwa zapisy daty w jednym wyrażeniu:
#   22-03-2000 / 22.03.2000 / 22/03/2000 / 22 . 03 . 2000  (grupy 1, 2, 4)
#   22 marca 2000                                          (grupy 1, 3, 4)
# Lookbehind blokuje trafienia w środku dłuższego ciągu liczb (np. numeru
# rachunku), lookahead — w środku roku (20003).
WZORZEC_DATY = re.compile(
    r"(?<![\d.,/-])(\d{1,2})"
    r"(?:[ ]?[-./][ ]?(\d{1,2})[ ]?[-./][ ]?|[ ]+(" + "|".join(NUMERY_MIESIECY) + r")[ ]+)"
    r"(\d{4})(?!\d)"
)


def znajdz_daty(ocr_text):
    """Wszystkie daty w tekście: [{"data": date, "pozycja": ..., "koniec": ...}].

    Pozycje odnoszą się do oryginalnego tekstu (normalizacja zdejmuje
    diakrytyki, ale nie zmienia długości). Wyrażenia, które wyglądają jak data,
    a nią nie są (31-02-2000), są pomijane.
    """
    if not ocr_text:
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    daty = []

    for dop in WZORZEC_DATY.finditer(znorm):
        dzien = int(dop.group(1))
        miesiac = int(dop.group(2)) if dop.group(2) else NUMERY_MIESIECY[dop.group(3)]
        rok = int(dop.group(4))

        try:
            data = date(rok, miesiac, dzien)
        except ValueError:
            continue

        daty.append({"data": data, "pozycja": dop.start(), "koniec": dop.end()})

    return daty


def parsuj_date(tekst):
    """Data z tekstu albo None.

    Zwraca datę tylko wtedy, gdy tekst zawiera dokładnie jedną. "22-03-2000 r."
    to jedna data; "od 22-03-2000 do 30-04-2000" to dwie, więc nie zgadujemy.
    """
    if not tekst:
        return None

    daty = znajdz_daty(str(tekst))
    if len(daty) != 1:
        return None

    return daty[0]["data"]


def szukaj_daty_w_ocr(ocr_text, data):
    """Trafienia danej daty w tekście OCR — w każdym zapisie.

    Zwraca ten sam kształt co szukaj_w_ocr, więc wynik można mieszać
    z trafieniami zwykłego szukania.
    """
    trafienia = []

    for wpis in znajdz_daty(ocr_text):
        if wpis["data"] != data:
            continue

        start, koniec = wpis["pozycja"], wpis["koniec"]
        od = max(0, start - DLUGOSC_KONTEKSTU)
        do = min(len(ocr_text), koniec + DLUGOSC_KONTEKSTU)

        trafienia.append({
            "pozycja": start,
            "strona": strona_dla_pozycji(ocr_text, start),
            "przed": ocr_text[od:start],
            "trafienie": ocr_text[start:koniec],
            "po": ocr_text[koniec:do],
            "dokladne": True,
        })

    return trafienia

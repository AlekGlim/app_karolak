"""Indeks dokumentu do szukajki: tekst każdej strony + pozycje słów na stronie.

Strona pochodzi z jednego z dwóch źródeł:
  - tekst OCR podzielony po markerach [STRONA_X] — typowy przypadek (skany);
    endpoint zwraca markdown bez pozycji słów, więc wiadomo, na której
    stronie jest trafienie, ale nie gdzie na niej,
  - warstwa tekstowa PDF (słowa z prostokątami) — rzadziej, dla PDF-ów
    wygenerowanych cyfrowo; trafienie da się wtedy zaznaczyć na obrazie strony.

Kształt strony:
  {"numer": int, "tekst": str, "mapa": [indeks słowa | None na znak] | None,
   "slowa": [{"x0", "x1", "top", "bottom"}]}  (punkty PDF, początek w lewym górnym rogu)
"""

import re

from core.szukanie import szukaj_w_ocr_z_wariantami

WZORZEC_MARKERA_STRONY = re.compile(r"\[STRONA_(\d+)\]")


def strona_ze_slow(numer, slowa):
    """Strona ze słów z prostokątami; słowa sklejone spacją w kolejności czytania.

    `mapa` wiąże każdy znak sklejonego tekstu ze słowem, z którego pochodzi —
    po niej trafienie w tekście zamienia się w prostokąty na stronie.
    """
    fragmenty, mapa = [], []

    for indeks, slowo in enumerate(slowa):
        fragmenty.append(slowo["text"])
        mapa.extend([indeks] * len(slowo["text"]))
        fragmenty.append(" ")
        mapa.append(None)

    return {
        "numer": numer,
        "tekst": "".join(fragmenty),
        "mapa": mapa,
        "slowa": [
            {"x0": s["x0"], "x1": s["x1"], "top": s["top"], "bottom": s["bottom"]}
            for s in slowa
        ],
    }


def strony_z_ocr(ocr_text):
    """{numer strony: strona} z tekstu OCR z markerami [STRONA_X]."""
    czesci = WZORZEC_MARKERA_STRONY.split(ocr_text or "")

    return {
        int(numer): {"numer": int(numer), "tekst": tekst, "mapa": None, "slowa": []}
        for numer, tekst in zip(czesci[1::2], czesci[2::2])
    }


def zloz_strony(strony_pdf, strony_ocr, liczba_stron):
    """Dla każdej strony: warstwa tekstowa PDF, jeśli ma słowa, inaczej tekst OCR.

    Wybór per strona, bo zdarzają się dokumenty mieszane (skan z doklejoną
    stroną wygenerowaną cyfrowo).
    """
    strony = []

    for numer in range(1, liczba_stron + 1):
        z_pdf = strony_pdf[numer - 1] if numer - 1 < len(strony_pdf) else None

        if z_pdf and z_pdf["slowa"]:
            strony.append(z_pdf)
        elif numer in strony_ocr:
            strony.append(strony_ocr[numer])
        else:
            strony.append({"numer": numer, "tekst": "", "mapa": None, "slowa": []})

    return strony


def scal_w_linie(slowa, indeksy):
    """Jeden prostokąt na linię tekstu.

    Fraza łamana między liniami daje dwa prostokąty, a nie jeden obejmujący
    pół strony.
    """
    if not indeksy:
        return []

    boxy = [slowa[i] for i in sorted(indeksy)]
    linie, biezaca = [], [boxy[0]]

    for box in boxy[1:]:
        poprzedni = biezaca[-1]
        wysokosc = poprzedni["bottom"] - poprzedni["top"]
        if abs(box["top"] - poprzedni["top"]) < wysokosc * 0.6:
            biezaca.append(box)
        else:
            linie.append(biezaca)
            biezaca = [box]
    linie.append(biezaca)

    return [{
        "x0": min(b["x0"] for b in linia),
        "x1": max(b["x1"] for b in linia),
        "top": min(b["top"] for b in linia),
        "bottom": max(b["bottom"] for b in linia),
    } for linia in linie]


def znajdz_w_stronach(strony, zapisy):
    """Trafienia zapisów (format warianty_do_szukania) na stronach, po kolei.

    Reguły szukania (dosłownie, odmiana jako zapas, każdy zapis daty i kwoty)
    są te same co w core.szukanie — tu dochodzi tylko numer strony
    i prostokąty do podświetlenia.
    """
    trafienia = []

    for strona in strony:
        if not strona["tekst"].strip():
            continue

        for trafienie in szukaj_w_ocr_z_wariantami(strona["tekst"], zapisy):
            prostokaty = []

            if strona["mapa"]:
                koniec = trafienie["pozycja"] + len(trafienie["trafienie"])
                indeksy = {
                    strona["mapa"][i]
                    for i in range(trafienie["pozycja"], koniec)
                    if strona["mapa"][i] is not None
                }
                prostokaty = scal_w_linie(strona["slowa"], indeksy)

            trafienia.append({**trafienie, "strona": strona["numer"], "prostokaty": prostokaty})

    return trafienia


def pierwsze_do_pokazania(trafienia):
    """Indeks trafienia, od którego zaczyna szukajka.

    Klik w pole ma pokazać to, co w polu stoi — wartość niezgodną pokazujemy
    na starcie tylko wtedy, gdy nic innego nie znaleziono.
    """
    for indeks, trafienie in enumerate(trafienia):
        if trafienie.get("rodzaj") != "zla":
            return indeks
    return 0

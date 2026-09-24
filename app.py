"""
Hipoteka AI — analiza umowy deweloperskiej (Proof of Concept)
Aplikacja Streamlit dla analityków hipotecznych.

Pliki projektu:
  app.py          ten plik — cała aplikacja
  data_loader.py  hurtownia: dane wniosku z UniFlow, cache wyników (tylko serwer)
  schemy/*.json   schematy ekstrakcji = pytanie do modelu
  dev/            dane trybu offline (opcjonalne, do pracy lokalnej)

Przepływ: numer wniosku -> dane klientów z UniFlow; upload PDF -> OCR ->
ekstrakcja (schemat + dane UniFlow w prompcie) -> panel ustaleń, dane z dokumentu,
szukajka, podsumowanie i ryzyka. Wynik trafia do cache w hurtowni.

Sekcje pliku (w tej kolejności):
  USTAWIENIA · TEKST OCR · KWOTY · DATY · WALIDACJE · SZUKANIE · INDEKS DOKUMENTU
  · ROZBIEŻNOŚCI · USTALENIA · SCHEMATY, PROMPT I KLUCZ CACHE · API · PDF
  · TRYB OFFLINE · ŹRÓDŁA DANYCH · ANALIZA · STAN SESJI · WIDOK: PANEL DOKUMENTU
  · widoki aplikacji (CSS, panel boczny, dane wniosku, pola, ustalenia, zakładki, main)

Sekcje od USTAWIEŃ do ROZBIEŻNOŚCI/USTALEŃ nie używają Streamlita — to czysta
logika, pokryta testami w tests/.

Lokalnie, bez hurtowni: HIPOTEKA_OFFLINE=1 streamlit run app.py — podmienia
wyłącznie źródła danych na pliki z dev/. Szczegóły: docs/INSTRUKCJA.md.

Stronę i miejsce każdej wartości wskazuje model (lista `zrodla`: pole, strona,
krótki cytat), a Python sprawdza, czy cytat naprawdę stoi na tej stronie
tekstu OCR (zweryfikuj_zrodla). Gdy stoi na innej stronie — wygrywa tekst;
gdy nie ma go w tekście — pole dostaje ✕. Wynik bez `zrodla` (starszy cache)
wraca do szukania wartości w tekście OCR i strony z markera [STRONA_X].
Kluczowe pola (daty,
identyfikatory, strony umowy) model zwraca z trzema poziomami: wartość główna,
inne zapisy tej samej wartości (wartosci_ok) i zapisy niezgodne (wartosci_zle).
Python sprawdza, czy każdy zapis naprawdę stoi w tekście, a dla dat
i identyfikatorów sam rozstrzyga, który zapis jest "ok", a który "zły"
(splaszcz_wynik, rozstrzygnij_podzial).

MOTYW: aplikacja podąża za motywem przeglądarki (jasny/ciemny). Aby to działało,
NIE ustawiaj base="light" w .streamlit/config.toml. Plik ustawia tylko kolor
akcentu kontrolek Streamlita (fioletowy) osobno dla motywu jasnego i ciemnego.
"""

import base64
import hashlib
import html
import io
import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache, partial
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pypdfium2 as pdfium
import requests
import streamlit as st

# Przycisk kopiowania wartości do UniFlow. Gdy pakietu nie ma w środowisku,
# aplikacja działa dalej — tylko bez przycisków (wymaga: pip install st-copy).
try:
    from st_copy import copy_button
    MA_KOPIOWANIE = True
except ImportError:
    copy_button = None
    MA_KOPIOWANIE = False


# =====================================================================
# USTAWIENIA
# =====================================================================
# Stałe aplikacji. Wartości zależne od środowiska można nadpisać zmienną
# środowiskową (HIPOTEKA_TOKEN, HIPOTEKA_CA_CERT, HIPOTEKA_BASE_URL,
# HIPOTEKA_LIMIT_OCR_S, HIPOTEKA_LIMIT_EKSTRAKCJI_S, HIPOTEKA_OFFLINE).

KATALOG_APLIKACJI = Path(__file__).resolve().parent

BASE_URL = os.environ.get("HIPOTEKA_BASE_URL", "https://hdspprd1.ux.mbank.pl/sde_service/api")
CA_CERT = os.environ.get("HIPOTEKA_CA_CERT", "/home/jovyan/security/ca.pem")
PLIK_TOKENU = Path(os.environ.get(
    "HIPOTEKA_TOKEN",
    "/home/jovyan/projects/analiza_prawna_hipoteka/token.txt",
))

SCHEMY_DIR = KATALOG_APLIKACJI / "schemy"
PLIK_LOGO = KATALOG_APLIKACJI / "logo_mbank.jpg"
KATALOG_DEV = KATALOG_APLIKACJI / "dev"

# Limity czasu zadań po stronie API (sekundy). Ekstrakcja długiego aktu
# notarialnego z sekcją rozbieżności potrafi trwać dłużej niż OCR.
LIMIT_OCR_S = int(os.environ.get("HIPOTEKA_LIMIT_OCR_S", "180"))
LIMIT_EKSTRAKCJI_S = int(os.environ.get("HIPOTEKA_LIMIT_EKSTRAKCJI_S", "300"))
ODSTEP_ODPYTYWANIA_S = 3

# Tryb offline: hurtownia i API zastąpione danymi z katalogu dev/.
# Wyłącznie do pracy nad wyglądem na komputerze bez dostępu do hurtowni.
OFFLINE = os.environ.get("HIPOTEKA_OFFLINE") == "1"


# =====================================================================
# TEKST OCR — normalizacja, markery stron, fragmenty do wyświetlenia
# =====================================================================
# Tekst OCR: normalizacja do porównań i znaczniki stron [STRONA_X].

def dodaj_markery_stron(ocr_text):

    # Znacznik bywa zapisany z encjami HTML (&lt;!-- ... --&gt;, jak w danych
    # demo) albo wprost (<!-- ... -->) — bez drugiego wariantu cały dokument
    # trafiłby na stronę 1.
    strony = re.split(
        r'(?:&lt;|<)!--\s*PageBreak\s*--(?:&gt;|>)',
        ocr_text
    )

    wynik = []

    for nr, tresc in enumerate(
        strony,
        start=1
    ):
        wynik.append(
            f"\n\n[STRONA_{nr}]\n{tresc}"
        )

    return "".join(wynik)


DLUGOSC_KONTEKSTU = 200


@lru_cache(maxsize=None)
def _znak_do_szukania(znak):
    """Jeden znak bez diakrytyku i wielkości liter — zawsze jeden znak.

    NFKD rozwija też znaki złożone ("…" -> "...", "ﬁ" -> "fi", "№" -> "No"),
    a "İ".lower() daje dwa znaki. Taki znak zostaje bez zmian: wynik ma mieć
    tę samą długość co wejście.
    """
    bez_diakrytyku = "".join(
        z for z in unicodedata.normalize("NFKD", znak)
        if not unicodedata.combining(z)
    ).lower()

    if len(bez_diakrytyku) == 1:
        return bez_diakrytyku

    maly = znak.lower()
    return maly if len(maly) == 1 else znak


def normalizuj_do_szukania(tekst):
    """Bez diakrytyków i wielkości liter — analityk wpisuje frazę z pamięci.

    Wynik ma zawsze tę samą długość co wejście: pozycje trafień w tekście
    znormalizowanym służą do wycinania fragmentów i szukania markera strony
    w tekście oryginalnym. Przy normalizacji całego tekstu naraz jeden "…"
    przesuwał wszystkie dalsze trafienia o dwa znaki.
    """
    return "".join(map(_znak_do_szukania, str(tekst)))


def strona_dla_pozycji(ocr_text, pozycja):
    """Numer strony dla znalezionej pozycji — po ostatnim markerze [STRONA_X].

    Zwraca None, gdy tekst nie ma markerów (np. wynik z cache zapisany
    przed ich dodaniem).
    """
    fragment = ocr_text[:pozycja]
    markery = re.findall(r"\[STRONA_(\d+)\]", fragment)
    return int(markery[-1]) if markery else None


def normalizuj_do_porownania(tekst):
    """Wielkość liter i układ białych znaków nie mają znaczenia — reszta tak.

    Celowo NIE zdejmujemy diakrytyków ani nie skracamy końcówek (jak robi to
    normalizuj_do_szukania). Tu pytamy "czy ten zapis naprawdę tam stoi",
    więc im ostrzejsze porównanie, tym mniej fałszywych potwierdzeń.
    """
    return re.sub(r"\s+", " ", str(tekst)).strip().lower()


def tekst_do_wyswietlenia(fragment):
    """Fragment tekstu OCR w postaci do pokazania analitykowi.

    Endpoint OCR (prebuilt-layout) zwraca markdown z encjami zamiast < i >:
    tabele jako &lt;table&gt;&lt;tr&gt;&lt;td&gt;…, komentarze stron
    (&lt;!-- PageHeader=… --&gt;), nagłówki "# ", znaczniki pól wyboru.
    Tu zostaje sam tekst: komórki tabeli rozdzielone " · ", wiersze " | ", reszta znaczników
    usunięta. Fragment jest wycinkiem, więc obcięte znaczniki na jego
    brzegach też są usuwane.

    Wynik to zwykły tekst — przed wstawieniem do HTML trzeba go escapować.
    """
    tekst = str(fragment)

    # encja przecięta brzegiem wycinka ("&l" na końcu, "t;" na początku)
    tekst = re.sub(r"&[a-zA-Z#0-9]{0,7}$", "", tekst)
    tekst = re.sub(r"^(?:l?t|g?t|a?m?p|q?u?o?t);", "", tekst)

    tekst = html.unescape(tekst)

    # komentarze, także obcięte na brzegach wycinka
    tekst = re.sub(r"<!--.*?-->", " ", tekst, flags=re.DOTALL)
    tekst = re.sub(r"^[^<]*?-->", " ", tekst, flags=re.DOTALL)
    tekst = re.sub(r"<!--.*$", " ", tekst, flags=re.DOTALL)

    # tabele: granica komórek -> separator, pozostałe znaczniki -> odstęp
    tekst = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " · ", tekst)
    tekst = re.sub(r"</t[dh]>\s*</tr>\s*<tr[^>]*>\s*<t[dh][^>]*>", " | ", tekst)
    tekst = re.sub(r"</tr>\s*<tr[^>]*>", " | ", tekst)
    tekst = re.sub(r"</?[a-zA-Z][^>]*>", " ", tekst)
    tekst = re.sub(r"^\s*/?[a-zA-Z]{1,10}>", " ", tekst)   # "td>" na początku wycinka
    tekst = re.sub(r"</?[a-zA-Z]{0,10}$", " ", tekst)       # "</t" na końcu wycinka

    tekst = re.sub(r"(?m)^\s*#{1,6}\s+", "", tekst)
    tekst = re.sub(r":(?:un)?selected:", " ", tekst)

    return re.sub(r"\s+", " ", tekst)


# =====================================================================
# KWOTY
# =====================================================================
# Kwoty w złotych: odczyt z tekstu i wzorce do szukania w OCR.

def wyciagnij_kwote(tekst):
    """Kwota w groszach z tekstu pola albo 0.

    Kolejno próbujemy:
      1. kwoty z groszami gdziekolwiek w tekście ("transza 1: 150 000,00 zł")
      2. całego pola jako kwoty ("450 000", "450 000 zł")
      3. kwoty bez groszy zakończonej walutą ("50 000 zł (zadatek)")

    Bez kroków 2-3 kwota zapisana bez ",00" dawała 0 i suma transz
    fałszywie nie zgadzała się z wartością transakcji.
    """
    if not tekst:
        return 0

    tekst = str(tekst)

    match = re.search(r'(\d[\d .]*,\d{2})', tekst)
    if match:
        return int(re.sub(r"[ .,]", "", match.group(1)))

    cale_pole = kwota_na_grosze(tekst)
    if cale_pole is not None:
        return cale_pole

    match = re.search(r"(\d{1,3}(?:[ .]\d{3})+|\d+)\s*(?:zł|zl|pln)", tekst, re.IGNORECASE)
    if match:
        return kwota_na_grosze(match.group(1)) or 0

    return 0


def kwota_na_grosze(tekst):
    """Kwota jako liczba groszy albo None.

    Rozumie "450 000,00 zł", "450.000,00", "450000", "450 000". Ostatni
    separator z 1-2 cyframi po nim to część ułamkowa; z trzema cyframi —
    separator tysięcy ("45.000" to 45 tysięcy, nie 45 zł).
    """
    if tekst is None:
        return None

    czysty = re.sub(r"(?i)z[łl]\b|pln|\s", "", str(tekst))
    dop = re.fullmatch(r"(\d+(?:[.,]\d{3})*)(?:[.,](\d{1,2}))?", czysty)
    if not dop:
        return None

    zlote = int(re.sub(r"[.,]", "", dop.group(1)))
    grosze = int(dop.group(2).ljust(2, "0")) if dop.group(2) else 0

    return zlote * 100 + grosze


def wzorzec_kwoty(grosze, scisle=True):
    """Wyrażenie regularne dopasowujące daną kwotę w każdym zapisie.

    Separator tysięcy może być spacją, kropką, złamaniem linii albo go nie
    być; część ułamkowa jest opcjonalna, gdy grosze są zerowe. Złamanie
    linii dopuszczamy, bo OCR skanu dzieli kwotę w tabeli na dwie linie
    ("720\\n000,00 zł") tak samo łatwo jak resztę tekstu — bez tego kwota
    z wyraźnie widocznej tabeli wychodziłaby jako "brak w dokumencie".
    Lookbehind i lookahead pilnują, żeby 500 nie dopasowało się do środka
    "45 500,00" ani "500 000", a kwota bez groszy nie złapała "450 000,50".

    `scisle=False` dopuszcza cyfry oddzielone odstępem przed kwotą: w tabeli
    zapisanej zwykłym tekstem numer wiersza stoi tuż przed kwotą
    ("1 144 000,00 zł 21-03-2026") i ściśle wygląda to na kwotę 1 144 000,00.
    Kropka przed kwotą dalej odpada — "1.144.000" to separator tysięcy.
    """
    zlote, gr = divmod(grosze, 100)

    cyfry = str(zlote)
    grupy = []
    while len(cyfry) > 3:
        grupy.insert(0, cyfry[-3:])
        cyfry = cyfry[:-3]
    grupy.insert(0, cyfry)

    calkowita = r"[\s.]?".join(grupy)
    ulamek = r"(?:,00)?" if gr == 0 else f",{gr:02d}"

    przed = r"(?<![\d,.])(?<!\d[\s.])" if scisle else r"(?<![\d,.])(?<!\d\.)"

    return przed + calkowita + ulamek + r"(?!\d|,\d|[\s.]\d{3})"


# Zapis, który na pewno jest kwotą: z separatorem tysięcy albo z groszami.
# Same cyfry ("2026", PESEL, numer działki) kwotą nie są.
WZORZEC_ZAPISU_KWOTY = re.compile(r"\d{1,3}(?:[ .]\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}")


def kwota_z_frazy(tekst):
    """Grosze, gdy fraza wygląda na kwotę; w przeciwnym razie None."""
    if tekst is None:
        return None

    czysty = re.sub(r"(?i)\s*(?:z[łl]|pln)\.?\s*$", "", str(tekst).strip())
    if not WZORZEC_ZAPISU_KWOTY.fullmatch(czysty):
        return None

    return kwota_na_grosze(czysty)


# =====================================================================
# DATY
# =====================================================================
# Daty w tekście OCR — w zapisie liczbowym i słownym ("22 marca 2000").

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

# Zapis zaczynający się od roku: 2000-03-22 / 2000.03.22 / 2000/03/22.
# Oba separatory muszą być takie same — "2000-03.22" to raczej fragment
# numeru niż data.
WZORZEC_DATY_OD_ROKU = re.compile(
    r"(?<![\d.,/-])(\d{4})[ ]?([-./])[ ]?(\d{1,2})[ ]?\2[ ]?(\d{1,2})(?!\d|[-./]\d)"
)


def znajdz_daty(ocr_text):
    """Wszystkie daty w tekście: [{"data": date, "pozycja": ..., "koniec": ...}].

    Rozumie zapis od dnia (22-03-2000, 22 marca 2000) i od roku (2000-03-22).
    Pozycje odnoszą się do oryginalnego tekstu (normalizacja zdejmuje
    diakrytyki, ale nie zmienia długości). Wyrażenia, które wyglądają jak data,
    a nią nie są (31-02-2000), są pomijane.
    """
    if not ocr_text:
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    daty = []

    def dodaj(dop, rok, miesiac, dzien):
        try:
            data = date(rok, miesiac, dzien)
        except ValueError:
            return
        daty.append({"data": data, "pozycja": dop.start(), "koniec": dop.end()})

    for dop in WZORZEC_DATY.finditer(znorm):
        miesiac = int(dop.group(2)) if dop.group(2) else NUMERY_MIESIECY[dop.group(3)]
        dodaj(dop, int(dop.group(4)), miesiac, int(dop.group(1)))

    for dop in WZORZEC_DATY_OD_ROKU.finditer(znorm):
        dodaj(dop, int(dop.group(1)), int(dop.group(3)), int(dop.group(4)))

    return sorted(daty, key=lambda d: d["pozycja"])


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

        trafienia.append(_trafienie(ocr_text, wpis["pozycja"], wpis["koniec"]))

    return trafienia


# =====================================================================
# WALIDACJE — PESEL, NRB, suma transz, numer wniosku
# =====================================================================
# Twarde walidacje liczone w Pythonie: PESEL, NRB, suma harmonogramu.

def waliduj_nrb(numer):

    if not numer:
        return "Brak numeru"

    nrb = "".join(filter(str.isdigit, str(numer)))

    if len(nrb) != 26:
        return "❌ Niepoprawna długość"

    try:
        liczba = nrb[2:] + "2521" + nrb[:2]

        if int(liczba) % 97 == 1:
            return "Poprawny strukturalnie"

        return "Niepoprawna suma kontrolna"

    except Exception:
        return "Błąd walidacji"


def waliduj_pesel(pesel):

    if not pesel:
        return "⚪"

    pesel = "".join(filter(str.isdigit, str(pesel)))

    if len(pesel) != 11:
        return "❌"

    try:

        rok = int(pesel[0:2])
        miesiac = int(pesel[2:4])
        dzien = int(pesel[4:6])

        if 1 <= miesiac <= 12:
            rok += 1900

        elif 21 <= miesiac <= 32:
            rok += 2000
            miesiac -= 20

        elif 41 <= miesiac <= 52:
            rok += 2100
            miesiac -= 40

        elif 61 <= miesiac <= 72:
            rok += 2200
            miesiac -= 60

        elif 81 <= miesiac <= 92:
            rok += 1800
            miesiac -= 80

        else:
            return "❌"

        datetime(rok, miesiac, dzien)

        wagi = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]

        suma = sum(
            int(c) * w
            for c, w in zip(pesel[:10], wagi)
        )

        kontrolna = (10 - (suma % 10)) % 10

        if kontrolna != int(pesel[10]):
            return "❌"

        return "✅"

    except Exception:
        return "❌"


def wartosc_transakcji(wynik):
    """Wartość, do której powinny sumować się transze, w groszach (0 = brak)."""
    return wyciagnij_kwote(
        wynik.get("laczna_wartosc_transakcji")
        or wynik.get("cena_nieruchomosci")
    )


def kwota_transzy(kwota, cena):
    """Kwota transzy w groszach albo None, gdy nie da się jej ustalić.

    Umowa może podać transzę tylko procentem ceny ("20% ceny") — wtedy
    liczymy ją od ceny. Kwota podana obok procentu ("20%, tj. 144 000 zł")
    ma pierwszeństwo, bo to ją przelewa bank.
    """
    grosze = wyciagnij_kwote(kwota)
    if grosze:
        return grosze

    procent = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(kwota or ""))
    if procent and cena:
        return round(cena * float(procent.group(1).replace(",", ".")) / 100)

    return None


def suma_transz(wynik, cena):
    """Suma transz w groszach albo None, gdy którejś kwoty nie da się ustalić.

    None zamiast liczenia takiej transzy jako 0 — inaczej jedna nieczytelna
    kwota dawała fałszywy alarm "suma transz nie zgadza się".
    """
    kwoty = [kwota_transzy(t.get("kwota"), cena) for t in wynik.get("harmonogram_transz") or []]
    if not kwoty or None in kwoty:
        return None
    return sum(kwoty)


def czy_wartosc_transakcji_zgodna(wynik):
    """✅ / ❌ gdy sumę transz da się porównać z wartością transakcji, inaczej ⚪."""
    cena = wartosc_transakcji(wynik)
    suma = suma_transz(wynik, cena)

    if cena == 0 or suma is None:
        return "⚪"

    return "✅" if cena == suma else "❌"


# Numer wniosku trafia do zapytań SQL, więc dopuszczamy wyłącznie znaki
# spotykane w numerach (np. KHB1553044, WN/2026/00184521). Apostrof, spacja,
# średnik itp. są odrzucane, zanim cokolwiek pójdzie do hurtowni.
# Ta sama reguła stoi w data_loader.py (_NUMER_WNIOSKU) — zmieniając jedną, zmień obie.
WZORZEC_NUMERU_WNIOSKU = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.\-]{0,63}")


def czy_poprawny_numer_wniosku(numer):
    return bool(numer) and WZORZEC_NUMERU_WNIOSKU.fullmatch(str(numer)) is not None


# =====================================================================
# SZUKANIE W TEKŚCIE OCR
# =====================================================================
# Szukanie wartości w tekście OCR i wyznaczanie numeru strony.
#
# Numery stron są deterministyczne: wartość jest szukana w tekście OCR,
# a strona wynika z najbliższego markera [STRONA_X] przed trafieniem.

def _trafienie(ocr_text, start, koniec, dokladne=True):
    """Trafienie w kształcie wspólnym dla wszystkich rodzajów szukania."""
    od = max(0, start - DLUGOSC_KONTEKSTU)
    do = min(len(ocr_text), koniec + DLUGOSC_KONTEKSTU)
    return {
        "pozycja": start,
        "strona": strona_dla_pozycji(ocr_text, start),
        "przed": ocr_text[od:start],
        "trafienie": ocr_text[start:koniec],
        "po": ocr_text[koniec:do],
        "dokladne": dokladne,
    }


def wzorzec_z_odmiana(fraza):
    """Regex tolerujący polską odmianę: dłuższe słowa skracamy o końcówkę.

    W akcie notarialnym stoi "w Warszawie", a w polu mamy "Warszawa".
    Bez tego połowa pól tekstowych nie znalazłaby się w dokumencie.
    """
    slowa = normalizuj_do_szukania(fraza).split()
    if not slowa:
        return None

    czesci = []
    for slowo in slowa:
        rdzen = re.escape(slowo[:-2]) if len(slowo) > 5 else re.escape(slowo)
        czesci.append(rdzen + r"\w*")

    return r"\b" + r"\s+".join(czesci)


def szukaj_w_ocr(ocr_text, fraza):
    """Trafienia frazy w tekście OCR, z numerem strony i fragmentem kontekstu."""
    if not ocr_text or not fraza or not str(fraza).strip():
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    trafienia = []

    def zbierz(wzor, dokladne):
        for dop in re.finditer(wzor, znorm):
            trafienia.append(_trafienie(ocr_text, *dop.span(), dokladne))

    # Słowa frazy rozdziela dowolny odstęp: w tekście OCR fraza łamie się
    # na końcu linii ("księgę\nwieczystą"), a pole z modelu ma zwykłą spację.
    slowa = normalizuj_do_szukania(fraza).split()
    if slowa:
        zbierz(r"\s+".join(re.escape(slowo) for slowo in slowa), True)

    # Odmiana dopiero jako zapas — inaczej "Nowak" łapałoby "Nowakowski".
    if not trafienia:
        wzor_odmiana = wzorzec_z_odmiana(fraza)
        if wzor_odmiana:
            zbierz(wzor_odmiana, False)

    widziane, unikalne = set(), []
    for t in sorted(trafienia, key=lambda t: t["pozycja"]):
        if t["pozycja"] not in widziane:
            widziane.add(t["pozycja"])
            unikalne.append(t)

    return unikalne


# Typ frazy decyduje, jak jej szukamy. Daty, kwoty i identyfikatory mają
# w dokumencie wiele zapisów tej samej wartości (2000-03-22 / 22 marca 2000,
# 450 000,00 / 450.000,00, WA1M/00012345/6 / WA1M 00012345 6) — szukamy ich
# po znaczeniu, a nie po napisie. Reszta (nazwiska, adresy) dosłownie.

def rozpoznaj_typ_frazy(fraza):
    """"data", "kwota", "identyfikator" albo "tekst"."""
    if parsuj_date(fraza):
        return "data"
    if kwota_z_frazy(fraza) is not None:
        return "kwota"
    if klucz_identyfikatora(fraza):
        return "identyfikator"
    return "tekst"


# Identyfikator: ciąg liter i cyfr rozdzielony spacjami, myślnikami,
# ukośnikami lub kropkami. Każda część ma cyfrę albo jest krótkim prefiksem
# literowym (PL w numerze rachunku), a cyfr jest co najmniej 6 — dzięki temu
# "Jan Kowalski" czy numer lokalu "20A" zostają zwykłym tekstem.
MIN_CYFR_IDENTYFIKATORA = 6
SEPARATOR_IDENTYFIKATORA = r"(?:[ \t]*[-/.][ \t]*|\s+)"


def klucz_zapisu_identyfikatora(tekst):
    """Same litery i cyfry, gdy tekst ma kształt identyfikatora; inaczej None.

    Bez progu liczby cyfr — dla pól, o których wiemy, że są identyfikatorami
    (numer działki "12/5" też się tu kwalifikuje).
    """
    if tekst is None:
        return None

    czesci = re.split(SEPARATOR_IDENTYFIKATORA, normalizuj_do_szukania(tekst).strip())
    if not all(re.fullmatch(r"[a-z0-9]+", c) for c in czesci):
        return None
    if not all(any(z.isdigit() for z in c) or len(c) <= 2 for c in czesci):
        return None

    return "".join(czesci)


def klucz_identyfikatora(fraza):
    """Same litery i cyfry identyfikatora ("wa1m000123456") albo None.

    Dla dowolnej frazy z szukajki, więc z progiem cyfr: "20A" to nie identyfikator.
    """
    klucz = klucz_zapisu_identyfikatora(fraza)
    if not klucz or sum(z.isdigit() for z in klucz) < MIN_CYFR_IDENTYFIKATORA:
        return None

    return klucz


def wzorzec_identyfikatora(klucz):
    """Regex dopasowujący identyfikator w każdym układzie separatorów.

    Między dowolnymi dwoma znakami może stać separator albo nie. Granice
    pilnują, żeby PESEL nie dopasował się do środka numeru rachunku zapisanego
    w grupach ("61 1090 1014 0000 ...") — przed i po trafieniu nie może być
    litery ani cyfry, także za pojedynczym separatorem w tej samej linii.
    """
    srodek = f"{SEPARATOR_IDENTYFIKATORA}?".join(re.escape(z) for z in klucz)
    return (
        r"(?<![a-z0-9])(?<![a-z0-9][-/.])(?<![0-9][ \t])"
        + srodek
        + r"(?![a-z0-9])(?![-/.][a-z0-9])(?![ \t][-/.]?[ \t]?[0-9])"
    )


def szukaj_identyfikatora_w_ocr(ocr_text, klucz):
    """Trafienia identyfikatora niezależnie od spacji, myślników i ukośników.

    Ten sam kształt wyniku co szukaj_w_ocr.
    """
    if not ocr_text or not klucz:
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    return [
        _trafienie(ocr_text, *dop.span())
        for dop in re.finditer(wzorzec_identyfikatora(klucz), znorm)
    ]


def warianty_do_szukania(fraza, potwierdzone):
    """Zapisy do wyszukania: [{"fraza": ..., "rodzaj": ...}].

    Gdy wpisana fraza jest jednym z zapisów pola z rozbieżnością, szukamy
    wszystkich jego zapisów — także niezgodnych, bo analityk chce zobaczyć,
    gdzie w dokumencie one stoją. Rodzaj pozwala je potem rozróżnić kolorem;
    bez tego "Nowak" wyglądałby na liście trafień tak samo jak "Kowalski".

    Gdy fraza nie należy do żadnego pola z rozbieżnością, zwraca samą frazę —
    szukajka działa wtedy jak dotychczas.
    """
    znorm_fraza = normalizuj_do_porownania(fraza)

    for wpis in (potwierdzone or []):
        zapisy = [{"fraza": wpis["wartosc_glowna"], "rodzaj": "glowna"}]

        for wartosc in wpis["wartosci_ok"]:
            zapisy.append({"fraza": wartosc, "rodzaj": "ok"})

        for wartosc in wpis["wartosci_zle"]:
            zapisy.append({"fraza": wartosc, "rodzaj": "zla"})

        if znorm_fraza in [normalizuj_do_porownania(z["fraza"]) for z in zapisy]:
            return zapisy

    return [{"fraza": fraza, "rodzaj": "szukana"}]


def szukaj_w_ocr_z_wariantami(ocr_text, zapisy):
    """Trafienia dla kilku zapisów naraz, posortowane po pozycji w tekście.

    `zapisy` w formacie z warianty_do_szukania. Każdy zapis szukamy osobno,
    sposobem zależnym od typu frazy (rozpoznaj_typ_frazy): data, kwota
    i identyfikator w każdym zapisie, tekst dosłownie z odmianą jako zapasem.
    Rodzaj zapisu przechodzi na trafienie.

    Gdy dwa zapisy trafią w to samo miejsce, wygrywa ten wcześniejszy na
    liście — dlatego warianty_do_szukania zwraca najpierw wartość główną,
    potem "ok", a na końcu niezgodne.
    """
    wszystkie = []

    for zapis in zapisy:
        fraza = zapis["fraza"]
        typ = rozpoznaj_typ_frazy(fraza)

        if typ == "kwota":
            # Kwotę i identyfikator szukamy wyłącznie ich wzorcem: łapie każdy
            # zapis i pilnuje granic liczby. Szukanie dosłowne znalazłoby
            # "685 000,00" także w środku "1 685 000,00", a zapas z odmianą
            # dopasowałby PESEL do dłuższego ciągu cyfr.
            trafienia_zapisu = szukaj_kwoty_w_ocr(ocr_text, kwota_z_frazy(fraza))
        elif typ == "identyfikator":
            trafienia_zapisu = szukaj_identyfikatora_w_ocr(ocr_text, klucz_identyfikatora(fraza))
        else:
            trafienia_zapisu = szukaj_w_ocr(ocr_text, fraza)

        # data znajduje się w każdym zapisie ("2000-03-22" znajdzie też
        # "22 marca 2000"); szukanie dosłowne zostaje dla fraz z datą w środku
        if typ == "data":
            trafienia_zapisu += szukaj_daty_w_ocr(ocr_text, parsuj_date(fraza))

        for trafienie in trafienia_zapisu:
            trafienie["fraza"] = zapis["fraza"]
            trafienie["rodzaj"] = zapis["rodzaj"]
            wszystkie.append(trafienie)

    widziane, unikalne = set(), []
    for t in sorted(wszystkie, key=lambda t: t["pozycja"]):
        if t["pozycja"] not in widziane:
            widziane.add(t["pozycja"])
            unikalne.append(t)

    return unikalne


def szukaj_kwoty_w_ocr(ocr_text, grosze):
    """Trafienia danej kwoty w tekście OCR — w każdym zapisie.

    Najpierw ściśle. Gdy nic nie ma, drugi raz z cyframi przed kwotą (numer
    wiersza tabeli zapisanej zwykłym tekstem, patrz wzorzec_kwoty) — takie
    trafienie jest niepewne ("dokladne": False), bo może być środkiem
    większej kwoty. Ten sam kształt wyniku co szukaj_w_ocr.
    """
    if not ocr_text:
        return []

    znorm = normalizuj_do_szukania(ocr_text)

    for scisle in (True, False):
        trafienia = [
            _trafienie(ocr_text, *dop.span(), scisle)
            for dop in re.finditer(wzorzec_kwoty(grosze, scisle), znorm)
        ]
        if trafienia:
            return trafienia

    return []


def strona_dla_wartosci(ocr_text, wartosc, potwierdzone=None, rodzaj=None):
    """Strona pierwszego trafienia wartości w tekście OCR albo None.

    W pełni deterministyczne: ta sama wartość i ten sam tekst dają zawsze
    tę samą stronę. Trafienia bez markera strony pomijamy — to tekst sprzed
    pierwszego markera albo wynik z cache zapisany bez markerów; zwrócenie
    None jest wtedy uczciwsze niż zgadywanie.

    `rodzaj` ("data" albo "kwota") włącza szukanie odporne na zapis: data
    zwrócona jako 22-03-2000 zostanie znaleziona jako "22 marca 2000",
    a kwota "450 000,00 zł" jako "450.000,00". Gdy to nie da trafienia
    (albo wartości nie da się odczytać), szukamy zwykłym tekstem.

    Pierwsze trafienie to świadomy wybór: wartości powtarzają się w całym
    dokumencie (miasto, nazwa dewelopera), a analityk zwykle chce zobaczyć,
    gdzie wartość pojawia się po raz pierwszy. Kolejne strony znajdzie
    w szukajce.

    `ocr_text` przychodzi parametrem, a nie z session_state — dzięki temu
    funkcja działa na tekście właściwego dokumentu i da się ją przetestować.
    """
    if rodzaj == "data":
        data = parsuj_date(wartosc)
        if data:
            for trafienie in szukaj_daty_w_ocr(ocr_text, data):
                if trafienie["strona"]:
                    return trafienie["strona"]

    if rodzaj == "kwota":
        strona = strona_dla_kwoty(ocr_text, wartosc)
        if strona:
            return strona

    zapisy = warianty_do_szukania(str(wartosc), potwierdzone)
    trafienia = szukaj_w_ocr_z_wariantami(ocr_text, zapisy)

    # Najpierw wartość przyjęta i jej inne zapisy: klik w pole ma pokazać to,
    # co w polu stoi. Na wartość niezgodną skaczemy dopiero, gdy nic innego
    # nie znaleziono — inaczej analityk trafiłby na "Nowaka" bez ostrzeżenia.
    for trafienie in trafienia:
        if trafienie["strona"] and trafienie["rodzaj"] != "zla":
            return trafienie["strona"]

    for trafienie in trafienia:
        if trafienie["strona"]:
            return trafienie["strona"]

    return None


POLA_DAT = {
    "data_umowy",
    "termin_przeniesienia_wlasnosci",
    "termin_odrebnej_wlasnosci",
}


# Numer umowy ("Repertorium A Nr 1123/2026") celowo poza listą — ma słowa,
# a nie sam numer, więc porównanie znak po znaku nie ma tu sensu.
POLA_IDENTYFIKATOROW = {
    "nip_dewelopera",
    "pesel_1",
    "pesel_2",
    "numer_dzialki",
    "numer_kw",
    "numer_rachunku_powierniczego",
    "otwarty_numer_rachunku_powierniczego",
}


POLA_KWOT = {
    "cena_nieruchomosci",
    "laczna_wartosc_transakcji",
    "laczna_suma_harmonogramu",
}


def strona_dla_kwoty(ocr_text, kwota, ktora=0):
    """Strona `ktora`-tego (od zera) trafienia kwoty w tekście OCR albo None.

    Gdy trafień jest mniej niż `ktora`+1, bierzemy ostatnie.
    """
    grosze = kwota_na_grosze(kwota)
    if grosze is None or not ocr_text:
        return None

    znorm = normalizuj_do_szukania(ocr_text)

    strony = []
    for dop in re.finditer(wzorzec_kwoty(grosze), znorm):
        strona = strona_dla_pozycji(ocr_text, dop.start())
        if strona:
            strony.append(strona)

    if not strony:
        return None

    return strony[min(ktora, len(strony) - 1)]


def strona_dla_tokenu(ocr_text, token):
    """Strona pierwszego trafienia krótkiego oznaczenia (A3, G26, numer KW).

    Szukamy jako osobnego tokenu, bo zwykłe szukanie podciągu znalazłoby
    "A3" w "A30" i w "KA3" — a tak krótkie oznaczenia to główna zawartość
    elementów tablic.
    """
    if not token or not str(token).strip() or not ocr_text:
        return None

    wzor = r"(?<!\w)" + re.escape(normalizuj_do_szukania(token).strip()) + r"(?!\w)"

    for dop in re.finditer(wzor, normalizuj_do_szukania(ocr_text)):
        strona = strona_dla_pozycji(ocr_text, dop.start())
        if strona:
            return strona

    return None


# =====================================================================
# INDEKS DOKUMENTU — strony i trafienia do szukajki
# =====================================================================
# Indeks dokumentu do szukajki: tekst każdej strony z OCR.
#
# Obsługujemy wyłącznie wskazanie strony: tekst OCR jest podzielony po
# markerach [STRONA_X], więc wiadomo, na której stronie stoi trafienie, ale
# nie gdzie na niej. Analityk dostaje stronę i fragment tekstu nad podglądem.
#
# Kształt strony: {"numer": int, "tekst": str}

WZORZEC_MARKERA_STRONY = re.compile(r"\[STRONA_(\d+)\]")


def strony_z_ocr(ocr_text):
    """{numer strony: strona} z tekstu OCR z markerami [STRONA_X]."""
    czesci = WZORZEC_MARKERA_STRONY.split(ocr_text or "")

    return {
        int(numer): {"numer": int(numer), "tekst": tekst}
        for numer, tekst in zip(czesci[1::2], czesci[2::2])
    }


def zloz_strony(strony_ocr, liczba_stron):
    """Strony dokumentu po kolei; strona bez tekstu OCR ma pusty tekst."""
    return [
        strony_ocr.get(numer, {"numer": numer, "tekst": ""})
        for numer in range(1, liczba_stron + 1)
    ]


def znajdz_w_stronach(strony, zapisy):
    """Trafienia zapisów (format warianty_do_szukania) na stronach, po kolei.

    Reguły szukania (dosłownie, odmiana jako zapas, każdy zapis daty i kwoty)
    są te same co w sekcji SZUKANIE — tu dochodzi tylko numer strony.
    """
    trafienia = []

    for strona in strony:
        if not strona["tekst"].strip():
            continue

        for trafienie in szukaj_w_ocr_z_wariantami(strona["tekst"], zapisy):
            trafienia.append({**trafienie, "strona": strona["numer"]})

    return trafienia


def pierwsze_do_pokazania(trafienia, strona=None):
    """Indeks trafienia, od którego zaczyna szukajka.

    Klik w pole ma pokazać to, co w polu stoi — wartość niezgodną pokazujemy
    na starcie tylko wtedy, gdy nic innego nie znaleziono. Gdy model wskazał
    stronę źródła, zaczynamy od trafienia na tej stronie: ta sama kwota czy
    miasto stoją w dokumencie w kilku rolach, a model wie, o którą chodzi.
    """
    if strona:
        na_stronie = [
            (indeks, t) for indeks, t in enumerate(trafienia) if t.get("strona") == strona
        ]
        for indeks, trafienie in na_stronie:
            if trafienie.get("rodzaj") != "zla":
                return indeks
        if na_stronie:
            return na_stronie[0][0]

    for indeks, trafienie in enumerate(trafienia):
        if trafienie.get("rodzaj") != "zla":
            return indeks
    return 0


# =====================================================================
# ROZBIEŻNOŚCI — weryfikacja wartości zgłoszonych przez model
# =====================================================================
# Weryfikacja rozbieżności zgłoszonych przez model z tekstem OCR.

def wariant_stoi_w_tekscie(znorm_ocr, znorm_wariant):
    """Czy wariant występuje w tekście jako osobny token.

    Sprawdzamy, czy tuż przed i tuż po trafieniu nie stoi litera ani cyfra —
    bez tego wariant "123" zostałby potwierdzony przez "1234" albo "A123",
    a to inny numer.
    """
    if not znorm_wariant:
        return False

    wzor = r"(?<!\w)" + re.escape(znorm_wariant) + r"(?!\w)"
    return re.search(wzor, znorm_ocr) is not None


def splaszcz_wynik(wynik):
    """Wynik modelu w kształcie, którego używa reszta aplikacji.

    Kluczowe pola schematu (daty, identyfikatory, strony umowy) model zwraca
    jako obiekt:
        {"wartosc_glowna": ..., "wartosci_ok": [...], "wartosci_zle": [...],
         "uzasadnienie": ...}
    Tu każde takie pole zamienia się w samą wartość główną, a inne zapisy
    trafiają do listy `rozbieznosci` w formacie
        {"pole", "wartosc_glowna", "wartosci_ok", "wartosci_zle", "uzasadnienie"}
    — tylko dla pól, w których któraś lista jest niepusta.

    Dzięki temu widoki, walidacje, kopiowanie do UniFlow i szukajka czytają
    zwykłe pola, a obiekt z poziomami zna tylko ta funkcja. Wynik w starym
    kształcie (płaskie pola + lista `rozbieznosci` od modelu, np. z cache)
    przechodzi bez zmian.
    """
    if not isinstance(wynik, dict):
        return wynik

    plaski = {}
    rozbieznosci = list(wynik.get("rozbieznosci") or [])

    for klucz, wartosc in wynik.items():
        if klucz == "rozbieznosci":
            continue
        if not (isinstance(wartosc, dict) and "wartosc_glowna" in wartosc):
            plaski[klucz] = wartosc
            continue

        glowna = str(wartosc.get("wartosc_glowna") or "").strip()
        plaski[klucz] = glowna or None

        ok = wartosc.get("wartosci_ok") or []
        zle = wartosc.get("wartosci_zle") or []
        if ok or zle:
            rozbieznosci.append({
                "pole": klucz,
                "wartosc_glowna": glowna,
                "wartosci_ok": ok,
                "wartosci_zle": zle,
                "uzasadnienie": wartosc.get("uzasadnienie") or "",
            })

    plaski["rozbieznosci"] = rozbieznosci
    return plaski


def rodzaj_zapisu(pole, glowna, wartosc):
    """"ok" / "zla" rozstrzygnięte przez Pythona albo None, gdy się nie da.

    Daty: ta sama data w innym zapisie to "ok", inna data — "zla".
    Identyfikatory: te same znaki po zdjęciu separatorów to "ok"; inne cyfry
    to "zla" ("0O123456" ma o jedno zero mniej niż "00123456"). Gdy różnią się
    tylko litery ("dz. 12/5" przy "12/5"), decyzję zostawiamy modelowi.
    Osoby i firmy — zawsze model: tam potrzebny jest kontekst roli.
    """
    if pole in POLA_DAT:
        data_glowna, data_zapisu = parsuj_date(glowna), parsuj_date(wartosc)
        if data_glowna and data_zapisu:
            return "ok" if data_glowna == data_zapisu else "zla"

    if pole in POLA_IDENTYFIKATOROW:
        klucz_glowny = klucz_zapisu_identyfikatora(glowna)
        klucz_zapisu = klucz_zapisu_identyfikatora(wartosc)
        if klucz_glowny and klucz_zapisu:
            if klucz_glowny == klucz_zapisu:
                return "ok"
            cyfry = lambda tekst: "".join(filter(str.isdigit, tekst))
            if cyfry(klucz_glowny) != cyfry(klucz_zapisu):
                return "zla"

    return None


def rozstrzygnij_podzial(potwierdzone):
    """Poprawia podział modelu na "ok" i "złe" tam, gdzie Python wie lepiej.

    Model wskazuje kandydatów, a dla dat i identyfikatorów werdykt liczy
    rodzaj_zapisu — model potrafi wpisać "15 marca 2026" jako inny zapis
    daty 2026-03-14. Pozostałe wartości zostają tam, gdzie umieścił je model.
    Element, w którym zostały same wartości "ok", nadal jest zwracany: służy
    szukajce i dymkowi przy polu, a panel ustaleń i tak pokazuje tylko "złe".
    """
    wynik = []

    for wpis in potwierdzone:
        ok, zle = [], []
        for wartosc, zdanie_modelu in (
            [(w, "ok") for w in wpis["wartosci_ok"]] + [(w, "zla") for w in wpis["wartosci_zle"]]
        ):
            rodzaj = rodzaj_zapisu(wpis["pole"], wpis["wartosc_glowna"], wartosc) or zdanie_modelu
            (ok if rodzaj == "ok" else zle).append(wartosc)

        wynik.append({**wpis, "wartosci_ok": ok, "wartosci_zle": zle})

    return wynik


# --- źródła wartości: strona i cytat wskazane przez model ---
#
# Model przy każdym polu podaje stronę i krótki cytat z dokumentu (lista
# `zrodla`). Wyszukanie wartości zostawiamy modelowi — rozumie rolę wartości
# ("cena lokalu", a nie pierwsza lepsza kwota), datę zapisaną słownie
# i pola złożone. Python tylko sprawdza, czy cytat naprawdę stoi w tekście
# OCR i na której stronie: model myli się przy numerach stron, więc gdy
# cytat stoi na innej stronie, wygrywa tekst, a gdy go nie ma — pole
# dostaje ✕ zamiast zmyślonego potwierdzenia.

WZORZEC_ZNACZNIKA_HTML = re.compile(r"&lt;.*?&gt;|<[^<>]*>", re.DOTALL)


def tekst_do_cytatu(tekst):
    """Tekst w postaci, w której porównujemy cytaty.

    Bez znaczników HTML z OCR (komórki tabel, komentarze), bez znaków
    markdown i cudzysłowów, ze sklejonymi przeniesieniami wyrazów
    ("Puław-\\nskiej"), z jednym rodzajem myślnika i jednym odstępem
    zamiast każdego ciągu białych znaków. Model przepisuje cytat bez
    znaczników i łamań linii, więc tak samo musi wyglądać tekst strony.
    """
    tekst = WZORZEC_ZNACZNIKA_HTML.sub(" ", str(tekst or ""))
    tekst = re.sub(r"(\w)-[ \t]*\n\s*(\w)", r"\1\2", tekst)
    tekst = normalizuj_do_szukania(tekst)
    tekst = re.sub(r"[‐‑‒–—―−]", "-", tekst)
    tekst = re.sub(r"[|*#„”\"«»]", " ", tekst)
    return re.sub(r"\s+", " ", tekst).strip()


def zweryfikuj_zrodla(ocr_text, zrodla):
    """{pole: źródło} — strona i cytat od modelu, sprawdzone w tekście OCR.

    Źródło: {"cytat", "strona", "strona_modelu", "status"}, gdzie status to
      "potwierdzone"    — cytat stoi na stronie wskazanej przez model,
      "inna_strona"     — cytat stoi w tekście, ale na innej stronie
                          (strona = pierwsza, na której stoi),
      "niepotwierdzone" — cytatu nie ma w tekście (strona = ta od modelu).

    Cytat musi stać w tekście jako całe słowa: "nr 4" nie potwierdza się
    w "nr 42". Gdy model podał to samo pole dwa razy, liczy się pierwszy wpis.
    """
    strony = {
        numer: tekst_do_cytatu(strona["tekst"])
        for numer, strona in strony_z_ocr(ocr_text).items()
    }
    wynik = {}

    for wpis in zrodla or []:
        if not isinstance(wpis, dict):
            continue

        pole = re.sub(r"\s+", "", str(wpis.get("pole") or ""))
        cytat = str(wpis.get("cytat") or "").strip()
        szukany = tekst_do_cytatu(cytat)
        if not pole or not szukany or pole in wynik:
            continue

        try:
            strona_modelu = int(wpis.get("strona"))
        except (TypeError, ValueError):
            strona_modelu = None

        wzor = re.compile(r"(?<!\w)" + re.escape(szukany) + r"(?!\w)")
        na_stronach = [numer for numer, tekst in strony.items() if wzor.search(tekst)]

        if strona_modelu in na_stronach:
            status, strona = "potwierdzone", strona_modelu
        elif na_stronach:
            status, strona = "inna_strona", na_stronach[0]
        else:
            status, strona = "niepotwierdzone", strona_modelu

        wynik[pole] = {
            "cytat": cytat,
            "strona": strona,
            "strona_modelu": strona_modelu,
            "status": status,
        }

    return wynik


# Pola z tablic mają w widoku klucz z numerem elementu ("prawo_cena_1"),
# a w liście `zrodla` ścieżkę ze schematu ("prawa_przynalezne[1].cena").
POLA_TABLIC_W_WIDOKU = {
    "prawo": ("prawa_przynalezne", {
        "rodzaj": "rodzaj", "tytul": "tytul_prawny",
        "oznaczenie": "oznaczenie", "cena": "cena",
    }),
    "dod": ("dodatkowe_nieruchomosci", {
        "rodzaj": "rodzaj_nieruchomosci", "adres": "ulica", "tytul": "tytul_prawny",
        "lokal": "numer_lokalu", "oznaczenie": "oznaczenie", "kw": "numer_kw",
        "cena": "cena_nieruchomosci",
    }),
}


def klucz_zrodla(klucz_pola):
    """Klucz pola z widoku w postaci, w jakiej model podaje go w `zrodla`.

    "adres" to ulica, numer budynku i miasto sklejone w widoku — źródłem
    jest miejsce, w którym stoi ulica (tam stoi też reszta adresu).
    Transze mają w widoku klucz z pozycji na liście (od 1) — tak samo
    numeruje elementy tablicy model w `zrodla`.
    """
    if klucz_pola == "adres":
        return "ulica"

    dop = re.fullmatch(r"transza_(\d+)_(kwota|termin)", klucz_pola)
    if dop:
        pole = "kwota" if dop.group(2) == "kwota" else "termin_platnosci"
        return f"harmonogram_transz[{dop.group(1)}].{pole}"

    dop = re.fullmatch(r"(prawo|dod)_([a-z]+)_(\d+)", klucz_pola)
    if dop:
        tablica, pola = POLA_TABLIC_W_WIDOKU[dop.group(1)]
        if dop.group(2) in pola:
            return f"{tablica}[{dop.group(3)}].{pola[dop.group(2)]}"

    return klucz_pola


def wartosc_doslowna(klucz_pola):
    """Czy wartość pola da się znaleźć w dokumencie jako tekst.

    Nie da się dla klasyfikacji (rodzaj, tytuł prawny — model wybiera
    określenie z listy), dla adresu sklejonego w widoku i dla liczby transz.
    Dla takich pól szukajka szuka cytatu, a nie wartości.
    """
    if klucz_pola in {"adres", "rodzaj_nieruchomosci", "liczba_transz"}:
        return False
    return not re.fullmatch(r"(prawo|dod)_(rodzaj|tytul|adres)_\d+", klucz_pola)


def cytat_zawiera_wartosc(cytat, wartosc):
    """Czy wartość stoi w cytacie — w dowolnym zapisie (data, kwota, identyfikator)."""
    return bool(szukaj_w_ocr_z_wariantami(cytat, warianty_do_szukania(str(wartosc), None)))


def zweryfikuj_warianty(ocr_text, rozbieznosci):
    """Odsiewa wartości, których nie ma w tekście OCR.

    Zwraca dwie listy:
      potwierdzone — elementy w formacie z modelu, ale wyłącznie z wartościami
                     potwierdzonymi w tekście; element bez żadnej potwierdzonej
                     wartości znika w całości
      odrzucone    — [{"pole": ..., "wartosc": ...}] — wartości zmyślone
                     przez model; ich liczba to tania miara jakości promptu

    Zachowujemy podział modelu na `wartosci_ok` i `wartosci_zle` — nie
    poprawiamy go. Sprawdzamy wyłącznie obecność: wartość musi stać w tekście
    dosłownie, jako osobny token (wielkość liter i układ spacji nie mają
    znaczenia). Prompt każe modelowi przepisywać wartości dokładnie z tekstu,
    więc wartość, której tam nie ma, jest błędem modelu, a nie innym zapisem.

    Wartość identyczna z wartością główną (po normalizacji) i powtórzenia są
    pomijane po cichu — to nie halucynacja, tylko szum, więc nie zawyżają
    licznika odrzuconych. Wartość obecna zarazem w "ok" i w "złe" liczy się
    jako "złe": lepiej pokazać analitykowi za dużo niż przemilczeć.

    Bez tekstu OCR nic nie da się potwierdzić, więc zwracamy puste listy
    (a nie "wszystko odrzucone" — brak tekstu to nie wina modelu).
    """
    potwierdzone = []
    odrzucone = []

    if not ocr_text or not isinstance(rozbieznosci, list):
        return potwierdzone, odrzucone

    znorm_ocr = normalizuj_do_porownania(ocr_text)

    def lista_wartosci(surowa):
        # model bywa niedbały — zamiast listy może dać napis albo nic
        if not surowa:
            return []
        if isinstance(surowa, str):
            return [surowa]
        return list(surowa)

    for wpis in rozbieznosci:
        if not isinstance(wpis, dict):
            continue

        pole = wpis.get("pole")
        glowna = str(wpis.get("wartosc_glowna") or "").strip()

        widziane = {normalizuj_do_porownania(glowna)}
        potwierdzone_ok = []
        potwierdzone_zle = []

        # "złe" przetwarzamy pierwsze, żeby wartość obecna w obu listach
        # została w "złe" (patrz docstring)
        for wartosc in lista_wartosci(wpis.get("wartosci_zle")):
            wartosc = str(wartosc).strip()
            znorm = normalizuj_do_porownania(wartosc)

            if not znorm or znorm in widziane:
                continue
            widziane.add(znorm)

            if wariant_stoi_w_tekscie(znorm_ocr, znorm):
                potwierdzone_zle.append(wartosc)
            else:
                odrzucone.append({"pole": pole, "wartosc": wartosc})

        for wartosc in lista_wartosci(wpis.get("wartosci_ok")):
            wartosc = str(wartosc).strip()
            znorm = normalizuj_do_porownania(wartosc)

            if not znorm or znorm in widziane:
                continue
            widziane.add(znorm)

            if wariant_stoi_w_tekscie(znorm_ocr, znorm):
                potwierdzone_ok.append(wartosc)
            else:
                odrzucone.append({"pole": pole, "wartosc": wartosc})

        if potwierdzone_ok or potwierdzone_zle:
            potwierdzone.append({
                "pole": pole,
                "wartosc_glowna": glowna,
                "wartosci_ok": potwierdzone_ok,
                "wartosci_zle": potwierdzone_zle,
                "uzasadnienie": str(wpis.get("uzasadnienie") or "").strip(),
            })

    return potwierdzone, odrzucone


# =====================================================================
# USTALENIA — panel „Do wyjaśnienia”
# =====================================================================
# Ustalenia do panelu analityka: walidacje, rozbieżności i weryfikacja UniFlow.

# Waga ustalenia dla wartości "złych", zależna od tego, czego dotyczy pole.
# Inna data albo inna osoba to sprzeczność w treści dokumentu — waga wysoka.
# Identyfikator odczytany inaczej to najczęściej wada OCR — waga średnia.
POZIOM_ROZBIEZNOSCI = {
    "data_umowy": "wysoki",
    "termin_przeniesienia_wlasnosci": "wysoki",
    "termin_odrebnej_wlasnosci": "wysoki",
    "nabywca_1": "wysoki",
    "nabywca_2": "wysoki",
    "nazwa_dewelopera": "wysoki",
    "numer_umowy": "sredni",
    "nip_dewelopera": "sredni",
    "pesel_1": "sredni",
    "pesel_2": "sredni",
    "numer_dzialki": "sredni",
    "numer_kw": "sredni",
    "numer_rachunku_powierniczego": "sredni",
    "otwarty_numer_rachunku_powierniczego": "sredni",
}


ETYKIETY_POL_ROZBIEZNOSCI = {
    "numer_umowy": "Numer umowy",
    "nip_dewelopera": "NIP dewelopera",
    "pesel_1": "PESEL nabywcy 1",
    "pesel_2": "PESEL nabywcy 2",
    "numer_dzialki": "Numer działki",
    "numer_kw": "Numer księgi wieczystej",
    "numer_rachunku_powierniczego": "Numer rachunku powierniczego",
    "otwarty_numer_rachunku_powierniczego": "Otwarty numer rachunku powierniczego",
    "data_umowy": "Data umowy",
    "termin_przeniesienia_wlasnosci": "Termin przeniesienia własności",
    "termin_odrebnej_wlasnosci": "Termin ustanowienia odrębnej własności",
    "nabywca_1": "Nabywca 1",
    "nabywca_2": "Nabywca 2",
    "nazwa_dewelopera": "Deweloper",
}


def stan_sekcji(stany):
    """Zlicza pola sekcji po rodzaju stanu (patrz stan_do_naglowka).

    Zwraca (ok, z_problemem, niepewne, brak). "odmiana" liczy się jako ok —
    przy polu jest wyciszona, więc w nagłówku też nie alarmuje.
    """
    ok = z_problemem = niepewne = brak = 0

    for stan in stany:
        if stan == "rozbieznosc":
            z_problemem += 1
        elif stan == "niepewne":
            niepewne += 1
        elif stan == "brak":
            brak += 1
        else:
            ok += 1

    return ok, z_problemem, niepewne, brak


# Mapowanie tytułów weryfikacji UniFlow na pola, których dotyczą — zapas
# dla wyników bez klucza "pole" (cache sprzed jego dodania). Model zwraca
# luźne tytuły, więc dopasowujemy po początkach słów — dzięki temu
# ostrzeżenie trafia też do dymka przy konkretnym polu.
#
# Kolejność ma znaczenie: wygrywa pierwsze dopasowanie. Imię i nazwisko
# są przed PESEL-em, bo opis niezgodności nazwiska zwykle dodaje
# "PESEL zgodny". Samo "nabywcy" jest na końcu, bo pada w opisie niemal
# każdej niezgodności ("PESEL drugiego nabywcy…"). "kw" tylko jako całe
# słowo — inaczej łapało "kwotę".
SLOWA_KLUCZOWE_POL = [
    ("nabywca_1", [r"\bimie", r"\bimion", r"\bnazwisk"]),
    ("pesel_1", [r"\bpesel"]),
    ("numer_kw", [r"\bksieg", r"\bksiag", r"\bwieczyst", r"\bkw\b"]),
    ("nazwa_dewelopera", [r"\bdewelop"]),
    ("cena_nieruchomosci", [r"\bcen", r"\bkwot", r"\bwartos"]),
    ("miasto", [r"\bmiejscowos", r"\bmiast"]),
    ("ulica", [r"\bulic", r"\badres"]),
    ("nabywca_1", [r"\bnabywc", r"\bwnioskodawc"]),
]

# Pola, które model może wskazać wprost w weryfikacji UniFlow (klucz "pole").
POLA_WERYFIKACJI = {"nabywca_1", "nabywca_2", "pesel_1", "pesel_2"}

# Co zrobić z wpisem weryfikacji UniFlow, zależnie od statusu.
KROKI_WERYFIKACJI = {
    "niezgodne": "Ustal przyczynę rozbieżności i udokumentuj.",
    "do_wyjasnienia": "Potwierdź, że to ta sama osoba (np. akt małżeństwa przy zmianie nazwiska), i ujednolić zapis.",
    "brak_danych": "Uzupełnij brakujące dane przed zakończeniem analizy.",
}

# Pola osobowe, które dla drugiej osoby mają odpowiednik z sufiksem _2.
POLA_OSOBOWE = {"nabywca_1": "nabywca_2", "pesel_1": "pesel_2"}

# "drugiego nabywcy", "Nabywca 2", "PESEL nr 2" — ale nie "2 nabywców".
WZORZEC_DRUGIEJ_OSOBY = r"\bdrugi|\b(?:nabywc|wnioskodawc|pesel)\w*\s+(?:nr\s+)?2\b"


def dopasuj_pole(tytul, opis):
    """Zgaduje, którego pola dotyczy wpis weryfikacji."""
    tekst = normalizuj_do_szukania(f"{tytul} {opis}")

    for pole, wzorce in SLOWA_KLUCZOWE_POL:
        if any(re.search(wzorzec, tekst) for wzorzec in wzorce):
            if pole in POLA_OSOBOWE and re.search(WZORZEC_DRUGIEJ_OSOBY, tekst):
                return POLA_OSOBOWE[pole]
            return pole

    return None


def zbierz_problemy(wynik, lista_weryfikacji, potwierdzone=None):
    """Buduje listę ustaleń wymagających decyzji analityka.

    Łączy dwa źródła o różnej wiarygodności:
      - weryfikację UniFlow zwróconą przez model (miękka, opisowa)
      - twarde walidacje liczone w Pythonie (suma kontrolna, arytmetyka)

    Te drugie są pewniejsze, więc idą na górę listy.

    `potwierdzone` (wynik potwierdzone_rozbieznosci) dodaje ustalenia o polach,
    które w dokumencie występują w niezgodnych wartościach (inna data, inna
    osoba, identyfikator odczytany inaczej) — tylko dla wartości, które
    naprawdę stoją w tekście OCR. Waga zależy od kategorii.

    Zgodności NIE trafiają do wyniku — panel, który potwierdza oczywistości,
    przestaje być czytany po kilku analizach.
    """
    ustalenia = []

    # --- twarde walidacje ---
    for numer in ("1", "2"):
        pesel = wynik.get(f"pesel_{numer}")
        if pesel and waliduj_pesel(pesel) == "❌":
            ustalenia.append({
                "pole": f"pesel_{numer}",
                "poziom": "wysoki",
                "tytul": f"PESEL nabywcy {numer} — błędna suma kontrolna",
                "opis": f"Odczytana wartość: {pesel}. Numer jest wewnętrznie niespójny.",
                "krok": "Sprawdź numer w dokumencie — prawdopodobny błąd odczytu OCR.",
            })

    rachunek = wynik.get("numer_rachunku_powierniczego")
    if rachunek:
        status = waliduj_nrb(rachunek)
        if status not in ("Poprawny strukturalnie", "Brak numeru"):
            ustalenia.append({
                "pole": "numer_rachunku_powierniczego",
                "poziom": "wysoki",
                "tytul": "Rachunek powierniczy — błędny numer",
                "opis": f"{status}. Odczytana wartość: {rachunek}",
                "krok": "Zweryfikuj numer przed uruchomieniem transz.",
            })

    if czy_wartosc_transakcji_zgodna(wynik) == "❌":
        cena = wartosc_transakcji(wynik)
        suma = suma_transz(wynik, cena)
        roznica = abs(cena - suma) / 100
        ustalenia.append({
            "pole": "laczna_wartosc_transakcji",
            "poziom": "sredni",
            "tytul": "Suma transz nie zgadza się z wartością transakcji",
            "opis": (
                f"Wartość transakcji: {cena / 100:,.2f} zł. "
                f"Suma transz: {suma / 100:,.2f} zł. "
                f"Różnica: {roznica:,.2f} zł."
            ).replace(",", " "),
            "krok": "Sprawdź harmonogram — możliwy błąd odczytu kwoty transzy.",
        })

    # --- rozbieżności w dokumencie, potwierdzone w tekście OCR ---
    # Ustalenie tworzą tylko wartości "złe". Wartości "ok" (ta sama data
    # w innym zapisie, odmiana nazwiska) to zwykła umowa i panel ma o nich
    # milczeć — służą wyłącznie do szukania stron.
    #
    # Tytuł i opis zostają surowym tekstem — escapują je miejsca, które
    # wstawiają je do HTML (panel_ustalen, dymek w _znacznik_pola).
    for wpis in (potwierdzone or []):
        if not wpis["wartosci_zle"]:
            continue

        pole = wpis["pole"]
        etykieta = ETYKIETY_POL_ROZBIEZNOSCI.get(pole, pole)

        opis = (
            f"Przyjęta wartość: {wpis['wartosc_glowna']}. "
            f"W dokumencie występuje też: {', '.join(wpis['wartosci_zle'])}."
        )
        if wpis["uzasadnienie"]:
            opis += f" {wpis['uzasadnienie']}"

        ustalenia.append({
            "pole": pole,
            "poziom": POZIOM_ROZBIEZNOSCI.get(pole, "sredni"),
            "tytul": f"Pole „{etykieta}” — niezgodne wartości w dokumencie",
            "opis": opis,
            "krok": "Sprawdź na skanie, która wartość jest prawidłowa (możliwa pomyłka OCR albo niespójność dokumentu).",
        })

    # --- weryfikacja UniFlow z modelu: tylko to, co NIE jest zgodne ---
    for wpis in (lista_weryfikacji or []):
        status = str(wpis.get("status", "")).lower().strip()

        if status == "zgodne":
            continue

        tytul = str(wpis.get("tytul") or "")
        opis = str(wpis.get("opis") or "")

        # Pole wskazane przez model wygrywa; zgadywanie po słowach tylko
        # dla wyników bez tego klucza. Pusty tekst to świadome "żadne pole"
        # (np. inna liczba osób) — wtedy nie zgadujemy.
        pole = wpis.get("pole")
        if pole not in POLA_WERYFIKACJI:
            pole = None if pole == "" else dopasuj_pole(tytul, opis)

        ustalenia.append({
            "pole": pole,
            "poziom": "wysoki" if status == "niezgodne" else "sredni",
            "tytul": tytul,
            "opis": opis,
            "krok": KROKI_WERYFIKACJI.get(status, KROKI_WERYFIKACJI["niezgodne"]),
        })

    kolejnosc = {"wysoki": 0, "sredni": 1}
    ustalenia.sort(key=lambda u: kolejnosc.get(u["poziom"], 2))
    return ustalenia


def problemy_wg_pola(ustalenia):
    """Mapa pole -> ustalenie, do dymków przy polach."""
    mapa = {}
    for ustalenie in ustalenia:
        if ustalenie.get("pole"):
            mapa.setdefault(ustalenie["pole"], ustalenie)
    return mapa


# =====================================================================
# SCHEMATY, PROMPT I KLUCZ CACHE
# =====================================================================
# Schematy ekstrakcji, prompt i klucze cache.

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

        ZASADY DLA WSZYSTKICH PÓL:
        - Wartości bierz wyłącznie z treści dokumentu. Nie uzupełniaj ich
          wiedzą ogólną ani danymi z UniFlow; gdy informacji nie ma,
          zwróć pustą wartość.
        - Liczby, kwoty, numery i oznaczenia przepisuj dokładnie tak, jak
          stoją w dokumencie — z tymi samymi spacjami, kropkami i ukośnikami.
          Wyjątek: daty tam, gdzie opis pola każe format RRRR-MM-DD.
        - Tekst zawiera znaczniki OCR (komentarze HTML, nagłówki i stopki
          stron, tabele). Nagłówki i stopki powtarzają się na każdej stronie
          — nie traktuj ich powtórzeń jako rozbieżności.

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


# =====================================================================
# API — endpointy OCR i Extract
# =====================================================================
# Endpointy OCR i Extract (sde_service): zlecenie zadania, odpytywanie, wynik.

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


def wywolaj_ocr_api(plik_bajty, token, document_group_id):
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


def wywolaj_extract_api(tekst, token, document_id, schema):
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


def wczytaj_token_z_pliku(plik):
    """access_token z pliku JSON albo None."""
    try:
        with open(plik, "r", encoding="utf-8") as f:
            return json.load(f).get("access_token")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# =====================================================================
# PDF — liczba stron i obraz strony
# =====================================================================

def pdf_liczba_stron(plik_bajty):
    dokument = pdfium.PdfDocument(plik_bajty)
    try:
        return len(dokument)
    finally:
        dokument.close()


def pdf_renderuj_strone(plik_bajty, numer_strony, skala):
    """Obraz strony (PIL, RGBA); numer_strony od 1."""
    dokument = pdfium.PdfDocument(plik_bajty)
    try:
        return dokument[numer_strony - 1].render(scale=skala).to_pil().convert("RGBA")
    finally:
        dokument.close()


# =====================================================================
# TRYB OFFLINE — atrapy hurtowni i API (HIPOTEKA_OFFLINE=1)
# =====================================================================
# Atrapy hurtowni i API do pracy lokalnej (HIPOTEKA_OFFLINE=1).
#
# Zastępują WYŁĄCZNIE wejście/wyjście. Cała logika (szukajka, rozbieżności,
# ustalenia, widoki) działa na tych danych dokładnie tak jak na produkcyjnych,
# więc nie powtarza się problem dawnego trybu demo, który dublował analizę
# i rozjeżdżał się ze schematem.
#
# Dane w katalogu dev/ (generuje je dev/generuj_umowe_demo.py):
#   wnioskodawcy.json               wiersze tabeli wnioskodawców (jak z hurtowni)
#   wynik_umowa_deweloperska.json   odpowiedź endpointu Extract
#   umowa_demo_skan.pdf             skan umowy — typowy przypadek, bez warstwy tekstowej
#   ocr_umowa_demo_skan.txt         odpowiedź endpointu OCR dla skanu
#   umowa_demo.pdf                  ta sama umowa z warstwą tekstową
#
# OCR: dla PDF-a z warstwą tekstową zwraca ten tekst; dla skanu zwraca
# ocr_umowa_demo_skan.txt (w formacie endpointu), niezależnie od wgranego
# skanu. Extract zwraca zawsze ten sam JSON, niezależnie od pliku.

# Ten sam zapis znacznika, który zwraca endpoint OCR — dodaj_markery_stron dzieli po nim strony.
ZNACZNIK_STRONY = "&lt;!-- PageBreak --&gt;"

_OFFLINE_CACHE = {}


def _offline_json(nazwa):
    with open(KATALOG_DEV / nazwa, "r", encoding="utf-8") as f:
        return json.load(f)


def offline_load_wnioskodawcy(nr_wniosku):
    wiersze = [w for w in _offline_json("wnioskodawcy.json") if w["NR_WNIOSKU"] == str(nr_wniosku).strip()]
    return pd.DataFrame(wiersze, columns=["NR_WNIOSKU", "IMIE", "NAZWISKO", "PESEL", "STAN_CYWILNY"])


def offline_load_kwoty_kredytu(nr_wniosku):
    return None


def offline_get_document_cache(pdf_hash, nr_wniosku, hash_schematu):
    return _OFFLINE_CACHE.get((pdf_hash, nr_wniosku, hash_schematu))


def offline_save_document_cache(pdf_hash, nr_wniosku, hash_schematu, id_analizy,
                        document_type, ocr_text, extracted_data):
    _OFFLINE_CACHE[(pdf_hash, nr_wniosku, hash_schematu)] = {
        "wynik": extracted_data,
        "ocr_text": ocr_text,
    }


def offline_wczytaj_token():
    return "offline"


def offline_wywolaj_ocr(plik_bajty, token, document_group_id):
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

    if not any(strona.strip() for strona in strony):
        return (KATALOG_DEV / "ocr_umowa_demo_skan.txt").read_text(encoding="utf-8")

    return ZNACZNIK_STRONY.join(strony)


def offline_wywolaj_extract(tekst, token, document_id, schema):
    time.sleep(0.5)
    return _offline_json("wynik_umowa_deweloperska.json")


# =====================================================================
# ŹRÓDŁA DANYCH — prawdziwe albo offline
# =====================================================================
# Aplikacja sięga po hurtownię i API wyłącznie przez zrodla(), więc przełączenie
# trybu nie dotyka logiki — zmienia się tylko, skąd przychodzą dane.
# data_loader.py (hurtownia) importuje moduły, które istnieją tylko na serwerze,
# dlatego jest importowany dopiero tutaj, a nie na początku pliku.

@lru_cache(maxsize=None)
def zrodla():
    if OFFLINE:
        return SimpleNamespace(
            NAZWA="Offline (dev/)",
            load_wnioskodawcy=offline_load_wnioskodawcy,
            load_kwoty_kredytu=offline_load_kwoty_kredytu,
            get_document_cache=offline_get_document_cache,
            save_document_cache=offline_save_document_cache,
            wczytaj_token=offline_wczytaj_token,
            wywolaj_ocr=offline_wywolaj_ocr,
            wywolaj_extract=offline_wywolaj_extract,
        )

    import data_loader

    return SimpleNamespace(
        NAZWA="Prawdziwe API",
        load_wnioskodawcy=data_loader.load_wnioskodawcy,
        load_kwoty_kredytu=data_loader.load_kwoty_kredytu,
        get_document_cache=data_loader.get_document_cache,
        save_document_cache=data_loader.save_document_cache,
        wczytaj_token=lambda: wczytaj_token_z_pliku(PLIK_TOKENU),
        wywolaj_ocr=wywolaj_ocr_api,
        wywolaj_extract=wywolaj_extract_api,
    )


# =====================================================================
# ANALIZA — cache → OCR → ekstrakcja → zapis do cache
# =====================================================================
# Przebieg analizy dokumentu: cache -> OCR -> ekstrakcja -> zapis do cache.
#
# Bez Streamlita: postęp raportowany przez callback, źródła danych (hurtownia,
# API) wstrzykiwane parametrem — dzięki temu całość da się przetestować.

@dataclass
class Analiza:
    """Wynik analizy jednego dokumentu w kontekście jednego wniosku."""
    pdf_hash: str
    nr_wniosku: str
    nazwa_pliku: str
    typ_dokumentu: str
    ocr_text: str
    wynik: dict                 # po splaszcz_wynik — tego używają widoki
    zrodlo: str
    czas: str
    id_analizy: str
    ostrzezenia: list = field(default_factory=list)
    wynik_surowy: dict = None   # dokładnie to, co zwrócił model (zakładka JSON, cache)


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
    wywolaj_ocr i wywolaj_extract (wynik zrodla() albo atrapa w testach).

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
            wynik=splaszcz_wynik(wynik),
            wynik_surowy=wynik,
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


# =====================================================================
# STAN SESJI
# =====================================================================
# Stan sesji Streamlita — wszystkie dane analizy trzymane pod jednym kluczem.
#
# Analiza jest przypisana do pary (hash dokumentu, numer wniosku). Wcześniej
# wynik był zapisany pod samą nazwą pliku, a tekst OCR pod jednym kluczem
# na całą sesję, przez co:
#   - po zmianie numeru wniosku na ekranie zostawała weryfikacja UniFlow
#     policzona dla poprzedniego wniosku,
#   - inny plik o tej samej nazwie pokazywał stary wynik,
#   - po wgraniu drugiego pliku szukajka działała na tekście pierwszego.

_ANALIZY = "analizy"
_UNIFLOW = "uniflow"


def _klucz(pdf_hash, nr_wniosku):
    return f"{pdf_hash}:{nr_wniosku}"


# --- analizy ---

def zapisz_analize(analiza):
    st.session_state.setdefault(_ANALIZY, {})[
        _klucz(analiza.pdf_hash, analiza.nr_wniosku)
    ] = analiza


def biezaca_analiza(pdf_hash, nr_wniosku):
    """Analiza bieżącego dokumentu dla bieżącego wniosku albo None."""
    if not pdf_hash or not nr_wniosku:
        return None
    return st.session_state.get(_ANALIZY, {}).get(_klucz(pdf_hash, nr_wniosku))


def usun_analize(pdf_hash, nr_wniosku):
    st.session_state.get(_ANALIZY, {}).pop(_klucz(pdf_hash, nr_wniosku), None)


# --- dane wniosku z UniFlow ---

def ustaw_uniflow(dane):
    st.session_state[_UNIFLOW] = dane


def dane_uniflow(nr_wniosku):
    """Dane UniFlow, ale tylko jeśli dotyczą podanego wniosku.

    Sprawdzenie numeru chroni przed wysłaniem do modelu danych klientów
    z poprzednio wpisanego wniosku.
    """
    dane = st.session_state.get(_UNIFLOW)
    if dane and dane.get("numer_wniosku") == nr_wniosku:
        return dane
    return None


# --- wgrany dokument (osobno dla każdej zakładki) ---

def zapamietaj_plik(typ_dokumentu, nazwa, bajty):
    st.session_state[f"{typ_dokumentu}_plik"] = {
        "nazwa": nazwa,
        "bajty": bajty,
        "hash": policz_hash_pdf(bajty),
    }


def wgrany_plik(typ_dokumentu):
    return st.session_state.get(f"{typ_dokumentu}_plik")


# =====================================================================
# WIDOK: PANEL DOKUMENTU — szukajka i podgląd strony
# =====================================================================
# Panel dokumentu: szukajka, nawigacja po trafieniach i podgląd strony.
#
# Układ jak w app_lite: jedno pole szukania, jeden pasek nawigacji, pod nim
# strona dokumentu. Klik w wartość pola po prawej wkleja ją do szukajki
# i przełącza na pierwsze wystąpienie.
#
# Endpoint OCR (prebuilt-layout) zwraca sam tekst w markdownie, podzielony na
# strony — bez pozycji słów. Szukajka przełącza więc podgląd na właściwą
# stronę i pokazuje nad nim fragment tekstu z trafieniem; na obrazie strony
# niczego nie zaznaczamy.

KLUCZ_FRAZY = "fraza_ocr"
KLUCZ_TRAFIENIA = "szukajka_nr"
KLUCZ_STRONY = "wybrana_strona_pdf"
KLUCZ_OSTATNIEJ_FRAZY = "szukajka_ostatnia_fraza"
KLUCZ_DOKUMENTU = "szukajka_dokument"
KLUCZ_STRONY_ZRODLA = "szukajka_strona_zrodla"

SKALA_RENDERU = 2.0
WYSOKOSC_PODGLADU = 800

# Kolor zależy od rodzaju trafienia (patrz warianty_do_szukania): przy polu
# z rozbieżnością widać naraz wartość przyjętą, jej inne zapisy i wartości
# niezgodne. "kolor" dla legendy i zaznaczenia we fragmencie tekstu.
# Niebieski = trafienie, morski zielony = ta sama wartość w innym zapisie,
# czerwony = wartość niezgodna. Czerwień jest zarezerwowana dla błędów.
RODZAJE_TRAFIEN = {
    "szukana": {"etykieta": "szukana fraza", "kolor": "#2563EB"},
    "glowna": {"etykieta": "wartość przyjęta", "kolor": "#2563EB"},
    "ok": {"etykieta": "inny zapis tej samej wartości", "kolor": "#0D9488"},
    "zla": {"etykieta": "wartość niezgodna", "kolor": "#C0392B"},
}


def ustaw_fraze_szukania(wartosc, strona=None):
    """Callback kliknięcia w wartość pola — wkleja ją do szukajki.

    Musi to być callback: widget text_input ma własny klucz w session_state
    i po pierwszym renderze ignoruje parametr `value`. Callbacki wykonują się
    PRZED ponownym uruchomieniem skryptu, więc ustawiona tu wartość zdąży
    trafić do widgetu.

    `strona` — strona ze źródła wskazanego przez model. Szukajka zaczyna od
    trafienia na tej stronie, a gdy fraza nie ma trafień, pokazuje tę stronę.
    """
    st.session_state[KLUCZ_FRAZY] = str(wartosc)
    if strona:
        st.session_state[KLUCZ_STRONY_ZRODLA] = int(strona)
        st.session_state[KLUCZ_STRONY] = int(strona)


# --- dane dokumentu (cache per dokument) ---

@st.cache_data(show_spinner="Wczytywanie dokumentu...", max_entries=16)
def _liczba_stron(_plik_bajty, pdf_hash):
    """Liczba stron PDF-a. Klucz cache: pdf_hash."""
    return pdf_liczba_stron(_plik_bajty)


@st.cache_data(show_spinner=False, max_entries=64)
def _obraz_strony(_plik_bajty, pdf_hash, numer_strony, skala):
    return pdf_renderuj_strone(_plik_bajty, numer_strony, skala)


# --- nawigacja ---

def _przewin_trafienie(o_ile, ostatni):
    numer = st.session_state.get(KLUCZ_TRAFIENIA, 0) + o_ile
    st.session_state[KLUCZ_TRAFIENIA] = max(0, min(numer, ostatni))


def _zmien_strone(o_ile, liczba_stron):
    numer = st.session_state.get(KLUCZ_STRONY, 1) + o_ile
    st.session_state[KLUCZ_STRONY] = max(1, min(numer, liczba_stron))


def _pasek_nawigacji(trafienia, aktywne, strona, liczba_stron):
    """Jeden pasek: po trafieniach, gdy są, a w przeciwnym razie po stronach."""
    kol_wstecz, kol_opis, kol_dalej = st.columns([1.35, 2, 1.35])

    if trafienia:
        rodzaj = RODZAJE_TRAFIEN[trafienia[aktywne]["rodzaj"]]
        opis = (
            f'<span class="legenda-kropka" style="background:{rodzaj["kolor"]}"></span>'
            f'Trafienie <b>{aktywne + 1}</b> z <b>{len(trafienia)}</b> · strona <b>{strona}</b>'
        )
        wstecz = ("← Poprzednie", aktywne == 0, _przewin_trafienie, (-1, len(trafienia) - 1))
        dalej = ("Następne →", aktywne >= len(trafienia) - 1, _przewin_trafienie, (1, len(trafienia) - 1))
    else:
        opis = f"Strona <b>{strona}</b> z <b>{liczba_stron}</b>"
        wstecz = ("← Strona", strona <= 1, _zmien_strone, (-1, liczba_stron))
        dalej = ("Strona →", strona >= liczba_stron, _zmien_strone, (1, liczba_stron))

    for kolumna, (etykieta, wylaczony, akcja, argumenty), klucz in (
        (kol_wstecz, wstecz, "dokument_wstecz"),
        (kol_dalej, dalej, "dokument_dalej"),
    ):
        with kolumna:
            st.button(
                etykieta,
                key=klucz,
                disabled=wylaczony,
                use_container_width=True,
                on_click=akcja,
                args=argumenty,
            )

    with kol_opis:
        st.markdown(f'<div class="pasek-nawigacji">{opis}</div>', unsafe_allow_html=True)


def _legenda(trafienia):
    """Legenda kolorów — tylko gdy w wynikach jest więcej niż jeden rodzaj."""
    obecne = []
    for trafienie in trafienia:
        etykieta = RODZAJE_TRAFIEN[trafienie["rodzaj"]]["etykieta"]
        if (trafienie["rodzaj"], etykieta) not in obecne:
            obecne.append((trafienie["rodzaj"], etykieta))

    if len(obecne) < 2:
        return

    wpisy = "".join(
        f'<span class="legenda-wpis">'
        f'<span class="legenda-kropka" style="background:{RODZAJE_TRAFIEN[rodzaj]["kolor"]}"></span>'
        f'{etykieta}</span>'
        for rodzaj, etykieta in obecne
    )
    st.markdown(f'<div class="legenda-trafien">{wpisy}</div>', unsafe_allow_html=True)


def _przytnij(tekst, dlugosc, od_konca):
    """Najwyżej `dlugosc` znaków, cięte na granicy słowa."""
    if len(tekst) <= dlugosc:
        return tekst
    if od_konca:
        wycinek = tekst[-dlugosc:]
        return wycinek[wycinek.find(" ") + 1:] if " " in wycinek else wycinek
    wycinek = tekst[:dlugosc]
    return wycinek[:wycinek.rfind(" ")] if " " in wycinek else wycinek


def _fragment(trafienie):
    """Karta z trafieniem w tekście OCR — na skanie jedyny wskaźnik, gdzie stoi fraza.

    Tekst przechodzi przez tekst_do_wyswietlenia: bez znaczników markdown
    i tabel z odpowiedzi OCR, komórki tabeli rozdzielone " · ".
    """
    rodzaj = RODZAJE_TRAFIEN[trafienie["rodzaj"]]
    przed = _przytnij(tekst_do_wyswietlenia(trafienie["przed"]).lstrip(), 150, od_konca=True)
    po = _przytnij(tekst_do_wyswietlenia(trafienie["po"]).rstrip(), 150, od_konca=False)
    fraza = tekst_do_wyswietlenia(trafienie["trafienie"]).strip()

    meta = f'Strona {trafienie["strona"]} · tekst z OCR'
    if not trafienie.get("dokladne", True):
        meta += " · forma odmieniona"

    st.markdown(
        f'<div class="kontekst-trafienia" style="border-left-color:{rodzaj["kolor"]}">'
        f'<div class="fragment-meta">{html.escape(meta)}</div>'
        f'…{html.escape(przed)}'
        f'<mark style="background:{rodzaj["kolor"]}33;box-shadow:inset 0 -2px 0 {rodzaj["kolor"]}">'
        f'{html.escape(fraza)}</mark>'
        f'{html.escape(po)}…'
        f'</div>',
        unsafe_allow_html=True,
    )


# --- panel ---

def panel_dokumentu(plik_bajty, pdf_hash, nazwa_pliku, ocr_text="", potwierdzone=None):
    """Szukajka + podgląd dokumentu.

    `ocr_text` (z markerami stron) to jedyne źródło tekstu — przed analizą
    szukajka jest nieaktywna;
    `potwierdzone` (rozbieżności) sprawia, że fraza będąca jednym z zapisów
    pola szuka od razu wszystkich jego zapisów, w kolorach rodzaju.
    """
    st.markdown('<p class="naglowek-sekcji">📄 Dokument</p>', unsafe_allow_html=True)

    # nowy dokument: od pierwszej strony i pierwszego trafienia
    if st.session_state.get(KLUCZ_DOKUMENTU) != pdf_hash:
        st.session_state[KLUCZ_DOKUMENTU] = pdf_hash
        st.session_state[KLUCZ_STRONY] = 1
        st.session_state[KLUCZ_TRAFIENIA] = 0
        st.session_state[KLUCZ_OSTATNIEJ_FRAZY] = None

    liczba_stron = _liczba_stron(plik_bajty, pdf_hash)
    strony = zloz_strony(strony_z_ocr(ocr_text), liczba_stron)

    # Przed analizą nie ma tekstu — szukajka czeka na OCR.
    ma_tekst = any(strona["tekst"].strip() for strona in strony)

    st.session_state.setdefault(KLUCZ_FRAZY, "")

    fraza = st.text_input(
        "Szukaj w dokumencie",
        key=KLUCZ_FRAZY,
        placeholder=(
            "Wpisz frazę albo kliknij wartość pola po prawej"
            if ma_tekst
            else "Szukanie w dokumencie będzie dostępne po analizie (OCR)"
        ),
        disabled=not ma_tekst,
        label_visibility="collapsed",
    )
    if not ma_tekst:
        fraza = ""

    trafienia = []
    if fraza.strip():
        trafienia = znajdz_w_stronach(strony, warianty_do_szukania(fraza, potwierdzone))

    # strona ze źródła obowiązuje tylko dla kliknięcia, które ją ustawiło
    strona_zrodla = st.session_state.pop(KLUCZ_STRONY_ZRODLA, None)

    # nowa fraza (wpisana albo z kliknięcia w pole) zaczyna od pierwszego
    # trafienia wartości przyjętej — na stronie wskazanej przez model, jeśli
    # tam jest — a nie od wartości niezgodnej
    if fraza != st.session_state.get(KLUCZ_OSTATNIEJ_FRAZY):
        st.session_state[KLUCZ_OSTATNIEJ_FRAZY] = fraza
        st.session_state[KLUCZ_TRAFIENIA] = pierwsze_do_pokazania(trafienia, strona_zrodla)

    aktywne = max(0, min(st.session_state.get(KLUCZ_TRAFIENIA, 0), len(trafienia) - 1))

    if trafienia:
        strona = trafienia[aktywne]["strona"]
        st.session_state[KLUCZ_STRONY] = strona
    else:
        strona = max(1, min(st.session_state.get(KLUCZ_STRONY, 1), liczba_stron))

    if fraza.strip() and not trafienia:
        st.warning(
            f"Nie znaleziono „{fraza}” w dokumencie. "
            "Wartość może być zapisana inaczej albo pochodzić z błędnego odczytu."
        )

    _pasek_nawigacji(trafienia, aktywne, strona, liczba_stron)

    if trafienia:
        _legenda(trafienia)
        _fragment(trafienia[aktywne])

    with st.container(height=WYSOKOSC_PODGLADU, border=True):
        st.image(
            _obraz_strony(plik_bajty, pdf_hash, strona, SKALA_RENDERU),
            use_container_width=True,
        )

    kol_info, kol_pobierz = st.columns([3, 1])
    with kol_info:
        st.markdown(
            f'<div class="info-pliku">{html.escape(nazwa_pliku)} · '
            f'{len(plik_bajty) / 1024:.0f} KB · {liczba_stron} str.</div>',
            unsafe_allow_html=True,
        )
    with kol_pobierz:
        st.download_button(
            "⬇ Pobierz",
            data=plik_bajty,
            file_name=nazwa_pliku,
            mime="application/pdf",
            use_container_width=True,
        )


# =====================================================================
# WIDOKI APLIKACJI
# =====================================================================


# Logo liczone od katalogu aplikacji, nie od katalogu uruchomienia.
# Brak pliku (np. lokalnie) nie blokuje aplikacji — po prostu nie ma logo.
logo_base64 = (
    base64.b64encode(PLIK_LOGO.read_bytes()).decode()
    if PLIK_LOGO.exists()
    else ""
)


# =====================================================================
# STYLE - kolory jako zmienne CSS, z osobnym wariantem dla motywu ciemnego
# =====================================================================

CUSTOM_CSS = """
<style>
    /* ---------- Motyw jasny (domyślny) ---------- */
    /* Akcent fioletowy — czerwień zostaje wyłącznie dla błędów i ryzyk.
       Ten sam kolor co primaryColor w .streamlit/config.toml. */
    :root {
        --akcent: #6D4FC2;
        --akcent-ciemny: #4E3796;
        --baner-od: #7B61D1;
        --baner-do: #4E3796;
        --tlo-strony: #F6F5FB;
        --tlo-karty: #FFFFFF;
        --obramowanie: #E7E3F3;
        --tekst: #1F2937;
        --tekst-przygaszony: #6B7280;
        --cien: 0 1px 3px rgba(0, 0, 0, 0.05);

        --ryzyko-wysokie: #C0392B;
        --ryzyko-wysokie-tlo: #FDECEA;
        --ryzyko-srednie: #B25E00;
        --ryzyko-srednie-tlo: #FFF4E5;
        --ryzyko-niskie: #1E7C34;
        --ryzyko-niskie-tlo: #E6F4EA;

    }

    /* ---------- Motyw ciemny ---------- */
    @media (prefers-color-scheme: dark) {
        :root {
            --akcent: #B3A0F2;
            --akcent-ciemny: #8F76E0;
            --baner-od: #5B43A8;
            --baner-do: #35246F;
            --tlo-strony: #0F0E17;
            --tlo-karty: #1B1A26;
            --obramowanie: #2F2C40;
            --tekst: #E8EAED;
            --tekst-przygaszony: #9BA1AC;
            --cien: 0 1px 3px rgba(0, 0, 0, 0.35);

            --ryzyko-wysokie: #FF7A85;
            --ryzyko-wysokie-tlo: #3A1D22;
            --ryzyko-srednie: #E0A458;
            --ryzyko-srednie-tlo: #3A2E1C;
            --ryzyko-niskie: #6BCB8B;
            --ryzyko-niskie-tlo: #1B3325;

        }
    }

    /* ---------- Tła kontenerów Streamlita ---------- */
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .stApp {
        background-color: var(--tlo-strony);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }

    /* ---------- Baner nagłówkowy ---------- */
    .banner-naglowek {
        background: linear-gradient(135deg, var(--baner-od) 0%, var(--baner-do) 100%);
        color: #FFFFFF;
        padding: 28px 32px;
        border-radius: 14px;
        margin-bottom: 24px;
    }
    .banner-naglowek h1 {
        margin: 0;
        font-size: 1.7rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    .banner-naglowek p {
        margin: 4px 0 0 0;
        opacity: 0.92;
        font-size: 0.95rem;
        color: #FFFFFF;
    }

    /* ---------- Nagłówki sekcji ---------- */
    .naglowek-sekcji {
        color: var(--tekst);
        font-weight: 700;
        font-size: 1.05rem;
        margin: 4px 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid var(--akcent);
    }

    /* ---------- Kafelki danych klienta ---------- */
    .kafelek {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: var(--cien);
        height: 100%;
    }
    .kafelek-etykieta {
        color: var(--tekst-przygaszony);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 4px;
    }
    .kafelek-wartosc {
        color: var(--tekst);
        font-size: 1.12rem;
        font-weight: 700;
    }

    /* ---------- Karty z wynikami ekstrakcji ---------- */
    .karta {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 16px 20px 10px 20px;
        margin-bottom: 14px;
    }
    .karta-tytul {
        color: var(--tekst);
        font-weight: 700;
        font-size: 0.95rem;
        margin-bottom: 12px;
    }
    .wiersz {
        display: grid;
        grid-template-columns: 45% 1fr auto;
        gap: 0 14px;
        align-items: baseline;
        padding: 7px 0;
        font-size: 0.9rem;
        border-bottom: 1px solid var(--obramowanie);
    }
    .wiersz:last-child {
        border-bottom: none;
    }
    .wiersz-etykieta {
        color: var(--tekst-przygaszony);
        font-size: 0.84rem;
    }
    .wiersz-wartosc {
        color: var(--tekst);
        font-weight: 600;
        word-break: break-word;
    }
    .wiersz-wartosc.pusto {
        color: var(--tekst-przygaszony);
        font-weight: 400;
        font-style: italic;
    }

    /* ---------- Podsumowanie ---------- */
    .podsumowanie {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 20px 24px;
        font-size: 0.97rem;
        line-height: 1.7;
        color: var(--tekst);
    }

    /* ---------- Ryzyka ---------- */
    .karta-ryzyko {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 13px 18px;
        margin-bottom: 10px;
        color: var(--tekst);
        font-size: 0.93rem;
        line-height: 1.6;
    }
    .karta-ryzyko-wysoka { border-left: 4px solid var(--ryzyko-wysokie); }
    .karta-ryzyko-srednia { border-left: 4px solid var(--ryzyko-srednie); }
    .karta-ryzyko-niska { border-left: 4px solid var(--ryzyko-niskie); }

    .badge-waga-wysoka {
        background-color: var(--ryzyko-wysokie-tlo);
        color: var(--ryzyko-wysokie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }
    .badge-waga-srednia {
        background-color: var(--ryzyko-srednie-tlo);
        color: var(--ryzyko-srednie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }
    .badge-waga-niska {
        background-color: var(--ryzyko-niskie-tlo);
        color: var(--ryzyko-niskie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }

    /* ---------- Plakietki trybu ---------- */
    .badge-tryb-api {
        background-color: var(--ryzyko-niskie-tlo);
        color: var(--ryzyko-niskie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.8em;
        font-weight: 600;
    }

    .info-pliku {
        color: var(--tekst-przygaszony);
        font-size: 0.85rem;
        margin-bottom: 8px;
    }
    .tekst-pomocniczy {
        color: var(--tekst-przygaszony);
        font-size: 0.92rem;
        margin-bottom: 14px;
    }
    

    /* ---------- Kontrolki Streamlita ---------- */
    div.stButton > button:first-child {
    background-color: var(--tlo-karty);
    color: var(--tekst);
    border: 1px solid var(--obramowanie);
    font-weight: 600;
    border-radius: 8px;
    padding: 0.5rem 1.2rem;
    }

    div.stButton > button:first-child:hover {
        border-color: var(--akcent);
        color: var(--akcent);
        background-color: var(--tlo-karty);
    }
    
    div.stButton > button:first-child:disabled {
        opacity: 0.45;
        border-color: var(--obramowanie);
        color: var(--tekst-przygaszony);
    }

    div.stButton > button:first-child:focus-visible {
        outline: 2px solid var(--akcent);
        outline-offset: 2px;
    }
    [data-testid="stFileUploader"] {
        border: 1.5px dashed var(--obramowanie);
        border-radius: 10px;
        padding: 6px;
        background-color: var(--tlo-karty);
    }

    @media (prefers-reduced-motion: reduce) {
        * { transition: none !important; animation: none !important; }
    }
    /* ---------- Dodatkowe---------- */
    .haslo-ryzyka {
    color: var(--akcent);
    font-weight: 800;
    font-size: 1.02rem;
    }
    
    /* Logo mBanku w lewym dolnym rogu sidebara */

   section[data-testid="stSidebar"]::after {
        content: "";

        position: absolute;
        left: 49%;
        bottom: 20px;

        transform: translateX(-50%);

        width: 180px;
        height: 70px;

        background-image: url("data:image/jpeg;base64,LOGO_PLACEHOLDER");
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;

        pointer-events: none;
    }
    
    [data-testid="stExpander"] details {
    border: 1px solid var(--obramowanie) !important;
    border-left: 4px solid var(--akcent) !important;
    border-radius: 10px !important;
    overflow: hidden;
    }

    [data-testid="stExpander"] summary {
        font-weight: 800 !important;
        letter-spacing: 0.05em;
    }

    [data-testid="stExpander"] {
        margin-bottom: 10px;
    }
    [data-testid="stExpander"] summary {
    background: var(--tlo-karty) !important;
    padding: 12px 16px !important;
    }

    [data-testid="stExpander"] summary:hover {
        background: var(--tlo-strony) !important;
    }
    [data-testid="stExpander"] details > div {
        padding: 12px !important;
    }


    /* --- panel ustaleń --- */
    .ustalenie {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        background: var(--tlo-karty, #FFF);
        border: 1px solid var(--obramowanie, #E5E7EB);
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 7px;
    }
    .ustalenie-wysokie { border-left: 4px solid #C0392B; }
    .ustalenie-srednie { border-left: 4px solid #B25E00; }
    .ustalenie-ikona { font-size: 1.05rem; line-height: 1.4; }
    .ustalenie-tresc { flex: 1; }
    .ustalenie-tytul {
        font-size: 0.92rem;
        font-weight: 800;
        color: var(--tekst, #1F2937);
        margin-bottom: 2px;
    }
    .ustalenie-opis {
        font-size: 0.86rem;
        color: var(--tekst, #1F2937);
        line-height: 1.5;
    }
    .ustalenie-krok {
        font-size: 0.83rem;
        color: var(--tekst-przygaszony, #6B7280);
        margin-top: 4px;
    }
    .bez-ustalen {
        background: #E6F4EA;
        color: #1E7C34;
        border-radius: 8px;
        padding: 11px 16px;
        font-size: 0.88rem;
        font-weight: 700;
        margin-bottom: 14px;
    }

    /* --- panel dokumentu: szukajka i nawigacja --- */
    .pasek-nawigacji {
        color: var(--tekst-przygaszony, #6B7280);
        font-size: 0.86rem;
        text-align: center;
        padding-top: 8px;
        white-space: nowrap;
    }
    .pasek-nawigacji b { color: var(--tekst, #1F2937); }
    .legenda-trafien {
        display: flex;
        flex-wrap: wrap;
        gap: 14px;
        margin: 0 0 8px;
        font-size: 0.76rem;
        color: var(--tekst-przygaszony, #6B7280);
    }
    .legenda-wpis { display: flex; align-items: center; gap: 5px; }
    .legenda-kropka {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
        vertical-align: middle;
    }
    /* fragment tekstu OCR z trafieniem — przy skanie główny wskaźnik położenia frazy */
    .kontekst-trafienia {
        background: var(--tlo-karty, #FFF);
        border: 1px solid var(--obramowanie, #E5E7EB);
        border-left: 4px solid var(--akcent, #6D4FC2);
        border-radius: 8px;
        padding: 10px 14px 11px;
        margin-bottom: 10px;
        font-size: 0.9rem;
        line-height: 1.6;
        color: var(--tekst, #1F2937);
        word-break: break-word;
    }
    .fragment-meta {
        color: var(--tekst-przygaszony, #6B7280);
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .kontekst-trafienia mark {
        color: var(--tekst, #1F2937);
        padding: 1px 3px;
        border-radius: 3px;
        font-weight: 700;
    }

    /* --- nagłówek pola z dymkiem --- */
    .pole-naglowek {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 2px;
    }
    .pole-etykieta {
        color: var(--tekst-przygaszony, #6B7280);
        font-size: 0.8rem;
    }
    .znacznik {
        font-size: 0.75rem;
        font-weight: 800;
        padding: 2px 8px;
        border-radius: 20px;
        cursor: help;
    }
    .znacznik-rozbieznosc { background: #FFF4E5; color: #B25E00; }
    .znacznik-ok { background: var(--ryzyko-niskie-tlo); color: var(--ryzyko-niskie); }
    .znacznik-brak { background: var(--ryzyko-wysokie-tlo); color: var(--ryzyko-wysokie); }
    /* Trafienie przez odmianę ("Warszawa" -> "w Warszawie") to poprawny wynik,
       nie problem — bez tła, bez pogrubienia i w przygaszonym kolorze,
       żeby wzrok szedł do ⚠ i ✕, a nie tutaj. */
    .znacznik-odmiana {
        background: transparent;
        color: var(--tekst-przygaszony);
        font-weight: 400;
        padding: 2px 0;
    }

    /* komponent st-copy renderuje się jako iframe — domyślnie rezerwuje
       za dużo pionu i rozpycha komórki siatki */
    iframe[title="st_copy.copy_button"] {
        height: 30px !important;
        width: auto !important;
        margin-top: 2px;
    }
    div[data-testid="stIFrame"]:has(iframe[title="st_copy.copy_button"]) {
        display: flex;
        justify-content: flex-end;
        width: 100%;
    }
</style>
"""
def konfiguruj_strone():
    """Ustawienia strony i style — pierwsze wywołania Streamlita w main().

    Wewnątrz funkcji, a nie na poziomie pliku, żeby import app.py (np. w testach)
    nie uruchamiał Streamlita.
    """
    st.set_page_config(
        page_title="Hipoteka AI - Analiza Umowy Deweloperskiej",
        page_icon="🏦",
        layout="wide",
    )
    st.markdown(
        CUSTOM_CSS.replace("LOGO_PLACEHOLDER", logo_base64),
        unsafe_allow_html=True,
    )


# =====================================================================
# PANEL BOCZNY
# =====================================================================

def panel_konfiguracji():
    """Panel boczny: token do API albo informacja o trybie offline.

    Tryb offline (HIPOTEKA_OFFLINE=1) podmienia wyłącznie źródła danych
    — hurtownię i API — na pliki z katalogu dev/. Logika i widoki są te same
    co na produkcji, więc nie wraca problem dawnego trybu demo.
    """
    st.sidebar.markdown("## ⚙️ Konfiguracja")

    token = zrodla().wczytaj_token()

    if OFFLINE:
        st.sidebar.warning("Tryb offline: dane przykładowe z katalogu dev/, bez hurtowni i API.")

    elif token:
        st.sidebar.success(f"Token wczytany z {PLIK_TOKENU.name}")

    else:
        st.sidebar.error(
            f"Brak poprawnego tokenu w {PLIK_TOKENU}. "
            'Dodaj plik JSON z kluczem "access_token".'
        )

    return token


# =====================================================================
# NAGŁÓWEK I DANE WNIOSKU
# =====================================================================

def banner_naglowek():
    st.markdown(
        """
        <div class="banner-naglowek">
            <h1>🏦 Hipoteka AI — Analiza Umowy Deweloperskiej</h1>
            <p>Proof of Concept · Sprint 1 · OCR + ekstrakcja i analiza przez LLM</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kafelek(etykieta, wartosc):
    st.markdown(
        f"""
        <div class="kafelek">
            <div class="kafelek-etykieta">{etykieta}</div>
            <div class="kafelek-wartosc">{wartosc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# def sekcja_dane_wniosku(dane):
#     st.markdown('<p class="naglowek-sekcji">📋 Dane Klienta / Dane Wniosku</p>', unsafe_allow_html=True)
#     col1, col2, col3, col4, col5 = st.columns(5)
#     with col1:
#         kafelek("Numer wniosku", dane["numer_wniosku"])
#     with col2:
#         kafelek("Imię", dane["imie"])
#     with col3:
#         kafelek("Nazwisko", dane["nazwisko"])
#     with col4:
#         kafelek("PESEL", dane["pesel"])
#     with col5:
#         kafelek("Stan cywilny", dane["stan_cywilny"])
#     with col6:
#         kafelek("Liczba wnioskodawców", dane["liczba_wnioskodawcow"])


# =====================================================================
# UPLOAD I PODGLĄD
# =====================================================================

def sekcja_numer_wniosku():
    st.markdown(
        '<p class="naglowek-sekcji">🔎 Numer wniosku</p>',
        unsafe_allow_html=True
    )

    st.caption(
        "Wprowadź numer wniosku z UniFlow, aby pobrać dane klienta."
    )

    return st.text_input(
        "Numer wniosku",
        placeholder="np. KHB1553044",
        label_visibility="collapsed"
    ).strip()

def sekcja_dane_uniflow(nr_wniosku):

    # Dane poprzedniego wniosku czyścimy przy każdym wyjściu bez trafienia —
    # inaczej trafiłyby do promptu analizy dla innego numeru.
    if not nr_wniosku:
        ustaw_uniflow(None)
        return

    if not czy_poprawny_numer_wniosku(nr_wniosku):
        ustaw_uniflow(None)
        st.error("Numer wniosku może zawierać tylko litery, cyfry i znaki / _ . -")
        return

    rekord = zrodla().load_wnioskodawcy(nr_wniosku)

    if rekord.empty:
        ustaw_uniflow(None)
        st.warning(f"Nie znaleziono wniosku {nr_wniosku}")
        return

    ustaw_uniflow({
        "numer_wniosku": nr_wniosku,
        "wnioskodawcy": rekord[
            ["IMIE", "NAZWISKO", "PESEL", "STAN_CYWILNY"]
        ].to_dict("records")
    })
    

    st.markdown(
        '<p class="naglowek-sekcji">📋 Dane Klienta</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        kafelek("Numer wniosku", nr_wniosku)

    with col2:
        kafelek("Liczba wnioskodawców", len(rekord))
        
    st.markdown(
    "<div style='height:10px;'></div>",
    unsafe_allow_html=True
    )
    
    osoby = list(rekord.iterrows())

    for i in range(0, len(osoby), 2):

        col1, col2 = st.columns(2)

        with col1:
            _, osoba = osoby[i]

            karta(
                f"👤 Wnioskodawca {i+1}",
                [
                    wiersz("Imię", osoba["IMIE"]),
                    wiersz("Nazwisko", osoba["NAZWISKO"]),
                    wiersz("PESEL", osoba["PESEL"]),
                    wiersz("Stan cywilny", osoba["STAN_CYWILNY"]),

                ]
            )

        if i + 1 < len(osoby):
            with col2:
                _, osoba = osoby[i + 1]

                karta(
                    f"👤 Wnioskodawca {i+2}",
                    [
                        wiersz("Imię", osoba["IMIE"]),
                        wiersz("Nazwisko", osoba["NAZWISKO"]),
                        wiersz("PESEL", osoba["PESEL"]),
                        wiersz("Stan cywilny", osoba["STAN_CYWILNY"]),

                    ]
                )

#     for i, (_, osoba) in enumerate(
#         rekord.iterrows(),
#         start=1
#     ):

#         karta(
#             f"👤 Wnioskodawca {i}",
#             [
#                 wiersz("Imię", osoba["IMIE"]),
#                 wiersz("Nazwisko", osoba["NAZWISKO"]),
#                 wiersz("PESEL", osoba["PESEL"]),
#             ]
#         )

        # st.dataframe(
        #     rekord[["IMIE", "NAZWISKO", "PESEL"]],
        #     use_container_width=True,
        #     hide_index=True,
        # )


def sekcja_upload_widget():
    st.markdown('<p class="naglowek-sekcji">📤 Upload Dokumentu</p>', unsafe_allow_html=True)
    st.caption("Wspierany dokument w Sprincie 1: umowa deweloperska (PDF).")
    return st.file_uploader("Wybierz plik PDF", type=["pdf"],  label_visibility="collapsed")


# =====================================================================
# WYNIKI EKSTRAKCJI
# =====================================================================

# Pola, które analityk przepisuje do UniFlow — tylko one dostają przycisk
# kopiowania. Przy pozostałych polach przycisk byłby szumem.
POLA_DO_PRZEPISANIA = {
    "numer_umowy",
    "data_umowy",
    "nazwa_dewelopera",
    "numer_kw",
    "numer_dzialki",
    "numer_budynku",
    "numer_lokalu",
    "cena_nieruchomosci",
    "laczna_wartosc_transakcji",
    "termin_przeniesienia_wlasnosci",
    "numer_rachunku_powierniczego",
    "otwarty_numer_rachunku_powierniczego",
    "bank_powiernika",
}


def _opis_trafien(trafienia):
    """Treść dymka: ile razy wartość stoi w dokumencie, na jakich stronach
    i — gdy zapis się różni — w jakich formach. Analityk najeżdża myszą
    i wie od razu, bez otwierania szukajki, czy warto sprawdzać dalej.
    """
    if not trafienia:
        return "Wartość nie występuje w dokumencie — możliwy błąd odczytu OCR."

    strony = sorted({t["strona"] for t in trafienia if t["strona"]})
    opis = f"Znaleziono {len(trafienia)}× w dokumencie"
    if strony:
        opis += f", strony: {', '.join(str(s) for s in strony)}"
    opis += "."

    formy = sorted({t["trafienie"].strip() for t in trafienia if t["trafienie"].strip()})
    if len(formy) > 1:
        opis += " Zapisy: " + ", ".join(f'„{f}”' for f in formy) + "."

    return opis


def _stan_zrodla(zrodlo, wartosc, sprawdz_wartosc):
    """Stan pola ze źródła wskazanego przez model: (rodzaj, tekst, dymek)."""
    cytat = f"„{zrodlo['cytat']}”"
    strona = zrodlo["strona"]
    strona_modelu = zrodlo["strona_modelu"]

    if zrodlo["status"] == "niepotwierdzone":
        gdzie = f" na stronie {strona_modelu}" if strona_modelu else ""
        dymek = (
            f"Model wskazał{gdzie} fragment {cytat}, ale tego fragmentu nie ma "
            "w tekście OCR — sprawdź wartość na skanie."
        )
        return "brak", "✕ brak źródła", dymek

    if zrodlo["status"] == "inna_strona":
        dymek = (
            f"Źródło: {cytat}, strona {strona}. Model wskazał stronę {strona_modelu}, "
            f"ale fragment stoi na stronie {strona}."
        )
    else:
        dymek = f"Źródło: {cytat}, strona {strona} — fragment potwierdzony w tekście OCR."

    # Cytat bez wartości to znak, że model wskazał nie to miejsce.
    if sprawdz_wartosc and not cytat_zawiera_wartosc(zrodlo["cytat"], wartosc):
        dymek += " Uwaga: cytat nie zawiera tej wartości — sprawdź, czy to właściwe miejsce."
        return "niepewne", f"? s. {strona}", dymek

    return "ok", f"✓ s. {strona}", dymek


def stan_pola(problem, wartosc=None, ocr_text=None, potwierdzone=None,
              zrodlo=None, sprawdz_wartosc=True):
    """Stan pola: (rodzaj, tekst znacznika, dymek) albo None.

    Wspólne źródło prawdy dla znacznika przy polu (_znacznik_pola)
    i licznika w nagłówku sekcji (stan_sekcji) — dzięki temu nagłówek
    nie pokazuje ✓ dla pola, przy którym stoi ✕.

    Rozbieżność z ustaleń ma pierwszeństwo — to już decyzja do podjęcia.
    Potem źródło od modelu (strona i cytat, sprawdzone w tekście OCR).
    Gdy źródła nie ma (wynik z cache sprzed listy `zrodla`), stan liczony
    szukaniem wartości w tekście OCR: "ok" z liczbą trafień, "odmiana" gdy
    znaleziono tylko przez odmianę, "brak" gdy wartości nie ma w dokumencie.

    None, gdy nie da się nic policzyć (pusta wartość albo brak ocr_text).
    Rodzaje: "rozbieznosc", "niepewne", "brak", "odmiana", "ok".
    """
    if problem:
        return "rozbieznosc", "⚠ rozbieżność", f'{problem.get("opis", "")} → {problem.get("krok", "")}'

    if zrodlo and wartosc:
        return _stan_zrodla(zrodlo, wartosc, sprawdz_wartosc)

    if not ocr_text or not wartosc:
        return None

    zapisy = warianty_do_szukania(str(wartosc), potwierdzone)
    trafienia = szukaj_w_ocr_z_wariantami(ocr_text, zapisy)
    dymek = _opis_trafien(trafienia)

    if not trafienia:
        return "brak", "✕ brak", dymek

    if all(not t.get("dokladne", True) for t in trafienia):
        return "odmiana", f"≈ {len(trafienia)}", dymek

    return "ok", f"✓ {len(trafienia)}", dymek


KLASY_ZNACZNIKOW = {
    "rozbieznosc": "znacznik-rozbieznosc",
    "niepewne": "znacznik-rozbieznosc",
    "brak": "znacznik-brak",
    "odmiana": "znacznik-odmiana",
    "ok": "znacznik-ok",
}


def _znacznik_pola(problem, wartosc=None, ocr_text=None, potwierdzone=None,
                   zrodlo=None, sprawdz_wartosc=True):
    """Znacznik stanu w nagłówku pola; dymek (title) tłumaczy go po najechaniu.

    Pusty string, gdy stan_pola nic nie policzył, żeby .pole-naglowek
    (min-height) wyrównał wysokość do pól ze znacznikiem.
    """
    stan = stan_pola(problem, wartosc, ocr_text, potwierdzone, zrodlo, sprawdz_wartosc)
    if not stan:
        return ""

    rodzaj, tekst, dymek = stan
    return f'<span class="znacznik {KLASY_ZNACZNIKOW[rodzaj]}" title="{html.escape(dymek)}">{tekst}</span>'


# Pola sklejane w widoku z kilku wartości (ulica, numer budynku, miasto).
# Sklejonej frazy nie ma w dokumencie, więc szukanie jej dałoby fałszywe ✕ —
# stan i stronę dają wyłącznie źródło od modelu (klucz_zrodla: adres -> ulica).
def pole_sklejone(klucz):
    return klucz == "adres" or klucz.startswith("dod_adres_")


def stan_do_naglowka(klucz, wartosc, problemy, ocr_text, potwierdzone, zrodla):
    """Rodzaj stanu pola do licznika w nagłówku sekcji.

    Liczony tak samo jak znacznik przy polu (_pole_pdf). Puste pole to
    "brak"; wypełnione, dla którego nie da się nic policzyć — "ok".
    """
    if not wartosc or not str(wartosc).strip():
        return "brak"

    stan = stan_pola(
        problemy.get(klucz),
        wartosc,
        None if pole_sklejone(klucz) else ocr_text,
        potwierdzone,
        (zrodla or {}).get(klucz_zrodla(klucz)),
        wartosc_doslowna(klucz),
    )
    return stan[0] if stan else "ok"


def _pole_pdf(
    etykieta,
    wartosc,
    key,
    problem=None,
    potwierdzone=None,
    ocr_text=None,
    kopiowanie=None,
    zrodla=None,
):
    """Pole z wartością: on_click wkleja do szukajki i skacze do strony.

    Callback on_click (ustaw_fraze_szukania) ustawia fraza_ocr PRZED
    kolejnym renderem — jedyny bezpieczny sposób modyfikacji klucza
    który należy do widgetu text_input. Ręczne
    st.session_state["fraza_ocr"] = ... po wyrenderowaniu widgetu rzuca
    błąd Streamlita ("cannot be modified after widget is instantiated").

    `zrodla` (wynik zweryfikuj_zrodla) daje stronę wskazaną przez model:
    klik skacze na nią, a szukajka zaczyna od trafienia na tej stronie.
    Dla pól, których wartość nie stoi w dokumencie dosłownie (klasyfikacje,
    adres sklejony w widoku), do szukajki trafia cytat zamiast wartości.

    `kopiowanie` nadpisuje domyślną regułę (POLA_DO_PRZEPISANIA) — potrzebne
    dla pól z dynamicznym kluczem, jak transze harmonogramu, których nie da
    się z góry wypisać w stałej liście.
    """

    if not wartosc:
        return

    zrodlo = (zrodla or {}).get(klucz_zrodla(key))
    doslowna = wartosc_doslowna(key)
    if pole_sklejone(key):
        ocr_text = None

    st.markdown(
        f'<div class="pole-naglowek">'
        f'<span class="pole-etykieta">{etykieta}</span>'
        f'{_znacznik_pola(problem, wartosc, ocr_text, potwierdzone, zrodlo, doslowna)}'
        f'</div>',
        unsafe_allow_html=True
    )

    fraza = str(wartosc) if doslowna or not zrodlo else zrodlo["cytat"]
    strona = zrodlo["strona"] if zrodlo else None

    st.button(
        str(wartosc),
        key=f"pole_{key}",
        use_container_width=True,
        help="Kliknij, aby znaleźć w dokumencie",
        on_click=ustaw_fraze_szukania,
        args=(fraza, strona),
    )

    pokaz_kopiowanie = key in POLA_DO_PRZEPISANIA if kopiowanie is None else kopiowanie
    if pokaz_kopiowanie:
        if MA_KOPIOWANIE:
            copy_button(
                str(wartosc),
                tooltip="Kopiuj do UniFlow",
                copied_label="Skopiowano",
                key=f"kopiuj_{key}"
            )
        else:
            with st.popover("⧉ Kopiuj", use_container_width=True):
                st.caption("Kliknij ikonę kopiowania w rogu:")
                st.code(str(wartosc), language=None)


def wiersz(etykieta, wartosc, ikona=""):
    etykieta_html = f"{etykieta} {ikona}" if ikona else etykieta

    if wartosc:
        return (
            f'<div class="wiersz">'
            f'<span class="wiersz-etykieta">{etykieta_html}</span>'
            f'<span class="wiersz-wartosc">{wartosc}</span>'
            f'</div>'
        )

    return (
        f'<div class="wiersz">'
        f'<span class="wiersz-etykieta">{etykieta_html}</span>'
        f'<span class="wiersz-wartosc pusto">brak w dokumencie</span>'
        f'</div>'
    )


def karta(tytul, wiersze):
    st.markdown(
        f'<div class="karta"><div class="karta-tytul">{tytul}</div>{"".join(wiersze)}</div>',
        unsafe_allow_html=True,
    )


# =====================================================================
# SZUKAJKA W TEKŚCIE OCR, ROZBIEŻNOŚCI I PANEL USTALEŃ
# =====================================================================
# Stronę wartości wskazuje model w liście `zrodla` (patrz zweryfikuj_zrodla);
# szukanie wartości w tekście OCR ze stroną z najbliższego markera
# [STRONA_X] zostaje dla wpisanych fraz i dla wyników bez `zrodla`. Rozbieżności (to samo pole wskazane w dokumencie niejednolicie)
# zgłasza model przy każdym kluczowym polu (wartosci_ok / wartosci_zle),
# a Python sprawdza, czy każda wartość naprawdę stoi w tekście, i rozstrzyga
# podział dla dat i identyfikatorów.


def potwierdzone_rozbieznosci(analiza):
    """Skrót: potwierdzone rozbieżności dla analizy, z jej własnym tekstem OCR.

    Weryfikacja jest liczona przy każdym wyświetleniu, a nie zapisywana
    w cache — kosztuje kilka wyrażeń regularnych, a dzięki temu wpis w cache
    zostaje surowym wynikiem modelu. Lista `rozbieznosci` pochodzi
    z splaszcz_wynik (pola z trzema poziomami); po weryfikacji w tekście
    podział "ok"/"złe" dla dat i identyfikatorów poprawia rozstrzygnij_podzial.
    """
    potwierdzone, _ = zweryfikuj_warianty(
        analiza.ocr_text,
        analiza.wynik.get("rozbieznosci"),
    )
    return rozstrzygnij_podzial(potwierdzone)


def etykieta_sekcji(ikona, nazwa, stany):
    """Nagłówek niosący stan także wtedy, gdy sekcja jest zwinięta.

    Zastępuje sztywne "×2"/"×4" — liczba pól nic nie mówi, a stan mówi,
    czy trzeba tę sekcję w ogóle otwierać. `stany` to rodzaje stanów pól
    z stan_do_naglowka, liczone tak samo jak znaczniki przy polach.
    """
    ok, z_problemem, niepewne, brak = stan_sekcji(stany)

    stan = []
    if z_problemem:
        stan.append(f"⚠ {z_problemem}")
    if niepewne:
        stan.append(f"? {niepewne}")
    if brak:
        stan.append(f"✕ {brak}")
    if ok:
        stan.append(f"✓ {ok}")

    etykieta = f"{ikona} {nazwa.upper()}"
    if stan:
        etykieta += "　" + "  ".join(stan)

    # sekcja z problemem otwiera się sama — praca do wykonania nie powinna
    # chować się za kliknięciem
    return etykieta, (z_problemem > 0 or niepewne > 0 or brak > 0)


def panel_ustalen(ustalenia):
    """Wyłącznie rzeczy wymagające decyzji analityka.

    Gdy nie ma rozbieżności — jedna zielona linia zamiast listy potwierdzeń.
    To celowe: panel, który milczy przy zgodnych wnioskach, zostanie
    przeczytany przy niezgodnych.
    """
    if not ustalenia:
        st.markdown(
            '<div class="bez-ustalen">✓ Brak rozbieżności wymagających wyjaśnienia</div>',
            unsafe_allow_html=True,
        )
        return

    wysokie = sum(1 for u in ustalenia if u["poziom"] == "wysoki")

    naglowek = f"Do wyjaśnienia: {len(ustalenia)}"
    if wysokie:
        naglowek += f" · w tym {wysokie} do potwierdzenia przed analizą"

    st.markdown(
        f'<p class="naglowek-sekcji">⚠️ {naglowek}</p>',
        unsafe_allow_html=True,
    )

    for ustalenie in ustalenia:
        klasa = (
            "ustalenie-wysokie"
            if ustalenie["poziom"] == "wysoki"
            else "ustalenie-srednie"
        )
        ikona = "🛑" if ustalenie["poziom"] == "wysoki" else "⚠️"

        st.markdown(
            f'<div class="ustalenie {klasa}">'
            f'<div class="ustalenie-ikona">{ikona}</div>'
            f'<div class="ustalenie-tresc">'
            f'<div class="ustalenie-tytul">{html.escape(ustalenie["tytul"])}</div>'
            f'<div class="ustalenie-opis">{html.escape(ustalenie["opis"])}</div>'
            f'<div class="ustalenie-krok">→ {html.escape(ustalenie["krok"])}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


def widok_umowy_deweloperskiej(analiza):

    wynik = analiza.wynik
    harmonogram = wynik.get("harmonogram_transz", [])

    # Wersja pole_pdf związana z tą konkretną analizą — tekstem OCR i źródłami
    # wskazanymi przez model — dzięki temu każde wywołanie niżej liczy tick
    # i stronę bez przenoszenia ich przez kolejne parametry w kilkudziesięciu
    # miejscach.
    zrodla = zweryfikuj_zrodla(analiza.ocr_text, wynik.get("zrodla"))
    pole_pdf = partial(
        _pole_pdf,
        ocr_text=analiza.ocr_text,
        zrodla=zrodla,
    )

    # Rozbieżności zgłoszone przez model, przepuszczone przez weryfikację
    # w tekście OCR — zasilają dymki przy polach, liczniki w nagłówkach sekcji
    # i szukajkę.
    potwierdzone = potwierdzone_rozbieznosci(analiza)

    ustalenia = zbierz_problemy(
        wynik,
        wynik.get("weryfikacja_uniflow", []),
        potwierdzone
    )

    problemy = problemy_wg_pola(ustalenia)

    klucze_problemow = set(problemy.keys())

    # Adres to sklejka ulicy, numeru i miasta — rozbieżność którejś z nich
    # pokazujemy przy nim.
    problemy.setdefault("adres", problemy.get("ulica") or problemy.get("miasto"))

    adres = " ".join(
        filter(
            None,
            [
                wynik.get("ulica", ""),
                wynik.get("numer_budynku", "")
            ]
        )
    ).strip()

    dodatkowe_nieruchomosci = (
        wynik.get("dodatkowe_nieruchomosci")
        or []
    )

    prawa_przynalezne = (
        wynik.get("prawa_przynalezne")
        or []
    )

    
    if wynik.get("miasto"):
        adres = (
            f"{adres}, {wynik['miasto']}"
            if adres
            else wynik["miasto"]
        )

    wartosci_pol = {**wynik, "adres": adres}

    def stany(klucze, wartosci=wartosci_pol):
        """Stany pól sekcji do nagłówka — te same co znaczniki przy polach."""
        return [
            stan_do_naglowka(klucz, wartosci.get(klucz), problemy, analiza.ocr_text, potwierdzone, zrodla)
            for klucz in klucze
        ]

    pesel_1_status = waliduj_pesel(
        wynik.get("pesel_1")
    )

    pesel_2_status = waliduj_pesel(
        wynik.get("pesel_2")
    )

    status_transakcji = czy_wartosc_transakcji_zgodna(
        wynik
    )

    rachunek = wynik.get(
        "numer_rachunku_powierniczego"
    )

    status_rachunku = waliduj_nrb(
        rachunek
    )

    ikona_rachunku = (
        "✅"
        if status_rachunku == "Poprawny strukturalnie"
        else ""
    )

    # ====================================================
    # DOKUMENT
    # ====================================================

    etykieta_dokument, _ = etykieta_sekcji(
        "📄",
        "Dokument",
        stany(["numer_umowy", "data_umowy"])
    )

    with st.expander(
        etykieta_dokument,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer umowy",
                wynik.get("numer_umowy"),
                "numer_umowy",
                problemy.get("numer_umowy"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "Data zawarcia",
                wynik.get("data_umowy"),
                "data_umowy",
                problemy.get("data_umowy"),
                potwierdzone
            )

    # ====================================================
    # NABYWCY
    # ====================================================

    etykieta_nabywcy, _ = etykieta_sekcji(
        "👤",
        "Nabywcy",
        stany(["nabywca_1", "pesel_1", "nabywca_2", "pesel_2"])
    )

    with st.expander(
        etykieta_nabywcy,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nabywca 1",
                wynik.get("nabywca_1"),
                "nabywca_1",
                problemy.get("nabywca_1"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                f"PESEL 1 {pesel_1_status}",
                wynik.get("pesel_1"),
                "pesel_1",
                problemy.get("pesel_1"),
                potwierdzone
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nabywca 2",
                wynik.get("nabywca_2"),
                "nabywca_2",
                problemy.get("nabywca_2"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                f"PESEL 2 {pesel_2_status}",
                wynik.get("pesel_2"),
                "pesel_2",
                problemy.get("pesel_2"),
                potwierdzone
            )

    # ====================================================
    # DEWELOPER
    # ====================================================

    etykieta_deweloper, _ = etykieta_sekcji(
        "🏗️",
        "Deweloper",
        stany(["nazwa_dewelopera", "nip_dewelopera"])
    )

    with st.expander(
        etykieta_deweloper,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nazwa",
                wynik.get("nazwa_dewelopera"),
                "nazwa_dewelopera",
                problemy.get("nazwa_dewelopera"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "NIP",
                wynik.get("nip_dewelopera"),
                "nip_dewelopera",
                problemy.get("nip_dewelopera"),
                potwierdzone
            )

    # ====================================================
    # RACHUNEK POWIERNICZY
    # ====================================================

    etykieta_rachunek_powierniczy, _ = etykieta_sekcji(
        "🏦",
        "Rachunek powierniczy",
        stany(["bank_powiernika", "otwarty_numer_rachunku_powierniczego", "numer_rachunku_powierniczego"])
    )

    with st.expander(
        etykieta_rachunek_powierniczy,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Bank",
                wynik.get("bank_powiernika"),
                "bank_powiernika",
                problemy.get("bank_powiernika")
            )

        with col2:
            pole_pdf(
                "Otwarty rachunek",
                wynik.get("otwarty_numer_rachunku_powierniczego"),
                "otwarty_numer_rachunku_powierniczego",
                problemy.get("otwarty_numer_rachunku_powierniczego"),
                potwierdzone
            )

        pole_pdf(
            f"Rachunek indywidualny ({ikona_rachunku})",
            wynik.get("numer_rachunku_powierniczego"),
            "numer_rachunku_powierniczego",
            problemy.get("numer_rachunku_powierniczego"),
            potwierdzone
        )

    # ====================================================
    # NIERUCHOMOŚĆ
    # ====================================================

    etykieta_nieruchomosc, _ = etykieta_sekcji(
        "🏠",
        "Nieruchomość",
        stany(["adres", "rodzaj_nieruchomosci", "numer_budynku", "numer_lokalu", "numer_dzialki", "numer_kw"])
    )

    with st.expander(
        etykieta_nieruchomosc,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            # Tick i strona wyłącznie ze źródła od modelu (pole_sklejone).
            pole_pdf(
                "Adres",
                adres,
                "adres",
                problemy.get("adres"),
            )

        with col2:
            pole_pdf(
                "Rodzaj",
                wynik.get("rodzaj_nieruchomosci"),
                "rodzaj_nieruchomosci",
                problemy.get("rodzaj_nieruchomosci")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer budynku",
                wynik.get("numer_budynku"),
                "numer_budynku",
                problemy.get("numer_budynku")
            )

        with col2:
            pole_pdf(
                "Numer lokalu",
                wynik.get("numer_lokalu"),
                "numer_lokalu",
                problemy.get("numer_lokalu")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer działki",
                wynik.get("numer_dzialki"),
                "numer_dzialki",
                problemy.get("numer_dzialki"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "Księga wieczysta",
                wynik.get("numer_kw"),
                "numer_kw",
                problemy.get("numer_kw"),
                potwierdzone
            )
        # ====================================================
    # PRAWA PRZYNALEŻNE
    # ====================================================

    if prawa_przynalezne:

        for idx, prawo in enumerate(
            prawa_przynalezne,
            start=1
        ):

            with st.expander(
                f"🚗 PRAWO PRZYNALEŻNE {idx}",
                expanded=False
            ):

                col1, col2 = st.columns(2)

                with col1:
                    pole_pdf(
                        "Rodzaj",
                        prawo.get("rodzaj"),
                        f"prawo_rodzaj_{idx}",
                        problemy.get(f"prawo_rodzaj_{idx}")
                    )

                with col2:
                    pole_pdf(
                        "Tytuł prawny",
                        prawo.get("tytul_prawny"),
                        f"prawo_tytul_{idx}",
                        problemy.get(f"prawo_tytul_{idx}")
                    )

                col1, col2 = st.columns(2)

                with col1:
                    pole_pdf(
                        "Oznaczenie",
                        prawo.get("oznaczenie"),
                        f"prawo_oznaczenie_{idx}",
                        problemy.get(f"prawo_oznaczenie_{idx}")
                    )

                with col2:
                    pole_pdf(
                        "Cena zakupu",
                        prawo.get("cena"),
                        f"prawo_cena_{idx}",
                        problemy.get(f"prawo_cena_{idx}")
                    )
    
        # ====================================================
    # DODATKOWE NIERUCHOMOŚCI
    # ====================================================

    for idx, nieruchomosc in enumerate(
        dodatkowe_nieruchomosci,
        start=1
    ):

        adres2 = " ".join(
            filter(
                None,
                [
                    nieruchomosc.get("ulica", ""),
                    nieruchomosc.get("numer_budynku", "")
                ]
            )
        ).strip()

        if nieruchomosc.get("miasto"):

            adres2 = (
                f"{adres2}, {nieruchomosc['miasto']}"
                if adres2
                else nieruchomosc["miasto"]
            )

        with st.expander(
            f"🏘️ DODATKOWA NIERUCHOMOŚĆ {idx}",
            expanded=False
        ):

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Rodzaj",
                    nieruchomosc.get(
                        "rodzaj_nieruchomosci"
                    ),
                    f"dod_rodzaj_{idx}",
                    problemy.get(f"dod_rodzaj_{idx}")
                )

            with col2:
                pole_pdf(
                    "Adres",
                    adres2,
                    f"dod_adres_{idx}",
                    problemy.get(f"dod_adres_{idx}"),
                )

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Tytuł prawny",
                    nieruchomosc.get(
                        "tytul_prawny"
                    ),
                    f"dod_tytul_{idx}",
                    problemy.get(f"dod_tytul_{idx}")
                )

            with col2:
                pole_pdf(
                    "Numer lokalu",
                    nieruchomosc.get(
                        "numer_lokalu"
                    ),
                    f"dod_lokal_{idx}",
                    problemy.get(f"dod_lokal_{idx}")
                )

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Oznaczenie",
                    nieruchomosc.get(
                        "oznaczenie"
                    ),
                    f"dod_oznaczenie_{idx}",
                    problemy.get(f"dod_oznaczenie_{idx}")
                )

            with col2:
                pole_pdf(
                    "Księga wieczysta",
                    nieruchomosc.get(
                        "numer_kw"
                    ),
                    f"dod_kw_{idx}",
                    problemy.get(f"dod_kw_{idx}")
                )

            pole_pdf(
                "Cena",
                nieruchomosc.get(
                    "cena_nieruchomosci"
                ),
                f"dod_cena_{idx}",
                problemy.get(f"dod_cena_{idx}")
            )

    # ====================================================
    # TRANSAKCJA
    # ====================================================

    etykieta_transakcja, _ = etykieta_sekcji(
        "💰",
        "Transakcja",
        stany(["cena_nieruchomosci", "laczna_wartosc_transakcji", "liczba_transz", "termin_przeniesienia_wlasnosci", "termin_odrebnej_wlasnosci"])
    )

    with st.expander(
        etykieta_transakcja,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Cena nieruchomości",
                wynik.get("cena_nieruchomosci"),
                "cena_nieruchomosci",
                problemy.get("cena_nieruchomosci")
            )

        with col2:
            pole_pdf(
                f"Wartość łączna {status_transakcji}",
                wynik.get("laczna_wartosc_transakcji"),
                "laczna_wartosc_transakcji",
                problemy.get("laczna_wartosc_transakcji")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Liczba transz",
                wynik.get("liczba_transz"),
                "liczba_transz",
                problemy.get("liczba_transz")
            )

        with col2:
            pole_pdf(
                "Przeniesienie własności",
                wynik.get("termin_przeniesienia_wlasnosci"),
                "termin_przeniesienia_wlasnosci",
                problemy.get("termin_przeniesienia_wlasnosci"),
                potwierdzone
            )

        pole_pdf(
            "Odrębna własność",
            wynik.get("termin_odrebnej_wlasnosci"),
            "termin_odrebnej_wlasnosci",
            problemy.get("termin_odrebnej_wlasnosci"),
            potwierdzone
        )

    # ====================================================
    # HARMONOGRAM
    # ====================================================
    # Każda transza jako dwa klikalne pola (kwota, termin), nie wiersz
    # tabeli — inaczej klik w pojedynczą kwotę i skok do jej miejsca
    # w dokumencie byłby niemożliwy do zrobienia w st.dataframe.

    # Klucze pól liczone z pozycji na liście (od 1), nie z numer_transzy od
    # modelu: dwie płatności bez numeru albo z powtórzonym numerem dawały
    # ten sam klucz widgetu i Streamlit przerywał render. Pozycja zgadza
    # się też z numerem elementu w źródłach (harmonogram_transz[N]).
    wynik_transz = {}
    for pozycja, t in enumerate(harmonogram, start=1):
        wynik_transz[f"transza_{pozycja}_kwota"] = t.get("kwota")
        wynik_transz[f"transza_{pozycja}_termin"] = t.get("termin_platnosci")

    etykieta_harmonogramu, otworz_harmonogram = etykieta_sekcji(
        "📅",
        "Harmonogram",
        stany(wynik_transz, wynik_transz)
    )

    with st.expander(
        etykieta_harmonogramu,
        # Otwiera się też, gdy nie zgadza się suma transz — problem
        # jest wtedy przypisany do laczna_wartosc_transakcji, nie do
        # pojedynczej transzy, więc same klucze transz go nie wykryją.
        expanded=otworz_harmonogram or "laczna_wartosc_transakcji" in klucze_problemow
    ):

        if harmonogram:

            for pozycja, t in enumerate(harmonogram, start=1):
                # W etykiecie numer z umowy, gdy jest — tak analityk go widzi w dokumencie.
                numer = t.get("numer_transzy") or pozycja

                col1, col2 = st.columns(2)

                with col1:
                    pole_pdf(
                        f"Transza {numer} — kwota",
                        t.get("kwota"),
                        f"transza_{pozycja}_kwota",
                        problemy.get(f"transza_{pozycja}_kwota"),
                        potwierdzone,
                        kopiowanie=True,
                    )

                with col2:
                    pole_pdf(
                        f"Transza {numer} — termin płatności",
                        t.get("termin_platnosci"),
                        f"transza_{pozycja}_termin",
                        problemy.get(f"transza_{pozycja}_termin"),
                        potwierdzone,
                        kopiowanie=True,
                    )

        else:
            st.caption(
                "Brak harmonogramu."
            )


def widok_json(wynik):

    st.json(
        wynik,
        expanded=True
    )

def widok_ocr(ocr_text):

    st.text_area(
        "Treść OCR",
        value=ocr_text,
        height=900
    )

    
def pokaz_wynik_dokumentu(analiza):

    if analiza.typ_dokumentu == "umowa_deweloperska":
        widok_umowy_deweloperskiej(analiza)
    else:
        widok_json(analiza.wynik_surowy or analiza.wynik)
        
        
def widok_podsumowania(tekst):
    st.markdown('<p class="naglowek-sekcji">📝 Podsumowanie</p>', unsafe_allow_html=True)
    st.markdown(f'<div class="podsumowanie">{tekst}</div>', unsafe_allow_html=True)


def widok_ryzyk(lista_ryzyk):
    st.markdown('<p class="naglowek-sekcji">⚠️ Potencjalne ryzyka</p>', unsafe_allow_html=True)

    if not lista_ryzyk:
        st.caption("Nie zidentyfikowano istotnych ryzyk w tym dokumencie.")
        return

    kolejnosc = {"wysoka": 0, "srednia": 1, "niska": 2}
    posortowane = sorted(lista_ryzyk, key=lambda r: kolejnosc.get(r.get("waga", "srednia"), 1))

    for ryzyko in posortowane:
        waga = ryzyko.get("waga", "srednia")
        if waga not in kolejnosc:
            waga = "srednia"

        opis = html.unescape(ryzyko.get("opis", ""))

        st.markdown(
            f'<div class="karta-ryzyko karta-ryzyko-{waga}">'
            f'<span class="badge-waga-{waga}">{waga}</span>'
            f'&nbsp;&nbsp;{opis}</div>',
            unsafe_allow_html=True,
        )

# =====================================================================
# URUCHOMIENIE ANALIZY
# =====================================================================

def uruchom_analize(plik_bajty, nazwa_pliku, numer_wniosku, token, typ_dokumentu, wymus_ponowna_analize=False):
    """Uruchamia analizę (analizuj) i zapisuje wynik w stanie sesji."""
    pasek = st.progress(0, text="Rozpoczynanie analizy...")

    try:
        analiza = analizuj(
            plik_bajty=plik_bajty,
            nazwa_pliku=nazwa_pliku,
            nr_wniosku=numer_wniosku,
            token=token,
            dane_uniflow=dane_uniflow(numer_wniosku),
            typ_dokumentu=typ_dokumentu,
            zrodla=zrodla(),
            wymus=wymus_ponowna_analize,
            postep=lambda procent, opis: pasek.progress(procent, text=opis),
        )
    except Exception as blad:
        pasek.empty()
        st.error(f"Analiza nie powiodła się: {blad}")
        return

    pasek.empty()
    zapisz_analize(analiza)
    st.rerun()


def sekcja_akcja_i_kluczowe_dane(plik_bajty, nazwa_pliku, pdf_hash, numer_wniosku, token, typ_dokumentu):
    analiza = biezaca_analiza(pdf_hash, numer_wniosku)

    if analiza is None:
        st.markdown('<p class="naglowek-sekcji">🔑 Kluczowe dane</p>', unsafe_allow_html=True)
        st.markdown(
            '<div class="tekst-pomocniczy">Dokument jest wczytany. Uruchom analizę, aby odczytać '
            'kluczowe dane, podsumowanie i wykaz ryzyk.</div>',
            unsafe_allow_html=True,
        )

        # Bez danych wniosku model nie ma z czym porównać nabywców, a wynik
        # z pustą weryfikacją trafiłby do cache — dlatego analiza czeka na wniosek.
        ma_wniosek = dane_uniflow(numer_wniosku) is not None
        czy_gotowe = bool(token) and ma_wniosek

        wymus_ponowna_analize = st.checkbox(
            "🔄 Wymuś ponowną analizę (pomiń cache)",
            value=False
        )

        if st.button("▶ Uruchom analizę dokumentu", type="primary", disabled=not czy_gotowe):
            uruchom_analize(
                plik_bajty, nazwa_pliku, numer_wniosku, token, typ_dokumentu, wymus_ponowna_analize
            )
        if not token:
            st.caption("Dodaj token.txt, aby korzystać z prawdziwego API.")
        if not ma_wniosek:
            st.caption("Wprowadź numer wniosku — dane klientów z UniFlow są porównywane z dokumentem.")
        return

    col_status, col_przycisk = st.columns([3, 1])
    with col_status:
        st.markdown(
            f'<div class="info-pliku" style="margin-top:8px;">✅ Analiza: '
            f'{analiza.czas} &nbsp;'
            f'<span class="badge-tryb-api">{analiza.zrodlo}</span></div>',
            unsafe_allow_html=True,
        )
    with col_przycisk:
        if st.button("↺ Ponów"):
            usun_analize(pdf_hash, numer_wniosku)
            st.rerun()

    for ostrzezenie in analiza.ostrzezenia:
        st.warning(ostrzezenie)

    tab_dane, tab_ocr, tab_json = st.tabs(
        [
            "🔑 Kluczowe dane",
            "📄 OCR",
            "📋 JSON"
        ]
    )

    with tab_dane:

        with st.container(
            height=900,
            border=True
        ):

            pokaz_wynik_dokumentu(analiza)
    with tab_ocr:

        widok_ocr(analiza.ocr_text)

    with tab_json:

        widok_json(analiza.wynik_surowy or analiza.wynik)

def sekcja_podsumowanie_i_ryzyka(analiza):
    if analiza is None:
        return

    wynik = analiza.wynik
    st.divider()
    widok_podsumowania(wynik.get("podsumowanie", ""))
    st.markdown("<div style='height:22px;'></div>", unsafe_allow_html=True)
    widok_ryzyk(wynik.get("potencjalne_ryzyka", []))

def widok_weryfikacji_uniflow(analiza):
    """Panel ustaleń: wyłącznie rzeczy wymagające decyzji analityka.

    Zastępuje listę wszystkich wyników weryfikacji UniFlow. Zgodności nie są
    pokazywane — panel, który potwierdza oczywistości, przestaje być czytany
    po kilku analizach. Do weryfikacji z modelu dochodzą twarde kontrole
    liczone w Pythonie (PESEL, NRB, suma transz) i rozbieżności w dokumencie.
    """

    ustalenia = zbierz_problemy(
        analiza.wynik,
        analiza.wynik.get("weryfikacja_uniflow", []),
        potwierdzone_rozbieznosci(analiza)
    )

    panel_ustalen(ustalenia)


# =====================================================================
# MAIN
# =====================================================================
# def wnioskodawcy_z_ocr(wynik):
#     wnioskodawcy = []

#     for nr in range (1,6):
#         nazwa = wynik.get(f"nabywca_{nr}")
#         pesel = wynik.get(f"pesel_{nr}")

#         if nazwa:
#             wnioskodawcy.append({
#                 "imie_nazwisko": nazwa.strip(),
#                 "pesel": str(pesel).strip() if pesel else "",
#             })

#     return wnioskodawcy

# def pokaz_porownanie(osoby_uniflow, wynik):

#     osoby_ocr = wnioskodawcy_z_ocr(wynik)

#     porownanie = []

#     max_osob = max(len(osoby_uniflow), len(osoby_ocr))

#     for i in range(max_osob):

#         osoba_h = osoby_uniflow[i] if i < len(osoby_uniflow) else {}
#         osoba_o = osoby_ocr[i] if i < len(osoby_ocr) else {}

#         porownanie.append({
#             "Wnioskodawca": i + 1,

#             "OCR Imię i nazwisko": osoba_o.get("imie_nazwisko", ""),
#             "Uniflow Imię i nazwisko": osoba_h.get("imie_nazwisko", ""),
#             "Zgodność imienia i nazwiska ": (
#                 "✅"
#                 if osoba_o.get("imie_nazwisko", "").lower()
#                 == osoba_h.get("imie_nazwisko", "").lower()
#                 else "❌"
#             ),

#             "OCR PESEL": osoba_o.get("pesel", ""),
#             "Uniflow PESEL": osoba_h.get("pesel", ""),
#             "Zgodność PESEL": (
#                 "✅"
#                 if osoba_o.get("pesel", "")
#                 == osoba_h.get("pesel", "")
#                 else "❌"
#             ),
#         })

#     st.markdown(
#         '<p class="naglowek-sekcji">✅ Porównanie OCR vs Uniflow</p>',
#         unsafe_allow_html=True,
#     )

#     st.dataframe(
#         pd.DataFrame(porownanie),
#         use_container_width=True,
#         hide_index=True,
#     )
   
    
def menu_boczne():

    wybor = st.sidebar.radio(
        "Nawigacja",
        [
            "📄 Umowa deweloperska",
            "📄 Umowa przedwstępna",
            "📄 Umowa rezerwacyjna",
            "📄 Wzór prospektu informacyjnego",
            "📄 Oświadczenie zbywcy",
            "📋 Podsumowanie"
        ]
    )

    return wybor


def zakladka_umowa_deweloperska(
    nr_wniosku,
    token
):
    # Typ dokumentu wynika z zakładki, a nie z nazwy pliku.
    typ_dokumentu = "umowa_deweloperska"

    plik = sekcja_upload_widget()

    if plik:
        zapamietaj_plik(typ_dokumentu, plik.name, plik.getvalue())

    plik_dane = wgrany_plik(typ_dokumentu)

    if not plik_dane:
        return

    bajty_pdf = plik_dane["bajty"]
    nazwa_pliku = plik_dane["nazwa"]
    pdf_hash = plik_dane["hash"]

    analiza = biezaca_analiza(pdf_hash, nr_wniosku)
    potwierdzone = potwierdzone_rozbieznosci(analiza) if analiza else None

    # Panel ustaleń na pełnej szerokości — przed podziałem na kolumny.
    if analiza:
        panel_ustalen(
            zbierz_problemy(
                analiza.wynik,
                analiza.wynik.get("weryfikacja_uniflow", []),
                potwierdzone
            )
        )

    col_podglad, col_dane = st.columns(
        [1, 1.05],
        gap="large"
    )

    with col_podglad:

        # Szukajka nad dokumentem: po analizie szuka w tekście OCR
        # (z wariantami z rozbieżności) i przełącza podgląd na stronę.
        panel_dokumentu(
            bajty_pdf,
            pdf_hash,
            nazwa_pliku,
            analiza.ocr_text if analiza else "",
            potwierdzone
        )

    with col_dane:
        sekcja_akcja_i_kluczowe_dane(
            bajty_pdf,
            nazwa_pliku,
            pdf_hash,
            nr_wniosku,
            token,
            typ_dokumentu
        )

    sekcja_podsumowanie_i_ryzyka(analiza)
    
    
def zakladka_podsumowanie(nr_wniosku):

    plik_dane = wgrany_plik("umowa_deweloperska")
    analiza = (
        biezaca_analiza(plik_dane["hash"], nr_wniosku)
        if plik_dane
        else None
    )

    if analiza is None:
        st.info(
            "Przeanalizuj dokument, aby zobaczyć podsumowanie."
        )
        return

    widok_weryfikacji_uniflow(analiza)
        

def main():
    konfiguruj_strone()

    token = panel_konfiguracji()

    banner_naglowek()

    if OFFLINE:
        st.warning(
            "**Tryb offline** — dane wniosku i wynik ekstrakcji pochodzą z katalogu dev/, "
            "a nie z hurtowni i API. Numer wniosku z danych przykładowych: KHB1553044."
        )

    # dane_wniosku = pobierz_dane_wniosku()
    # sekcja_dane_wniosku(dane_wniosku)
    # st.divider()
    
    nr_wniosku = sekcja_numer_wniosku()
    
    sekcja_dane_uniflow(nr_wniosku)
  
    zakladka = menu_boczne()
    
    if zakladka == "📋 Podsumowanie":

        zakladka_podsumowanie(nr_wniosku)

    elif zakladka == "📄 Umowa deweloperska":

        zakladka_umowa_deweloperska(
            nr_wniosku,
            token
        )

    elif zakladka == "📄 Umowa przedwstępna":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Umowa rezerwacyjna":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Wzór prospektu informacyjnego":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Oświadczenie zbywcy":

        st.info("W przygotowaniu")


if __name__ == "__main__":
    main()

"""Źródła wartości: strona i cytat od modelu, sprawdzane w tekście OCR."""
import json
from pathlib import Path

import pytest

from app import (
    cytat_zawiera_wartosc,
    dodaj_markery_stron,
    klucz_zrodla,
    pierwsze_do_pokazania,
    splaszcz_wynik,
    tekst_do_cytatu,
    wartosc_doslowna,
    zweryfikuj_zrodla,
)

DEV = Path(__file__).resolve().parent.parent / "dev"

OCR = (
    "\n\n[STRONA_1]\n# Repertorium A Nr 1123/2026\n"
    "przedmiotem umowy jest lokal mieszkalny nr 42 w budynku przy ul.\n"
    "Puław-\nskiej 17B w Warszawie\n"
    "\n\n[STRONA_2]\n"
    "&lt;tr&gt;&lt;td&gt;1&lt;/td&gt;&lt;td&gt;144 000,00 zł&lt;/td&gt;"
    "&lt;td&gt;21-03-2026&lt;/td&gt;&lt;/tr&gt;\n"
    "Łączna wartość transakcji wynosi 720\n000,00 zł."
)


def zrodlo(pole, strona, cytat):
    return {"pole": pole, "strona": strona, "cytat": cytat}


# --- porównywanie cytatu z tekstem ---

def test_tekst_do_cytatu_skleja_przeniesienia_i_lamania():
    assert tekst_do_cytatu("ul.\nPuław-\nskiej 17B") == tekst_do_cytatu("ul. Puławskiej 17B")
    assert tekst_do_cytatu("Rep. A\n  nr 5") == "rep. a nr 5"


def test_tekst_do_cytatu_usuwa_znaczniki_tabeli():
    oczekiwany = tekst_do_cytatu("1 144 000,00 zł")
    assert tekst_do_cytatu("&lt;td&gt;1&lt;/td&gt;&lt;td&gt;144 000,00 zł") == oczekiwany
    assert tekst_do_cytatu("<td>1</td><td>144 000,00 zł") == oczekiwany
    assert tekst_do_cytatu("1 | 144 000,00 zł") == oczekiwany


def test_tekst_do_cytatu_ujednolica_myslniki_i_cudzyslowy():
    assert tekst_do_cytatu("lokal — „A”") == tekst_do_cytatu('lokal - "A"')


# --- weryfikacja źródeł ---

def test_cytat_na_wskazanej_stronie_jest_potwierdzony():
    wynik = zweryfikuj_zrodla(OCR, [zrodlo("numer_lokalu", 1, "lokal mieszkalny nr 42")])
    assert wynik["numer_lokalu"]["status"] == "potwierdzone"
    assert wynik["numer_lokalu"]["strona"] == 1


def test_zla_strona_od_modelu_przegrywa_z_tekstem():
    wynik = zweryfikuj_zrodla(OCR, [zrodlo("numer_lokalu", 2, "lokal mieszkalny nr 42")])
    assert wynik["numer_lokalu"]["status"] == "inna_strona"
    assert wynik["numer_lokalu"]["strona"] == 1
    assert wynik["numer_lokalu"]["strona_modelu"] == 2


def test_cytatu_spoza_tekstu_nie_potwierdzamy():
    wynik = zweryfikuj_zrodla(OCR, [zrodlo("numer_lokalu", 1, "lokal mieszkalny nr 43")])
    assert wynik["numer_lokalu"]["status"] == "niepotwierdzone"
    assert wynik["numer_lokalu"]["strona"] == 1


def test_cytat_musi_stac_jako_cale_slowa():
    # "nr 4" nie może potwierdzić się w "nr 42"
    wynik = zweryfikuj_zrodla(OCR, [zrodlo("numer_lokalu", 1, "lokal mieszkalny nr 4")])
    assert wynik["numer_lokalu"]["status"] == "niepotwierdzone"


def test_cytat_przez_lamanie_linii_i_przeniesienie_wyrazu():
    wynik = zweryfikuj_zrodla(OCR, [
        zrodlo("ulica", 1, "przy ul. Puławskiej 17B w Warszawie"),
        zrodlo("laczna_wartosc_transakcji", 2, "Łączna wartość transakcji wynosi 720 000,00 zł"),
    ])
    assert wynik["ulica"]["status"] == "potwierdzone"
    assert wynik["laczna_wartosc_transakcji"]["status"] == "potwierdzone"


def test_cytat_z_wiersza_tabeli():
    wynik = zweryfikuj_zrodla(OCR, [
        zrodlo("harmonogram_transz[1].kwota", 2, "1 | 144 000,00 zł | 21-03-2026"),
    ])
    assert wynik["harmonogram_transz[1].kwota"]["status"] == "potwierdzone"


def test_pierwszy_wpis_pola_wygrywa_a_smieci_sa_pomijane():
    wynik = zweryfikuj_zrodla(OCR, [
        "nie słownik",
        zrodlo("", 1, "lokal"),
        zrodlo("numer_lokalu", "abc", ""),
        zrodlo("numer_lokalu", "1", "lokal mieszkalny nr 42"),
        zrodlo("numer_lokalu", 2, "Repertorium A Nr 1123/2026"),
    ])
    assert list(wynik) == ["numer_lokalu"]
    assert wynik["numer_lokalu"]["cytat"] == "lokal mieszkalny nr 42"
    assert wynik["numer_lokalu"]["strona_modelu"] == 1


def test_brak_listy_zrodel():
    assert zweryfikuj_zrodla(OCR, None) == {}


def test_spacje_w_kluczu_pola_od_modelu():
    wynik = zweryfikuj_zrodla(OCR, [zrodlo("harmonogram_transz[1]. kwota", 2, "144 000,00 zł")])
    assert "harmonogram_transz[1].kwota" in wynik


# --- cytat a wartość pola ---

@pytest.mark.parametrize("cytat, wartosc", [
    ("1 | 144 000,00 zł | 21-03-2026", "144 000,00 zł"),
    ("do dnia 30 czerwca 2027 r.", "2027-06-30"),
    ("księgę wieczystą nr WA1M/00123456/7", "WA1M 00123456 7"),
])
def test_cytat_zawiera_wartosc(cytat, wartosc):
    assert cytat_zawiera_wartosc(cytat, wartosc)


def test_cytat_z_inna_wartoscia():
    assert not cytat_zawiera_wartosc("Cena lokalu wynosi 685 000,00 zł", "720 000,00 zł")


# --- klucze pól z widoku ---

@pytest.mark.parametrize("klucz, oczekiwany", [
    ("numer_kw", "numer_kw"),
    ("adres", "ulica"),
    ("transza_2_kwota", "harmonogram_transz[2].kwota"),
    ("transza_2_termin", "harmonogram_transz[2].termin_platnosci"),
    ("prawo_tytul_1", "prawa_przynalezne[1].tytul_prawny"),
    ("prawo_cena_3", "prawa_przynalezne[3].cena"),
    ("dod_kw_1", "dodatkowe_nieruchomosci[1].numer_kw"),
    ("dod_adres_2", "dodatkowe_nieruchomosci[2].ulica"),
])
def test_klucz_zrodla(klucz, oczekiwany):
    assert klucz_zrodla(klucz) == oczekiwany


@pytest.mark.parametrize("klucz, doslowna", [
    ("numer_kw", True),
    ("transza_1_kwota", True),
    ("prawo_oznaczenie_1", True),
    ("adres", False),
    ("rodzaj_nieruchomosci", False),
    ("liczba_transz", False),
    ("prawo_tytul_1", False),
    ("dod_rodzaj_2", False),
])
def test_wartosc_doslowna(klucz, doslowna):
    assert wartosc_doslowna(klucz) is doslowna


# --- szukajka zaczyna od strony źródła ---

def test_pierwsze_trafienie_na_stronie_zrodla():
    trafienia = [{"strona": 1}, {"strona": 2, "rodzaj": "zla"}, {"strona": 2}, {"strona": 3}]
    assert pierwsze_do_pokazania(trafienia, 2) == 2
    assert pierwsze_do_pokazania(trafienia, 3) == 3
    # strona bez trafień — zwykła kolejność
    assert pierwsze_do_pokazania(trafienia, 5) == 0
    assert pierwsze_do_pokazania(trafienia) == 0


# --- podział na strony ---

def test_znacznik_strony_zapisany_wprost():
    tekst = dodaj_markery_stron("a<!-- PageBreak -->b&lt;!-- PageBreak --&gt;c")
    assert "[STRONA_3]" in tekst


# --- dane demo ---

def test_zrodla_w_danych_demo():
    """Każde źródło demo stoi w tekście, a jedno ma celowo złą stronę."""
    wynik = splaszcz_wynik(json.loads(
        (DEV / "wynik_umowa_deweloperska.json").read_text(encoding="utf-8")))
    ocr = dodaj_markery_stron((DEV / "ocr_umowa_demo_skan.txt").read_text(encoding="utf-8"))

    zrodla = zweryfikuj_zrodla(ocr, wynik["zrodla"])

    statusy = {pole: z["status"] for pole, z in zrodla.items()}
    assert "niepotwierdzone" not in statusy.values()
    assert [p for p, s in statusy.items() if s == "inna_strona"] == ["termin_odrebnej_wlasnosci"]

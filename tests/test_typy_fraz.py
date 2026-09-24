"""Szukanie po typie frazy: data, kwota i identyfikator w każdym zapisie."""

import pytest

from app import (
    klucz_identyfikatora,
    rozpoznaj_typ_frazy,
    szukaj_identyfikatora_w_ocr,
    szukaj_w_ocr_z_wariantami,
    warianty_do_szukania,
)

OCR = (
    "[STRONA_1]\nUmowa zawarta dnia 22 marca 2000 r. Nabywca Jan Kowalski, "
    "PESEL 85010112345, zamieszkały w Warszawie. Księga wieczysta WA1M/00012345/6."
    "\n[STRONA_2]\nKW nr WA1M 00012345 6. Data 22.03.2000. Rachunek powierniczy "
    "61 1090 1014 0000 0712 1981 2874. NIP 123-456-32-18. Lokal nr 20A."
)


@pytest.mark.parametrize("fraza, typ", [
    ("2000-03-22", "data"),
    ("22 marca 2000", "data"),
    ("450 000,00 zł", "kwota"),
    ("85010112345", "identyfikator"),
    ("WA1M/00012345/6", "identyfikator"),
    ("PL61 1090 1014 0000 0712 1981 2874", "identyfikator"),
    ("123-456-32-18", "identyfikator"),
    ("Jan Kowalski", "tekst"),
    ("20A", "tekst"),
    ("12/3", "tekst"),
    ("Repertorium A Nr 1234/2026", "tekst"),
])
def test_rozpoznaj_typ_frazy(fraza, typ):
    assert rozpoznaj_typ_frazy(fraza) == typ


def test_klucz_identyfikatora_ignoruje_separatory_i_wielkosc_liter():
    assert klucz_identyfikatora("WA1M/00012345/6") == klucz_identyfikatora("wa1m 00012345 6")
    assert klucz_identyfikatora("123-456-32-18") == "1234563218"


def szukaj(fraza):
    zapisy = [{"fraza": fraza, "rodzaj": "szukana"}]
    return [(t["strona"], t["trafienie"]) for t in szukaj_w_ocr_z_wariantami(OCR, zapisy)]


def test_data_od_roku_znajduje_kazdy_zapis():
    assert szukaj("2000-03-22") == [(1, "22 marca 2000"), (2, "22.03.2000")]


def test_data_w_innym_zapisie_znajduje_date_od_roku():
    ocr = "[STRONA_1]\nTermin 2027-09-30."
    trafienia = szukaj_w_ocr_z_wariantami(ocr, [{"fraza": "30 września 2027", "rodzaj": "szukana"}])
    assert [t["trafienie"] for t in trafienia] == ["2027-09-30"]


def test_ksiega_wieczysta_w_kazdym_ukladzie_separatorow():
    oczekiwane = [(1, "WA1M/00012345/6"), (2, "WA1M 00012345 6")]
    assert szukaj("WA1M/00012345/6") == oczekiwane
    assert szukaj("wa1m-00012345-6") == oczekiwane


def test_rachunek_zapisany_ciagiem_znajduje_zapis_w_grupach():
    assert szukaj("61109010140000071219812874") == [(2, "61 1090 1014 0000 0712 1981 2874")]


def test_nip_bez_myslnikow():
    assert szukaj("1234563218") == [(2, "123-456-32-18")]


def test_pesel_nie_trafia_w_srodek_numeru_rachunku():
    # 10901014000 to cyfry z wnętrza rachunku — to nie jest PESEL z dokumentu
    assert szukaj_identyfikatora_w_ocr(OCR, "10901014000") == []
    assert szukaj("85010112345") == [(1, "85010112345")]


def test_pesel_nie_trafia_w_dluzszy_ciag_cyfr():
    assert szukaj_identyfikatora_w_ocr("[STRONA_1]\nnr 8501011234599", "85010112345") == []


def test_blad_ocr_dalej_szukany_doslownie():
    # "O" zamiast zera: identyfikator szukany jak jest napisany — trafia tylko zapis z błędem
    ocr = "[STRONA_1]\nKW WA1M/0OO12345/6 oraz WA1M/00012345/6"
    trafienia = szukaj_w_ocr_z_wariantami(ocr, [{"fraza": "WA1M/0OO12345/6", "rodzaj": "zla"}])
    assert [t["trafienie"] for t in trafienia] == ["WA1M/0OO12345/6"]


def test_wartosci_niezgodne_dalej_oznaczone_przy_zmienionym_formacie():
    ocr = "[STRONA_1]\nzawarta 22 marca 2000\n[STRONA_2]\numowa z dnia 23/03/2000"
    potwierdzone = [{
        "pole": "data_umowy",
        "wartosc_glowna": "2000-03-22",
        "wartosci_ok": ["22 marca 2000"],
        "wartosci_zle": ["23/03/2000"],
        "uzasadnienie": "",
    }]
    trafienia = szukaj_w_ocr_z_wariantami(ocr, warianty_do_szukania("2000-03-22", potwierdzone))
    assert [(t["strona"], t["rodzaj"]) for t in trafienia] == [(1, "glowna"), (2, "zla")]

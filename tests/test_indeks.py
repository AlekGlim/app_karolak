import pytest

from app import (
    pierwsze_do_pokazania,
    strony_z_ocr,
    zloz_strony,
    znajdz_w_stronach,
)
from app import kwota_z_frazy
from app import szukaj_w_ocr_z_wariantami


def test_strony_z_ocr_bez_markerow_w_tekscie():
    strony = strony_z_ocr("\n\n[STRONA_1]\nPierwsza\n\n[STRONA_2]\nDruga")
    assert sorted(strony) == [1, 2]
    assert "STRONA" not in strony[2]["tekst"]
    assert strony_z_ocr("") == {}


def test_zloz_strony_uzupelnia_strony_bez_tekstu():
    strony = zloz_strony(strony_z_ocr("[STRONA_1]\nocr 1[STRONA_2]\nocr 2"), 3)

    assert [s["numer"] for s in strony] == [1, 2, 3]
    assert strony[1]["tekst"] == "\nocr 2"
    assert strony[2]["tekst"] == ""                  # strona 3 bez tekstu OCR


def test_trafienie_wskazuje_strone():
    strony = zloz_strony(strony_z_ocr("[STRONA_1]\nx[STRONA_2]\nCena 685.000,00 zł"), 2)
    trafienia = znajdz_w_stronach(strony, [{"fraza": "685 000,00 zł", "rodzaj": "szukana"}])

    assert [(t["strona"], t["trafienie"], t["rodzaj"]) for t in trafienia] == [
        (2, "685.000,00", "szukana"),
    ]


def test_pierwsze_do_pokazania_omija_wartosc_niezgodna():
    assert pierwsze_do_pokazania([{"rodzaj": "zla"}, {"rodzaj": "glowna"}]) == 1
    assert pierwsze_do_pokazania([{"rodzaj": "zla"}]) == 0
    assert pierwsze_do_pokazania([]) == 0


@pytest.mark.parametrize("fraza, grosze", [
    ("685 000,00 zł", 68_500_000),
    ("685.000", 68_500_000),
    ("35 000,00 PLN", 3_500_000),
    ("12,50", 1_250),
])
def test_kwota_z_frazy(fraza, grosze):
    assert kwota_z_frazy(fraza) == grosze


@pytest.mark.parametrize("fraza", ["2026", "89052112345", "12/5", "WA1M/00123456/7", "Puławskiej", None])
def test_fraza_niebedaca_kwota(fraza):
    assert kwota_z_frazy(fraza) is None


def test_szukanie_kwoty_w_kazdym_zapisie():
    tekst = "Cena 685.000,00 zł, zaliczka 685 000 zł, inna 1 685 000,00 zł."
    trafienia = szukaj_w_ocr_z_wariantami(tekst, [{"fraza": "685 000,00 zł", "rodzaj": "szukana"}])
    assert [t["trafienie"] for t in trafienia] == ["685.000,00", "685 000"]

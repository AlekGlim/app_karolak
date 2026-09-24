import pytest

from core.indeks import (
    pierwsze_do_pokazania,
    scal_w_linie,
    strona_ze_slow,
    strony_z_ocr,
    zloz_strony,
    znajdz_w_stronach,
)
from core.kwoty import kwota_z_frazy
from core.szukanie import szukaj_w_ocr_z_wariantami


def _slowo(tekst, x0, top, szerokosc=None):
    szerokosc = szerokosc or 6 * len(tekst)
    return {"text": tekst, "x0": x0, "x1": x0 + szerokosc, "top": top, "bottom": top + 10}


# dwie linie: "ul. Puławskiej 17B" / "w Warszawie"
SLOWA = [
    _slowo("ul.", 10, 100),
    _slowo("Puławskiej", 30, 100),
    _slowo("17B", 100, 100),
    _slowo("w", 10, 120),
    _slowo("Warszawie", 20, 120),
]


def test_strona_ze_slow_mapuje_znaki_na_slowa():
    strona = strona_ze_slow(1, SLOWA)
    assert strona["tekst"] == "ul. Puławskiej 17B w Warszawie "
    assert strona["mapa"][4] == 1
    assert strona["mapa"][3] is None


def test_trafienie_ma_prostokaty_po_jednym_na_linie():
    strona = strona_ze_slow(1, SLOWA)
    trafienia = znajdz_w_stronach([strona], [{"fraza": "17B w Warszawie", "rodzaj": "szukana"}])

    assert len(trafienia) == 1
    assert trafienia[0]["strona"] == 1
    assert trafienia[0]["rodzaj"] == "szukana"
    assert trafienia[0]["prostokaty"] == [
        {"x0": 100, "x1": 118, "top": 100, "bottom": 110},
        {"x0": 10, "x1": 74, "top": 120, "bottom": 130},
    ]


def test_scal_w_linie_pusto():
    assert scal_w_linie(SLOWA, set()) == []


def test_strony_z_ocr_bez_markerow_w_tekscie():
    strony = strony_z_ocr("\n\n[STRONA_1]\nPierwsza\n\n[STRONA_2]\nDruga")
    assert sorted(strony) == [1, 2]
    assert "STRONA" not in strony[2]["tekst"]
    assert strony[2]["mapa"] is None
    assert strony_z_ocr("") == {}


def test_zloz_strony_wybiera_zrodlo_per_strona():
    z_pdf = [strona_ze_slow(1, SLOWA), strona_ze_slow(2, [])]
    z_ocr = strony_z_ocr("[STRONA_1]\nocr 1[STRONA_2]\nocr 2")
    strony = zloz_strony(z_pdf, z_ocr, 3)

    assert strony[0]["slowa"]                       # strona 1 z warstwy tekstowej
    assert strony[1]["tekst"] == "\nocr 2"           # strona 2 to skan -> OCR
    assert strony[2]["tekst"] == ""                  # strona 3 bez żadnego tekstu


def test_trafienie_na_stronie_z_ocr_bez_prostokatow():
    strony = zloz_strony([], strony_z_ocr("[STRONA_1]\nx[STRONA_2]\nCena 685.000,00 zł"), 2)
    trafienia = znajdz_w_stronach(strony, [{"fraza": "685 000,00 zł", "rodzaj": "szukana"}])

    assert [(t["strona"], t["trafienie"], t["prostokaty"]) for t in trafienia] == [
        (2, "685.000,00", []),
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

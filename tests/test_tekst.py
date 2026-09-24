import pytest

from core.tekst import (
    dodaj_markery_stron,
    normalizuj_do_porownania,
    normalizuj_do_szukania,
    strona_dla_pozycji,
)


def test_szukanie_ignoruje_diakrytyki_i_wielkosc_liter():
    assert normalizuj_do_szukania("Września ŹDŹBŁO") == "wrzesnia zdzbło"


def test_porownanie_ignoruje_wielkosc_liter_i_uklad_spacji():
    assert normalizuj_do_porownania("  Jan \n  KOWALSKI ") == "jan kowalski"


def test_porownanie_zachowuje_diakrytyki():
    assert normalizuj_do_porownania("Łódź") != normalizuj_do_porownania("Lodz")


@pytest.mark.xfail(reason="Znany błąd: NFKD rozwija '…' i ligatury, przesuwając pozycje trafień")
def test_normalizacja_do_szukania_zachowuje_dlugosc_tekstu():
    tekst = "Umowa… ﬁrma № 5"
    assert len(normalizuj_do_szukania(tekst)) == len(tekst)


def test_markery_stron_dzielone_na_zescapowanym_znaczniku():
    ocr = "pierwsza&lt;!-- PageBreak --&gt;druga&lt;!--PageBreak--&gt;trzecia"
    wynik = dodaj_markery_stron(ocr)
    assert wynik == "\n\n[STRONA_1]\npierwsza\n\n[STRONA_2]\ndruga\n\n[STRONA_3]\ntrzecia"


def test_strona_dla_pozycji():
    tekst = "wstęp [STRONA_1] aaa [STRONA_2] bbb"
    assert strona_dla_pozycji(tekst, tekst.index("wstęp")) is None
    assert strona_dla_pozycji(tekst, tekst.index("aaa")) == 1
    assert strona_dla_pozycji(tekst, tekst.index("bbb")) == 2

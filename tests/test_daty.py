from datetime import date

import pytest

from app import parsuj_date, szukaj_daty_w_ocr, znajdz_daty


@pytest.mark.parametrize("tekst", [
    "22-03-2000", "22.03.2000", "22/03/2000", "22 . 03 . 2000",
    "22 marca 2000", "dnia 22 marca 2000 r.",
])
def test_rozne_zapisy_tej_samej_daty(tekst):
    assert parsuj_date(tekst) == date(2000, 3, 22)


def test_miesiac_slownie_z_diakrytykami():
    assert parsuj_date("30 września 2027") == date(2027, 9, 30)
    assert parsuj_date("1 października 2027") == date(2027, 10, 1)


def test_nieistniejaca_data_pomijana():
    assert znajdz_daty("31-02-2000") == []


def test_nie_lapie_daty_w_srodku_numeru():
    assert znajdz_daty("rachunek 1234-05-2000 oraz 01-01-20003") == []


def test_dwie_daty_to_brak_jednoznacznej():
    assert parsuj_date("od 22-03-2000 do 30-04-2000") is None
    assert parsuj_date("") is None


def test_szukaj_daty_w_ocr_zwraca_strone_i_kontekst():
    ocr = "[STRONA_1]\nwstęp\n[STRONA_2]\nzawarta 22 marca 2000 r. w Warszawie"
    trafienia = szukaj_daty_w_ocr(ocr, date(2000, 3, 22))
    assert len(trafienia) == 1
    assert trafienia[0]["strona"] == 2
    assert trafienia[0]["trafienie"] == "22 marca 2000"
    assert szukaj_daty_w_ocr(ocr, date(2000, 3, 23)) == []


@pytest.mark.parametrize("tekst", ["2000-03-22", "2000.03.22", "2000/03/22", "2000-3-22"])
def test_zapis_od_roku(tekst):
    assert parsuj_date(tekst) == date(2000, 3, 22)


def test_zapis_od_roku_wymaga_tych_samych_separatorow():
    assert znajdz_daty("2000-03.22") == []
    assert znajdz_daty("12000-03-22") == []
    assert znajdz_daty("2000-03-221") == []


def test_daty_w_obu_zapisach_posortowane_po_pozycji():
    daty = znajdz_daty("najpierw 2000-03-22, potem 23 marca 2000")
    assert [d["data"] for d in daty] == [date(2000, 3, 22), date(2000, 3, 23)]

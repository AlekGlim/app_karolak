from app import (
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


def test_normalizacja_do_szukania_zachowuje_dlugosc_tekstu():
    tekst = "Umowa… ﬁrma № 5 İ ½"
    assert len(normalizuj_do_szukania(tekst)) == len(tekst)


def test_trafienie_po_wielokropku_wskazuje_wlasciwy_fragment():
    from app import szukaj_w_ocr

    ocr = "[STRONA_1]\n" + "Uwaga… " * 50 + "[STRONA_2]\nJan Kowalski"
    trafienie = szukaj_w_ocr(ocr, "Jan Kowalski")[0]
    assert trafienie["trafienie"] == "Jan Kowalski"
    assert trafienie["strona"] == 2


def test_markery_stron_dzielone_na_zescapowanym_znaczniku():
    ocr = "pierwsza&lt;!-- PageBreak --&gt;druga&lt;!--PageBreak--&gt;trzecia"
    wynik = dodaj_markery_stron(ocr)
    assert wynik == "\n\n[STRONA_1]\npierwsza\n\n[STRONA_2]\ndruga\n\n[STRONA_3]\ntrzecia"


def test_strona_dla_pozycji():
    tekst = "wstęp [STRONA_1] aaa [STRONA_2] bbb"
    assert strona_dla_pozycji(tekst, tekst.index("wstęp")) is None
    assert strona_dla_pozycji(tekst, tekst.index("aaa")) == 1
    assert strona_dla_pozycji(tekst, tekst.index("bbb")) == 2


def test_tekst_do_wyswietlenia_tabela_i_encje_na_brzegach():
    from app import tekst_do_wyswietlenia

    fragment = (
        "t;21-03-2026&lt;/td&gt;&lt;/tr&gt;\n&lt;tr&gt;&lt;td&gt;2&lt;/td&gt;"
        "&lt;td&gt;216 000,00 zł&lt;/td&gt;&lt;td&gt;15.08.2026&l"
    )
    assert tekst_do_wyswietlenia(fragment).strip() == "21-03-2026 | 2 · 216 000,00 zł · 15.08.2026"


def test_tekst_do_wyswietlenia_komentarze_naglowki_i_przeciete_znaczniki():
    from app import tekst_do_wyswietlenia

    fragment = (
        'Header="Kancelaria" --&gt;\n\n# UMOWA DEWELOPERSKA\n\n'
        '§ 1. Deweloper :selected: oświadcza\n&lt;!-- PageNumber="1" --&gt;\ndalej &lt;!-- Page'
    )
    assert tekst_do_wyswietlenia(fragment).strip() == "UMOWA DEWELOPERSKA § 1. Deweloper oświadcza dalej"


def test_tekst_do_wyswietlenia_encje_zwyklego_tekstu():
    from app import tekst_do_wyswietlenia

    # endpoint zamienia < > & na encje także w zwykłym tekście
    assert tekst_do_wyswietlenia("cena 5 &lt; 6 oraz A &amp; B") == "cena 5 < 6 oraz A & B"

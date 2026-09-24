from core.szukanie import (
    strona_dla_kwoty,
    strona_dla_tokenu,
    strona_dla_wartosci,
    szukaj_w_ocr,
    szukaj_w_ocr_z_wariantami,
    warianty_do_szukania,
)

OCR = (
    "\n\n[STRONA_1]\nAkt notarialny z dnia 22 marca 2026 r. zawarty w Warszawie. "
    "Nabywca: Jan Kowalski. Cena 450.000,00 zł."
    "\n\n[STRONA_2]\nData 22-03-2026. Jana Kowalskiego. Nowak jako nabywca. "
    "Miejsce postojowe A30 oraz A3. Termin: 30 września 2027."
)

POTWIERDZONE = [{
    "pole": "nabywca_1",
    "wartosc_glowna": "Jan Kowalski",
    "wartosci_ok": ["Jana Kowalskiego"],
    "wartosci_zle": ["Nowak"],
    "uzasadnienie": "",
}]


def test_szukanie_bez_wielkosci_liter_i_diakrytykow():
    trafienia = szukaj_w_ocr(OCR, "WRZESNIA")
    assert [t["strona"] for t in trafienia] == [2]
    assert trafienia[0]["trafienie"] == "września"
    assert trafienia[0]["dokladne"] is True


def test_odmiana_jako_zapas_gdy_brak_trafienia_doslownego():
    trafienia = szukaj_w_ocr(OCR, "Warszawa")
    assert len(trafienia) == 1
    assert trafienia[0]["trafienie"] == "Warszawie"
    assert trafienia[0]["dokladne"] is False


def test_kontekst_trafienia():
    t = szukaj_w_ocr(OCR, "Jan Kowalski")[0]
    assert t["przed"].endswith("Nabywca: ")
    assert t["po"].startswith(". Cena")


def test_pusta_fraza_lub_tekst():
    assert szukaj_w_ocr(OCR, "  ") == []
    assert szukaj_w_ocr("", "Jan") == []


def test_warianty_dla_frazy_z_rozbieznosci():
    zapisy = warianty_do_szukania("jana kowalskiego", POTWIERDZONE)
    assert zapisy == [
        {"fraza": "Jan Kowalski", "rodzaj": "glowna"},
        {"fraza": "Jana Kowalskiego", "rodzaj": "ok"},
        {"fraza": "Nowak", "rodzaj": "zla"},
    ]


def test_warianty_dla_zwyklej_frazy():
    assert warianty_do_szukania("cena", POTWIERDZONE) == [{"fraza": "cena", "rodzaj": "szukana"}]
    assert warianty_do_szukania("cena", None) == [{"fraza": "cena", "rodzaj": "szukana"}]


def test_szukanie_z_wariantami_oznacza_rodzaj_i_sortuje():
    zapisy = warianty_do_szukania("Jan Kowalski", POTWIERDZONE)
    trafienia = szukaj_w_ocr_z_wariantami(OCR, zapisy)
    assert [(t["trafienie"], t["rodzaj"]) for t in trafienia] == [
        ("Jan Kowalski", "glowna"),
        ("Jana Kowalskiego", "ok"),
        ("Nowak", "zla"),
    ]


def test_fraza_data_znajduje_kazdy_zapis():
    trafienia = szukaj_w_ocr_z_wariantami(OCR, [{"fraza": "22-03-2026", "rodzaj": "szukana"}])
    assert [(t["trafienie"], t["strona"]) for t in trafienia] == [
        ("22 marca 2026", 1),
        ("22-03-2026", 2),
    ]


def test_strona_dla_wartosci_data_w_innym_zapisie():
    assert strona_dla_wartosci(OCR, "30-09-2027", rodzaj="data") == 2


def test_strona_dla_wartosci_kwota_w_innym_zapisie():
    assert strona_dla_wartosci(OCR, "450 000,00 zł", rodzaj="kwota") == 1


def test_strona_dla_wartosci_omija_wartosc_niezgodna():
    ocr = "[STRONA_1]\nNowak jako nabywca.\n[STRONA_2]\nNabywca Jan Kowalski."
    assert strona_dla_wartosci(ocr, "Jan Kowalski", POTWIERDZONE) == 2


def test_strona_dla_wartosci_brak():
    assert strona_dla_wartosci(OCR, "Gdańsk") is None


def test_strona_dla_kwoty_ktore_trafienie():
    ocr = "[STRONA_1]\n100 000,00 zł\n[STRONA_2]\n100.000 zł"
    assert strona_dla_kwoty(ocr, "100 000 zł") == 1
    assert strona_dla_kwoty(ocr, "100 000 zł", ktora=1) == 2
    assert strona_dla_kwoty(ocr, "100 000 zł", ktora=5) == 2
    assert strona_dla_kwoty(ocr, "nie kwota") is None


def test_strona_dla_tokenu_jako_osobne_slowo():
    ocr = "[STRONA_1]\nlokal A30\n[STRONA_2]\nmiejsce A3."
    assert strona_dla_tokenu(ocr, "A3") == 2
    assert strona_dla_tokenu(ocr, "B7") is None


def test_fraza_lamana_na_koncu_linii_to_trafienie_dokladne():
    ocr = "[STRONA_1]\nprowadzi księgę\nwieczystą nr WA1M/00123456/7"
    trafienia = szukaj_w_ocr(ocr, "prowadzi księgę wieczystą")
    assert [(t["trafienie"], t["dokladne"]) for t in trafienia] == [("prowadzi księgę\nwieczystą", True)]

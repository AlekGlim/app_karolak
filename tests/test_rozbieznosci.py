from app import wariant_stoi_w_tekscie, zweryfikuj_warianty

OCR = "Umowa nr 123/2026. W innym miejscu I23/2026. Nabywca Jan Kowalski, Kowalskiemu."


def _wpis(**kwargs):
    wpis = {"pole": "numer_umowy", "wartosc_glowna": "123/2026",
            "wartosci_ok": [], "wartosci_zle": [], "uzasadnienie": ""}
    wpis.update(kwargs)
    return wpis


def test_wariant_jako_osobny_token():
    assert wariant_stoi_w_tekscie("numer 123 i", "123")
    assert not wariant_stoi_w_tekscie("numer 1234 i", "123")
    assert not wariant_stoi_w_tekscie("numer a123 i", "123")
    assert not wariant_stoi_w_tekscie("cokolwiek", "")


def test_potwierdzona_zla_wartosc():
    potwierdzone, odrzucone = zweryfikuj_warianty(OCR, [_wpis(wartosci_zle=["I23/2026"])])
    assert potwierdzone == [_wpis(wartosci_zle=["I23/2026"])]
    assert odrzucone == []


def test_zmyslona_wartosc_odrzucona_a_wpis_znika():
    potwierdzone, odrzucone = zweryfikuj_warianty(OCR, [_wpis(wartosci_zle=["999/2026"])])
    assert potwierdzone == []
    assert odrzucone == [{"pole": "numer_umowy", "wartosc": "999/2026"}]


def test_wartosc_w_obu_listach_zostaje_zla():
    potwierdzone, _ = zweryfikuj_warianty(
        OCR, [_wpis(wartosci_ok=["I23/2026"], wartosci_zle=["I23/2026"])]
    )
    assert potwierdzone[0]["wartosci_ok"] == []
    assert potwierdzone[0]["wartosci_zle"] == ["I23/2026"]


def test_powtorzenie_wartosci_glownej_pomijane_po_cichu():
    potwierdzone, odrzucone = zweryfikuj_warianty(
        OCR, [_wpis(wartosci_ok=["123/2026 "], wartosci_zle=["I23/2026"])]
    )
    assert potwierdzone[0]["wartosci_ok"] == []
    assert odrzucone == []


def test_napis_zamiast_listy():
    potwierdzone, _ = zweryfikuj_warianty(
        OCR, [_wpis(pole="nabywca_1", wartosc_glowna="Jan Kowalski", wartosci_ok="Kowalskiemu")]
    )
    assert potwierdzone[0]["wartosci_ok"] == ["Kowalskiemu"]


def test_brak_tekstu_lub_zly_format():
    assert zweryfikuj_warianty("", [_wpis(wartosci_zle=["I23/2026"])]) == ([], [])
    assert zweryfikuj_warianty(OCR, None) == ([], [])
    assert zweryfikuj_warianty(OCR, ["nie słownik"]) == ([], [])

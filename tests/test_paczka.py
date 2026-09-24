"""Paczka .txt do wysłania mailem: pakowanie i odtworzenie projektu."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "narzedzia"))
from pakuj_do_txt import KATALOG_PROJEKTU, pliki_projektu, spakuj  # noqa: E402
from rozpakuj import odtworz  # noqa: E402


def _porownaj_z_projektem(katalog):
    for wzgledna in pliki_projektu(KATALOG_PROJEKTU):
        assert (katalog / wzgledna).read_bytes() == (KATALOG_PROJEKTU / wzgledna).read_bytes(), wzgledna


@pytest.mark.parametrize("jeden_plik", [False, True])
def test_pelny_obieg_odtwarza_projekt_bajt_w_bajt(tmp_path, jeden_plik):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka", jeden_plik=jeden_plik)

    # w paczce są wyłącznie pliki .txt i żaden nie jest ukryty
    assert all(p.suffix == ".txt" for p in paczka.iterdir())
    assert not any(p.name.startswith(".") for p in paczka.iterdir())

    assert odtworz(paczka, tmp_path / "projekt") == []
    _porownaj_z_projektem(tmp_path / "projekt")


def test_pdf_jako_base64_a_kod_jako_czytelny_tekst(tmp_path):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka")
    manifest = json.loads((paczka / "MANIFEST.txt").read_text(encoding="utf-8"))
    kodowanie = {w["sciezka"]: w["kodowanie"] for w in manifest["pliki"]}

    assert kodowanie["dev/umowa_demo_skan.pdf"] == "base64"
    assert kodowanie["core/szukanie.py"] == "utf-8"
    assert "def szukaj_w_ocr(" in (paczka / "core--szukanie.py.txt").read_text(encoding="utf-8")


def test_sekrety_i_moduly_serwerowe_nie_trafiaja_do_paczki(tmp_path):
    projekt = tmp_path / "projekt"
    (projekt / "impala_connector").mkdir(parents=True)
    for nazwa in ("app.py", "token.txt", "config.py", "helpers.py", "ca.pem", "impala_connector/x.py"):
        (projekt / nazwa).write_text("x\n", encoding="utf-8")

    assert [p.as_posix() for p in pliki_projektu(projekt)] == ["app.py"]


def test_poczta_zamienila_konce_linii_i_dodala_bom(tmp_path):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka")

    for plik in paczka.iterdir():
        tekst = plik.read_text(encoding="utf-8")
        plik.write_bytes(("﻿" + tekst).replace("\n", "\r\n").encode("utf-8"))

    assert odtworz(paczka, tmp_path / "projekt") == []
    _porownaj_z_projektem(tmp_path / "projekt")


def test_brak_zalacznika_nic_nie_zapisuje(tmp_path):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka")
    (paczka / "app.py.txt").unlink()

    problemy = odtworz(paczka, tmp_path / "projekt")

    assert problemy == ["app.py: brak załącznika app.py.txt"]
    assert not (tmp_path / "projekt").exists()


def test_zmieniona_tresc_wykryta_suma_kontrolna(tmp_path):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka")
    plik = paczka / "ustawienia.py.txt"
    plik.write_text(plik.read_text(encoding="utf-8").replace("180", "18"), encoding="utf-8")

    problemy = odtworz(paczka, tmp_path / "projekt")
    assert len(problemy) == 1 and "suma kontrolna" in problemy[0]


def test_nie_nadpisuje_zmienionego_projektu_bez_flagi(tmp_path):
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka")
    cel = tmp_path / "projekt"
    assert odtworz(paczka, cel) == []

    (cel / "app.py").write_text("moje zmiany\n", encoding="utf-8")
    assert "app.py: plik już istnieje i jest inny (użyj --nadpisz)" in odtworz(paczka, cel)
    assert (cel / "app.py").read_text(encoding="utf-8") == "moje zmiany\n"

    assert odtworz(paczka, cel, nadpisz=True) == []
    _porownaj_z_projektem(cel)


def test_rozpakowanie_przez_python_ROZPAKUJ_py_txt(tmp_path):
    """Dokładnie tak, jak zrobi to odbiorca maila: plik .txt uruchomiony Pythonem."""
    paczka = spakuj(katalog_wyjsciowy=tmp_path / "paczka", jeden_plik=True)

    wynik = subprocess.run(
        [sys.executable, "ROZPAKUJ.py.txt"],
        cwd=paczka, capture_output=True, text=True, encoding="utf-8",
    )

    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert "Odtworzono" in wynik.stdout
    _porownaj_z_projektem(tmp_path / "hipoteka_ai")


def test_nie_usuwa_obcego_katalogu(tmp_path):
    obcy = tmp_path / "moje_dokumenty"
    obcy.mkdir()
    (obcy / "wazne.docx").write_text("x", encoding="utf-8")

    with pytest.raises(SystemExit):
        spakuj(katalog_wyjsciowy=obcy)
    assert (obcy / "wazne.docx").exists()

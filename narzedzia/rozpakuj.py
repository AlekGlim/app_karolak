"""Odtwarza projekt z paczki plików .txt (wysłanej mailem).

Ten plik jedzie w paczce jako ROZPAKUJ.py.txt. Nie trzeba zmieniać mu
nazwy — Python uruchamia plik niezależnie od rozszerzenia:

    python ROZPAKUJ.py.txt                    # do katalogu hipoteka_ai obok paczki
    python ROZPAKUJ.py.txt C:\\projekty\\hipoteka
    python ROZPAKUJ.py.txt cel --nadpisz      # nadpisz pliki, które się różnią

Wszystkie załączniki z maila zapisz w jednym katalogu razem z tym plikiem.
Paczka zawiera MANIFEST.txt z listą plików i ich sumami SHA-256. Każdy plik
jest sprawdzany po odtworzeniu, więc zgubiony albo zmieniony przez pocztę
załącznik zostanie wykryty, zanim aplikacja zacznie dziwnie działać.

Tylko biblioteka standardowa — działa na czystym Pythonie 3.8+.
"""

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

MANIFEST = "MANIFEST.txt"
JEDEN_PLIK = "PACZKA_CALOSC.txt"
ZNACZNIK_POCZATKU = "=====[ HIPOTEKA-AI PLIK: {} ]====="
ZNACZNIK_KONCA = "=====[ HIPOTEKA-AI KONIEC: {} ]====="


def _tekst_bez_zmian_poczty(tekst):
    """Cofa to, co po drodze robią poczta i edytory: CRLF i znacznik BOM.

    Pliki projektu mają końce linii LF i nie mają BOM — po tej normalizacji
    suma kontrolna musi się zgadzać.
    """
    return tekst.lstrip("\ufeff").replace("\r\n", "\n")


def _czytaj_zalaczniki(katalog):
    """{nazwa pliku .txt: treść} z PACZKA_CALOSC.txt albo None (paczka z osobnych plików)."""
    calosc = katalog / JEDEN_PLIK
    if not calosc.exists():
        return None

    tresc = _tekst_bez_zmian_poczty(calosc.read_text(encoding="utf-8"))

    # znacznik końca powtarza nazwę pliku (\1), więc sekcja kończy się zawsze
    # na własnym znaczniku, nawet gdyby treść zawierała podobny tekst
    wzor = re.compile(
        re.escape(ZNACZNIK_POCZATKU).replace(r"\{\}", "(.+?)") + "\n"
        + r"(.*?)\n"
        + re.escape(ZNACZNIK_KONCA).replace(r"\{\}", r"\1") + "\n",
        re.DOTALL,
    )
    return {nazwa: tekst for nazwa, tekst in wzor.findall(tresc)}


def odtworz(katalog_paczki, katalog_docelowy, nadpisz=False):
    """Odtwarza pliki. Zwraca listę problemów (pusta = wszystko w porządku)."""
    katalog_paczki = Path(katalog_paczki)
    katalog_docelowy = Path(katalog_docelowy)

    sciezka_manifestu = katalog_paczki / MANIFEST
    if not sciezka_manifestu.exists():
        return [f"Brak {MANIFEST} w {katalog_paczki} — to nie jest katalog z paczką."]

    manifest = json.loads(_tekst_bez_zmian_poczty(sciezka_manifestu.read_text(encoding="utf-8")))
    zalaczniki = _czytaj_zalaczniki(katalog_paczki)

    # najpierw sprawdzamy całą paczkę, dopiero potem cokolwiek zapisujemy —
    # niekompletna paczka nie może zostawić połowicznie nadpisanego projektu
    gotowe, problemy = [], []

    for wpis in manifest["pliki"]:
        sciezka = wpis["sciezka"]

        if ".." in Path(sciezka).parts or Path(sciezka).is_absolute():
            problemy.append(f"{sciezka}: niedozwolona ścieżka w manifeście")
            continue

        if zalaczniki is not None:
            tekst = zalaczniki.get(wpis["plik_txt"])
        else:
            plik_txt = katalog_paczki / wpis["plik_txt"]
            tekst = (
                _tekst_bez_zmian_poczty(plik_txt.read_text(encoding="utf-8"))
                if plik_txt.exists()
                else None
            )

        if tekst is None:
            problemy.append(f"{sciezka}: brak załącznika {wpis['plik_txt']}")
            continue

        try:
            if wpis["kodowanie"] == "base64":
                dane = base64.b64decode("".join(tekst.split()), validate=True)
            else:
                dane = tekst.encode("utf-8")
        except ValueError as blad:
            problemy.append(f"{sciezka}: uszkodzony załącznik ({blad})")
            continue

        if hashlib.sha256(dane).hexdigest() != wpis["sha256"]:
            problemy.append(
                f"{sciezka}: suma kontrolna się nie zgadza — załącznik "
                f"{wpis['plik_txt']} zmienił się po drodze"
            )
            continue

        cel = katalog_docelowy / sciezka
        if cel.exists() and cel.read_bytes() != dane and not nadpisz:
            problemy.append(f"{sciezka}: plik już istnieje i jest inny (użyj --nadpisz)")
            continue

        gotowe.append((cel, dane))

    if problemy:
        return problemy

    for cel, dane in gotowe:
        cel.parent.mkdir(parents=True, exist_ok=True)
        cel.write_bytes(dane)

    return []


def main(argumenty=None):
    parser = argparse.ArgumentParser(description="Odtwarza projekt Hipoteka AI z paczki .txt.")
    parser.add_argument(
        "cel", nargs="?", default=None,
        help="katalog docelowy (domyślnie: hipoteka_ai obok paczki)",
    )
    parser.add_argument("--paczka", default=None, help="katalog z plikami .txt (domyślnie: katalog tego pliku)")
    parser.add_argument("--nadpisz", action="store_true", help="nadpisz istniejące pliki, które się różnią")
    args = parser.parse_args(argumenty)

    katalog_paczki = Path(args.paczka) if args.paczka else Path(__file__).resolve().parent
    katalog_docelowy = Path(args.cel) if args.cel else katalog_paczki.parent / "hipoteka_ai"

    problemy = odtworz(katalog_paczki, katalog_docelowy, nadpisz=args.nadpisz)

    if problemy:
        print("Nic nie zostało zapisane. Problemy:")
        for problem in problemy:
            print(f"  - {problem}")
        return 1

    manifest = json.loads(_tekst_bez_zmian_poczty((katalog_paczki / MANIFEST).read_text(encoding="utf-8")))
    print(f"Odtworzono {len(manifest['pliki'])} plików w: {katalog_docelowy.resolve()}")
    print()
    print("Dalej:")
    print(f"  cd {katalog_docelowy}")
    print("  pip install -r requirements.txt")
    print("  streamlit run app.py                     # serwer z hurtownią")
    print("  HIPOTEKA_OFFLINE=1 streamlit run app.py  # lokalnie, bez hurtowni (Windows: patrz docs/INSTRUKCJA.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

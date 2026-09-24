"""Pakuje projekt do plików .txt — do wysłania mailem tam, gdzie przechodzi tylko .txt.

Uruchomienie z katalogu projektu:

    python narzedzia/pakuj_do_txt.py              # osobny .txt na każdy plik
    python narzedzia/pakuj_do_txt.py --jeden-plik # wszystko w jednym PACZKA_CALOSC.txt

Wynik trafia do katalogu paczka_wysylka/ (poprzednia zawartość jest usuwana):

    00_PRZECZYTAJ.txt     instrukcja dla odbiorcy
    ROZPAKUJ.py.txt       skrypt odtwarzający projekt (python ROZPAKUJ.py.txt)
    MANIFEST.txt          lista plików, ich ścieżek i sum SHA-256
    app.py.txt, core--szukanie.py.txt, ...   pliki projektu
    dev--umowa_demo.pdf.base64.txt           pliki binarne jako base64

W nazwach "--" zastępuje "/", a "_" kropkę na początku nazwy (.gitignore ->
_gitignore.txt); prawdziwą ścieżkę zna MANIFEST.txt.

Do paczki NIE trafiają: token.txt, certyfikaty *.pem, moduły serwerowe hurtowni
(config.py, helpers.py, impala_connector/), katalogi .git, cache i sama paczka.
"""

import argparse
import base64
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

KATALOG_PROJEKTU = Path(__file__).resolve().parent.parent
KATALOG_PACZKI = "paczka_wysylka"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rozpakuj import JEDEN_PLIK, MANIFEST, ZNACZNIK_KONCA, ZNACZNIK_POCZATKU  # noqa: E402

# Katalogi i pliki pomijane w całości.
POMIJANE_KATALOGI = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", ".ipynb_checkpoints",
    ".streamlit", "impala_connector", KATALOG_PACZKI,
}
POMIJANE_PLIKI = {
    "token.txt",      # sekret
    "config.py",      # parametry połączenia z hurtownią — zostają na serwerze
    "helpers.py",     # moduł serwerowy
    ".DS_Store",
}
POMIJANE_ROZSZERZENIA = {".pem", ".key", ".pyc", ".log"}

INSTRUKCJA = """\
HIPOTEKA AI — PACZKA DO ODTWORZENIA PROJEKTU
Utworzono: {data} · plików: {liczba} · tryb: {tryb}

1. Zapisz WSZYSTKIE załączniki z maila w jednym, pustym katalogu.
   (Nie zmieniaj ich nazw ani treści.)

2. W tym katalogu uruchom:

       python ROZPAKUJ.py.txt

   Projekt zostanie odtworzony w katalogu "hipoteka_ai" obok katalogu paczki.
   Inny katalog docelowy: python ROZPAKUJ.py.txt C:\\sciezka\\do\\projektu
   Nadpisanie istniejącego projektu: python ROZPAKUJ.py.txt <katalog> --nadpisz

   Skrypt sprawdza sumę kontrolną każdego pliku. Jeśli czegoś brakuje albo
   poczta coś zmieniła, wypisze które pliki i NIC nie zapisze.

3. W odtworzonym katalogu:

       pip install -r requirements.txt
       streamlit run app.py

   Lokalnie, bez hurtowni (tryb offline):
       Windows PowerShell:  $env:HIPOTEKA_OFFLINE="1"; streamlit run app.py
       Windows cmd:         set HIPOTEKA_OFFLINE=1 && streamlit run app.py
       Linux / macOS:       HIPOTEKA_OFFLINE=1 streamlit run app.py

W paczce NIE MA (trzeba mieć na miejscu): token.txt, certyfikatu ca.pem,
modułów serwerowych config.py, helpers.py, impala_connector/.
Pełna instrukcja: docs/INSTRUKCJA.md w odtworzonym projekcie.
"""


def pliki_projektu(katalog):
    """Ścieżki względne plików do spakowania, posortowane."""
    wynik = []

    for sciezka in sorted(katalog.rglob("*")):
        wzgledna = sciezka.relative_to(katalog)

        if any(czesc in POMIJANE_KATALOGI for czesc in wzgledna.parts):
            continue
        if not sciezka.is_file():
            continue
        if sciezka.name in POMIJANE_PLIKI or sciezka.suffix.lower() in POMIJANE_ROZSZERZENIA:
            continue

        wynik.append(wzgledna)

    return wynik


def jako_tekst(dane):
    """Treść pliku jako tekst albo None, jeśli plik trzeba zakodować base64.

    Tekstem jedzie tylko czysty UTF-8 bez NUL, CR i BOM — takiego pliku
    poczta nie zepsuje w sposób, którego rozpakowanie nie umiałoby cofnąć.
    """
    if b"\x00" in dane or b"\r" in dane or dane.startswith(b"\xef\xbb\xbf"):
        return None
    try:
        return dane.decode("utf-8")
    except UnicodeDecodeError:
        return None


def nazwa_txt(wzgledna, base64_):
    """Nazwa załącznika: "/" -> "--", kropka na początku -> "_".

    Plik zaczynający się od kropki (.gitignore) jest ukryty — gubi go zwykłe
    kopiowanie, Eksplorator Windows i część programów pocztowych. Prawdziwą
    nazwę i tak zna MANIFEST.txt.
    """
    czesci = ["_" + czesc[1:] if czesc.startswith(".") else czesc for czesc in wzgledna.parts]
    nazwa = "--".join(czesci)
    return f"{nazwa}.base64.txt" if base64_ else f"{nazwa}.txt"


def spakuj(katalog_projektu=KATALOG_PROJEKTU, katalog_wyjsciowy=None, jeden_plik=False):
    """Tworzy paczkę. Zwraca ścieżkę katalogu paczki."""
    katalog_projektu = Path(katalog_projektu)
    wyjscie = Path(katalog_wyjsciowy) if katalog_wyjsciowy else katalog_projektu / KATALOG_PACZKI

    # usuwamy tylko to, co wygląda na naszą paczkę — nie cudzy katalog
    if wyjscie.exists():
        if any(wyjscie.iterdir()) and not (wyjscie / MANIFEST).exists():
            raise SystemExit(f"{wyjscie} istnieje i nie wygląda na paczkę — nie usuwam go.")
        shutil.rmtree(wyjscie)
    wyjscie.mkdir(parents=True)

    wpisy, zalaczniki = [], {}

    for wzgledna in pliki_projektu(katalog_projektu):
        dane = (katalog_projektu / wzgledna).read_bytes()
        tekst = jako_tekst(dane)

        if tekst is None:
            b64 = base64.b64encode(dane).decode("ascii")
            tekst = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76)) + "\n"
            kodowanie = "base64"
        else:
            kodowanie = "utf-8"

        nazwa = nazwa_txt(wzgledna, kodowanie == "base64")
        zalaczniki[nazwa] = tekst
        wpisy.append({
            "sciezka": wzgledna.as_posix(),
            "plik_txt": nazwa,
            "kodowanie": kodowanie,
            "rozmiar": len(dane),
            "sha256": hashlib.sha256(dane).hexdigest(),
        })

    if jeden_plik:
        czesci = []
        for nazwa, tekst in zalaczniki.items():
            czesci.append(ZNACZNIK_POCZATKU.format(nazwa) + "\n" + tekst + "\n" + ZNACZNIK_KONCA.format(nazwa) + "\n")
        (wyjscie / JEDEN_PLIK).write_text("".join(czesci), encoding="utf-8", newline="\n")
    else:
        for nazwa, tekst in zalaczniki.items():
            (wyjscie / nazwa).write_text(tekst, encoding="utf-8", newline="\n")

    manifest = {
        "projekt": "hipoteka_ai",
        "utworzono": datetime.now().isoformat(timespec="seconds"),
        "tryb": "jeden_plik" if jeden_plik else "osobne_pliki",
        "pliki": wpisy,
    }
    (wyjscie / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    shutil.copyfile(Path(__file__).resolve().parent / "rozpakuj.py", wyjscie / "ROZPAKUJ.py.txt")

    (wyjscie / "00_PRZECZYTAJ.txt").write_text(
        INSTRUKCJA.format(
            data=manifest["utworzono"].replace("T", " "),
            liczba=len(wpisy),
            tryb="jeden plik z całością" if jeden_plik else "osobny plik .txt na każdy plik projektu",
        ),
        encoding="utf-8",
        newline="\n",
    )

    return wyjscie


def main(argumenty=None):
    parser = argparse.ArgumentParser(description="Pakuje projekt do plików .txt do wysłania mailem.")
    parser.add_argument("--jeden-plik", action="store_true", help="wszystkie pliki w jednym PACZKA_CALOSC.txt")
    parser.add_argument("--wyjscie", default=None, help=f"katalog paczki (domyślnie: {KATALOG_PACZKI}/)")
    args = parser.parse_args(argumenty)

    wyjscie = spakuj(katalog_wyjsciowy=args.wyjscie, jeden_plik=args.jeden_plik)

    pliki = sorted(p for p in wyjscie.iterdir() if p.is_file())
    rozmiar = sum(p.stat().st_size for p in pliki)
    manifest = json.loads((wyjscie / MANIFEST).read_text(encoding="utf-8"))

    print(f"Paczka: {wyjscie}")
    print(f"Plików projektu: {len(manifest['pliki'])} · załączników do wysłania: {len(pliki)} "
          f"· razem {rozmiar / 1024:.0f} KB")
    print("Wyślij WSZYSTKIE pliki z tego katalogu. Instrukcja dla odbiorcy: 00_PRZECZYTAJ.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

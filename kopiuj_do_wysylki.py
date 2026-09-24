"""Kopiuje pliki potrzebne do działania aplikacji do katalogu paczka_wysylka/
i dopisuje każdemu rozszerzenie .txt (app.py -> app.py.txt).

Uruchomienie z katalogu projektu:

    python kopiuj_do_wysylki.py

Struktura katalogów zostaje zachowana (schemy/umowa_deweloperska.json -> paczka_wysylka/schemy/umowa_deweloperska.json.txt).
Na drugim komputerze wystarczy odtworzyć te same katalogi i usunąć końcówkę .txt
z nazw — patrz docs/INSTRUKCJA.md, "Przeniesienie projektu na inny komputer".

Listę kopiowanych plików i katalogów zmienia się w WYMAGANE poniżej.
"""

import shutil
from pathlib import Path

KATALOG_PROJEKTU = Path(__file__).resolve().parent
KATALOG_PACZKI = KATALOG_PROJEKTU / "paczka_wysylka"

# Pliki i katalogi potrzebne do uruchomienia aplikacji.
WYMAGANE = [
    "app.py",
    "data_loader.py",
    "schemy",
    "requirements.txt",
    "README.md",
    "docs",
    "dev",       # dane trybu offline — potrzebne tylko do pracy lokalnej
    # "tests", "pytest.ini", "requirements-dev.txt",   # odkomentuj, żeby wysłać też testy
]

# Nigdy nie kopiujemy: cache Pythona, sekretów.
POMIJANE = {"__pycache__", "token.txt"}


def main():
    if KATALOG_PACZKI.exists():
        shutil.rmtree(KATALOG_PACZKI)

    skopiowane = 0

    for wpis in WYMAGANE:
        zrodlo = KATALOG_PROJEKTU / wpis
        pliki = [zrodlo] if zrodlo.is_file() else sorted(p for p in zrodlo.rglob("*") if p.is_file())

        for plik in pliki:
            wzgledna = plik.relative_to(KATALOG_PROJEKTU)
            if POMIJANE & set(wzgledna.parts) or plik.suffix == ".pem":
                continue

            cel = KATALOG_PACZKI / wzgledna.parent / (plik.name + ".txt")
            cel.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(plik, cel)
            skopiowane += 1
            print(f"  {wzgledna}  ->  {cel.relative_to(KATALOG_PROJEKTU)}")

    print(f"\nSkopiowano {skopiowane} plików do {KATALOG_PACZKI}")


if __name__ == "__main__":
    main()

"""Stałe aplikacji. Wartości zależne od środowiska można nadpisać zmienną.

Nazwa `ustawienia`, a nie `config`, bo na serwerze istnieje już moduł
`config` z parametrami połączenia z hurtownią.
"""

import os
from pathlib import Path

KATALOG_APLIKACJI = Path(__file__).resolve().parent

BASE_URL = os.environ.get("HIPOTEKA_BASE_URL", "https://hdspprd1.ux.mbank.pl/sde_service/api")
CA_CERT = os.environ.get("HIPOTEKA_CA_CERT", "/home/jovyan/security/ca.pem")
PLIK_TOKENU = Path(os.environ.get(
    "HIPOTEKA_TOKEN",
    "/home/jovyan/projects/analiza_prawna_hipoteka/token.txt",
))

SCHEMY_DIR = KATALOG_APLIKACJI / "schemy"
PLIK_LOGO = KATALOG_APLIKACJI / "logo_mbank.jpg"
KATALOG_DEV = KATALOG_APLIKACJI / "dev"

# Limity czasu zadań po stronie API (sekundy). Ekstrakcja długiego aktu
# notarialnego z sekcją rozbieżności potrafi trwać dłużej niż OCR.
LIMIT_OCR_S = int(os.environ.get("HIPOTEKA_LIMIT_OCR_S", "180"))
LIMIT_EKSTRAKCJI_S = int(os.environ.get("HIPOTEKA_LIMIT_EKSTRAKCJI_S", "300"))
ODSTEP_ODPYTYWANIA_S = 3

# Tryb offline: hurtownia i API zastąpione danymi z katalogu dev/.
# Wyłącznie do pracy nad wyglądem na komputerze bez dostępu do hurtowni.
OFFLINE = os.environ.get("HIPOTEKA_OFFLINE") == "1"

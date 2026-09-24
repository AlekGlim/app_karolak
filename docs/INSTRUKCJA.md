# Hipoteka AI — instrukcja

Instrukcja ma trzy części:

1. [Uruchomienie](#1-uruchomienie) — na serwerze, lokalnie bez hurtowni i przeniesienie
   projektu mailem jako pliki `.txt`.
2. [Praca analityka](#2-praca-analityka) — co widać na ekranie i jak z tego korzystać.
3. [Pliki i wprowadzanie zmian](#3-pliki-i-wprowadzanie-zmian) — co leży w którym pliku, jak
   zmienić prompt, dodać pole, nowy typ dokumentu, walidację albo wygląd.

Na końcu: [zasady, których trzeba pilnować](#4-zasady-których-trzeba-pilnować)
i [rozwiązywanie problemów](#5-rozwiązywanie-problemów).

---

## 1. Uruchomienie

### Na serwerze (JupyterHub, dostęp do hurtowni i API)

```
streamlit run app.py
```

Aplikacja uruchamia się z katalogu repozytorium. Oprócz plików z repo na serwerze muszą być:

| Co | Gdzie | Po co |
|---|---|---|
| `config.py`, `helpers.py`, `impala_connector/` | obok `app.py` albo na ścieżce Pythona | połączenie z hurtownią (moduły serwerowe, nie ma ich w repo) |
| token API | `/home/jovyan/projects/analiza_prawna_hipoteka/token.txt` | plik JSON z kluczem `"access_token"` |
| certyfikat | `/home/jovyan/security/ca.pem` | weryfikacja TLS przy wywołaniach API |
| `logo_mbank.jpg` | obok `app.py` | logo w panelu bocznym (bez pliku aplikacja działa, tylko bez logo) |

Ścieżki tokenu i certyfikatu, adres API i limity czasu można zmienić bez edycji kodu,
zmiennymi środowiskowymi:

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `HIPOTEKA_TOKEN` | `/home/jovyan/projects/analiza_prawna_hipoteka/token.txt` | plik z tokenem |
| `HIPOTEKA_CA_CERT` | `/home/jovyan/security/ca.pem` | certyfikat CA |
| `HIPOTEKA_BASE_URL` | `https://hdspprd1.ux.mbank.pl/sde_service/api` | adres API |
| `HIPOTEKA_LIMIT_OCR_S` | `180` | ile sekund czekać na OCR |
| `HIPOTEKA_LIMIT_EKSTRAKCJI_S` | `300` | ile sekund czekać na ekstrakcję |
| `HIPOTEKA_OFFLINE` | brak | `1` włącza tryb offline (patrz niżej) |

### Lokalnie, bez hurtowni — tryb offline

Tryb offline podmienia **wyłącznie źródła danych**: zamiast hurtowni i API aplikacja czyta
pliki z katalogu `dev/`. Cała logika i wszystkie widoki są te same co na produkcji, więc
tryb nadaje się do pracy nad wyglądem, szukajką, panelem ustaleń itp.

```
pip install -r requirements.txt

# Linux / macOS
HIPOTEKA_OFFLINE=1 streamlit run app.py

# Windows, PowerShell
$env:HIPOTEKA_OFFLINE="1"; streamlit run app.py

# Windows, cmd
set HIPOTEKA_OFFLINE=1 && streamlit run app.py
```

Dalej: numer wniosku `KHB1553044`, dokument `dev/umowa_demo_skan.pdf` (skan — typowy
przypadek) albo `dev/umowa_demo.pdf` (ten sam dokument z warstwą tekstową).

W trybie offline:

- na górze strony i w panelu bocznym widać ostrzeżenie „Tryb offline”,
- ekstrakcja zwraca zawsze ten sam wynik (`dev/wynik_umowa_deweloperska.json`),
  niezależnie od wgranego pliku,
- OCR skanu zwraca zawsze `dev/ocr_umowa_demo_skan.txt`; OCR PDF-a z warstwą tekstową
  zwraca jego prawdziwy tekst,
- „cache” trzymany jest w pamięci procesu — po restarcie Streamlita znika.

**Nigdy nie ustawiaj `HIPOTEKA_OFFLINE` na serwerze, z którego korzystają analitycy.**

### Testy

```
pip install -r requirements-dev.txt
pytest
```

Testy nie potrzebują hurtowni ani API. Uruchamiaj je przed każdym wdrożeniem.

### Przeniesienie projektu na inny komputer (mailem, same pliki .txt)

**Na komputerze, z którego wysyłasz** — w katalogu projektu:

```
python kopiuj_do_wysylki.py
```

Skrypt kopiuje pliki potrzebne do działania aplikacji do katalogu `paczka_wysylka/`
i każdemu dopisuje `.txt` na końcu nazwy (`app.py` → `app.py.txt`). Katalogi zostają
takie same. Listę kopiowanych plików zmienia się w `WYMAGANE` na początku skryptu
(testy są tam zakomentowane). `token.txt` i certyfikaty `*.pem` nigdy nie są kopiowane.

**Na komputerze, na który przenosisz:**

1. Zapisz pliki w takim układzie:

   ```
   hipoteka_ai/
     app.py.txt
     data_loader.py.txt
     requirements.txt.txt
     README.md.txt
     .streamlit/  config.toml.txt
     schemy/  umowa_deweloperska.json.txt
     docs/    INSTRUKCJA.md.txt
     dev/     wnioskodawcy.json.txt  wynik_umowa_deweloperska.json.txt
              ocr_umowa_demo_skan.txt.txt  umowa_demo.pdf.txt  umowa_demo_skan.pdf.txt
              generuj_umowe_demo.py.txt
   ```

   Do samego działania na serwerze wystarczą `app.py`, `data_loader.py`, `requirements.txt`,
   `schemy/` i `.streamlit/` (kolory kontrolek; katalog zaczyna się od kropki — w Windowsie
   utwórz go w wierszu poleceń: `mkdir .streamlit`). `dev/` jest potrzebny tylko w trybie offline, `docs/` i `README.md` to opis.

2. Usuń końcówkę `.txt` z nazw — **tylko jedną, ostatnią** (`requirements.txt.txt` →
   `requirements.txt`). Ręcznie albo jednym poleceniem w katalogu `hipoteka_ai`:

   ```
   # Windows, PowerShell
   Get-ChildItem -Recurse -File -Filter *.txt | Rename-Item -NewName { $_.Name -replace '\.txt$', '' }

   # Linux / macOS
   find . -type f -name "*.txt" -exec sh -c 'mv "$1" "${1%.txt}"' _ {} \;
   ```

   Polecenie uruchom **raz** — drugie uruchomienie zdjęłoby `.txt` także z
   `requirements.txt` i `ocr_umowa_demo_skan.txt`.

   W Eksploratorze Windows włącz najpierw *Widok → Rozszerzenia nazw plików*,
   inaczej `.txt` nie będzie widoczne przy zmianie nazwy.

3. Dalej jak zwykle: `pip install -r requirements.txt`, `streamlit run app.py`.

Pliki PDF w `dev/` to tylko przykłady do trybu offline; jeśli poczta ich nie przepuści,
aplikacja działa bez nich.

---

## 2. Praca analityka

### Krok po kroku

1. **Numer wniosku.** Wpisz numer z UniFlow (np. `KHB1553044`). Pod spodem pojawiają się
   karty wnioskodawców z hurtowni. Numer może zawierać tylko litery, cyfry i znaki `/ _ . -`.
2. **Upload.** Wgraj PDF umowy w zakładce „Umowa deweloperska” (panel boczny).
3. **Analiza.** Kliknij „▶ Uruchom analizę dokumentu”. Przycisk jest nieaktywny, dopóki
   nie ma tokenu albo nie znaleziono wniosku — bez danych klientów model nie miałby z czym
   porównać nabywców.
   - Jeśli ten sam dokument był już analizowany dla tego wniosku, wynik przychodzi z cache
     (plakietka „Cache Impala”) w kilka sekund.
   - „🔄 Wymuś ponowną analizę” pomija cache.
4. **Panel „Do wyjaśnienia”** (pełna szerokość, nad dokumentem) — wyłącznie rzeczy
   wymagające decyzji: błędny PESEL lub numer rachunku, niezgodna suma transz, rozbieżności
   w samym dokumencie, niezgodności z UniFlow. Zgodności nie są pokazywane. Gdy nic nie
   wymaga wyjaśnienia, jest jedna zielona linia.
5. **Dane z dokumentu** (prawa kolumna), pogrupowane w sekcje. Nagłówek sekcji pokazuje
   stan: `⚠` pola z problemem, `✕` pola puste, `✓` pola wypełnione.
   - **Klik w wartość** wkleja ją do szukajki i pokazuje stronę, na której występuje.
   - **Kopiuj** (tylko pola przepisywane do UniFlow) kopiuje wartość do schowka.
   - **⚠ rozbieżność** przy etykiecie — najedź myszą, żeby zobaczyć szczegóły.
6. **Dokument** (lewa kolumna) — szukajka i podgląd strony, opis niżej.
7. **Podsumowanie i ryzyka** — pod obiema kolumnami.
8. **Zakładka „Podsumowanie”** w panelu bocznym — sam panel ustaleń dla bieżącego
   dokumentu i wniosku.

„↺ Ponów” usuwa wynik z bieżącej sesji i pozwala uruchomić analizę jeszcze raz.
Zmiana numeru wniosku chowa wynik — jest przypisany do pary (dokument, wniosek);
powrót do poprzedniego numeru przywraca go bez ponownej analizy.

### Szukajka

Większość dokumentów to skany. Endpoint OCR zwraca sam tekst podzielony na strony,
bez pozycji słów, dlatego szukajka działa tak:

- fraza (wpisana albo z kliknięcia w pole) **przełącza podgląd na stronę**, na której występuje,
- **nad podglądem pojawia się fragment tekstu z OCR** z zaznaczoną frazą — na tej podstawie
  analityk odnajduje miejsce na skanie,
- pasek „← Poprzednie · Trafienie 2 z 5 · strona 3 · Następne →” przechodzi po kolejnych
  wystąpieniach; bez frazy ten sam pasek przewija strony.

Dla PDF-a z warstwą tekstową (wygenerowanego cyfrowo, nie skanu) fraza jest dodatkowo
zaznaczona na obrazie strony.

Na skanie przed analizą pole szukania jest nieaktywne — nie ma jeszcze tekstu.

Szukanie jest odporne na wielkość liter, polskie znaki (`wrzesnia` znajdzie `września`)
i łamanie linii. Szukajka najpierw rozpoznaje, czym jest fraza, i od tego zależy,
jak jej szuka:

| Fraza | Szukana | Przykład |
|---|---|---|
| data | w każdym zapisie, także od roku | `2026-03-14` znajdzie `14 marca 2026` i `14.03.2026` |
| kwota | w każdym zapisie | `685 000,00 zł` znajdzie `685.000,00` |
| identyfikator (co najmniej 6 cyfr: PESEL, NIP, KW, rachunek) | bez względu na spacje, myślniki i ukośniki | `WA1M/00123456/7` znajdzie `WA1M 00123456 7`; PESEL nie trafi w środek numeru rachunku |
| cała reszta | dosłownie, a gdy nic nie ma — z odmianą | `Warszawa` → `w Warszawie` („forma odmieniona”) |

Zapis z błędem OCR (`WA1M/0O123456/7`, z literą O) jest szukany tak, jak go wpisano —
znajdzie tylko miejsce z błędem.

**Kolory** przy polu z rozbieżnością (np. dwie różne daty umowy w dokumencie):

| Kolor | Znaczenie |
|---|---|
| niebieski | szukana fraza albo wartość przyjęta przez model |
| morski zielony | ta sama wartość zapisana inaczej (`14 marca 2026` zamiast `14-03-2026`) |
| czerwony | wartość niezgodna — inna data, inna osoba albo prawdopodobny błąd OCR |

Szukajka zaczyna od wartości przyjętej; do niezgodnej przechodzi się „Następne →”.

---

## 3. Pliki i wprowadzanie zmian

### Mapa plików

```
app.py                 cała aplikacja (sekcje opisane niżej)
data_loader.py         hurtownia: wnioskodawcy z UniFlow, cache wyników — tylko na serwerze
schemy/
  umowa_deweloperska.json   schemat ekstrakcji = pytanie do modelu
dev/                   dane trybu offline (patrz 3.10)
tests/                 testy pytest
kopiuj_do_wysylki.py   kopia plików z końcówką .txt do wysłania mailem (patrz 1.)
```

`app.py` jest podzielony na sekcje z nagłówkami w komentarzach
(`# ====…` / `# NAZWA SEKCJI`). Najłatwiej przeskakiwać między nimi, szukając nazwy sekcji:

| Sekcja w `app.py` | Co zawiera |
|---|---|
| USTAWIENIA | adres API, ścieżki (token, certyfikat, schematy, logo, `dev/`), limity czasu, `OFFLINE` |
| TEKST OCR | normalizacja do szukania, markery `[STRONA_X]`, `tekst_do_wyswietlenia` (czyszczenie fragmentu OCR) |
| KWOTY | odczyt kwot, wzorce kwot, `kwota_z_frazy` |
| DATY | daty liczbowe i słowne (`14 marca 2026`) |
| WALIDACJE | PESEL, NRB, suma transz, `WZORZEC_NUMERU_WNIOSKU` |
| SZUKANIE W TEKŚCIE OCR | szukanie frazy, warianty z rozbieżności, `wzorzec_z_odmiana`, strona dla wartości |
| INDEKS DOKUMENTU | strony dokumentu (OCR albo warstwa tekstowa PDF), trafienia na stronach |
| ROZBIEŻNOŚCI | sprawdzenie, czy wartości zgłoszone przez model stoją w tekście OCR |
| USTALENIA | panel „Do wyjaśnienia”: `zbierz_problemy`, `POZIOM_ROZBIEZNOSCI`, `SLOWA_KLUCZOWE_POL` |
| SCHEMATY, PROMPT I KLUCZ CACHE | `SCHEMATY`, `SZABLON_PROMPTU`, `klucz_wersji` |
| API | `wywolaj_ocr_api`, `wywolaj_extract_api`, odpytywanie statusu, odczyt tokenu |
| PDF | liczba stron, warstwa tekstowa, obraz strony |
| TRYB OFFLINE | atrapy hurtowni i API (`offline_*`) |
| ŹRÓDŁA DANYCH | `zrodla()` — prawdziwe źródła (API + `data_loader.py`) albo offline |
| ANALIZA | `Analiza`, `analizuj`: cache → OCR → ekstrakcja → zapis do cache |
| STAN SESJI | analizy (klucz: hash PDF + numer wniosku), dane UniFlow, wgrany plik |
| WIDOK: PANEL DOKUMENTU | szukajka, pasek nawigacji, podgląd strony, `RODZAJE_TRAFIEN` (kolory) |
| WIDOKI APLIKACJI | CSS, panel boczny, dane wniosku, pola z danymi, panel ustaleń, podsumowanie i ryzyka, zakładki, `main()` |

Sekcje od USTAWIEŃ do USTALEŃ i SCHEMATÓW nie używają Streamlita — to czysta logika,
pokryta testami w `tests/`.

### Przepływ danych

```
numer wniosku ──► zrodla().load_wnioskodawcy (data_loader.py) ──► ustaw_uniflow
                                                                      │
PDF ──► analizuj (ANALIZA) ◄──────────────────────────────────────────┘ (dane klientów do promptu)
          │
          ├─ cache (data_loader.get_document_cache) ── trafienie ──► wynik
          │
          ├─ OCR (wywolaj_ocr_api) ──► dodaj_markery_stron
          ├─ prompt (zbuduj_prompt) ──► Extract (wywolaj_extract_api)
          └─ zapis do cache (data_loader.save_document_cache)
                                   │
                                   ▼
                        zapisz_analize(Analiza)
                                   │
       ┌───────────────────────────┼─────────────────────────────┐
       ▼                           ▼                             ▼
panel „Do wyjaśnienia”    dane z dokumentu              dokument + szukajka
(USTALENIA)               (widok_umowy_deweloperskiej)  (panel_dokumentu)
```

`Analiza` niesie wszystko o jednej analizie: `wynik` (JSON z modelu), `ocr_text`
(z markerami stron), `zrodlo`, `czas`, `ostrzezenia`.

---

### 3.1. Zmiana tego, o co pytamy model

Model dostaje prompt i schemat. **Opisy pól w schemacie to najważniejsza część pytania.**

- **Opis pola, reguły rozbieżności, ryzyka, podsumowanie** → `schemy/umowa_deweloperska.json`,
  pole `description` przy danym kluczu.
- **Tekst wokół danych UniFlow i treści dokumentu** → `app.py`, sekcja SCHEMATY, PROMPT
  I KLUCZ CACHE, stała `SZABLON_PROMPTU`. Zostaw w niej `{tekst_uniflow}` i `{ocr_text}`.

Po każdej zmianie schematu albo szablonu cache sam przestaje trafiać (klucz cache zawiera
skrót schematu, szablonu i danych UniFlow), więc każdy dokument zostanie przy następnym
otwarciu przeanalizowany ponownie. To zamierzone — stary wynik odpowiadałby na inne pytanie —
ale kosztuje: nie zmieniaj schematu na produkcji „na próbę”.

Nowy prompt najlepiej sprawdzić najpierw w notatniku `analiza_prawna_umowa_dew.ipynb`.

### 3.2. Dodanie nowego pola do umowy deweloperskiej

Przykład: pole `powierzchnia_uzytkowa`.

1. **Schemat** — `schemy/umowa_deweloperska.json`, w `properties`:
   ```json
   "powierzchnia_uzytkowa": {
       "type": "string",
       "description": "Powierzchnia użytkowa lokalu w m², np. 58,40"
   }
   ```
   Jeśli pole jest obowiązkowe, dopisz klucz także do listy `required`.
2. **Widok** — `app.py`, funkcja `widok_umowy_deweloperskiej`. Znajdź sekcję (np. `NIERUCHOMOŚĆ`),
   dopisz klucz do listy przekazywanej do `etykieta_sekcji` (od niej zależą liczniki ⚠ ✕ ✓)
   i dodaj pole w kolumnie:
   ```python
   with col1:
       pole_pdf(
           "Powierzchnia",
           wynik.get("powierzchnia_uzytkowa"),
           "powierzchnia_uzytkowa",
           problemy.get("powierzchnia_uzytkowa")
       )
   ```
   Pierwszy argument to etykieta na ekranie, trzeci — klucz ze schematu. Klucz musi być
   unikalny w całej zakładce (służy też jako klucz przycisku Streamlita).
3. **Kopiowanie do UniFlow** (opcjonalnie) — dopisz klucz do `POLA_DO_PRZEPISANIA` w `app.py`.
4. **Rozbieżności** (tylko jeśli pole ma być sprawdzane pod kątem niejednolitych zapisów
   w dokumencie):
   - w schemacie dopisz klucz do listy pól w opisie `rozbieznosci` i dodaj reguły dla
     tego rodzaju pola,
   - w `app.py`, sekcja USTALENIA, dopisz etykietę do `ETYKIETY_POL_ROZBIEZNOSCI` i wagę do
     `POZIOM_ROZBIEZNOSCI` (`"wysoki"` albo `"sredni"`).
5. **Tryb offline** — dopisz przykładową wartość do `dev/wynik_umowa_deweloperska.json`,
   inaczej pola nie zobaczysz lokalnie. Test `test_offline_wynik_zgodny_ze_schematem`
   pilnuje, żeby ten plik nie miał kluczy spoza schematu.

Pole puste w wyniku (`None` albo `""`) nie jest wyświetlane — `pole_pdf` je pomija.

### 3.3. Nowy typ dokumentu (np. umowa przedwstępna)

1. Dodaj schemat `schemy/umowa_przedwstepna.json`. Nazwa pliku musi odpowiadać wpisowi
   w słowniku `SCHEMATY` w `app.py` — typy są już tam wpisane.
2. W `app.py` dodaj funkcję zakładki — najprościej skopiować `zakladka_umowa_deweloperska`
   i zmienić `typ_dokumentu = "umowa_przedwstepna"`. Typ decyduje o schemacie; nazwa pliku
   nie ma znaczenia.
3. W `main()` podmień `st.info("W przygotowaniu")` dla tej pozycji menu na wywołanie nowej
   zakładki.
4. Widok wyniku: dopóki nie napiszesz własnego, `pokaz_wynik_dokumentu` pokazuje wynik jako
   JSON. Własny widok dopisz tam jako kolejny warunek na `analiza.typ_dokumentu`.
5. Panel ustaleń, szukajka, cache i podsumowanie działają bez zmian, jeśli schemat ma pola
   `podsumowanie`, `potencjalne_ryzyka`, `weryfikacja_uniflow` (i opcjonalnie `rozbieznosci`).

### 3.4. Nowa twarda walidacja (liczona w Pythonie)

Przykład: sprawdzenie NIP-u dewelopera.

1. Funkcja w `app.py`, sekcja WALIDACJE, np. `waliduj_nip(nip)`, zwracająca prosty wynik.
2. Ustalenie w sekcji USTALENIA, funkcja `zbierz_problemy`, sekcja „twarde walidacje” —
   wzoruj się na PESEL-u. Klucz `"pole"` musi być kluczem ze schematu, wtedy znacznik
   ⚠ pojawi się też przy polu.
3. Test w `tests/test_walidacje.py` i `tests/test_ustalenia.py` (importy: `from app import ...`).

Twarde walidacje są pewniejsze niż ocena modelu, więc ustalenia z nich trafiają na górę panelu.

### 3.5. Waga ustaleń i przypisanie ich do pól

Wszystko w `app.py`, sekcja USTALENIA:

- `POZIOM_ROZBIEZNOSCI` — waga niezgodnych wartości w dokumencie, per pole.
- `SLOWA_KLUCZOWE_POL` — po jakich słowach wpis weryfikacji UniFlow z modelu jest
  przypisywany do pola (dymek ⚠ przy polu). **Kolejność ma znaczenie**: wygrywa pierwsze
  dopasowanie, dlatego „nabywca” jest na końcu. Wzorce to wyrażenia regularne na tekście
  bez polskich znaków i małymi literami.
- Kolejność w panelu: `wysoki` przed `sredni`.

### 3.6. Szukajka

| Co zmienić | Gdzie |
|---|---|
| kolory trafień (niebieski / morski zielony / czerwony) i ich opisy w legendzie | sekcja PANEL DOKUMENTU, `RODZAJE_TRAFIEN` |
| jak rozpoznawany jest typ frazy (data, kwota, identyfikator, tekst) | sekcja SZUKANIE, `rozpoznaj_typ_frazy` |
| co uznajemy za identyfikator (np. minimalna liczba cyfr) | sekcja SZUKANIE, `klucz_identyfikatora`, `MIN_CYFR_IDENTYFIKATORA` |
| ile tekstu pokazuje karta fragmentu | sekcja PANEL DOKUMENTU, `_fragment` (liczba `150`) |
| wysokość podglądu strony | sekcja PANEL DOKUMENTU, `WYSOKOSC_PODGLADU` |
| jak czyszczony jest tekst OCR (tabele, komentarze, nagłówki) | sekcja TEKST OCR, `tekst_do_wyswietlenia` |
| od ilu liter słowo jest skracane przy odmianie | sekcja SZUKANIE, `wzorzec_z_odmiana` |
| rozpoznawanie dat i nazw miesięcy | sekcja DATY |
| co uznajemy za kwotę | sekcja KWOTY, `WZORZEC_ZAPISU_KWOTY` |

Klik w pole wkleja wartość funkcją `ustaw_fraze_szukania` (callback przycisku). Nie da się
tego zrobić zwykłym przypisaniem po wyrenderowaniu pola tekstowego — Streamlit zgłosi błąd.

### 3.7. Wygląd

- **Kolory i style** — `app.py`, stała `CUSTOM_CSS`. Kolory są zmiennymi CSS na górze
  (`--akcent`, `--baner-od`, `--tlo-karty`, …) z osobnym wariantem dla motywu ciemnego —
  zmieniaj oba. Akcent jest fioletowy; czerwień jest zarezerwowana dla błędów i ryzyk.
- **Kolor kontrolek Streamlita** (pole szukania, przełączniki, zakładki, spinner) —
  `.streamlit/config.toml`, `primaryColor` w `[theme.light]` i `[theme.dark]`. Trzymaj go
  zgodnie z `--akcent` w `CUSTOM_CSS`. Bez tego pliku kontrolki będą czerwone.
- **Wysokość prawej kolumny** — `app.py`, `sekcja_akcja_i_kluczowe_dane`,
  `st.container(height=900)`. Przy zmianie dopasuj `WYSOKOSC_PODGLADU` (sekcja PANEL DOKUMENTU),
  żeby kolumny kończyły się w podobnej linii.
- **Nagłówek** — `banner_naglowek` w `app.py`.
- Aplikacja podąża za motywem przeglądarki. Nie ustawiaj `base="light"` w
  `.streamlit/config.toml`.
- `.streamlit/config.toml` jest czytany z katalogu, z którego uruchamiasz
  `streamlit run app.py` — uruchamiaj aplikację z katalogu projektu.

### 3.8. Hurtownia

`data_loader.py`:

- nazwy tabel i zapytania,
- `load_wnioskodawcy` — kolumny `IMIE`, `NAZWISKO`, `PESEL`, `STAN_CYWILNY` trafiają do
  promptu i na karty wnioskodawców; nowa kolumna wymaga też zmiany w `sekcja_dane_uniflow`
  (`app.py`),
- `ttl=600` — co ile sekund dane wniosku są pobierane ponownie,
- `save_document_cache` — **kolejność kolumn w DataFrame musi odpowiadać kolejności
  kolumn w tabeli** (insert jest pozycyjny).

Każda wartość wstawiana do SQL przechodzi walidację (`_numer_wniosku`, `_hash`). Nowy
parametr zapytania też musi przez nią przejść — nigdy nie wstawiaj do f-stringa tekstu
wpisanego przez użytkownika. Dozwolony format numeru wniosku: `WZORZEC_NUMERU_WNIOSKU` w `app.py` (sekcja WALIDACJE)
i `_NUMER_WNIOSKU` w `data_loader.py` — **zmieniaj oba naraz**.

`load_kwoty_kredytu` jest gotowe, ale obecnie nieużywane.

### 3.9. API

`app.py`, sekcja API — adresy endpointów i parametry (`document_type`, `ocr_model`).
Limity czasu i adres bazowy są w sekcji USTAWIENIA (albo w zmiennych środowiskowych).
Endpoint OCR zwraca tekst ze znacznikami `&lt;!-- PageBreak --&gt;`; na nich
`dodaj_markery_stron` (sekcja TEKST OCR) opiera podział na strony. Jeśli format się zmieni,
popraw wyrażenie w tej funkcji — od niego zależą numery stron w całej aplikacji.

### 3.10. Dane trybu offline

| Plik | Zawartość | Jak zmienić |
|---|---|---|
| `dev/wnioskodawcy.json` | wiersze tabeli wnioskodawców | edytuj ręcznie; nowy numer wniosku = nowe wiersze z tym numerem |
| `dev/wynik_umowa_deweloperska.json` | odpowiedź Extract | edytuj ręcznie; tylko klucze ze schematu |
| `dev/umowa_demo.pdf`, `dev/umowa_demo_skan.pdf`, `dev/ocr_umowa_demo_skan.txt` | dokument i jego OCR | zmień treść w `dev/generuj_umowe_demo.py` i uruchom `python dev/generuj_umowe_demo.py` (wymaga `reportlab`) |

Treść umowy demo, wynik ekstrakcji i OCR muszą do siebie pasować — inaczej szukajka nie
znajdzie wartości pól. Umowa demo ma celowe rozbieżności (druga data zawarcia, `O` zamiast
`0` w numerze KW, inne nazwisko drugiego nabywcy niż we wniosku), żeby było co oglądać
w panelu ustaleń.

---

## 4. Zasady, których trzeba pilnować

- **Logika bez Streamlita.** Funkcje z sekcji od USTAWIEŃ do SCHEMATÓW nie wołają `st.*` —
  dane (np. `ocr_text`) przychodzą parametrem, nie z `st.session_state`. Dzięki temu da się
  je przetestować. `st.set_page_config` i CSS są w `konfiguruj_strone()` wywoływanej
  w `main()`, żeby import `app.py` w testach nie uruchamiał Streamlita.
- **Stan sesji tylko przez funkcje z sekcji STAN SESJI.** Wynik analizy jest przypisany do pary (hash PDF,
  numer wniosku); klucz tylko po nazwie pliku pokazywałby wyniki innego dokumentu albo wniosku.
- **Tekst z modelu, OCR i UniFlow jest niezaufany.** Przed wstawieniem do HTML
  (`st.markdown(..., unsafe_allow_html=True)`) przepuść go przez `html.escape`.
  Wyjątek: opis ryzyka, w którym model celowo zwraca `<h4>`.
  **Stan obecny:** część starszych widoków jeszcze tego nie robi — `panel_ustalen` (wpisy
  weryfikacji UniFlow), `widok_podsumowania`, `kafelek`, `wiersz` i dymek w `_znacznik_pola`.
  Do poprawy; przy zmianach w tych funkcjach dodaj `html.escape`.
- **Unikalne klucze widgetów.** Dwa przyciski z tym samym `key` kończą się błędem Streamlita.
- **Token nie trafia do repozytorium** — `token.txt` i `*.pem` są w `.gitignore`.
- **Zmiana schematu lub promptu unieważnia cache** (patrz 3.1).
- **Przed wdrożeniem:** `pytest` i przejście przepływu w trybie offline.

---

## 5. Rozwiązywanie problemów

| Objaw | Przyczyna | Co zrobić |
|---|---|---|
| „Brak poprawnego tokenu” w panelu bocznym | brak pliku tokenu albo zły JSON | sprawdź plik z `HIPOTEKA_TOKEN`; musi zawierać `{"access_token": "..."}` |
| „Analiza nie powiodła się: 401 …” | token wygasł | wygeneruj nowy token |
| „Przekroczono limit oczekiwania na: OCR / Ekstrakcja” | długi dokument albo obciążone API | spróbuj ponownie; w razie potrzeby zwiększ `HIPOTEKA_LIMIT_*_S` |
| „Nie znaleziono wniosku” dla istniejącego numeru | wniosek dodany niedawno (dane odświeżają się co 10 min) albo filtr nie pasuje do typu kolumny | odczekaj; jeśli się powtarza, sprawdź warunek `WHERE` w `load_wnioskodawcy` |
| „Numer wniosku może zawierać tylko…” | znak spoza dozwolonych | jeśli to poprawny format numeru, rozszerz `WZORZEC_NUMERU_WNIOSKU` |
| żółte ostrzeżenie „Wynik nie został zapisany do cache” | błąd zapisu do Impali (Kerberos, metadane) | analiza jest kompletna; przy następnym otwarciu zostanie wykonana ponownie |
| przycisk „Uruchom analizę” nieaktywny | brak tokenu albo wniosku | wpisz poprawny numer wniosku, sprawdź token |
| pole szukania nieaktywne | skan przed analizą — nie ma jeszcze tekstu | uruchom analizę |
| wszystkie trafienia na „stronie 1” | endpoint OCR zmienił format znacznika `PageBreak` | popraw wzorzec w `dodaj_markery_stron` (sekcja TEKST OCR) |
| fraza nie jest zaznaczona na stronie | skan bez warstwy tekstowej (norma) albo brak `pdfplumber` | na skanach to oczekiwane — pozycję wskazuje fragment tekstu nad podglądem |
| brak przycisku „Kopiuj” jednym kliknięciem | brak pakietu `st-copy` | `pip install st-copy`; bez niego działa zapasowy wariant z ikoną kopiowania |
| brak logo | brak `logo_mbank.jpg` obok `app.py` | skopiuj plik |
| `ModuleNotFoundError: No module named 'config'` (albo `helpers`) | aplikacja uruchomiona poza serwerem bez trybu offline | lokalnie uruchamiaj z `HIPOTEKA_OFFLINE=1` |
| aplikacja nie widzi pliku, choć jest w katalogu | nazwa wciąż kończy się na `.txt` (Windows ukrywa rozszerzenia) | włącz widok rozszerzeń i usuń końcówkę `.txt` |

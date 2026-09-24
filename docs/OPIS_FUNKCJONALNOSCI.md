# Hipoteka AI — opis funkcjonalności i kierunki rozwoju

Dokument opisuje, co aplikacja robi dziś, na jakich zasadach działa i co można
rozwinąć dalej. Instrukcja uruchomienia i wprowadzania zmian w kodzie jest
w [INSTRUKCJA.md](INSTRUKCJA.md).

Spis treści:

1. [Cel aplikacji](#1-cel-aplikacji)
2. [Przebieg pracy analityka](#2-przebieg-pracy-analityka)
3. [Funkcjonalności](#3-funkcjonalności)
4. [Zasady działania pod spodem](#4-zasady-działania-pod-spodem)
5. [Znane ograniczenia](#5-znane-ograniczenia)
6. [Pomysły na przyszłość](#6-pomysły-na-przyszłość)
7. [Proponowana kolejność prac](#7-proponowana-kolejność-prac)

---

## 1. Cel aplikacji

Hipoteka AI wspiera analityka hipotecznego przy weryfikacji **umowy deweloperskiej**
dołączonej do wniosku kredytowego. Zamiast czytać cały akt notarialny, analityk dostaje:

- **kluczowe dane z umowy** (strony, nieruchomość, cena, rachunek powierniczy,
  harmonogram), gotowe do przepisania do UniFlow;
- **listę rzeczy do wyjaśnienia**: błędne numery, niezgodności z wnioskiem
  i niespójności w samym dokumencie;
- **szybkie sprawdzenie źródła**: każdą wartość można jednym kliknięciem odnaleźć
  w dokumencie;
- **podsumowanie i ryzyka** z perspektywy banku jako wierzyciela hipotecznego.

Podział pracy:

- **Model językowy** czyta dokument i wyciąga dane.
- **Python sprawdza to, co da się sprawdzić deterministycznie:** sumy kontrolne,
  zgodność kwot, czy cytat wskazany przez model naprawdę stoi na podanej stronie.
- **Analityk podejmuje decyzję.** Aplikacja pokazuje tylko to, co wymaga jego uwagi.

Większość dokumentów to **skany**. OCR (prebuilt-layout) zwraca tekst w markdownie
podzielony na strony, bez położenia słów na stronie. Cała aplikacja jest do tego
dostosowana.

---

## 2. Przebieg pracy analityka

```
 1. Numer wniosku         ──►  dane wnioskodawców z UniFlow (hurtownia)
 2. Wgranie PDF umowy     ──►  podgląd dokumentu
 3. „Uruchom analizę”     ──►  OCR ──► ekstrakcja (model) ──► zapis do cache
 4. Panel „Do wyjaśnienia”     tylko problemy, od najważniejszych
 5. Dane z dokumentu      ◄──►  szukajka i podgląd strony
 6. Podsumowanie i ryzyka
```

Jeśli ten sam dokument był już analizowany dla tego wniosku, wynik przychodzi
z cache w kilka sekund, bez ponownego OCR i ekstrakcji.

---

## 3. Funkcjonalności

### 3.1. Dane wniosku z UniFlow

- Analityk wpisuje numer wniosku (np. `KHB1553044`). Aplikacja pobiera z hurtowni
  wnioskodawców: imię, nazwisko, PESEL i stan cywilny.
- Wnioskodawcy są pokazani na kartach nad dokumentem.
- Dane trafiają do promptu, dzięki czemu model porównuje nabywców z umowy z osobami
  z wniosku.
- Numer wniosku przechodzi walidację: dozwolone są tylko litery, cyfry i znaki `/ _ . -`.
  Chroni to zapytania do hurtowni przed wstrzyknięciem SQL.
- Dane wniosku są odświeżane co 10 minut.
- Bez znalezionego wniosku nie da się uruchomić analizy, bo model nie miałby
  z czym porównać nabywców.

### 3.2. Wgranie dokumentu i analiza

- **Upload PDF** w zakładce „Umowa deweloperska”. Podgląd stron jest dostępny od razu.
- **OCR** przez endpoint `sde_service`. Znaczniki podziału stron z OCR są zamieniane
  na markery `[STRONA_X]`, z których aplikacja wylicza numery stron.
- **Ekstrakcja** tym samym API. Model dostaje schemat pól
  (`schemy/umowa_deweloperska.json`), dane z UniFlow i tekst dokumentu.
- **Cache w hurtowni (Impala).** Wynik jest zapisywany pod kluczem:
  skrót pliku + numer wniosku + wersja pytania. Wersja pytania to skrót schematu,
  szablonu promptu i danych UniFlow. Zmiana któregokolwiek z nich wymusza nową analizę,
  więc stary wynik nigdy nie odpowiada na inne pytanie.
- **„🔄 Wymuś ponowną analizę”** pomija cache.
- **„↺ Ponów”** czyści wynik w bieżącej sesji.
- **Wynik jest przypisany do pary (dokument, wniosek).** Zmiana numeru wniosku chowa
  wynik, a powrót do poprzedniego numeru przywraca go bez ponownej analizy.
- **Plakietka źródła wyniku:** „Cache Impala”, „Prawdziwe API” (świeża analiza)
  albo „Offline (dev/)”.

### 3.3. Panel „Do wyjaśnienia”

Zasada: **pokazujemy tylko to, co wymaga decyzji.** Zgodności nie są wyświetlane.
Panel, który potwierdza oczywistości, po kilku analizach przestaje być czytany.
Gdy nic nie wymaga uwagi, panel pokazuje jedną zieloną linię.

Źródła ustaleń:

| Źródło | Co sprawdza | Kto liczy | Poziom |
|---|---|---|---|
| Walidacja PESEL | suma kontrolna i poprawność daty w numerze | Python | wysoki |
| Walidacja NRB | długość i suma kontrolna rachunku powierniczego | Python | wysoki |
| Suma harmonogramu | czy transze sumują się do wartości transakcji; podaje różnicę w zł | Python | średni |
| Rozbieżności w dokumencie | to samo pole zapisane w dokumencie różnie, np. dwie daty zawarcia umowy, `O` zamiast `0` w numerze KW | model wskazuje zapisy; Python potwierdza je w tekście, a dla dat i identyfikatorów sam rozstrzyga „ok” / „zła” | wysoki lub średni, zależnie od pola |
| Weryfikacja z UniFlow | nabywcy z umowy a wnioskodawcy z wniosku: nazwiska, liczba osób | model | wg statusu |

**Pola z trzema poziomami.** 14 kluczowych pól (daty, identyfikatory, strony umowy)
model zwraca jako obiekt:

```json
"data_umowy": {
  "wartosc_glowna": "2026-03-14",
  "wartosci_ok": ["14 marca 2026"],
  "wartosci_zle": ["15 marca 2026"],
  "uzasadnienie": "W komparycji 14 marca, na końcu aktu 15 marca."
}
```

- `wartosc_glowna` — wartość przyjęta; daty w formacie RRRR-MM-DD (zgodnie z timestampem
  w UniFlow),
- `wartosci_ok` — ta sama wartość zapisana w dokumencie inaczej (tylko do szukajki
  i dymka przy polu, panel o nich milczy),
- `wartosci_zle` — zapisy niezgodne; każdy tworzy ustalenie w panelu.

Python sprawdza, czy każdy zapis naprawdę stoi w tekście (zmyślone odpadają), a dla dat
i identyfikatorów sam decyduje o podziale: ta sama data w innym zapisie to „ok”, inna
data — „zła”; te same znaki bez separatorów to „ok”, inne cyfry — „zła”. Przy osobach
i firmach podział zostaje po stronie modelu, bo wymaga kontekstu roli.

Każde ustalenie ma **tytuł, opis i sugerowany krok** (np. „Sprawdź na skanie,
która wartość jest prawidłowa”). Ustalenia dotyczące konkretnego pola dodatkowo
oznaczają to pole znacznikiem ⚠.

### 3.4. Dane z dokumentu

Prawa kolumna zawiera wyekstrahowane pola pogrupowane w sekcje:

| Sekcja | Pola |
|---|---|
| Dokument | numer umowy (repertorium), data zawarcia |
| Nabywcy | nabywca 1 i 2, PESEL-e |
| Deweloper | nazwa, NIP |
| Rachunek powierniczy | bank, numer otwartego rachunku, numer indywidualny |
| Nieruchomość | rodzaj, adres, numer działki, KW, prawa przynależne (miejsca postojowe, komórki), dodatkowe nieruchomości |
| Transakcja | cena, łączna wartość, liczba transz, harmonogram, terminy przeniesienia i ustanowienia odrębnej własności |

- **Nagłówek sekcji pokazuje jej stan:** `⚠` pola z problemem, `✕` pola puste,
  `✓` pola wypełnione.
- **Klik w wartość** wkleja ją do szukajki i przełącza podgląd na stronę, na której
  występuje.
- **„Kopiuj”** przy polach przepisywanych do UniFlow (numer umowy, data, deweloper,
  KW, działka, adres, ceny, rachunki, termin przeniesienia) kopiuje wartość do schowka.
- **„⚠ rozbieżność”** przy etykiecie pola: po najechaniu myszą widać wszystkie zapisy
  tej wartości w dokumencie.
- **Zakładka „OCR”** pokazuje pełny tekst z OCR, a **zakładka „JSON”** surowy wynik
  modelu (do diagnostyki).

### 3.5. Dokument i szukajka

Lewa kolumna to podgląd dokumentu z szukajką.

- **Fraza** (wpisana albo z kliknięcia w pole) przełącza podgląd na stronę, na której
  występuje.
- **Karta fragmentu** nad podglądem pokazuje tekst OCR wokół trafienia z zaznaczoną
  frazą. Na skanie to główna wskazówka, gdzie szukać. Tabele i znaczniki markdown
  z OCR są zamieniane na czytelny tekst.
- **Pasek nawigacji** „← Poprzednie · Trafienie 2 z 5 · strona 3 · Następne →”
  przechodzi po wystąpieniach. Bez frazy przewija strony.
- **Tylko strona, bez zaznaczania na obrazie.** Aplikacja wskazuje stronę i fragment
  tekstu — także dla PDF-a z warstwą tekstową. Szukanie działa po analizie.

**Szukanie po znaczeniu, a nie po napisie.** Szukajka rozpoznaje typ frazy:

| Typ frazy | Jak szukana | Przykład |
|---|---|---|
| data | w każdym zapisie (dzień, miesiąc słownie, od roku) | `2026-03-14` znajdzie `14 marca 2026` i `14.03.2026` |
| kwota | w każdym zapisie, z pilnowaniem granic liczby | `685 000,00 zł` znajdzie `685.000,00`, ale nie `1 685 000,00` |
| identyfikator (PESEL, NIP, KW, rachunek) | bez względu na spacje, myślniki i ukośniki | `WA1M/00123456/7` znajdzie `WA1M 00123456 7`; PESEL nie trafi w środek rachunku |
| tekst | dosłownie, bez wielkości liter i polskich znaków; z odmianą jako zapasem | `Warszawa` znajdzie `w Warszawie` |

Zapis z błędem OCR (np. litera `O` zamiast zera) jest szukany tak, jak go wpisano,
więc znajduje dokładnie miejsce z błędem.

**Kolory trafień** przy polu z rozbieżnością:

| Kolor | Znaczenie |
|---|---|
| niebieski | wartość przyjęta albo szukana fraza |
| morski zielony | ta sama wartość w innym zapisie |
| czerwony | wartość niezgodna |

Szukajka zaczyna od wartości przyjętej. Do wartości niezgodnych przechodzi się
przyciskiem „Następne →”.

### 3.6. Podsumowanie i ryzyka

- **Podsumowanie** (5–8 zdań) opisuje dokument z perspektywy banku: stan prawny,
  możliwość ustanowienia hipoteki, warunki uruchomienia środków, harmonogram,
  przeniesienie własności.
- **Ryzyka** to tylko okoliczności podwyższające ryzyko względem typowej umowy
  deweloperskiej. Standardowe elementy, jak hipoteka banku finansującego inwestycję
  z procedurą bezobciążeniowego wyodrębnienia lokalu czy mieszkaniowy rachunek
  powierniczy, nie są zgłaszane.
- Zakładka **„Podsumowanie”** w panelu bocznym zbiera panel ustaleń dla bieżącego
  dokumentu i wniosku.

### 3.7. Pozostałe typy dokumentów

W menu są już: umowa przedwstępna, umowa rezerwacyjna, wzór prospektu informacyjnego
i oświadczenie zbywcy. Dziś pokazują komunikat „W przygotowaniu”.

Zaplecze do ich obsługi jest gotowe: słownik schematów, cache, szukajka, panel ustaleń
i podsumowanie. Każdy nowy typ wymaga tylko schematu i zakładki (patrz INSTRUKCJA 3.3).

### 3.8. Tryb offline

`HIPOTEKA_OFFLINE=1` podmienia **wyłącznie źródła danych** (hurtownię i API) na pliki
z `dev/`. Logika i widoki są identyczne jak na produkcji, więc można lokalnie, bez
dostępu do hurtowni, pracować nad wyglądem, szukajką i panelem ustaleń.

Umowa demo (`dev/umowa_demo_skan.pdf`) ma celowe usterki do oglądania:

- dwie różne daty zawarcia umowy;
- `O` zamiast `0` w numerze KW;
- inne nazwisko drugiego nabywcy niż we wniosku.

### 3.9. Wygląd

- **Motyw jasny i ciemny** przełącza się automatycznie za przeglądarką.
- **Akcent jest fioletowy.** Czerwień jest zarezerwowana dla błędów i ryzyk,
  żeby nie sugerowała problemu tam, gdzie go nie ma.
- **Układ:** panel ustaleń na pełną szerokość, pod nim dwie kolumny (dokument
  i dane), na dole podsumowanie i ryzyka.

---

## 4. Zasady działania pod spodem

| Zasada | Dlaczego |
|---|---|
| **Stronę wartości wskazuje model, a Python ją sprawdza.** Przy każdym polu model podaje stronę i krótki cytat (`zrodla`). Python szuka cytatu w tekście OCR: stoi na wskazanej stronie → ✓, na innej → wygrywa tekst, nie ma go → ✕. | Model rozumie rolę wartości (cena lokalu, a nie pierwsza kwota w dokumencie), daty słownie i pola złożone, czego szukanie napisu nie umie. Za to myli numery stron i potrafi zmyślić — stąd sprawdzenie cytatu. |
| **Każda rozbieżność zgłoszona przez model jest sprawdzana w tekście.** Wartość, której nie ma w dokumencie, jest odrzucana. | Chroni przed wartościami zmyślonymi przez model. Liczba odrzuconych to tania miara jakości promptu. |
| **Twarde kontrole (PESEL, NRB, sumy) liczy Python.** | Sumy kontrolnej nie trzeba zgadywać. |
| **Klucz cache zawiera wersję pytania.** | Po zmianie schematu nie pokażemy wyniku odpowiadającego na stare pytanie. |
| **Wszystko, co trafia do SQL, przechodzi whitelistę.** | Hurtownia nie obsługuje parametrów zapytań. |
| **Logika jest oddzielona od Streamlita.** | Około 170 testów automatycznych bez hurtowni i API. |
| **Token i certyfikaty nigdy nie trafiają do repozytorium ani paczki wysyłkowej.** | Bezpieczeństwo. |

---

## 5. Znane ograniczenia

- **Brak położenia słów.** Nie zaznaczamy frazy na obrazie strony — OCR nie zwraca
  współrzędnych, a zaznaczanie z warstwy tekstowej PDF zostało usunięte, żeby był jeden
  scenariusz dla wszystkich dokumentów. Analityk dostaje stronę i fragment tekstu.
- **Format OCR z produkcji nie jest jeszcze sprawdzony na prawdziwym dokumencie.**
  Obsługa znaczników stron i tabel powstała na podstawie opisu i danych demo.
- **Typ kolumny `nr_wniosku` w hurtowni** jest do potwierdzenia (zapytanie rzutuje
  go na tekst).
- **Część starszych widoków nie escapuje HTML** w tekstach z modelu i UniFlow:
  wpisy weryfikacji UniFlow, podsumowanie, kafelki i dymek rozbieżności. Ryzyko
  jest niskie, ale do poprawy.
- **Weryfikacja z UniFlow jest dziś po stronie modelu.** Zgodność PESEL-i można
  sprawdzić deterministycznie, a nie jest.
- **Tryb offline zwraca zawsze ten sam wynik ekstrakcji**, niezależnie od wgranego
  pliku.

---

## 6. Pomysły na przyszłość

Przy każdym pomyśle: **korzyść** dla analityka i **nakład** (S — dzień lub dwa,
M — kilka dni, L — tydzień i więcej).

### 6.1. Schemat z trzema poziomami — zrobione, do obserwacji

Opis w 3.3. Po wdrożeniu warto sprawdzić na prawdziwych umowach:

- jak często Python poprawia podział modelu na „ok” i „zła” (jeśli często — doprecyzować
  opisy w schemacie),
- ile zapisów model zmyśla (odrzucone przy weryfikacji w tekście),
- czy format RRRR-MM-DD jest wygodny przy przepisywaniu do UniFlow; jeśli formularz
  oczekuje DD-MM-RRRR, przycisk „Kopiuj” może konwertować datę.

### 6.2. Więcej kontroli liczonych w Pythonie

| Kontrola | Korzyść | Nakład |
|---|---|---|
| **Suma kontrolna NIP** dewelopera | wyłapuje błędy odczytu i literówki | S |
| **Cyfra kontrolna numeru KW** (numer księgi ma cyfrę kontrolną) | wyłapuje błędy OCR w numerze KW bez udziału modelu | S |
| **PESEL z umowy a PESEL z UniFlow** porównywane bezpośrednio | pewna, natychmiastowa zgodność nabywców | S |
| **Liczba transz** a długość harmonogramu | niespójność ekstrakcji albo umowy | S |
| **Terminy:** transze przed terminem przeniesienia własności, data umowy nie z przyszłości | nietypowy harmonogram jako sygnał ryzyka | S |
| **Cena lokalu + prawa przynależne + dodatkowe nieruchomości = łączna wartość** | kontrola kompletności ceny | S |
| **Kwota kredytu z wniosku a cena** (`load_kwoty_kredytu` jest gotowe) | wstępny wskaźnik LTV i sygnał przy dużej różnicy | M |

### 6.3. Szukajka

| Pomysł | Korzyść | Nakład |
|---|---|---|
| **Wyszukiwanie przybliżone** (różnica jednego znaku) dla identyfikatorów | znajduje błędy OCR (`O`/`0`, `l`/`1`) niezależnie od modelu i może zgłaszać je jako rozbieżności | M |
| **Licznik wystąpień przy każdym polu** („3 miejsca w dokumencie”) | analityk od razu widzi, które wartości warto sprawdzić | S |
| **Lepsza odmiana nazwisk i nazw** (słownik odmiany zamiast obcinania końcówek) | mniej fałszywych trafień przy nazwiskach | M |
| **Lista wszystkich trafień** jako klikalna tabela (strona + fragment) | szybszy przegląd przy wielu wystąpieniach | S |

### 6.4. Nowe typy dokumentów i porównania między nimi

| Pomysł | Korzyść | Nakład |
|---|---|---|
| **Umowa przedwstępna i rezerwacyjna** (schemat + widok) | ten sam proces dla kolejnych dokumentów z wniosku | M na typ |
| **Prospekt informacyjny** | stan prawny inwestycji, hipoteki banku finansującego | M |
| **Oświadczenie zbywcy** | zakres pól do ustalenia z analitykami | M |
| **Porównanie między dokumentami** wniosku (cena, KW, lokal, terminy w rezerwacyjnej a deweloperskiej) | wyłapuje zmiany między etapami transakcji | L |
| **Rozpoznawanie typu dokumentu** po wgraniu | mniej pomyłek przy wyborze zakładki | M |
| **Umowa w kilku plikach** (np. osobny załącznik z harmonogramem) | obsługa realnych paczek dokumentów | M |

### 6.5. Praca analityka

| Pomysł | Korzyść | Nakład |
|---|---|---|
| **Decyzja przy ustaleniu:** „wyjaśnione / do klienta / błąd odczytu” z komentarzem, zapisywana w hurtowni | ślad audytowy i dane o trafności ustaleń | M |
| **Notatka do wniosku** generowana z ustaleń, podsumowania i ryzyk (tekst do wklejenia albo PDF) | mniej ręcznego przepisywania | M |
| **Kopiowanie wszystkich pól naraz** w kolejności formularza UniFlow | szybsze przepisywanie | S |
| **Historia analiz wniosku** (kto, kiedy, jaki dokument, jaka wersja schematu) | powrót do wcześniejszych analiz, audyt | M |

### 6.6. Jakość modelu i monitoring

| Pomysł | Korzyść | Nakład |
|---|---|---|
| **Zbiór wzorcowy** 20–30 zanonimizowanych umów z poprawnymi wynikami i skrypt porównujący | każdą zmianę promptu można zmierzyć przed wdrożeniem | M |
| **Zapis metryk:** czasy OCR i ekstrakcji, liczba odrzuconych wartości, puste pola, ustalenia wg typu | widać, gdzie model się myli i czy zmiany pomagają | S |
| **Wersja schematu zapisana przy wyniku w cache** | wiadomo, na jakie pytanie odpowiadał stary wynik | S |
| **Informacja zwrotna od analityka** (z 6.5) jako materiał do poprawy promptu | poprawki oparte na danych, nie na przeczuciu | M |

### 6.7. Porządki techniczne

| Pomysł | Korzyść | Nakład |
|---|---|---|
| **Escapowanie HTML** w starszych widokach | domyka zasadę „tekst z zewnątrz jest niezaufany” | S |
| **Test na prawdziwej odpowiedzi OCR** (zanonimizowany fragment) | pewność, że podział stron i tabele działają na produkcji | S |
| **Limit rozmiaru i liczby stron PDF** z czytelnym komunikatem | brak przekroczeń czasu przy bardzo dużych plikach | S |
| **Analiza w tle** z paskiem postępu (OCR, ekstrakcja) | analityk widzi, na jakim etapie jest analiza | M |

---

## 7. Proponowana kolejność prac

1. **Zrobione:** szukajka po typie frazy, schemat z trzema poziomami i podział
   „ok / zła” liczony przez Python. Teraz obserwacja na prawdziwych umowach (6.1).
2. **Szybkie korzyści (S):**
   - kontrole NIP, KW, PESEL z UniFlow i terminów (6.2);
   - escapowanie HTML i test na prawdziwym OCR (6.7);
   - zapis metryk (6.6).
3. **Zbiór wzorcowy umów (6.6)** — zanim zaczniemy intensywniej zmieniać prompt.
4. **Decyzje przy ustaleniach i notatka do wniosku (6.5)** — największa oszczędność
   czasu analityka.
5. **Kolejne typy dokumentów i porównania między nimi (6.4).**

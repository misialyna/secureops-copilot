# Notatki z wdrożenia — Etap 10 (Railway + Neon + Langfuse, produkcja)

Stan na koniec dnia. Zasada jak przy sesji odbiorczej Etapu 7: to są notatki robocze,
nie finalny raport — kolejne dni dopisują do tego samego pliku.

## Co działa

- **Build na Railway** — `railway.toml` (`builder = "DOCKERFILE"`) wymusza `docker/Dockerfile`
  zamiast automatycznej detekcji Railpack. Obraz buduje się poprawnie, 3.14GB (po fixie
  torch CPU-only — zobacz commit `426a069`).
- **Publiczny URL działa**, `GET /health` odpowiada `200 OK`.
- **Connection pool fix do Neona** (`AsyncConnectionPool` + `check=AsyncConnectionPool
  .check_connection` w `backend/app/graph/checkpointer.py`, commit `08accfd`) — potwierdzony
  lokalnie realnym testem (zabicie połączenia przez `pg_terminate_backend` z zewnątrz +
  transparentne odzyskanie bez błędu). **Nie potwierdzony jeszcze na żywo na Railway** — test
  zaplanowany: odczekać kilka minut bezczynności od startu kontenera (na tyle, żeby Neon zdążył
  uśpić połączenie), potem kliknąć "Rozpocznij analizę" w UI.

## Do zdiagnozowania jutro

### 1. Podejrzenie OOM przy pierwszym `/start` (model embeddingowy)

**Objaw**: kontener restartuje się w trakcie obsługi `/start` — w logach widać długie ładowanie
modelu embeddingowego (bge-m3), ~60s kodowania jednego batcha, a zaraz potem drugi
`Started server process [1]` (czyli restart, nie łagodne zakończenie requestu).

**Zweryfikowane w kodzie w tej sesji** (`backend/app/rag/retriever.py`):
- `_get_embedding_model()` i `get_retriever()` SĄ poprawnie cache'owane przez
  `@lru_cache(maxsize=1)` — to nie jest bug cache'owania w obrębie jednego procesu.
- Ważna nuansa co do timingu: `get_retriever()` (obiekt `KnowledgeRetriever` + `QdrantClient`)
  jest budowany **eagerly** w `lifespan()` przy starcie kontenera (przez `build_graph()`), ale
  sam model `SentenceTransformer` (bge-m3, ~2GB wag) ładuje się **leniwie** — dopiero przy
  pierwszym realnym wywołaniu `search()`, czyli w trakcie obsługi pierwszego `/start`, nie
  wcześniej. To dokładnie tłumaczy zaobserwowany timing (długie ładowanie + kodowanie widoczne
  w logach requestu, nie w logach startu).
- **Jeśli kontener restartuje się (OOM), nowy proces musi załadować model od zera** — to może
  wyglądać jak "model się nie cache'uje", ale to oczekiwane zachowanie po restarcie procesu
  (cache w pamięci nie przeżywa restartu), nie defekt logiki cache'owania. Jeśli realną
  przyczyną restartu jest OOM w trakcie ładowania/kodowania, każdy kolejny restart powtórzy
  dokładnie ten sam kryzys (crash-loop) — trzeba to potwierdzić, zanim naprawimy złą rzecz.

**Niezakończone w tej sesji**:
- Brak dokładnej liczby peak RAM z Railway Metrics — użytkowniczka nie zdążyła jej wkleić.
- Nie zmierzono jeszcze peak RAM lokalnie przez `docker stats` podczas testowego `/start`.

**Potencjalne kierunki naprawy (niezweryfikowane, do rozważenia jutro, w kolejności najtańsze
najpierw)**:
1. Mniejszy `batch_size` przy `model.encode()` w `KnowledgeRetriever.search()` — ale UWAGA:
   `search()` koduje pojedyncze zapytanie (1 string), nie batch dokumentów — batch_size
   prawdopodobnie nie jest tu istotny; to `app/rag/ingest.py` koduje 286 chunków w batchach, a
   to dzieje się przy BUDOWIE obrazu (Dockerfile), nie w runtime. Do zweryfikowania, czy 60s
   "kodowania" w logu produkcyjnym to w ogóle `ingest`, czy pojedyncze zapytanie `search()` —
   pojedyncze zapytanie nie powinno trwać 60s, więc to podejrzane i wymaga sprawdzenia, co
   dokładnie loguje się w tym momencie.
2. `torch.set_num_threads(1)` — ograniczenie liczby wątków, które torch domyślnie próbuje
   wykorzystać (na małym/tanim CPU Railway może to obniżyć zarówno czas, jak i szczytowe
   zużycie pamięci przy alokacji buforów per-wątek).
3. Sprawdzić, czy limit RAM darmowego tieru Railway w ogóle mieści model ~2GB + reszta stosu
   (FastAPI, torch runtime, connection pool do Neona, Langfuse SDK) — jeśli nie, jedyna trwała
   naprawa to większy plan, mniejszy model embeddingowy, albo model serwowany zewnętrznie.
4. Rozważyć eager-loading modelu w `lifespan()` zamiast leniwego ładowania przy pierwszym
   `search()` — nie zmniejszy to zużycia pamięci, ale ujawni OOM od razu przy starcie
   kontenera (czytelny, wczesny fail) zamiast w trakcie obsługi żądania użytkownika.

### 2. Langfuse: 401 przy eksporcie trace'ów

**Podejrzenie**: zła wartość jednej ze zmiennych w Railway Variables (`LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) — literówka, wklejony niewłaściwy klucz, albo brak
jednej z trzech. Niezdiagnozowane w tej sesji.

## Pierwszy krok jutro

Sprawdzić wykres **Memory** w zakładce **Metrics** w Railway — dokładna wartość peak RAM
podczas obsługi `/start` jest kluczowa do potwierdzenia (albo obalenia) hipotezy OOM i wyboru
dalszego kierunku naprawy z listy powyżej.

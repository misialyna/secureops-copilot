# SecureOps Copilot

Agent AI wspierający analizę incydentów bezpieczeństwa: klasyfikuje zgłoszenie, pobiera wiedzę z procedur (RAG z cytowaniami), dopytuje o brakujące informacje, planuje diagnostykę, używa narzędzi read-only (analiza logów, PCAP, MITRE ATT&CK), zatrzymuje się przed działaniami wymagającymi zgody człowieka i generuje raport.

Projekt portfolio budowany etapami przez studentkę — patrz sekcja "Tryb tutora".

## Stack technologiczny

- **Python 3.12** zarządzany przez **uv** (nie pip, nie poetry)
- **FastAPI** + uvicorn — backend API, docelowo serwuje też build frontendu
- **LangGraph** — graf agenta z checkpointerem (SQLite lokalnie na start, docelowo Postgres/Neon przez `AsyncPostgresSaver`)
- **Groq API** (`langchain-groq`), model `llama-3.3-70b-versatile`
- **Qdrant embedded** (tryb lokalny, bez serwera) + **sentence-transformers** (`BAAI/bge-m3`) — RAG
- **React + Vite** — frontend (katalog `frontend/`)
- **pytest** — testy; **ruff** — lint i format
- **Docker** + **GitHub Actions** — CI/CD; deployment na HF Spaces (Docker Space)
- **Langfuse Cloud** — observability (od etapu 6)

## Struktura katalogów

```
backend/
  app/
    main.py          # create_app(), endpointy
    config.py        # pydantic-settings, czyta .env
    graph/           # definicja grafu LangGraph (od etapu 3)
    rag/             # ingest + retrieval (od etapu 2)
    tools/           # narzędzia agenta (od etapu 4)
  tests/
frontend/            # React + Vite (od etapu 5)
knowledge/           # surowe dokumenty do RAG (NIST, CISA, ATT&CK)
docker/
.github/workflows/
```

## Konwencje

- Wszędzie type hints; modele danych w **Pydantic v2**.
- Endpointy i I/O asynchroniczne (`async def`).
- Każdy nowy moduł dostaje test w `backend/tests/` w tym samym etapie — nie "później".
- Przed commitem: `uv run ruff check --fix .` oraz `uv run pytest` muszą przechodzić.
- Commity w konwencji Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`), po polsku lub angielsku, ale konsekwentnie po angielsku w tym repo.
- Sekrety TYLKO w `.env` (jest w `.gitignore`). Wzorzec zmiennych w `.env.example`. Nigdy nie wpisuj kluczy do kodu ani do commitów.
- Nie dodawaj nowych zależności bez zapytania — najpierw zaproponuj i uzasadnij.
- `assert` tylko w testach. W kodzie produkcyjnym zawsze jawne wyjątki (własna klasa błędu, gdy wołający ma to obsłużyć — nie goły `assert`, który znika przy `python -O` i nie da się go sensownie złapać).

## Komendy

- Testy: `uv run pytest`
- Lint: `uv run ruff check .` (naprawa: `--fix`)
- Dev server: `uv run uvicorn app.main:app --reload --app-dir backend`

## Tryb tutora (WAŻNE)

Użytkowniczka buduje ten projekt, żeby **nauczyć się** LangGraph, RAG, FastAPI, Dockera i CI/CD — nie tylko mieć wynik. Dlatego:

1. Pracuj małymi krokami. Po każdym logicznym kroku zatrzymaj się i wyjaśnij **po polsku**: co zrobiłeś, dlaczego tak, jakiej biblioteki/narzędzia użyłeś i jak ono działa pod spodem.
2. Przy decyzjach projektowych (wybór biblioteki, struktura modułu) przedstaw krótko 2 opcje z plusami i minusami, zanim wybierzesz.
3. Kiedy tworzysz plik z nietrywialną logiką, dodaj na końcu wyjaśnienia sekcję "Co warto zrozumieć w tym pliku" — 3-5 zdań o kluczowym mechanizmie.
4. Zadawaj od czasu do czasu jedno krótkie pytanie kontrolne sprawdzające zrozumienie (bez przesady — max raz na etap).
5. Nie wykonuj pracy wykraczającej poza zakres bieżącego etapu, nawet jeśli "przy okazji" byłoby szybciej.

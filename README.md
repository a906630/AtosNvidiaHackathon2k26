# CZK - Centrum Zarzadzania Kryzysowego

Wieloagentowy system wspierajacy centrum kryzysowe: **FastAPI + LangGraph + NVIDIA NIM + open-source observability**.

## Co jest zaimplementowane

- wyspecjalizowani agenci domenowi: `flood`, `cyber`, `terror`, `infrastructure`, `traffic`
- orchestracja przez `supervisor -> domain_verifier -> cross_domain_correlator -> priority_assessor -> comms_generator`
- **cross-domain correlator analizuje snapshot ostatnio dodanych incydentów** (do 25 rekordów) w celu wychwycenia korelacji i zależności między zgłoszeniami, nie tylko bieżące incydent
- końcowe zalecenia (`recommended_actions`) oraz komunikaty (`service_message`, `citizen_message`) są generowane w języku polskim
- metryki naplywu zgloszen w czasie rzeczywistym
- analiza publicznych zrodel danych dla Polski
- stack open-source (bez platnego search API)

## Pydantic i standard serializacji

Kontrakty API sa walidowane i serializowane przez modele z `app/schemas.py`:

- `IncidentInput`, `IncidentResponse`, `IncidentResult`
- `RealtimeLoad`
- `MermaidGraphResponse`, `GraphJsonResponse`, `GraphRunPreviewResponse`

Dzieki temu endpointy maja stabilny format odpowiedzi i lepsza dokumentacje OpenAPI.

## Multi-incident correlation

`cross_domain_correlator` node analizuje snapshot do 25 ostatnio dodanych incydentów ze store:

- Wczytuje historię z `app/store.py::get_recent_incidents(limit=25)` na starcie przepływu
- Buduje kontekst Multi-incydentowy w promptzie LLM
- Wyświetla w diagnostyce: `processing_log[...].details.analyzed_recent_incidents`
- Zwraca w `cross_domain_relations.analyzed_recent_incidents` - ile incydentów zjadło analiza

Dzięki temu corelator dostrzega wzorce całego systemu, a nie tylko izolowany incydent.

## Modele per agent (NVIDIA NIM)

Aplikacja używa backendu NVIDIA NIM (`NVIDIA_BASE_URL`) i pozwala przypisać osobny model do każdej roli agenta.

### Rekomendacja modeli (jakość vs koszt)

- `supervisor` -> `meta/llama-3.1-8b-instruct`
  - szybka klasyfikacja i routing, niski koszt inferencji
- `domain_verifier` -> `meta/llama-3.3-70b-instruct`
  - najlepsza jakość syntezy OSINT i oceny wiarygodności sygnałów
- `cross_domain_correlator` -> `meta/llama-3.1-70b-instruct`
  - lepsze wnioskowanie relacyjne między wieloma incydentami
- `priority_assessor` -> `meta/llama-3.1-70b-instruct`
  - stabilniejsze decyzje priorytetyzacji na tle realtime load
- `comms_generator` -> `meta/llama-3.1-70b-instruct`
  - bardziej spójne komunikaty operacyjne i publiczne

Modele mogą się powtarzać między agentami (to celowe i wspierane).

### Konfiguracja ENV

W `.env` możesz ustawić mapowanie agent -> model:

```dotenv
NVIDIA_BASE_URL=http://localhost:8000/v1
NVIDIA_API_KEY=no-key
NVIDIA_MODEL=meta/llama-3.3-70b-instruct

NVIDIA_MODEL_SUPERVISOR=meta/llama-3.1-8b-instruct
NVIDIA_MODEL_DOMAIN_VERIFIER=meta/llama-3.3-70b-instruct
NVIDIA_MODEL_CROSS_DOMAIN_CORRELATOR=meta/llama-3.1-70b-instruct
NVIDIA_MODEL_PRIORITY_ASSESSOR=meta/llama-3.1-70b-instruct
NVIDIA_MODEL_COMMS_GENERATOR=meta/llama-3.1-70b-instruct
```

Jeśli nie ustawisz zmiennych per-agent, aplikacja użyje `NVIDIA_MODEL` jako fallback.

## Endpointy API

### Incident API

- `POST /api/v1/incidents` - przyjecie zgloszenia
- `GET /api/v1/incidents/{incident_id}/result` - finalny wynik
- `GET /api/v1/incidents` - lista zgloszen
- `GET /api/v1/metrics/live?window_minutes=15` - metryki realtime

### Visualization API

- `GET /viz/stream/{incident_id}` - live SSE z krokow agentow
- `GET /viz/graph` - topologia jako Mermaid
- `GET /viz/graph/json` - topologia jako JSON (nodes + edges)
- `GET /viz/output/{incident_id}` - podglad danych wyjsciowych jako JSON

### System

- `GET /health` - status systemu + GPU info + tracing URL

## Troubleshooting (NVIDIA NIM + guardrails)

- `LLM Guard unavailable: No module named 'llm_guard'`
  - oznacza brak pakietu `llm-guard`; aplikacja przechodzi wtedy na regex fallback
  - po instalacji zależności (`pip install -r requirements.txt`) pełny pipeline guardrails powinien działać
- `Correlator LLM error: [404] Not Found`
  - zwykle oznacza model niedostępny na danej instancji NIM
  - sprawdź katalog modeli: `GET /v1/models` i dopasuj `.env`
  - aplikacja waliduje mapowanie agent->model i próbuje fallback do `NVIDIA_MODEL`
  - dodatkowo przy `404 model_not_found` wykonywany jest retry z modelem fallbackowym
- brak widocznych zapytań do mediów/search w logach
  - domain verifiers logują teraz każde zapytanie i status odpowiedzi (`[flood_verifier] search query: ...`)
  - jeśli widzisz `search-tool-unavailable`, środowisko nie ma działającego backendu wyszukiwania

## Publiczne zrodla danych (Polska)

Przykladowe zrodla z katalogu `app/data/public_sources.py`:

- powodzie: IMGW, RCB, Hydroportal, sygnaly X
- cyber: CERT Polska, CSIRT GOV, NASK, Zaufana Trzecia Strona
- terror: RCB, ABW, Policja, komunikaty panstwowe
- infrastruktura: GDDKiA, PKP PLK, PSE, dane.gov.pl
- ruch: GDDKiA mapa drog, API UM Warszawa, Jakdojade

## Uruchomienie lokalne

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
python main.py
```

Po starcie:

- app: `http://localhost:8000`
- docs: `http://localhost:8000/docs`
- traces (Phoenix): `http://localhost:6006`

## Uruchomienie w Docker (GPU)

W repo są gotowe pliki: `Dockerfile`, `.dockerignore`, `docker-compose.yml`.

### Build obrazu

```bash
docker build -t czk-api:latest .
```

### Run kontenera (GPU + host NIM)

> Dla scenariusza, gdzie NIM działa na hoście Brev na porcie `8000`.

```bash
docker run --rm -it \
  --gpus all \
  --network host \
  --env-file .env \
  -e APP_PORT=8080 \
  -e NVIDIA_BASE_URL=http://localhost:8000/v1 \
  czk-api:latest
```

API będzie wtedy dostępne na `http://localhost:8080`.

### Alternatywa: docker compose

`docker-compose.yml` mapuje port `8080` dla API i `6006` dla Phoenix.
Jeśli NIM działa na hoście Linux/Brev, ustaw w `.env`:

`NVIDIA_BASE_URL=http://host.docker.internal:8000/v1`

Następnie uruchom:

```bash
docker compose up --build
```

### Skróty przez Makefile

Repo zawiera `Makefile`, który opakowuje najczęstsze komendy Docker Compose.

```bash
make build
make up-d
make logs
make smoke
make down
```

---

## Deployment na NVIDIA Brev (L40S) - krok po kroku

Poniższe kroki zakładają, że instancja ma dostęp do internetu i GPU.

### Krok 1 - wybierz instancję

Minimalny rekomendowany profil dla tego projektu: **1x L40S**.

Dlaczego L40S:

1. Dużo lepszy zapas VRAM niż T4/L4 dla większych modeli NIM.
2. Stabilniejsza latencja przy równoległych requestach agentów.
3. Lepszy margines dla dodatkowego obciążenia (np. reranking CUDA).

### Krok 2 - przygotuj środowisko

```bash
git clone {{repo_address}}
cd NvidiaHackathon2k26
cp .env.example .env
```

### Krok 3 - uruchom NIM na hoście Brev

Upewnij się, że lokalny endpoint NIM odpowiada na porcie `8000` (lub dostosuj port).

Przykład szybkiej weryfikacji:

```bash
curl http://localhost:8000/v1/models
```

### Krok 4 - zbuduj obraz aplikacji

```bash
docker build -t czk-api:latest .
```

### Krok 5 - uruchom kontener aplikacji na L40S

W trybie host-network `localhost:8000` wskazuje hostowy NIM, a API uruchamiamy na `8080`, by uniknąć konfliktu portów.

```bash
docker run --rm -it \
  --gpus all \
  --network host \
  --env-file .env \
  -e APP_PORT=8080 \
  -e NVIDIA_BASE_URL=http://localhost:8000/v1 \
  czk-api:latest
```

### Krok 6 - smoke test

```bash
curl http://localhost:8080/health
curl http://localhost:8080/viz/graph/json
```

W odpowiedzi `/health` sprawdź:

- `status: ok`
- `gpu.cuda_available: true` (jeśli środowisko ma poprawnie podpięte GPU)
- poprawny `nvidia_base_url`

### Krok 7 - wariant z docker compose

W `.env` ustaw URL do hosta:

`NVIDIA_BASE_URL=http://host.docker.internal:8000/v1`

```bash
docker compose up --build
```

### Krok 8 - operacyjnie (rekomendacje)

1. Wlacz forward portow: `8080` (API), `6006` (Phoenix).
2. Trzymaj `APP_DEBUG=false` poza demo.
3. Przenies in-memory store do Redis/PostgreSQL przy dluzszym uzyciu.
4. Dla wiekszego ruchu uruchamiaj przez process manager (np. `gunicorn` + `uvicorn workers`).

## Struktura projektu

```text
main.py
requirements.txt
.env.example
Makefile
Dockerfile
.dockerignore
docker-compose.yml
langgraph.json
app/
  config.py
  store.py
  observability.py
  schemas.py
  data/
    public_sources.py
  agents/
    state.py
    tools.py
    cuda_utils.py
    graph.py
  api/
    incidents.py
    visualization.py
static/
  dashboard.html
```

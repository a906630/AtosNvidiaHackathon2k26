# CZK - Centrum Zarzadzania Kryzysowego

Wieloagentowy system wspierajacy centrum kryzysowe: **FastAPI + LangGraph + NVIDIA NIM + open-source observability**.

## Co jest zaimplementowane

- wyspecjalizowani agenci domenowi: `flood`, `cyber`, `terror`, `infrastructure`, `traffic`
- orchestracja przez `supervisor -> domain_verifier -> cross_domain_correlator -> priority_assessor -> comms_generator`
- metryki naplywu zgloszen w czasie rzeczywistym
- analiza publicznych zrodel danych dla Polski
- stack open-source (bez platnego search API)

## Pydantic i standard serializacji

Kontrakty API sa walidowane i serializowane przez modele z `app/schemas.py`:

- `IncidentInput`, `IncidentResponse`, `IncidentResult`
- `RealtimeLoad`
- `MermaidGraphResponse`, `GraphJsonResponse`, `GraphRunPreviewResponse`

Dzieki temu endpointy maja stabilny format odpowiedzi i lepsza dokumentacje OpenAPI.

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

---

## Deployment na NVIDIA Brev - krok po kroku

Poniższe kroki zakladaja, ze instancja ma dostep do internetu i GPU.

### Krok 1 - wybierz instancje

Rekomendacje (praktyczne):

1. **MVP / szybkie demo**: T4 lub L4 (nizszy koszt, wystarczajace do testow przeplywu).
2. **Lepsza responsywnosc i wiekszy ruch**: A10G / L40.
3. **Ciezsze modele, duze obciazenie**: A100/H100.

### Krok 2 - przygotuj srodowisko

```bash
git clone {{repo_address}}
cd NvidiaHackathon2k26
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Krok 3 - zainstaluj CUDA-enabled PyTorch i zaleznosci

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

### Krok 4 - skonfiguruj ENV

```bash
cp .env.example .env
```

Ustaw w `.env`:

- `NVIDIA_BASE_URL` (lokalny NIM lub chmura NVIDIA)
- `NVIDIA_MODEL`
- `NVIDIA_API_KEY` (`no-key` dla local NIM)

### Krok 5 - uruchom aplikacje

```bash
python main.py
```

### Krok 6 - smoke test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/viz/graph/json
```

### Krok 7 - operacyjnie (rekomendacje)

1. Wlacz forward portow: `8000` (API), `6006` (Phoenix).
2. Trzymaj `APP_DEBUG=false` poza demo.
3. Przenies in-memory store do Redis/PostgreSQL przy dluzszym uzyciu.
4. Dla wiekszego ruchu uruchamiaj przez process manager (np. `gunicorn` + `uvicorn workers`).

## Struktura projektu

```text
main.py
requirements.txt
.env.example
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

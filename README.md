# 🛡️ Sikor8 — Crisis Management Center

> Wieloagentowy system AI wspierający centrum zarządzania kryzysowego.
> Zbudowany na **NVIDIA NIM + LangGraph + FastAPI** z pełną obserwowalnością i sceptycznym modelem weryfikacji wiarygodności.

---

## 📐 Architektura systemu

```mermaid
graph TB
    subgraph "🖥️ Frontend"
        DASH[Dashboard HTML/JS]
        SSE[SSE Live Stream]
    end

    subgraph "⚡ FastAPI Backend"
        API[REST API :8080]
        VIZ[Visualization API]
        STORE[(In-Memory Store)]
    end

    subgraph "🧠 LangGraph Multi-Agent Pipeline"
        SUP[🎯 Supervisor Agent]
        FV[🌊 Flood Verifier]
        CV[💻 Cyber Verifier]
        TV[🚨 Terror Verifier]
        IV[🏗️ Infrastructure Verifier]
        TRV[🚗 Traffic Verifier]
        CDC[🔁 Cross-Domain Correlator]
        PA[⚖️ Priority Assessor]
        CG[📢 Comms Generator]
    end

    subgraph "🟢 NVIDIA Stack"
        NIM[NVIDIA NIM<br/>LLM Inference]
        CUDA[CUDA Reranker<br/>sentence-transformers]
        GPU[NVIDIA GPU<br/>L40S / A100 / T4]
    end

    subgraph "🔍 External Sources"
        DDG[DuckDuckGo Search]
        PUB[Polish Public Sources<br/>IMGW, CERT, RCB, GDDKiA]
    end

    subgraph "🔭 Observability"
        PHX[Arize Phoenix :6006<br/>Traces + Latency]
        OTEL[OpenTelemetry SDK]
    end

    DASH -->|POST /api/v1/incidents| API
    API --> SUP
    SUP -->|fan-out| FV & CV & TV & IV & TRV
    FV & CV & TV & IV & TRV --> CDC
    CDC --> PA --> CG
    CG -->|result| STORE
    VIZ -->|SSE events| SSE
    SSE --> DASH

    FV & CV & TV & IV & TRV -->|search queries| DDG
    FV & CV & TV & IV & TRV -->|curated URLs| PUB
    FV & CV & TV & IV & TRV -->|rerank results| CUDA

    SUP & FV & CV & TV & IV & TRV & CDC & PA & CG -->|LLM inference| NIM
    NIM --> GPU
    CUDA --> GPU

    API & SUP & FV & CV & TV & IV & TRV & CDC & PA & CG -->|traces| OTEL --> PHX
```

---

## 🔄 Przepływ przetwarzania incydentu

```mermaid
sequenceDiagram
    actor User as 👤 Operator / Obywatel
    participant API as ⚡ FastAPI
    participant SUP as 🎯 Supervisor
    participant NIM as 🟢 NVIDIA NIM
    participant VER as 🔍 Domain Verifiers (×5)
    participant DDG as 🌐 DuckDuckGo
    participant CUDA as 🖥️ CUDA Reranker
    participant CRED as 📊 Credibility Model
    participant CDC as 🔁 Cross-Domain Correlator
    participant PRI as ⚖️ Priority Assessor
    participant COM as 📢 Comms Generator
    participant DASH as 🖥️ Dashboard

    User->>API: POST /api/v1/incidents
    API->>SUP: Przekaż incydent
    SUP->>NIM: Klasyfikuj kategorię
    NIM-->>SUP: {category: "flood", related: ["infrastructure"]}
    SUP->>VER: Fan-out do wybranych verifierów

    par Parallel Verification
        VER->>DDG: Zapytania wyszukiwania (×8)
        DDG-->>VER: Surowe wyniki
        VER->>CUDA: Reranking (GPU accelerated)
        CUDA-->>VER: Top-K wyniki
        VER->>CRED: Compute credibility score
        CRED-->>VER: {score: 0.25, risk: 0.55}
        VER->>NIM: Krytyczna analiza snippetów
        NIM-->>VER: {credibility_score, reasoning}
        VER->>CRED: Bound LLM output
        CRED-->>VER: Bounded score [min, max]
    end

    VER->>CDC: Wyniki weryfikacji
    CDC->>NIM: Analiza cross-domain (25 recent incidents)
    NIM-->>CDC: {dependency_graph, related_categories}

    CDC->>PRI: Credibility + correlations
    PRI->>NIM: Priorytetyzacja z sanity checks
    NIM-->>PRI: {priority: "P3_MEDIUM"}

    PRI->>COM: Priority + recommended_actions
    COM->>NIM: Generuj komunikaty (PL)
    NIM-->>COM: {service_message, citizen_message}

    COM-->>API: Pełny wynik
    API-->>DASH: SSE stream events
    DASH-->>User: 🎉 Wynik na dashboardzie
```

---

## 🟢 NVIDIA Technology Stack

### NVIDIA NIM (Neural Inference Microservice)

| Komponent | Rola | Szczegóły |
|---|---|---|
| **NVIDIA NIM** | Inferencja LLM | Lokalna lub chmurowa inferencja modeli Meta Llama |
| **Per-agent routing** | Optymalizacja | Każdy agent może korzystać z innego modelu NIM |
| **Automatic fallback** | Resilience | Przy 404 model_not_found → automatyczny retry z katalogiem NIM |
| **Model catalog** | Discovery | `GET /v1/models` — automatyczne mapowanie dostępnych modeli |

```mermaid
graph LR
    subgraph "NVIDIA NIM Endpoint (:8000)"
        CATALOG[Model Catalog API]
        LLM8B[meta/llama-3.1-8b-instruct<br/>⚡ Fast · Low cost]
        LLM70B[meta/llama-3.3-70b-instruct<br/>🎯 High quality]
    end

    SUP[Supervisor] -->|fast classification| LLM8B
    VER[Domain Verifiers] -->|deep analysis| LLM70B
    CDC[Correlator] -->|multi-incident reasoning| LLM70B
    PRI[Priority Assessor] -->|stable decisions| LLM8B
    COM[Comms Generator] -->|Polish text gen| LLM8B

    APP[App Startup] -->|resolve models| CATALOG
```

### NVIDIA CUDA — GPU-Accelerated Reranking

Moduł `app/agents/cuda_utils.py` implementuje **CUDA-accelerated semantic reranking**:

```mermaid
graph LR
    RAW[Surowe wyniki wyszukiwania<br/>8-16 snippetów] -->|GPU inference| RERANKER[sentence-transformers<br/>cross-encoder on CUDA]
    RERANKER -->|Top-K sorted| TOP[Top 4 najistotniejsze<br/>snippety]
    TOP --> LLM[LLM Verifier<br/>via NVIDIA NIM]

    style RERANKER fill:#76b900,color:#000
```

- **Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2` na GPU
- **Zadanie**: Reranking wyników DuckDuckGo wg relevancji do opisu incydentu
- **Hardware**: Wykrywa CUDA automatycznie, fallback na CPU
- **Wpływ**: Eliminuje szum z wyników wyszukiwania zanim trafią do LLM

### NVIDIA GPU Requirements

| Profil | GPU | VRAM | Rekomendacja |
|---|---|---|---|
| **Minimum** | T4 | 16 GB | Tylko 8B modele |
| **Rekomendowany** | L40S | 48 GB | 8B + 70B mixed routing |
| **Optymalny** | A100 | 80 GB | Pełny 70B dla wszystkich agentów |

### Integracja z NVIDIA Brev

```mermaid
graph TB
    subgraph "NVIDIA Brev Instance (L40S)"
        NIM_HOST[NVIDIA NIM :8000<br/>meta/llama-3.3-70b]
        subgraph "Docker Container"
            APP[Sikor8 API :8080]
            PHX[Phoenix :6006]
            CUDA_RE[CUDA Reranker]
        end
        GPU[L40S GPU 48GB VRAM]
    end

    APP -->|host.docker.internal:8000| NIM_HOST
    NIM_HOST --> GPU
    CUDA_RE --> GPU
    
    USER[👤 Remote User] -->|port forward :8080| APP
    USER -->|port forward :6006| PHX
```

---

## 📊 Sceptyczny model weryfikacji wiarygodności

System implementuje philosophy **"START SKEPTICAL — EARN TRUST"**:

```mermaid
graph TD
    INC[📥 Incydent] --> BASE[Baseline: 10%<br/>Każde zgłoszenie startuje nisko]
    BASE --> SEARCH[🔍 Wyszukiwanie publicznych źródeł]
    
    SEARCH -->|brak wyników| LOW[❌ Max 25%<br/>Brak niezależnej weryfikacji]
    SEARCH -->|1 źródło| MED_LOW[⚠️ Max 50%<br/>Ograniczona koroboracja]
    SEARCH -->|2+ niezależne źródła| ANALYZE[📊 Analiza koherencji]
    
    ANALYZE -->|echo wyszukiwarki| ECHO[Echo penalty<br/>Wynik × 0.25]
    ANALYZE -->|nowe szczegóły w źródłach| CORR[✅ Corroboration bonus<br/>overlap + new_info]
    
    ECHO --> BOUNDED[🔒 LLM Bounds<br/>Constraining hallucinated confidence]
    CORR --> BOUNDED
    
    BOUNDED --> FINAL[Final credibility score]
    FINAL -->|< 35%| P4[P4_LOW priority]
    FINAL -->|35-50%| P3[P3_MEDIUM priority]
    FINAL -->|50-75%| P2[P2_HIGH priority]
    FINAL -->|> 75% + corroborated| P1[P1_CRITICAL priority]

    style BASE fill:#7f1d1d,color:#fca5a5
    style LOW fill:#7f1d1d,color:#fca5a5
    style CORR fill:#14532d,color:#86efac
    style P1 fill:#7f1d1d,color:#fca5a5
    style P4 fill:#14532d,color:#86efac
```

### Kluczowe mechanizmy anty-zawyżania

| Mechanizm | Opis |
|---|---|
| **Low baseline (10%)** | Niezweryfikowane zgłoszenie startuje na minimum |
| **Echo detection** | Wyniki wyszukiwania powtarzające query ≠ niezależna weryfikacja |
| **New info requirement** | True corroboration wymaga NOWYCH szczegółów w źródłach |
| **Evidence caps** | 0 wyników → max 25%, 1 wynik → max 50% |
| **LLM bounds** | Output LLM ograniczony do [min, max] wg ilości evidence |
| **Deepfake risk** | Startuje wysoko (55%), spada tylko z corroboration |
| **Priority sanity check** | Niska wiarygodność + wysoki deepfake risk → max P3 |

---

## 🛠️ Wykorzystywane technologie

### NVIDIA Ecosystem

| Technologia | Zastosowanie |
|---|---|
| **NVIDIA NIM** | Inferencja LLM (Llama 3.1/3.3) — lokalna lub cloud |
| **NVIDIA CUDA** | GPU-accelerated semantic reranking |
| **NVIDIA Brev** | Hosting instancji z GPU (L40S) |
| **NVIDIA Container Toolkit** | Docker + GPU passthrough |
| **langchain-nvidia-ai-endpoints** | Python SDK do NIM API |

### AI / ML Stack

| Technologia | Zastosowanie |
|---|---|
| **LangGraph** | Orchestracja multi-agent workflow z fan-out/fan-in |
| **LangChain** | Abstrakcja LLM calls + tool integration |
| **sentence-transformers** | Cross-encoder reranking na GPU |
| **PyTorch (CUDA)** | Runtime dla modeli reranking |

### Application Stack

| Technologia | Zastosowanie |
|---|---|
| **FastAPI** | REST API + SSE streaming + OpenAPI docs |
| **Pydantic v2** | Walidacja schematów, typed contracts |
| **DuckDuckGo Search** | Open-source OSINT (zero API keys) |
| **Arize Phoenix** | Observability — traces, latency, token usage |
| **OpenTelemetry** | Distributed tracing SDK |

### Infrastructure

| Technologia | Zastosowanie |
|---|---|
| **Docker** | Konteneryzacja z NVIDIA runtime |
| **Docker Compose** | Orchestracja usług |
| **CUDA 12.4 + cuDNN** | Base image (`nvidia/cuda:12.4.1-cudnn-runtime`) |

---

## 🏗️ Modele per agent (NVIDIA NIM)

Aplikacja pozwala przypisać osobny model NIM do każdego agenta:

| Agent | Rekomendowany model | Uzasadnienie |
|---|---|---|
| `supervisor` | `meta/llama-3.1-8b-instruct` | Szybka klasyfikacja, niski koszt |
| `domain_verifier` | `meta/llama-3.3-70b-instruct` | Najlepsza jakość analizy OSINT |
| `cross_domain_correlator` | `meta/llama-3.1-70b-instruct` | Wnioskowanie relacyjne multi-incident |
| `priority_assessor` | `meta/llama-3.1-8b-instruct` | Stabilne decyzje z sanity checks |
| `comms_generator` | `meta/llama-3.1-8b-instruct` | Szybkie generowanie komunikatów PL |

```dotenv
# .env
NVIDIA_BASE_URL=http://localhost:8000/v1
NVIDIA_API_KEY=no-key
NVIDIA_MODEL=meta/llama-3.3-70b-instruct

NVIDIA_MODEL_SUPERVISOR=meta/llama-3.1-8b-instruct
NVIDIA_MODEL_DOMAIN_VERIFIER=meta/llama-3.3-70b-instruct
NVIDIA_MODEL_CROSS_DOMAIN_CORRELATOR=meta/llama-3.1-70b-instruct
NVIDIA_MODEL_PRIORITY_ASSESSOR=meta/llama-3.1-8b-instruct
NVIDIA_MODEL_COMMS_GENERATOR=meta/llama-3.1-8b-instruct
```

---

## 🌐 Publiczne źródła danych (Polska)

| Domena | Źródła |
|---|---|
| 🌊 Flood | IMGW, RCB, Hydroportal, X (#powódź) |
| 💻 Cyber | CERT Polska, CSIRT GOV, NASK, Zaufana Trzecia Strona |
| 🚨 Terror | RCB, ABW, Policja, komunikaty państwowe |
| 🏗️ Infrastructure | GDDKiA, PKP PLK, PSE, dane.gov.pl |
| 🚗 Traffic | GDDKiA mapa dróg, API UM Warszawa, Jakdojade |

---

## 🔗 Endpointy API

### Incidents
| Method | Endpoint | Opis |
|---|---|---|
| `POST` | `/api/v1/incidents` | Przyjęcie zgłoszenia |
| `GET` | `/api/v1/incidents` | Lista zgłoszeń |
| `GET` | `/api/v1/incidents/{id}/result` | Wynik analizy |
| `GET` | `/api/v1/metrics/live` | Metryki realtime |
| `POST` | `/api/v1/incidents/{id}/approve` | Approval gate |
| `GET` | `/api/v1/incidents/{id}/approvals` | Historia zatwierdzeń |

### Visualization
| Method | Endpoint | Opis |
|---|---|---|
| `GET` | `/viz/stream/{id}` | SSE live stream agentów |
| `GET` | `/viz/graph` | Topologia Mermaid |
| `GET` | `/viz/graph/json` | Topologia JSON |

### System
| Method | Endpoint | Opis |
|---|---|---|
| `GET` | `/health` | Status + GPU info + tracing URL |

---

## 🚀 Uruchomienie

### Lokalne

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
python main.py
```

### Docker

```bash
cp .env.example .env
# edytuj .env (ustaw NVIDIA_BASE_URL)
docker compose up --build
```

### NVIDIA Brev (L40S)

```bash
git clone <repo>
cd NvidiaHackathon2k26
cp .env.example .env
# Upewnij się że NIM odpowiada: curl http://localhost:8000/v1/models
docker build -t czk-api:latest .
docker run --gpus all --network host --env-file .env czk-api:latest
```

Po starcie:
- 🖥️ Dashboard: `http://localhost:8080/static/dashboard.html`
- 📄 API Docs: `http://localhost:8080/docs`
- 🔭 Phoenix Traces: `http://localhost:6006`

---

## 📁 Struktura projektu

```text
main.py                          # FastAPI entrypoint
requirements.txt                 # Dependencies (NVIDIA, LangGraph, CUDA)
Dockerfile                       # nvidia/cuda:12.4.1-cudnn base image
docker-compose.yml               # GPU container orchestration
langgraph.json                   # LangGraph Studio config
.env.example                     # Konfiguracja NVIDIA NIM + app

app/
  config.py                      # Pydantic settings (NVIDIA NIM config)
  store.py                       # In-memory incident store
  observability.py               # Arize Phoenix + OpenTelemetry setup
  schemas.py                     # Pydantic API contracts
  agents/
    graph.py                     # LangGraph workflow (9 nodes, fan-out)
    state.py                     # TypedDict state schema
    tools.py                     # DuckDuckGo search tool
    cuda_utils.py                # CUDA reranker (sentence-transformers)
    credibility_model.py         # Skeptical credibility scoring engine
    severity_engine.py           # Deterministic severity scoring
  api/
    incidents.py                 # Incident CRUD + metrics
    visualization.py             # SSE streaming + graph topology
  data/
    public_sources.py            # Polish OSINT source catalog
  security/
    prompt_guard.py              # LLM guardrails (regex + llm-guard)

static/
  dashboard.html                 # Real-time operator dashboard
  images/                        # Credibility visualization assets

examples/
  send_incidents.py              # Batch incident sender
  incidents/                     # 50 realistic crisis scenarios (5 categories × 10)
```

---

## 🧪 Testowanie

```bash
# Unit test modelu credibility
python test_credibility_model.py

# Wyślij 50 przykładowych incydentów
python examples/send_incidents.py

# Smoke test
curl http://localhost:8080/health
curl http://localhost:8080/viz/graph/json
```

Szczegółowe instrukcje: [examples/README.md](examples/README.md)


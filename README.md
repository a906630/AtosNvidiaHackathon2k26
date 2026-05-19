# 🛡️ Sikor8 — Crisis Management Center

> Wieloagentowy system AI wspierający centrum zarządzania kryzysowego.
> Zbudowany na **NVIDIA NIM + LangGraph + FastAPI** z pełną obserwowalnością i sceptycznym modelem weryfikacji wiarygodności.

---

## 📐 Architektura systemu

```mermaid
graph TB
    subgraph "🖥️ Frontend"
        DASH[Dashboard HTML/JS]
        SSE[Strumień SSE na żywo]
    end

    subgraph "⚡ Backend FastAPI"
        API[REST API :8080]
        VIZ[API wizualizacji]
        STORE[(Magazyn w pamięci)]
    end

    subgraph "🧠 Wieloagentowy pipeline LangGraph"
        SUP[🎯 Supervisor]
        FV[🌊 Weryfikator powodzi]
        CV[💻 Weryfikator cyber]
        TV[🚨 Weryfikator terroryzmu]
        IV[🏗️ Weryfikator infrastruktury]
        TRV[🚗 Weryfikator ruchu]
        CDC[🔁 Korelator międzydomenowy]
        PA[⚖️ Ocena priorytetu]
        CG[📢 Generator komunikatów]
    end

    subgraph "🟢 Stos NVIDIA"
        NIM[NVIDIA NIM<br/>Inferencja LLM]
        CUDA[CUDA Reranker<br/>sentence-transformers]
        GPU[NVIDIA GPU<br/>L40S / A100 / T4]
    end

    subgraph "🔍 Źródła zewnętrzne"
        DDG[DuckDuckGo Search]
        PUB[Polskie źródła publiczne<br/>IMGW, CERT, RCB, GDDKiA]
    end

    subgraph "🔭 Obserwowalność"
        PHX[Arize Phoenix :6006<br/>Ślady i latencja]
        OTEL[OpenTelemetry SDK]
    end

    DASH -->|POST /api/v1/incidents| API
    API --> SUP
    SUP -->|rozgałęzienie| FV & CV & TV & IV & TRV
    FV & CV & TV & IV & TRV --> CDC
    CDC --> PA --> CG
    CG -->|wynik| STORE
    VIZ -->|zdarzenia SSE| SSE
    SSE --> DASH

    FV & CV & TV & IV & TRV -->|zapytania wyszukiwania| DDG
    FV & CV & TV & IV & TRV -->|kuratorowane URL-e| PUB
    FV & CV & TV & IV & TRV -->|reranking wyników| CUDA

    SUP & FV & CV & TV & IV & TRV & CDC & PA & CG -->|inferencja LLM| NIM
    NIM --> GPU
    CUDA --> GPU

    API & SUP & FV & CV & TV & IV & TRV & CDC & PA & CG -->|ślady| OTEL --> PHX
```

---

## 🔄 Przepływ przetwarzania incydentu

```mermaid
sequenceDiagram
    actor Użytkownik as 👤 Operator / Obywatel
    participant API as ⚡ FastAPI
    participant SUP as 🎯 Supervisor
    participant NIM as 🟢 NVIDIA NIM
    participant WER as 🔍 Weryfikatory domenowe (×5)
    participant DDG as 🌐 DuckDuckGo
    participant CUDA as 🖥️ CUDA Reranker
    participant WIAR as 📊 Model wiarygodności
    participant KOR as 🔁 Korelator międzydomenowy
    participant PRI as ⚖️ Ocena priorytetu
    participant KOM as 📢 Generator komunikatów
    participant DASH as 🖥️ Dashboard

    Użytkownik->>API: POST /api/v1/incidents
    API->>SUP: Przekaż incydent
    SUP->>NIM: Klasyfikuj kategorię
    NIM-->>SUP: {category: "flood", related: ["infrastructure"]}
    SUP->>WER: Rozgałęzienie do wybranych weryfikatorów

    par Równoległa weryfikacja
        WER->>DDG: Zapytania wyszukiwania (×8)
        DDG-->>WER: Surowe wyniki
        WER->>CUDA: Reranking (akceleracja GPU)
        CUDA-->>WER: Najlepsze wyniki (Top-K)
        WER->>WIAR: Oblicz ocenę wiarygodności
        WIAR-->>WER: {score: 0.25, risk: 0.55}
        WER->>NIM: Krytyczna analiza snippetów
        NIM-->>WER: {credibility_score, reasoning}
        WER->>WIAR: Ogranicz wyjście LLM
        WIAR-->>WER: Ograniczony wynik [min, max]
    end

    WER->>KOR: Wyniki weryfikacji
    KOR->>NIM: Analiza cross-domain (25 ostatnich incydentów)
    NIM-->>KOR: {dependency_graph, related_categories}

    KOR->>PRI: Wiarygodność + korelacje
    PRI->>NIM: Priorytetyzacja z kontrolą spójności
    NIM-->>PRI: {priority: "P3_MEDIUM"}

    PRI->>KOM: Priorytet + zalecane działania
    KOM->>NIM: Generuj komunikaty (PL)
    NIM-->>KOM: {service_message, citizen_message}

    KOM-->>API: Pełny wynik
    API-->>DASH: Strumień zdarzeń SSE
    DASH-->>Użytkownik: 🎉 Wynik na dashboardzie
```

---

## 🟢 Stos technologiczny NVIDIA

### NVIDIA NIM (Neural Inference Microservice)

| Komponent | Rola | Szczegóły |
|---|---|---|
| **NVIDIA NIM** | Inferencja LLM | Lokalna lub chmurowa inferencja modeli Meta Llama |
| **Routing per agent** | Optymalizacja | Każdy agent może korzystać z innego modelu NIM |
| **Automatyczny fallback** | Odporność | Przy 404 model_not_found → automatyczny retry z katalogiem NIM |
| **Katalog modeli** | Odkrywanie | `GET /v1/models` — automatyczne mapowanie dostępnych modeli |

```mermaid
graph LR
    subgraph "NVIDIA NIM Endpoint (:8000)"
        CATALOG[API katalogu modeli]
        LLM8B[meta/llama-3.1-8b-instruct<br/>⚡ Szybki · Niski koszt]
        LLM70B[meta/llama-3.3-70b-instruct<br/>🎯 Wysoka jakość]
    end

    SUP[Supervisor] -->|szybka klasyfikacja| LLM8B
    WER[Weryfikatory domenowe] -->|głęboka analiza| LLM70B
    KOR[Korelator] -->|wnioskowanie wieloincydentowe| LLM70B
    PRI[Ocena priorytetu] -->|stabilne decyzje| LLM8B
    KOM[Generator komunikatów] -->|generowanie tekstu PL| LLM8B

    APP[Start aplikacji] -->|rozpoznaj modele| CATALOG
```

### NVIDIA CUDA — Reranking z akceleracją GPU

Moduł `app/agents/cuda_utils.py` implementuje **semantyczny reranking z akceleracją CUDA**:

```mermaid
graph LR
    RAW[Surowe wyniki wyszukiwania<br/>8-16 snippetów] -->|inferencja GPU| RERANKER[sentence-transformers<br/>cross-encoder na CUDA]
    RERANKER -->|posortowane Top-K| TOP[4 najistotniejsze<br/>snippety]
    TOP --> LLM[Weryfikator LLM<br/>przez NVIDIA NIM]

    style RERANKER fill:#76b900,color:#000
```

- **Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2` na GPU
- **Zadanie**: Reranking wyników DuckDuckGo wg trafności do opisu incydentu
- **Sprzęt**: Automatyczne wykrywanie CUDA, fallback na CPU
- **Wpływ**: Eliminuje szum z wyników wyszukiwania zanim trafią do LLM

### Wymagania GPU NVIDIA

| Profil | GPU | VRAM | Rekomendacja |
|---|---|---|---|
| **Minimum** | T4 | 16 GB | Tylko modele 8B |
| **Rekomendowany** | L40S | 48 GB | Mieszany routing 8B + 70B |
| **Optymalny** | A100 | 80 GB | Pełny 70B dla wszystkich agentów |

### Integracja z NVIDIA Brev

```mermaid
graph TB
    subgraph "Instancja NVIDIA Brev (L40S)"
        NIM_HOST[NVIDIA NIM :8000<br/>meta/llama-3.3-70b]
        subgraph "Kontener Docker"
            APP[Sikor8 API :8080]
            PHX[Phoenix :6006]
            CUDA_RE[CUDA Reranker]
        end
        GPU[L40S GPU 48GB VRAM]
    end

    APP -->|host.docker.internal:8000| NIM_HOST
    NIM_HOST --> GPU
    CUDA_RE --> GPU
    
    USER[👤 Zdalny użytkownik] -->|przekierowanie portu :8080| APP
    USER -->|przekierowanie portu :6006| PHX
```

---

## 📊 Sceptyczny model weryfikacji wiarygodności

System implementuje filozofię **„ZACZNIJ SCEPTYCZNIE — ZAUFANIE TRZEBA ZDOBYĆ"**:

```mermaid
graph TD
    INC[📥 Incydent] --> BASE[Punkt startowy: 10%<br/>Każde zgłoszenie zaczyna nisko]
    BASE --> SEARCH[🔍 Wyszukiwanie źródeł publicznych]
    
    SEARCH -->|brak wyników| LOW[❌ Maks. 25%<br/>Brak niezależnej weryfikacji]
    SEARCH -->|1 źródło| MED_LOW[⚠️ Maks. 50%<br/>Ograniczona koroboracja]
    SEARCH -->|2+ niezależne źródła| ANALYZE[📊 Analiza koherencji]
    
    ANALYZE -->|echo wyszukiwarki| ECHO[Kara za echo<br/>Wynik × 0.25]
    ANALYZE -->|nowe szczegóły w źródłach| CORR[✅ Bonus za koroborację<br/>pokrycie + nowe info]
    
    ECHO --> BOUNDED[🔒 Ograniczenia LLM<br/>Blokowanie zawyżonej pewności]
    CORR --> BOUNDED
    
    BOUNDED --> FINAL[Końcowa ocena wiarygodności]
    FINAL -->|poniżej 35%| P4[P4_LOW — niski priorytet]
    FINAL -->|35-50%| P3[P3_MEDIUM — średni priorytet]
    FINAL -->|50-75%| P2[P2_HIGH — wysoki priorytet]
    FINAL -->|powyżej 75% + potwierdzone| P1[P1_CRITICAL — krytyczny]

    style BASE fill:#7f1d1d,color:#fca5a5
    style LOW fill:#7f1d1d,color:#fca5a5
    style CORR fill:#14532d,color:#86efac
    style P1 fill:#7f1d1d,color:#fca5a5
    style P4 fill:#14532d,color:#86efac
```

### Kluczowe mechanizmy anty-zawyżania

| Mechanizm | Opis |
|---|---|
| **Niski punkt startowy (10%)** | Niezweryfikowane zgłoszenie zaczyna na minimum |
| **Wykrywanie echa** | Wyniki powtarzające zapytanie ≠ niezależna weryfikacja |
| **Wymóg nowych informacji** | Prawdziwa koroboracja wymaga NOWYCH szczegółów w źródłach |
| **Limity wg dowodów** | 0 wyników → maks. 25%, 1 wynik → maks. 50% |
| **Ograniczenia wyjścia LLM** | Wynik LLM ograniczony do [min, max] wg ilości dowodów |
| **Ryzyko deepfake** | Startuje wysoko (55%), spada tylko przy koroboracji |
| **Kontrola spójności priorytetu** | Niska wiarygodność + wysokie ryzyko deepfake → maks. P3 |

---

## 🛠️ Wykorzystywane technologie

### Ekosystem NVIDIA

| Technologia | Zastosowanie |
|---|---|
| **NVIDIA NIM** | Inferencja LLM (Llama 3.1/3.3) — lokalna lub chmurowa |
| **NVIDIA CUDA** | Semantyczny reranking z akceleracją GPU |
| **NVIDIA Brev** | Hosting instancji z GPU (L40S) |
| **NVIDIA Container Toolkit** | Docker z obsługą GPU |
| **langchain-nvidia-ai-endpoints** | Python SDK do NVIDIA NIM API |

### Stos AI / ML

| Technologia | Zastosowanie |
|---|---|
| **LangGraph** | Orkiestracja wieloagentowa z rozgałęzieniem i złączaniem |
| **LangChain** | Abstrakcja wywołań LLM + integracja narzędzi |
| **sentence-transformers** | Reranking cross-encoder na GPU |
| **PyTorch (CUDA)** | Środowisko uruchomieniowe modeli reranking |

### Stos aplikacyjny

| Technologia | Zastosowanie |
|---|---|
| **FastAPI** | REST API + strumieniowanie SSE + dokumentacja OpenAPI |
| **Pydantic v2** | Walidacja schematów, typowane kontrakty |
| **DuckDuckGo Search** | OSINT open-source (zero kluczy API) |
| **Arize Phoenix** | Obserwowalność — ślady, latencja, zużycie tokenów |
| **OpenTelemetry** | SDK rozproszonego śledzenia |

### Infrastruktura

| Technologia | Zastosowanie |
|---|---|
| **Docker** | Konteneryzacja z NVIDIA runtime |
| **Docker Compose** | Orkiestracja usług |
| **CUDA 12.4 + cuDNN** | Obraz bazowy (`nvidia/cuda:12.4.1-cudnn-runtime`) |

---

## 🏗️ Modele per agent (NVIDIA NIM)

Aplikacja pozwala przypisać osobny model NIM do każdego agenta:

| Agent | Rekomendowany model | Uzasadnienie |
|---|---|---|
| `supervisor` | `meta/llama-3.1-8b-instruct` | Szybka klasyfikacja, niski koszt |
| `domain_verifier` | `meta/llama-3.3-70b-instruct` | Najlepsza jakość analizy OSINT |
| `cross_domain_correlator` | `meta/llama-3.1-70b-instruct` | Wnioskowanie relacyjne między incydentami |
| `priority_assessor` | `meta/llama-3.1-8b-instruct` | Stabilne decyzje z kontrolą spójności |
| `comms_generator` | `meta/llama-3.1-8b-instruct` | Szybkie generowanie komunikatów po polsku |

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
| 🌊 Powodzie | IMGW, RCB, Hydroportal, X (#powódź) |
| 💻 Cyberbezpieczeństwo | CERT Polska, CSIRT GOV, NASK, Zaufana Trzecia Strona |
| 🚨 Terroryzm | RCB, ABW, Policja, komunikaty państwowe |
| 🏗️ Infrastruktura | GDDKiA, PKP PLK, PSE, dane.gov.pl |
| 🚗 Ruch drogowy | GDDKiA mapa dróg, API UM Warszawa, Jakdojade |

---

## 🔗 Endpointy API

### Incydenty
| Metoda | Endpoint | Opis |
|---|---|---|
| `POST` | `/api/v1/incidents` | Przyjęcie zgłoszenia |
| `GET` | `/api/v1/incidents` | Lista zgłoszeń |
| `GET` | `/api/v1/incidents/{id}/result` | Wynik analizy |
| `GET` | `/api/v1/metrics/live` | Metryki w czasie rzeczywistym |
| `POST` | `/api/v1/incidents/{id}/approve` | Brama zatwierdzenia |
| `GET` | `/api/v1/incidents/{id}/approvals` | Historia zatwierdzeń |

### Wizualizacja
| Metoda | Endpoint | Opis |
|---|---|---|
| `GET` | `/viz/stream/{id}` | Strumień SSE agentów na żywo |
| `GET` | `/viz/graph` | Topologia Mermaid |
| `GET` | `/viz/graph/json` | Topologia JSON |

### System
| Metoda | Endpoint | Opis |
|---|---|---|
| `GET` | `/health` | Status + informacje o GPU + URL śledzenia |

---

## 🚀 Uruchomienie

### Lokalnie

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
- 📄 Dokumentacja API: `http://localhost:8080/docs`
- 🔭 Ślady Phoenix: `http://localhost:6006`

---

## 📁 Struktura projektu

```text
main.py                          # Punkt wejścia FastAPI
requirements.txt                 # Zależności (NVIDIA, LangGraph, CUDA)
Dockerfile                       # Obraz bazowy nvidia/cuda:12.4.1-cudnn
docker-compose.yml               # Orkiestracja kontenerów z GPU
langgraph.json                   # Konfiguracja LangGraph Studio
.env.example                     # Konfiguracja NVIDIA NIM + aplikacji

app/
  config.py                      # Ustawienia Pydantic (konfiguracja NVIDIA NIM)
  store.py                       # Magazyn incydentów w pamięci
  observability.py               # Konfiguracja Arize Phoenix + OpenTelemetry
  schemas.py                     # Kontrakty API Pydantic
  agents/
    graph.py                     # Przepływ LangGraph (9 węzłów, rozgałęzienie)
    state.py                     # Schemat stanu TypedDict
    tools.py                     # Narzędzie wyszukiwania DuckDuckGo
    cuda_utils.py                # CUDA reranker (sentence-transformers)
    credibility_model.py         # Sceptyczny silnik oceny wiarygodności
    severity_engine.py           # Deterministyczny scoring istotności
  api/
    incidents.py                 # CRUD incydentów + metryki
    visualization.py             # Strumieniowanie SSE + topologia grafu
  data/
    public_sources.py            # Katalog polskich źródeł OSINT
  security/
    prompt_guard.py              # Zabezpieczenia LLM (regex + llm-guard)

static/
  dashboard.html                 # Dashboard operatora w czasie rzeczywistym
  images/                        # Zasoby wizualizacji wiarygodności

examples/
  send_incidents.py              # Masowe wysyłanie incydentów
  incidents/                     # 50 realistycznych scenariuszy kryzysowych (5 kategorii × 10)
```

---

## 🧪 Testowanie

```bash
# Test jednostkowy modelu wiarygodności
python test_credibility_model.py

# Wyślij 50 przykładowych incydentów
python examples/send_incidents.py

# Szybki test poprawności
curl http://localhost:8080/health
curl http://localhost:8080/viz/graph/json
```

Szczegółowe instrukcje: [examples/README.md](examples/README.md)


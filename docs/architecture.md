# RAG System Architecture

## System Context

```mermaid
C4Context
    title JOL RAG System — System Context (Pilot: Lithuania)

    Person(analyst, "Analyst", "Queries documents via RAG API")
    Person(admin, "Admin", "Ingests documents, manages data")

    System(rag, "RAG Service", "FastAPI + Qdrant + MinIO on rag-prod-lt01")
    System(ollama, "Ollama LLM", "GPU inference on llm-prod-lt01")
    System(proxy, "Reverse Proxy", "TLS 1.3 termination")

    Rel(analyst, proxy, "HTTPS 443")
    Rel(admin, proxy, "HTTPS 443")
    Rel(proxy, rag, "HTTP 8000 (localhost)")
    Rel(rag, ollama, "HTTP 11434 (VLAN 30→40)")
```

## Data Flow

```mermaid
flowchart TD
    subgraph "rag-prod-lt01 (10.40.40.10, VLAN 40)"
        API[FastAPI RAG API<br/>:8000]
        QDRANT[Qdrant Vector DB<br/>:6333]
        MINIO[MinIO Object Store<br/>:9000]
        REDIS[Redis Queue<br/>:6379]
        WORKER[Ingestion Worker]
        EMBED[Embedding Model<br/>all-MiniLM-L6-v2<br/>CPU, local]
    end

    subgraph "llm-prod-lt01 (10.30.30.10, VLAN 30)"
        OLLAMA[Ollama<br/>mistral-7b-instruct<br/>GPU]
    end

    API -->|embed query| EMBED
    API -->|vector search| QDRANT
    API -->|generate answer| OLLAMA
    API -->|store raw docs| MINIO
    API -->|enqueue job| REDIS
    WORKER -->|consume jobs| REDIS
    WORKER -->|embed chunks| EMBED
    WORKER -->|upsert vectors| QDRANT

    style EMBED fill:#e8f5e9
    style OLLAMA fill:#fff3e0
    style QDRANT fill:#e3f2fd
```

## Trust Boundaries

```mermaid
flowchart LR
    subgraph "External (Internet)"
        USER[User Browser]
    end

    subgraph "DMZ / Proxy Tier"
        PROXY[Reverse Proxy<br/>TLS 1.3 termination<br/>WAF rules]
    end

    subgraph "VLAN 40 — AI Services"
        RAGAPI[RAG API<br/>JWT auth<br/>Rate limiting]
        QDRANT2[Qdrant<br/>API-key auth]
        MINIO2[MinIO<br/>SSE-S3 encryption]
    end

    subgraph "VLAN 30 — GPU/LLM"
        LLM[Ollama<br/>No auth required<br/>VLAN-restricted]
    end

    USER -->|HTTPS 443| PROXY
    PROXY -->|HTTP 8000<br/>localhost only| RAGAPI
    RAGAPI -->|API-key| QDRANT2
    RAGAPI -->|credentials| MINIO2
    RAGAPI -->|HTTP 11434| LLM

    style PROXY fill:#ffcdd2
    style RAGAPI fill:#c8e6c9
```

## Network Topology

| Segment | VLAN | Subnet | Purpose |
|---------|------|--------|---------|
| AI Services | 40 | 10.40.40.0/24 | RAG, MCP, Hermes VMs |
| GPU/LLM | 30 | 10.30.30.0/24 | Ollama inference (bare-metal) |
| Management | 60 | 10.60.60.0/24 | Proxmox hypervisor, bastion |
| Backup | 10 | 10.10.10.0/24 | PBS backup server |

## Encryption Layers

| Layer | Mechanism | Standard |
|-------|-----------|----------|
| Data at rest (block) | LUKS2 (AES-XTS-256) | GDPR Art. 32 |
| Data at rest (object) | MinIO SSE-S3 | AES-256-GCM |
| Data in transit (external) | TLS 1.3 at reverse proxy | ISO 27001 A.13.2 |
| Data in transit (internal) | VLAN isolation + API keys | Risk accepted (pilot) |
| Backups | age encryption (X25519) | SOC 2 CC6.1 |

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Ollama on llm-prod-lt01 (not local) | RAG VM has no GPU; Ollama already provisioned with GPU |
| all-MiniLM-L6-v2 embeddings | CPU-friendly (384-dim), fast, no external API calls |
| Docker Compose (not K8s) | Pilot simplicity; single VM; extractable later |
| Qdrant (not Pinecone/Weaviate) | Self-hosted, EU data residency, API-key auth |
| MinIO (not S3) | Self-hosted, SSE-S3, no cloud dependency |
| JWT HS256 (not OIDC) | Pilot phase; structure supports RS256 migration |
| mTLS deferred | Pilot risk acceptance; VLAN isolation compensates |

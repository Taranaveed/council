# Council — System Architecture

**Version 2.0 · July 2026**

---

## System Flowchart

```
                    Council App
                              |
                           Login
                              |
                       Role Selection
                    /                  \
           Business Owner              Buyer
            /         \                   |
   Service 1       Service 2        Service 3
Price Bargaining  Audience Discovery  Local Deal Finder
```

> Every service follows the same pipeline:
> **Form → Live Data → 3-Agent Debate → Judge → Dashboard**

---

## Shared Pipeline (All Services)

| Step | What Happens |
|------|--------------|
| **1 · Login** | User signs in |
| **2 · Role Pick** | User chooses **Business Owner** or **Buyer** |
| **3 · Service Pick** | User selects one of the 3 services |
| **4 · Fill Form** | User enters details for that service |
| **5 · Live Sync** | Backend fetches real prices before AI runs |
| **6 · AI Debate** | 3 agents argue over the live data |
| **7 · Judge** | Judge outputs a structured JSON verdict |
| **8 · Dashboard** | User sees the final recommendation |

---

## Roles & Services

| Role | Services Available |
|------|-------------------|
| **Business Owner** | Service 1 — Price Bargaining · Service 2 — Audience Discovery |
| **Buyer** | Service 3 — Local Deal Finder |

---

## Service 1 — Price Bargaining

**Role:** Business Owner  
**Purpose:** Find the optimal selling price using live competitor data.

### User Inputs

| Field | Description |
|-------|-------------|
| Product Specs | Key features, materials, and product details |
| Estimated Price Range | Minimum and maximum price under consideration |

### AI Agent Council

| Agent | Focus |
|-------|-------|
| Premium Maximizer | Higher margins and premium positioning |
| Volume Discounter | Lower prices to drive sales volume |
| Market Benchmark Proxy | Live competitor prices as ground truth |

### Output

Recommended selling price, market comparison, and debate summary.

**API:** `POST /api/modes/price-bargaining`

---

## Service 2 — Audience Discovery

**Role:** Business Owner  
**Purpose:** Identify who would buy the product and why.

### User Inputs

| Field | Description |
|-------|-------------|
| Product Name | Name of the product being analyzed |
| Problem It Solves | Primary problem the product addresses |

### AI Agent Council

| Agent | Focus |
|-------|-------|
| Demographic Scout | Age, income, location, lifestyle |
| Psychographic Analyst | Values, motivations, buying triggers |
| Utility Specialist | Practical use cases and feature fit |

### Output

Three ideal buyer persona profiles with motivations and channel recommendations.

**API:** `POST /api/modes/audience-discovery`

---

## Service 3 — Local Deal Finder

**Role:** Buyer  
**Purpose:** Find the best real-world deal from live local listings.

### User Inputs

| Field | Description |
|-------|-------------|
| Item Name | Product the buyer wants to purchase |
| Max Budget | Maximum amount willing to spend *(optional)* |
| Location | City or region for localized search |

### AI Agent Council

| Agent | Focus |
|-------|-------|
| Thrift Advocate | Lowest price and best value |
| Risk Analyst | Vendor trust, warranty, return policy |
| Contextual Persona | Fit for buyer budget, location, and urgency |

### Output

Buy/Pass verdict, best deal card, store link, alternatives, and agent reasoning.

**API:** `POST /api/modes/deal-finder`

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React + Vite + TypeScript | Dashboards and forms |
| Backend API | FastAPI (Python) | Routing and agent orchestration |
| Live Prices | Node.js + SerpApi | Real market data before AI runs |
| AI Engine | Groq · Llama 3.3 70B | Agent debates and Judge verdict |

---

*Official architecture map — Council*

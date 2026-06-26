# Dialectic Node

A sophisticated multi-agent debate system that simulates structured dialectical discourse between AI agents. Experience real-time debates on complex topics with proponent, opponent, and judge agents.

##  Features

- **Real-time Streaming**: Watch debates unfold live with streaming responses
- **Multi-Agent Architecture**: Proponent defends the thesis, Opponent critiques it, Judge evaluates the discourse
- **Structured Debate**: Each round follows a formal dialectical structure with reasoning and argumentation
- **Modern UI**: Sleek terminal-inspired interface with live typing effects
- **RESTful API**: FastAPI backend with comprehensive debate management
- **Type-Safe**: Full TypeScript support on frontend and backend

##  Architecture

### Backend (FastAPI)
- **Framework**: FastAPI with async support
- **LLM Integration**: Groq API with Llama 3.3 70B model
- **Streaming**: Server-Sent Events (SSE) for real-time updates
- **Data Models**: Pydantic for type safety
- **CORS**: Configured for frontend integration

### Frontend (React + Vite)
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite for fast development
- **Styling**: Tailwind CSS with custom terminal theme
- **State Management**: React hooks with custom debate stream hook
- **Real-time**: EventSource for SSE consumption

##  Quick Start

### Prerequisites
- Python 3.8+
- Node.js 18+
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Taranaveed/dialectic-node.git
   cd dialectic-node
   ```

2. **Backend Setup**
   ```bash
   cd backend
   python -m venv venv
   # On Windows
   venv\Scripts\activate
   # On macOS/Linux
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Environment Variables**
   Create a `.env` file in the backend directory:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   ```

4. **Frontend Setup**
   ```bash
   cd ../frontend
   npm install
   ```

### Running the Application

1. **Start Backend**
   ```bash
   cd backend
   # Activate virtual environment if not already
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Start Frontend** (in a new terminal)
   ```bash
   cd frontend
   npm run dev
   ```

3. **Open Browser**
   Navigate to `http://localhost:5173`

## Usage

1. Enter a thesis statement (e.g., "Artificial Intelligence will benefit humanity")
2. Set the number of debate rounds (1-10)
3. Click "Start Debate"
4. Watch the real-time debate unfold between:
   - **Proponent**: Defends the thesis with reasoned arguments
   - **Opponent**: Critiques and challenges the proponent's position
   - **Judge**: Evaluates the debate quality and declares a verdict

##  API Documentation

### Endpoints

#### POST `/debate/start`
Initialize a new debate session.

**Request Body:**
```json
{
  "thesis": "Your thesis statement here",
  "max_rounds": 3,
  "model": "llama-3.3-70b-versatile"
}
```

**Response:**
```json
{
  "debate_id": "uuid-string",
  "status": "initialized"
}
```

#### GET `/debate/stream/{debate_id}`
Stream the debate in real-time using Server-Sent Events.

**Events:**
- `turn_start`: Indicates start of a speaker's turn
- `token`: Streaming token data
- `turn_end`: Complete response for a speaker
- `judge_verdict`: Final evaluation
- `debate_complete`: Debate finished

#### GET `/debate/result/{debate_id}`
Get the complete debate transcript and results.

##  Agent System

### Proponent Agent
- **Role**: Defends the thesis statement
- **Structure**: Uses chain-of-thought reasoning with `<reasoning>` and `<argument>` tags
- **Prompt**: Charitable interpretation with evidence-based defense

### Opponent Agent
- **Role**: Critiques and challenges the thesis
- **Structure**: Analytical approach with `<analysis>` and `<critique>` tags
- **Prompt**: Skeptical but fair examination

### Judge Agent
- **Role**: Meta-analyst evaluating discourse quality
- **Evaluation**: Coherence, evidence, rigor, precision, novelty, fairness
- **Verdict**: Structured assessment with justification

## UI Components

- **Debate Stage**: Main interface with controls and live terminals
- **Terminal Panels**: Real-time streaming for each agent
- **Transcript Panels**: Complete debate history
- **Verdict Display**: Judge's evaluation with scoring

## 🛠️ Development

### Backend Development
```bash
cd backend
# Install dev dependencies
pip install -r requirements-dev.txt
# Run tests
pytest
# Format code
black .
```

### Frontend Development
```bash
cd frontend
# Install dependencies
npm install
# Start dev server
npm run dev
# Build for production
npm run build
# Preview production build
npm run preview
```

## Project Structure

```
dialectic-node/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── api/
│   │   │   └── debate.py        # Debate endpoints
│   │   ├── core/
│   │   │   └── llm_service.py   # Groq integration
│   │   ├── models/
│   │   │   └── debate.py        # Data models
│   │   └── agents/
│   │       ├── prompts.py       # Agent prompts
│   │       └── __init__.py
│   ├── requirements.txt
│   └── venv/                    # Virtual environment
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   └── DebateStage.tsx  # Main component
│   │   ├── hooks/
│   │   │   └── useDebateStream.ts # Streaming hook
│   │   ├── types/
│   │   │   └── debate.ts        # TypeScript types
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── .gitignore
└── README.md
```

##  Environment Variables

### Backend
- `GROQ_API_KEY`: Your Groq API key (required)

 

 

## Acknowledgments

- **Groq**: For providing fast LLM inference
- **FastAPI**: For the excellent async web framework
- **React**: For the component-based UI framework
- **Tailwind CSS**: For the utility-first styling approach


# Quickstart

## 1. Clone and set up

```bash
git clone https://github.com/YOUR_USERNAME/visiblehand
cd visiblehand
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL=sqlite:///visiblehand.db
```

## 3. Migrate and seed

```bash
# Apply schema migrations
python -c "import alembic.config; alembic.config.main(argv=['upgrade', 'head'])"

# Seed 8-country demo dataset
python -m scripts.seed_demo_data
```

Or with make:
```bash
make seed
```

## 4. Start the API

```bash
make run
# or: uvicorn api.main:app --reload --port 8000
```

## 5. Score a country

```bash
curl http://localhost:8000/risk/BR | python -m json.tool
```

```json
{
  "country": "BR",
  "name": "Brazil",
  "composite": 52.0,
  "ci_low": 46.5,
  "ci_high": 57.6,
  "confidence": 0.70,
  "risk_level": "Moderate",
  "breakdown": {
    "economic": 48.5,
    "political": 56.3,
    "nlp_sentiment": 58.0,
    "governance": 45.5
  },
  "top_drivers": ["rapid_escalation", "elevated_protest_activity", "low_fx_reserves_deteriorating"],
  ...
}
```

## 6. Open the dashboard

Visit [http://localhost:8000/dashboard](http://localhost:8000/dashboard).

## 7. Optional: Enable FinBERT ONNX

For faster, more accurate NLP scoring (requires ~120 MB model download):

```bash
pip install torch transformers onnxruntime
python scripts/export_finbert_onnx.py
# Model saved to models/finbert-onnx/
```

After export, restart the API — it will automatically detect and load the ONNX model.

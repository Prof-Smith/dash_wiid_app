
# WIID Choropleth + Student Insights (Dash)

## Local Run
```bash
cd dash_wiid_app
python -m venv .venv
# Windows: .venv\Scriptsctivate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python app.py
# open http://localhost:8050
```

## Deploy on Render
- Root directory: `dash_wiid_app`
- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`
- Optional env var: `APP_READONLY=1` to disable writes

## Data files
- `data/wiid_latest_per_country.csv` (mapping data; replace with the curated file you generated earlier)
- `data/student_submissions.csv` (created/updated by the app)

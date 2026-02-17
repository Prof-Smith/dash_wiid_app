# app.py
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, dash_table, no_update
import dash_bootstrap_components as dbc

# ------------------------------------------------------------------------------------
# Paths & configuration
# ------------------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent

# Map data: keep it read-only from the repo so a GitHub update refreshes on next deploy
WIID_PATH = APP_DIR / "data" / "wiid_latest_per_country.csv"

# Submissions: writable path (default /tmp/submissions; use /data with a Render Disk)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/submissions"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SUBS_PATH = DATA_DIR / "student_submissions.csv"

READ_ONLY = os.getenv("APP_READONLY", "0") == "1"

print(f"[BOOT] WIID_PATH={WIID_PATH}  DATA_DIR={DATA_DIR}  "
      f"writable={os.access(DATA_DIR, os.W_OK)}  READ_ONLY={READ_ONLY}")

# ------------------------------------------------------------------------------------
# WIID loader with validation (prevents broken map when CSV is malformed)
# ------------------------------------------------------------------------------------
EXPECTED_COLS = [
    "country", "c3", "year", "gini", "resource",
    "scale_detailed", "incomegroup", "region_wb"
]

def load_wiid_latest(path: Path) -> pd.DataFrame:
    # Try comma first; if only 1 column, try semicolon (Excel export variant)
    df = pd.read_csv(path)
    if df.shape[1] == 1:
        df = pd.read_csv(path, sep=";")
    # Normalize headers
    df.columns = [c.strip().lower() for c in df.columns]
    # Validate required columns
    missing = [c for c in EXPECTED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"WIID CSV missing required columns: {missing}. "
            f"Ensure header matches: {', '.join(EXPECTED_COLS)}"
        )
    # Coerce types
    df["c3"] = df["c3"].astype(str).str.upper()
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["gini"] = pd.to_numeric(df["gini"], errors="coerce")
    # Filter rows suitable for plotting
    df = df.dropna(subset=["c3", "year", "gini"])
    return df[EXPECTED_COLS]

latest = load_wiid_latest(WIID_PATH)

# ------------------------------------------------------------------------------------
# Submissions – load/save
# ------------------------------------------------------------------------------------
SUB_COLS = [
    "timestamp", "student_id", "country_iso3", "title",
    "summary_md", "evidence_links", "rating", "status"
]

def load_subs() -> pd.DataFrame:
    if not SUBS_PATH.exists():
        return pd.DataFrame(columns=SUB_COLS)
    df = pd.read_csv(SUBS_PATH)
    # normalize columns
    for c in SUB_COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[SUB_COLS]
    df["status"] = df["status"].fillna("").str.lower()
    return df

def save_subs(df: pd.DataFrame):
    if READ_ONLY:
        return False, "Read-only mode: saving disabled."
    try:
        df = df.reindex(columns=SUB_COLS)
        SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(SUBS_PATH, index=False)
        return True, f"Saved to {SUBS_PATH}"
    except Exception as e:
        return False, f"Error saving: {e}"

# ------------------------------------------------------------------------------------
# App & Layout
# ------------------------------------------------------------------------------------
app = Dash(__name__, external_stylesheets=[dbc.themes.LITERA],
           title="WIID Map + Student Insights")
server = app.server

# Left panel: Map (figure is provided by callback)
map_panel = dbc.Col(
    dcc.Graph(id="map", config={"responsive": True}, style={"height": "100vh"}),
    md=8
)

# Right panel: Country facts + Featured Student Insight + Recent submissions table
right_panel = dbc.Col([
    html.Div(id="country-facts"),
    html.Hr(),
    html.H5("Featured Student Insight"),
    html.Div(id="student-note"),
    html.Hr(),
    html.H6("Recent Submissions"),
    dash_table.DataTable(
        id="sub-table",
        columns=[{"name": c, "id": c} for c in
                 ["timestamp", "student_id", "title", "rating", "status"]],
        page_size=6,
        style_cell={"whiteSpace": "normal", "height": "auto", "textAlign": "left"},
        style_table={"overflowX": "auto"},
    ),
    dcc.Interval(id="interval-refresh", interval=20_000, n_intervals=0)
], id="right-panel", md=4, style={"height": "100vh", "overflowY": "auto"})

# Admin tools
admin_help = dcc.Markdown("""
**Admin mode** (TA/Instructor):
- Edit statuses (`approved`, `pending`, `rejected`) directly in the table.
- Click **Save** to write back to `student_submissions.csv`.
""")

admin_controls = dbc.Row([
    dbc.Col(
        dbc.Badge("Read-only", color="secondary", className="me-2")
        if READ_ONLY else dbc.Badge("Writable", color="success", className="me-2"),
        md="auto"),
    dbc.Col(
        dbc.Button("Save Changes", id="btn-save", color="primary",
                   n_clicks=0, disabled=READ_ONLY),
        md="auto"),
    dbc.Col(html.Div(id="save-status", className="ms-2"), md="auto")
], className="mb-2")

admin_table = dash_table.DataTable(
    id="admin-table",
    columns=[{"name": c, "id": c, "editable": True} for c in SUB_COLS],
    page_size=10, editable=True, row_deletable=False,
    style_cell={"whiteSpace": "pre-wrap", "height": "auto", "textAlign": "left"},
    style_table={"overflowX": "auto"}
)

admin_tab = dbc.Container([
    admin_help,
    admin_controls,
    admin_table,
    dcc.Interval(id="interval-admin-refresh", interval=30_000, n_intervals=0),

    html.Hr(),

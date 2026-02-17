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

# Map data: load from repo so updating CSV in GitHub updates the map
WIID_PATH = APP_DIR / "data" / "wiid_latest_per_country.csv"

# Submissions: writable location (default /tmp/submissions)
# For persistence across redeploys: create a Render Disk and set DATA_DIR=/data
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/submissions"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SUBS_PATH = DATA_DIR / "student_submissions.csv"
READ_ONLY = os.getenv("APP_READONLY", "0") == "1"

print(f"[BOOT] WIID_PATH={WIID_PATH}  DATA_DIR={DATA_DIR} "
      f"writable={os.access(DATA_DIR, os.W_OK)}  READ_ONLY={READ_ONLY}")

# --- Seed student submissions once from the repo copy (if the runtime copy is missing) ---
REPO_SUBS = APP_DIR / "data" / "student_submissions.csv"
if not SUBS_PATH.exists() and REPO_SUBS.exists():
    try:
        SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUBS_PATH.write_bytes(REPO_SUBS.read_bytes())
        print(f"[BOOT] Seeded submissions from {REPO_SUBS} -> {SUBS_PATH}")
    except Exception as e:
        print(f"[BOOT] Could not seed submissions: {e}")

# ------------------------------------------------------------------------------------
# Load WIID map snapshot (validated)
# ------------------------------------------------------------------------------------
EXPECTED_COLS = [
    "country", "c3", "year", "gini", "resource",
    "scale_detailed", "incomegroup", "region_wb"
]

def load_wiid_latest(path: Path) -> pd.DataFrame:
    # Try comma; fallback to semicolon
    df = pd.read_csv(path)
    if df.shape[1] == 1:
        df = pd.read_csv(path, sep=";")
    # Normalize headers
    df.columns = [c.strip().lower() for c in df.columns]
    # Check required columns
    missing = [c for c in EXPECTED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"WIID CSV missing required columns: {missing}. "
            f"Expected: {', '.join(EXPECTED_COLS)}"
        )
    # Coerce types
    df["c3"] = df["c3"].astype(str).str.upper()
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["gini"] = pd.to_numeric(df["gini"], errors="coerce")
    # Filter usable rows
    df = df.dropna(subset=["c3", "year", "gini"])
    return df[EXPECTED_COLS]

latest = load_wiid_latest(WIID_PATH)

# ------------------------------------------------------------------------------------
# Submissions load/save
# ------------------------------------------------------------------------------------
SUB_COLS = [
    "timestamp", "student_id", "country_iso3", "title",
    "summary_md", "evidence_links", "rating", "status"
]

def load_subs() -> pd.DataFrame:
    if not SUBS_PATH.exists():
        return pd.DataFrame(columns=SUB_COLS)
    df = pd.read_csv(SUBS_PATH)
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
app = Dash(
    __name__, external_stylesheets=[dbc.themes.LITERA],
    title="WIID Map + Student Insights"
)
server = app.server

# Map panel
map_panel = dbc.Col(
    dcc.Graph(id="map", config={"responsive": True}, style={"height": "100vh"}),
    md=8
)

# Right-side panel
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
    dcc.Interval(id="interval-refresh", interval=20000, n_intervals=0)
], id="right-panel", md=4, style={"height": "100vh", "overflowY": "auto"})

# Admin tab
admin_help = dcc.Markdown("""
**Admin mode** (TA/Instructor):  
- Edit statuses (`approved`, `pending`, `rejected`) directly.  
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
    dbc.Col(html.Div(id="save-status"), md="auto"),
], className="mb-2")

admin_table = dash_table.DataTable(
    id="admin-table",
    columns=[{"name": c, "id": c, "editable": True} for c in SUB_COLS],
    page_size=10,
    editable=True,
    style_cell={"whiteSpace": "pre-wrap", "height": "auto", "textAlign": "left"},
    style_table={"overflowX": "auto"}
)

admin_tab = dbc.Container([
    admin_help,
    admin_controls,
    admin_table,
    dcc.Interval(id="interval-admin-refresh", interval=30000, n_intervals=0),

    html.Hr(),
    html.Div([
        html.Button("Download submissions CSV", id="btn-dl", n_clicks=0,
                    className="btn btn-outline-secondary"),
        dcc.Download(id="download-csv")
    ], className="mt-3"),
], fluid=True, className="p-3")

# Submit tab
submission_form = dbc.Card(dbc.CardBody([
    dcc.Markdown("**Student submission:** Use Markdown in the summary."),
    dbc.Row([
        dbc.Col(dbc.Input(id="in-student-id", placeholder="Student ID or alias"), md=3),
        dbc.Col(dbc.Input(id="in-iso3", placeholder="ISO-3 (e.g., ARG)"), md=2),
        dbc.Col(dbc.Input(id="in-title", placeholder="Title"), md=7),
    ], className="mb-2"),
    dbc.Textarea(id="in-summary", placeholder="Summary (Markdown allowed)",
                 style={"height": "140px"}),
    dbc.Input(id="in-links", placeholder="Evidence links (semicolon-separated)",
              className="mt-2"),
    dbc.Row([
        dbc.Col(dbc.Input(id="in-rating", type="number", min=1, max=5,
                          placeholder="1–5 rating"), md=2),
        dbc.Col(dbc.Select(id="in-status",
                           options=[
                               {"label": "pending", "value": "pending"},
                               {"label": "approved", "value": "approved"},
                               {"label": "rejected", "value": "rejected"},
                           ],
                           value="pending"), md=3),
        dbc.Col(dbc.Button("Submit", id="btn-submit", color="secondary",
                           className="mt-2 mt-md-0", n_clicks=0,
                           disabled=READ_ONLY), md=2),
        dbc.Col(html.Div(id="submit-status"), md=5)
    ], className="mt-2")
]))

student_tab = dbc.Container(submission_form, fluid=True, className="p-3")

# Tabs
app.layout = dbc.Container([
    html.H2("Visualizing Income Inequality + Student Insights"),
    dcc.Tabs(id="tabs", value="tab-map", children=[
        dcc.Tab(label="Map & Insights", value="tab-map",
                children=[dbc.Row([map_panel, right_panel], className="mt-3")]),
        dcc.Tab(label="Admin", value="tab-admin", children=[admin_tab]),
        dcc.Tab(label="Submit", value="tab-submit", children=[student_tab]),
    ])
], fluid=True)

# ------------------------------------------------------------------------------------
# Helper components
# ------------------------------------------------------------------------------------
def country_facts_card(row):
    if row is None:
        return dbc.Alert("Click a country on the map to see details.",
                         color="info", className="mb-3")
    items = [
        html.Li(["Country: ", html.B(row["country"])]),
        html.Li(f"ISO‑3: {row['c3']}"),
        html.Li(f"Gini (latest): {row['gini']:.2f}"),
        html.Li(f"Reference year: {int(row['year'])}"),
        html.Li(f"Concept: {row['resource']}"),
        html.Li(f"Scale: {row['scale_detailed']}"),
        html.Li(f"Income group: {row['incomegroup']}"),
        html.Li(f"Region: {row['region_wb']}"),
        html.Li("Note: latest year & concept differ across countries.")
    ]
    return dbc.Card(dbc.CardBody([
        html.H5("Country Facts"), html.Ul(items)
    ]))

def featured_md_block(note):
    if note is None:
        return dcc.Markdown("_No approved student note yet for this country._")
    md = f"""### {note.get('title','(Untitled)')}

{note.get('summary_md','')}

**Evidence:** {note.get('evidence_links','')}

**Rating:** {note.get('rating','')}/5
"""
    return dcc.Markdown(md)

# ------------------------------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------------------------------
@app.callback(
    Output("map", "figure"),
    Output("country-facts", "children"),
    Output("student-note", "children"),
    Output("sub-table", "data"),
    Input("map", "clickData"),
    Input("interval-refresh", "n_intervals")
)
def update_panel(clickData, _):
    subs = load_subs()

    base_fig = px.choropleth(
        latest,
        locations="c3",
        color="gini",
        hover_name="country",
        hover_data={
            "c3": False, "gini": ":.2f", "year": True,
            "resource": True, "scale_detailed": True,
            "incomegroup": True, "region_wb": True
        },
        color_continuous_scale=px.colors.sequential.Plasma,
        range_color=(latest["gini"].min(), latest["gini"].max()),
        labels={"gini": "Gini (0–100)"},
        title="Latest Available Gini by Country (WIID curated)"
    )
    base_fig.update_layout(coloraxis_colorbar=dict(title="Gini"))

    # Outline overlay
    submitted_iso = subs["country_iso3"].dropna().str.upper().unique().tolist()
    if submitted_iso:
        overlay_df = pd.DataFrame({"c3": submitted_iso, "flag": 1})
        overlay = go.Choropleth(
            locations=overlay_df["c3"],
            z=overlay_df["flag"],
            locationmode="ISO-3",
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
            showscale=False,
            marker_line_color="#10e0e0",
            marker_line_width=2.5,
            hoverinfo="skip"
        )
        base_fig.add_trace(overlay)

    if not clickData:
        return base_fig, country_facts_card(None), featured_md_block(None), []

    iso3 = clickData["points"][0]["location"]
    row = latest.loc[latest["c3"] == iso3].iloc[0].to_dict()

    sub_iso = subs[subs["country_iso3"] == iso3].copy()

    if not sub_iso.empty:
        sub_iso["timestamp"] = pd.to_datetime(sub_iso["timestamp"], errors="coerce")
        recent = sub_iso.sort_values("timestamp", ascending=False).head(12)
        recent["timestamp"] = recent["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        recent_table = recent[
            ["timestamp", "student_id", "title", "rating", "status"]
        ].to_dict("records")
    else:
        recent_table = []

    approved = sub_iso[sub_iso["status"] == "approved"].copy()
    if not approved.empty:
        approved["timestamp"] = pd.to_datetime(approved["timestamp"], errors="coerce")
        featured = approved.sort_values("timestamp",
                                        ascending=False).iloc[0].to_dict()
    else:
        featured = None

    return base_fig, country_facts_card(row), featured_md_block(featured), recent_table


@app.callback(
    Output("admin-table", "data"),
    Input("tabs", "value"),
    Input("interval-admin-refresh", "n_intervals")
)
def admin_reload(tab, _):
    if tab != "tab-admin":
        return no_update
    subs = load_subs()
    if not subs.empty:
        subs["timestamp"] = pd.to_datetime(subs["timestamp"], errors="coerce")
        subs = subs.sort_values("timestamp", ascending=False)
        subs["timestamp"] = subs["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    return subs.to_dict("records")


@app.callback(
    Output("save-status", "children"),
    Input("btn-save", "n_clicks"),
    State("admin-table", "data")
)
def admin_save(n, rows):
    if not n:
        return ""
    if READ_ONLY:
        return dbc.Alert("Read-only mode: saving disabled.",
                         color="secondary")
    if rows is None:
        return dbc.Alert("No rows to save.", color="warning")

    df = pd.DataFrame(rows)
    ok, msg = save_subs(df)
    color = "success" if ok else "danger"
    return dbc.Alert(msg, color=color)


@app.callback(
    Output("submit-status", "children"),
    Input("btn-submit", "n_clicks"),
    State("in-student-id", "value"),
    State("in-iso3", "value"),
    State("in-title", "value"),
    State("in-summary", "value"),
    State("in-links", "value"),
    State("in-rating", "value"),
    State("in-status", "value")
)
def submit(n, student_id, iso3, title, summary, links, rating, status):
    if not n:
        return ""
    if READ_ONLY:
        return dbc.Alert("Read-only mode: submission disabled.",
                         color="secondary")

    missing = [
        label for value, label in [
            (iso3, "Country ISO‑3"),
            (title, "Title"),
            (summary, "Summary")
        ] if not value
    ]
    if missing:
        return dbc.Alert(f"Missing: {', '.join(missing)}", color="warning")

    subs = load_subs()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "timestamp": now,
        "student_id": (student_id or "").strip(),
        "country_iso3": (iso3 or "").strip().upper(),
        "title": (title or "").strip(),
        "summary_md": summary or "",
        "evidence_links": links or "",
        "rating": rating if rating is not None else "",
        "status": (status or "pending").lower()
    }

    subs = pd.concat([subs, pd.DataFrame([entry])], ignore_index=True)
    ok, msg = save_subs(subs)
    color = "success" if ok else "danger"
    return dbc.Alert(msg, color=color)


@app.callback(
    Output("download-csv", "data"),
    Input("btn-dl", "n_clicks"),
    prevent_initial_call=True
)
def download(n):
    if not n:
        return no_update
    df = load_subs()
    return dcc.send_data_frame(df.to_csv, "student_submissions.csv",
                               index=False)


# ------------------------------------------------------------------------------------
# Run
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host="0.0.0.0", port=port)

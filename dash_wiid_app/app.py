import os
from pathlib import Path
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
from datetime import datetime
import plotly.graph_objects as go


APP_DIR  = Path(__file__).resolve().parent
# Use DATA_DIR if provided (e.g., /data when using a Render Disk), otherwise /tmp/submissions (always writable)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/submissions"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LATEST_PATH = DATA_DIR / "wiid_latest_per_country.csv"
SUBS_PATH   = DATA_DIR / "student_submissions.csv"
READ_ONLY   = os.getenv("APP_READONLY", "0") == "0"

# One-time seeding from the repo's bundled data/ (read-only) to the writable DATA_DIR
repo_data = APP_DIR / "data"

if not LATEST_PATH.exists() and (repo_data / "wiid_latest_per_country.csv").exists():
    LATEST_PATH.write_bytes((repo_data / "wiid_latest_per_country.csv").read_bytes())

if not SUBS_PATH.exists() and (repo_data / "student_submissions.csv").exists():
    SUBS_PATH.write_bytes((repo_data / "student_submissions.csv").read_bytes())

def save_subs(df: pd.DataFrame):
    if READ_ONLY:
        return False, "Read-only mode: saving disabled."
    try:
        cols = ["timestamp","student_id","country_iso3","title","summary_md","evidence_links","rating","status"]
        df = df.reindex(columns=cols)
        df.to_csv(SUBS_PATH, index=False)
        return True, f"Saved to {SUBS_PATH}"
    except Exception as e:
        return False, f"Error saving: {e}"

# ---- Data loaders ----
def load_latest():
    latest = pd.read_csv(LATEST_PATH)
    latest["year"] = latest["year"].astype(int)
    latest["gini"] = pd.to_numeric(latest["gini"], errors="coerce")
    return latest

def load_subs():
    if not SUBS_PATH.exists():
        cols = ["timestamp","student_id","country_iso3","title","summary_md","evidence_links","rating","status"]
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(SUBS_PATH)
    if "status" in df.columns:
        df["status"] = df["status"].fillna("").str.lower()
    return df

def save_subs(df: pd.DataFrame):
    if READ_ONLY:
        return False, "Read-only mode: saving disabled."
    cols = ["timestamp","student_id","country_iso3","title","summary_md","evidence_links","rating","status"]
    df = df.reindex(columns=cols)
    df.to_csv(SUBS_PATH, index=False)
    return True, "Saved."

# ---- Figure ----
latest = load_latest()
fig_map = px.choropleth(
    latest, locations="c3", color="gini",
    hover_name="country",
    hover_data={"c3":False, "gini":":.2f", "year":True, "resource":True, "scale_detailed":True,
                "incomegroup":True, "region_wb":True},
    color_continuous_scale=px.colors.sequential.Plasma,
    range_color=(latest["gini"].min(), latest["gini"].max()),
    labels={"gini":"Gini (0–100)"},
    title="Latest Available Gini by Country (WIID curated)"
)
fig_map.update_layout(coloraxis_colorbar=dict(title='Gini'))

# ---- App layout ----
app = Dash(__name__, external_stylesheets=[dbc.themes.LITERA], title="WIID Map + Student Insights")
server = app.server

map_panel = dbc.Col(
    dcc.Graph(
        id="map",
        config={"responsive": True},
        style={"height": "100vh"}
    ),
    md=8
)

right_panel = dbc.Col([
    html.Div(id="country-facts"),
    html.Hr(),
    html.H5("Featured Student Insight"),
    html.Div(id="student-note"),
    html.Hr(),
    html.H6("Recent Submissions"),
    dash_table.DataTable(
        id="sub-table",
        columns=[{"name": c, "id": c} for c in ["timestamp","student_id","title","rating","status"]],
        page_size=6,
        style_cell={"whiteSpace":"normal","height":"auto","textAlign":"left"},
        style_table={"overflowX":"auto"},
    ),
    dcc.Interval(id="interval-refresh", interval=20_000, n_intervals=0)
], id="right-panel", md=4, style={"height":"100vh","overflowY":"auto"})

admin_help = dcc.Markdown("""
**Admin mode** (TA/Instructor):
- Edit statuses (`approved`, `pending`, `rejected`) directly in the table.
- Click **Save** to write back to `student_submissions.csv`.
""")
admin_controls = dbc.Row([
    dbc.Col(dbc.Badge("Read-only", color="secondary", className="me-2") if READ_ONLY else dbc.Badge("Writable", color="success", className="me-2"), md="auto"),
    dbc.Col(dbc.Button("Save Changes", id="btn-save", color="primary", n_clicks=0, disabled=READ_ONLY), md="auto"),
    dbc.Col(html.Div(id="save-status", className="ms-2"), md="auto"),
], className="mb-2")
admin_table = dash_table.DataTable(
    id="admin-table",
    columns=[{"name": c, "id": c, "editable": True} for c in
             ["timestamp","student_id","country_iso3","title","summary_md","evidence_links","rating","status"]],
    page_size=10, editable=True, row_deletable=False,
    style_cell={"whiteSpace":"pre-wrap","height":"auto","textAlign":"left"},
    style_table={"overflowX":"auto"}
)
admin_tab = dbc.Container([admin_help, admin_controls, admin_table, dcc.Interval(id="interval-admin-refresh", interval=30_000, n_intervals=0)], fluid=True, className="p-3")

form_help = dcc.Markdown("""
**Student submission (optional):**
Add your note below. Use Markdown in the summary. Instructor may approve it before featuring.
""")
submission_form = dbc.Card(dbc.CardBody([
    form_help,
    dbc.Row([
        dbc.Col(dbc.Input(id="in-student-id", placeholder="Student ID or alias"), md=3),
        dbc.Col(dbc.Input(id="in-iso3", placeholder="Country ISO-3 (e.g., ARG)"), md=2),
        dbc.Col(dbc.Input(id="in-title", placeholder="Title (e.g., 'Inequality in Argentina, 2018–2023')"), md=7),
    ], className="mb-2"),
    dbc.Textarea(id="in-summary", placeholder="Summary (Markdown supported)", style={"height":"140px"}),
    dbc.Input(id="in-links", placeholder="Evidence links (semicolon-separated)", className="mt-2"),
    dbc.Row([
        dbc.Col(dbc.Input(id="in-rating", type="number", min=1, max=5, step=1, placeholder="1-5 rating"), md=2),
        dbc.Col(dbc.Select(id="in-status", options=[{"label":"pending","value":"pending"},{"label":"approved","value":"approved"},{"label":"rejected","value":"rejected"}], value="pending"), md=3),
        dbc.Col(dbc.Button("Submit", id="btn-submit", color="secondary", className="mt-2 mt-md-0", n_clicks=0, disabled=READ_ONLY), md=2),
        dbc.Col(html.Div(id="submit-status"), md=5),
    ], className="mt-2")
]))
student_tab = dbc.Container(submission_form, fluid=True, className="p-3")

app.layout = dbc.Container([
    html.H2("Visualizing Income Inequality + Student Insights"),
    dcc.Tabs(id="tabs", value="tab-map", children=[
        dcc.Tab(label="Map & Insights", value="tab-map", children=[dbc.Row([map_panel, right_panel], className="mt-3")]),
        dcc.Tab(label="Admin", value="tab-admin", children=[admin_tab]),
        dcc.Tab(label="Submit", value="tab-submit", children=[student_tab]),
    ])
], fluid=True)

# ---- helpers ----
def country_facts_card(row):
    if row is None:
        return dbc.Alert("Click a country on the map to see details.", color="info", className="mb-3")
    items = [
        html.Li(["Country: ", html.B(row["country"]) ]),
        html.Li(f"ISO-3: {row['c3']}") ,
        html.Li(f"Gini (latest): {row['gini']:.2f}"),
        html.Li(f"Reference year: {int(row['year'])}"),
        html.Li(f"Concept: {row['resource']}"),
        html.Li(f"Scale: {row['scale_detailed']}"),
        html.Li(f"Income group: {row['incomegroup']}"),
        html.Li(f"Region: {row['region_wb']}"),
        html.Li("Note: Latest year & concepts differ across countries; interpret cautiously."),
    ]
    return dbc.Card(dbc.CardBody([html.H5("Country Facts", className="card-title"), html.Ul(items)]))

def featured_md_block(note):
    if note is None:
        return dcc.Markdown("_No approved student note yet for this country._")
    md = f"""### {note.get('title','(Untitled)')}
{note.get('summary_md','')}
**Evidence:** {note.get('evidence_links','')}
**Rating:** {note.get('rating','')}/5
"""
    return dcc.Markdown(md)

# ---- callbacks ----
@app.callback(
    Output("map", "figure"),                      # NEW: update the map figure
    Output("country-facts", "children"),
    Output("student-note", "children"),
    Output("sub-table", "data"),
    Input("map", "clickData"),
    Input("interval-refresh", "n_intervals")
)
def update_country_panel(clickData, _):
    subs = load_subs()

    # --- Build the base choropleth (same as you do at startup) ---
    base_fig = px.choropleth(
        latest, locations="c3", color="gini",
        hover_name="country",
        hover_data={"c3": False, "gini":":.2f", "year":True, "resource":True,
                    "scale_detailed":True, "incomegroup":True, "region_wb":True},
        color_continuous_scale=px.colors.sequential.Plasma,
        range_color=(latest["gini"].min(), latest["gini"].max()),
        labels={"gini":"Gini (0–100)"},
        title="Latest Available Gini by Country (WIID curated)"
    )
    base_fig.update_layout(coloraxis_colorbar=dict(title='Gini'))

    # --- Compute the outlined countries list ---
    # Any submission:
    submitted_iso = subs["country_iso3"].dropna().str.upper().unique().tolist()
    # If you prefer approved-only, use this instead:
    # submitted_iso = subs.loc[subs["status"].str.lower().eq("approved"), "country_iso3"].dropna().str.upper().unique().tolist()

    if submitted_iso:
        overlay_df = pd.DataFrame({"c3": submitted_iso, "flag": 1})

        # Transparent fill, bold outline
        overlay = go.Choropleth(
            locations=overlay_df["c3"],
            z=overlay_df["flag"],
            locationmode="ISO-3",
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],  # fully transparent
            showscale=False,
            marker_line_color="#10e0e0",   # outline color (cyan)
            marker_line_width=2.5,
            hoverinfo="skip",
            name="Student submissions"
        )
        base_fig.add_trace(overlay)

        # Optional helper note
        base_fig.add_annotation(
            x=0.01, y=1.02, xref="paper", yref="paper",
            showarrow=False,
            text="Outlined countries: student submissions present",
            font=dict(size=12, color="#10e0e0")
        )

    # --- Your existing panel logic (unchanged below) ---
    if not clickData:
        return base_fig, country_facts_card(None), featured_md_block(None), []

    iso3 = clickData["points"][0]["location"]
    row = latest.loc[latest["c3"] == iso3].iloc[0].to_dict()

    sub_iso = subs[subs["country_iso3"] == iso3].copy()
    table_data = []
    if not sub_iso.empty:
        sub_iso["timestamp"] = pd.to_datetime(sub_iso["timestamp"], errors="coerce")
        table_data = sub_iso.sort_values("timestamp", ascending=False)[
            ["timestamp","student_id","title","rating","status"]
        ].head(12)
        table_data["timestamp"] = table_data["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        table_data = table_data.to_dict("records")

    featured = None
    approved = sub_iso[sub_iso["status"].str.lower() == "approved"].copy()
    if not approved.empty:
        approved["timestamp"] = pd.to_datetime(approved["timestamp"], errors="coerce")
        featured = approved.sort_values("timestamp", ascending=False).iloc[0].to_dict()

    return base_fig, country_facts_card(row), featured_md_block(featured), table_data

@app.callback(
    Output("admin-table", "data"),
    Input("tabs", "value"),
    Input("interval-admin-refresh", "n_intervals"),
)
def refresh_admin_data(tab_value, _):
    if tab_value != "tab-admin":
        return dash_table.DataTable.data
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
def save_admin_edits(n_clicks, rows):
    if not n_clicks:
        return ""
    if READ_ONLY:
        return dbc.Alert("Read-only mode: saving disabled.", color="secondary", className="mt-2")
    df = pd.DataFrame(rows)
    ok, msg = save_subs(df)
    alert_color = "success" if ok else "danger"
    return dbc.Alert(msg, color=alert_color, className="mt-2")

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
def append_submission(n_clicks, student_id, iso3, title, summary, links, rating, status):
    if not n_clicks:
        return ""
    if READ_ONLY:
        return dbc.Alert("Read-only mode: submission disabled.", color="secondary")
    missing = []
    if not iso3: missing.append("Country ISO-3")
    if not title: missing.append("Title")
    if not summary: missing.append("Summary")
    if missing:
        return dbc.Alert(f"Missing: {', '.join(missing)}", color="warning")
    subs = load_subs()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    new_row = {
        "timestamp": now,
        "student_id": student_id or "",
        "country_iso3": (iso3 or "").strip().upper(),
        "title": (title or "").strip(),
        "summary_md": summary or "",
        "evidence_links": links or "",
        "rating": rating if rating is not None else "",
        "status": (status or "pending").lower()
    }
    subs = pd.concat([subs, pd.DataFrame([new_row])], ignore_index=True)
    ok, msg = save_subs(subs)
    color = "success" if ok else "danger"
    return dbc.Alert(msg, color=color)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8050))   # Render sets PORT at runtime
    app.run(
        debug=False,           # Turn off debug on Render
        host="0.0.0.0",
        port=port
    )

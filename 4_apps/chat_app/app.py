import html
import logging
import os
import time
import uuid
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient
from agent_client import query_agent
import lakebase

APP_TITLE = "Marketing Campaign Insights"

# Set page configuration (must be the first Streamlit command)
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="figures/brand_logo.png",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The Agent Bricks agent app to call (set in app.yaml; `agent-bricks-` + deployment_name in
# 3_agent-bricks/agent/agent.toml).
AGENT_APP_NAME = os.getenv("AGENT_APP_NAME")
assert AGENT_APP_NAME, (
    "Set the AGENT_APP_NAME environment variable (app.yaml) to the name of the agent app "
    "deployed with `agentbricks deploy`, for example agent-bricks-marketing-agent."
)

# Starter questions shown on the empty chat screen: (icon, label, prompt sent to the agent).
SUGGESTIONS = [
    (":material/trending_up:", "Top campaigns by sales",
     "Which campaigns drove the most sales in 2024?"),
    (":material/groups:", "Sales by customer segment",
     "How do total sales break down by customer segment?"),
    (":material/location_on:", "Best-performing cities",
     "Which cities generate the most sales, and which customer segments drive them?"),
    (":material/savings:", "Budget vs. results",
     "Compare budget and sales for the top 5 campaigns."),
]

# Built-in avatars keep the user/assistant test IDs that style.css uses to style each role.
ASSISTANT_AVATAR = None
USER_AVATAR = None


def get_user_info():
    headers = st.context.headers
    return dict(
        user_name=headers.get("X-Forwarded-Preferred-Username"),
        user_email=headers.get("X-Forwarded-Email"),
        user_id=headers.get("X-Forwarded-User"),
    )

user_info = get_user_info()


# Load custom CSS
def load_css():
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()


def render_message(content: str):
    """Render chat content, escaping '$' so Streamlit doesn't treat dollar
    amounts (e.g. "$55.66 million") as LaTeX math delimiters."""
    st.markdown(content.replace("$", "\\$"))


@st.cache_resource
def _get_ws():
    return WorkspaceClient()


@st.cache_data(ttl=600)
def get_sidebar_links():
    """Build the sidebar quick-links at runtime so the demo is portable: nothing
    is hardcoded to a specific workspace host / org / dashboard id. The host and
    org are read from the app's own credentials, and the dashboard id is
    resolved from an env var (DASHBOARD_ID) or by display name (DASHBOARD_NAME)."""
    w = _get_ws()
    host = w.config.host or ""
    if host and not host.startswith("http"):
        host = f"https://{host}"

    try:
        org = w.get_workspace_id()
    except Exception:
        org = os.getenv("DATABRICKS_WORKSPACE_ID")

    # "Insights Portal" opens the published dashboard (not Databricks One).
    dashboard_url = None
    dash_id = os.getenv("DASHBOARD_ID")
    dash_name = os.getenv("DASHBOARD_NAME", "Marketing Campaign Analytics - Sales Dashboard")
    try:
        if not dash_id:
            dash_id = next(
                (d.dashboard_id for d in w.lakeview.list()
                 if d.display_name == dash_name),
                None,
            )
        if dash_id and host:
            query = f"?o={org}&view=fullscreen" if org else "?view=fullscreen"
            dashboard_url = f"{host}/dashboardsv3/{dash_id}/published{query}"
    except Exception as e:
        logger.warning("Could not resolve Sales Dashboard link: %s", e)

    return dashboard_url


INSIGHTS_PORTAL_URL = get_sidebar_links()

PAGES = {"Assistant": ":material/forum: Assistant", "Add data": ":material/add_circle: Add data"}


def new_conversation():
    st.session_state.messages = []
    st.session_state.agent_session_id = str(uuid.uuid4())


def _user_card() -> str:
    email = user_info.get("user_email") or ""
    name = user_info.get("user_name") or ""
    if not name or "@" in name:  # Databricks Apps sends the email as the username
        local = (name or email).split("@")[0]
        name = " ".join(p.capitalize() for p in local.replace("_", ".").split(".") if p) or "Guest"
    initial = html.escape(name[:1].upper() or "?")
    return f"""
    <div class="sb-user">
        <div class="sb-avatar">{initial}</div>
        <div class="sb-user-text"><b>{html.escape(name)}</b>{html.escape(email)}</div>
    </div>"""


# Sidebar: brand, navigation, quick links, signed-in user (always visible)
with st.sidebar:
    st.image("figures/brand_logo.png", use_container_width=True)
    st.markdown(f"<div class='sb-title'>{APP_TITLE}</div>"
                "<div class='sb-sub'>Your AI analyst for campaigns, customers and sales</div>",
                unsafe_allow_html=True)

    page = st.segmented_control(
        "Page", list(PAGES), format_func=PAGES.get, default="Assistant",
        key="page", label_visibility="collapsed",
    ) or "Assistant"  # clicking the selected option again clears it; stay on a page

    if page == "Assistant":
        st.button("New conversation", icon=":material/edit_square:", use_container_width=True,
                  on_click=new_conversation,
                  disabled=not st.session_state.get("messages"))

    if INSIGHTS_PORTAL_URL:
        st.markdown("<div class='sb-section'>Explore</div>", unsafe_allow_html=True)
        st.link_button("Insights Portal", INSIGHTS_PORTAL_URL, icon=":material/space_dashboard:",
                       use_container_width=True)

    st.markdown("<div class='sb-section'>Signed in</div>" + _user_card()
                + "<div class='sb-footer'>Built on Databricks Apps · Agent Bricks · Lakebase</div>",
                unsafe_allow_html=True)

CUSTOMER_SEGMENTS = [
    "Budget Shopper", "Churn Risk", "Deal Seeker", "First-time Buyer", "High Value",
    "In-Store Regular", "Loyal Customer", "Occasional Shopper", "Online Shopper", "Premium Shopper",
]
LOCATIONS = [
    "Albuquerque", "Arlington", "Atlanta", "Austin", "Baltimore", "Boston", "Charlotte", "Chicago",
    "Colorado Springs", "Columbus", "Dallas", "Denver", "Detroit", "El Paso", "Fort Worth", "Fresno",
    "Houston", "Indianapolis", "Jacksonville", "Kansas City", "Las Vegas", "Long Beach", "Los Angeles",
    "Louisville", "Memphis", "Mesa", "Miami", "Milwaukee", "Minneapolis", "Nashville", "New Orleans",
    "New York", "Oakland", "Oklahoma City", "Omaha", "Philadelphia", "Phoenix", "Portland", "Raleigh",
    "Sacramento", "San Antonio", "San Diego", "San Francisco", "San Jose", "Seattle", "Tampa", "Tucson",
    "Tulsa", "Virginia Beach", "Washington",
]


def page_header(title: str, subtitle: str):
    st.markdown(f"<div class='page-head'><h2>{title}</h2><p>{subtitle}</p></div>",
                unsafe_allow_html=True)


def data_page():
    """Add campaigns and customers. Rows go to Lakebase Postgres; Lakehouse Sync streams them to
    Unity Catalog, where Genie, the dashboard, and the agent read them."""
    page_header("Add data",
                "Create campaigns and customers. They're saved in Lakebase and synced to the "
                "lakehouse, so the assistant can answer questions about them within a few minutes.")
    if not lakebase.is_configured():
        st.info("Lakebase is not connected to this app yet. Run `5_lakebase/0_SetupLakebase` "
                "to enable this page.", icon=":material/database_off:")
        return
    st.badge("Lakebase connected", icon=":material/database:", color="green")
    created_by = user_info.get("user_email") or "unknown"
    campaigns_tab, customers_tab = st.tabs([":material/campaign: New campaign",
                                            ":material/person_add: New customer"])

    with campaigns_tab:
        with st.form("new_campaign", clear_on_submit=True):
            name = st.text_input("Campaign name", placeholder="e.g. Holiday Running Push")
            c1, c2 = st.columns(2)
            start = c1.date_input("Start date", value=date(2024, 11, 1),
                                  min_value=lakebase.CALENDAR_START, max_value=lakebase.CALENDAR_END)
            end = c2.date_input("End date", value=date(2024, 11, 30),
                                min_value=lakebase.CALENDAR_START, max_value=lakebase.CALENDAR_END)
            budget = st.number_input("Budget (USD)", min_value=1000, max_value=10_000_000, value=250_000,
                                     step=5000, help="Total campaign budget in US dollars.")
            st.caption("Dates must fall in 2024, the period covered by the sales calendar.")
            if st.form_submit_button("Add campaign", type="primary", icon=":material/add:"):
                try:
                    new = lakebase.insert_campaign(name, start, end, int(budget), created_by)
                    st.toast(f"Campaign **{new['campaign_id']}** added", icon=":material/check_circle:")
                    st.success(f"Added campaign {new['campaign_id']}. It's at the top of the table below. "
                               "Lakehouse Sync copies it to Unity Catalog within a few minutes.")
                except ValueError as e:
                    st.error(str(e))
        _records_section("campaigns")

    with customers_tab:
        with st.form("new_customer", clear_on_submit=True):
            c1, c2 = st.columns(2)
            first = c1.text_input("First name")
            last = c2.text_input("Last name")
            email = st.text_input("Email", placeholder="name@example.com")
            c3, c4 = st.columns(2)
            location = c3.selectbox("Residential location", LOCATIONS)
            segment = c4.selectbox("Customer segment", CUSTOMER_SEGMENTS)
            if st.form_submit_button("Add customer", type="primary", icon=":material/add:"):
                try:
                    new = lakebase.insert_customer(first, last, email, location, segment, created_by)
                    st.toast(f"Customer **{new['customer_id']}** added", icon=":material/check_circle:")
                    st.success(f"Added customer {new['customer_id']}. It's at the top of the table below. "
                               "Lakehouse Sync copies it to Unity Catalog within a few minutes.")
                except ValueError as e:
                    st.error(str(e))
        _records_section("customers")


# Friendlier headers and formats for the record tables.
_COLUMN_CONFIG = {
    "campaign_sk": None, "customer_sk": None,  # internal keys: hidden
    "campaign_id": st.column_config.TextColumn("ID"),
    "customer_id": st.column_config.TextColumn("ID"),
    "campaign_name": st.column_config.TextColumn("Campaign"),
    "start_date_sk": st.column_config.DateColumn("Start", format="MMM D, YYYY"),
    "end_date_sk": st.column_config.DateColumn("End", format="MMM D, YYYY"),
    "campaign_budget": st.column_config.NumberColumn("Budget", format="dollar"),
    "first_name": st.column_config.TextColumn("First name"),
    "last_name": st.column_config.TextColumn("Last name"),
    "email": st.column_config.TextColumn("Email"),
    "residential_location": st.column_config.TextColumn("City"),
    "customer_segment": st.column_config.TextColumn("Segment"),
    "created_by": st.column_config.TextColumn("Added by"),
    "created_at": st.column_config.DatetimeColumn("Added at", format="MMM D, YYYY h:mm a"),
    "record_source": st.column_config.TextColumn("Source", help="source = original data, app = added here"),
}
_SOURCES = {"all": "All sources", "source": "Source data", "app": "Added in app"}
def _prepare(columns, rows) -> list[dict]:
    """Rows -> dicts for st.dataframe: date keys (days of 2024, see lakebase.date_sk) become dates."""
    records = [dict(zip(columns, r)) for r in rows]
    for rec in records:
        for col in ("start_date_sk", "end_date_sk"):
            if isinstance(rec.get(col), int):
                rec[col] = lakebase.CALENDAR_START + timedelta(days=rec[col] - 1)
        if "campaign_budget" in rec and rec["campaign_budget"] is not None:
            rec["campaign_budget"] = float(rec["campaign_budget"])
    return records


def _table(columns, rows, height=None):
    df = pd.DataFrame(_prepare(columns, rows), columns=columns)
    if "created_at" in df:  # source rows have no timestamp: NaT renders as an empty cell
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    st.dataframe(df, hide_index=True, use_container_width=True, height=height,
                 column_config={c: _COLUMN_CONFIG[c] for c in columns if c in _COLUMN_CONFIG})


def _records_section(table: str):
    """All records (synced source data + app records), read live from Lakebase."""
    st.markdown(f"<div class='section-label'>{table.capitalize()}</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([5, 3, 1], vertical_alignment="bottom")
    search = c1.text_input("Search", key=f"search_{table}", label_visibility="collapsed",
                           placeholder=f"Search {table}...")
    source = c2.selectbox("Source", list(_SOURCES), format_func=_SOURCES.get, key=f"source_{table}",
                          label_visibility="collapsed")
    c3.button("", icon=":material/refresh:", key=f"refresh_{table}", help="Reload", use_container_width=True)
    try:
        n, has_source = lakebase.counts(table)
        columns, rows = lakebase.browse(table, search, source)
    except Exception as e:  # e.g. the database is still waking up
        logger.warning("Could not read %s: %s", table, e)
        st.caption("Could not load records right now. Try refresh in a moment.")
        return
    total = sum(n.values())
    shown = f"showing {len(rows):,}" + (" (first 200 matches; search to narrow down)" if len(rows) >= 200 else "")
    if has_source:
        st.caption(f"**{total:,}** {table} in Lakebase: {n.get('source', 0):,} from the source data "
                   f"(synced table), {n.get('app', 0):,} added in the app · {shown}.")
    else:
        st.caption(f"**{n.get('app', 0):,}** {table} added in the app · {shown}. The source data isn't synced "
                   "to Lakebase yet: run `5_lakebase/0_SetupLakebase` to create the synced tables.")
    if rows:
        _table(columns, rows, height=360)
    else:
        st.caption("No matching records.")


def _empty_state():
    """Welcome screen with starter questions, shown before the first message."""
    st.markdown(
        "<div class='hero'>"
        "<span class='eyebrow'>✦ AI assistant</span>"
        "<h1>Ask anything about your <span class='gradient-text'>campaigns</span></h1>"
        "<p>Get instant answers on campaign performance, customer segments and sales, "
        "straight from your governed lakehouse data.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="suggestions"):
        cols = st.columns(2)
        for i, (icon, label, prompt) in enumerate(SUGGESTIONS):
            if cols[i % 2].button(label, icon=icon, key=f"suggestion_{i}", use_container_width=True,
                                  help=prompt):
                st.session_state.pending_prompt = prompt
                st.rerun()


def chat_page():
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
    # One agent session per browser chat: the agent keeps the conversation history server-side.
    if "agent_session_id" not in st.session_state:
        st.session_state.agent_session_id = str(uuid.uuid4())

    typed = st.chat_input("Ask about campaigns, customers or sales...")
    prompt = typed or st.session_state.pop("pending_prompt", None)

    if not st.session_state.messages and not prompt:
        _empty_state()
        return

    # Display all messages from history
    for message in st.session_state.messages:
        avatar = USER_AVATAR if message["role"] == "user" else ASSISTANT_AVATAR
        with st.chat_message(message["role"], avatar=avatar):
            render_message(message["content"])

    if not prompt:
        return

    # Add the new user message to history and display it
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=USER_AVATAR):
        render_message(prompt)

    # Get and display the assistant response
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        started = time.monotonic()
        with st.status("Analyzing your data...", expanded=False) as status:
            st.write("Routing your question to the marketing agent...")
            try:
                # Send only the new turn; the agent's session store has the history.
                assistant_response = query_agent(
                    agent_app_name=AGENT_APP_NAME,
                    session_id=st.session_state.agent_session_id,
                    user_message=prompt,
                )
                status.update(label=f"Answered in {time.monotonic() - started:.1f}s",
                              state="complete", expanded=False)
            except Exception as e:
                logger.exception("Agent call failed")
                status.update(label="Something went wrong", state="error", expanded=False)
                assistant_response = ("Sorry, I couldn't reach the marketing agent just now. "
                                      f"Please try again in a moment.\n\n`{type(e).__name__}`")
        render_message(assistant_response)

    st.session_state.messages.append({"role": "assistant", "content": assistant_response})
    # Rerun so the sidebar's "New conversation" button picks up the new history.
    st.rerun()


if page == "Add data":
    data_page()
else:
    chat_page()

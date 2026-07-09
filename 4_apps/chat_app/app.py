import logging
import os
import time
import streamlit as st
from databricks.sdk import WorkspaceClient
from model_serving_utils import query_endpoint, is_endpoint_supported

# Set page configuration (must be the first Streamlit command)
st.set_page_config(
    page_title="Retail Insights Assistant",
    page_icon="figures/brand_logo.png",
    layout="centered"
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure environment variable is set correctly
SERVING_ENDPOINT = os.getenv('SERVING_ENDPOINT')
assert SERVING_ENDPOINT, \
    ("Unable to determine serving endpoint to use for chatbot app. If developing locally, "
     "set the SERVING_ENDPOINT environment variable to the name of your serving endpoint. If "
     "deploying to a Databricks app, include a serving endpoint resource named "
     "'serving_endpoint' with CAN_QUERY permissions, as described in "
     "https://docs.databricks.com/aws/en/generative-ai/agent-framework/chat-app#deploy-the-databricks-app")

# Check if the endpoint is supported
endpoint_supported = is_endpoint_supported(SERVING_ENDPOINT)

# Log a warning if endpoint is not standard, but don't block usage
if not endpoint_supported:
    logger.warning(
        f"Endpoint '{SERVING_ENDPOINT}' has a non-standard task type. "
        "The app will attempt to use it anyway."
    )

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
    org are read from the app's own credentials, and the Sales Dashboard id is
    resolved from an env var (DASHBOARD_ID) or by display name (DASHBOARD_NAME)."""
    w = _get_ws()
    host = w.config.host or ""
    if host and not host.startswith("http"):
        host = f"https://{host}"

    try:
        org = w.get_workspace_id()
    except Exception:
        org = os.getenv("DATABRICKS_WORKSPACE_ID")

    # Databricks One is the "Insights Portal" landing page.
    portal_url = f"{host}/one" if host else None

    # Resolve the published Sales Dashboard link.
    dashboard_url = None
    dash_id = os.getenv("DASHBOARD_ID")
    dash_name = os.getenv("DASHBOARD_NAME", "Zanlorensi Athletics - Sales Dashboard")
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

    return portal_url, dashboard_url


INSIGHTS_PORTAL_URL, SALES_DASHBOARD_URL = get_sidebar_links()

# Sidebar with logo and title (always visible)
with st.sidebar:
    # Full-width (square) logo.
    st.image("figures/brand_logo.png", use_container_width=True)
    
    st.markdown("<h2 style='text-align: center;'>Retail Insights Assistant</h2>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("<p style='text-align: center;'><em>Chatbot powered by <strong>Databricks Apps</strong></em></p>", unsafe_allow_html=True)

    _links = []
    if INSIGHTS_PORTAL_URL:
        _links.append(f'<li><a href="{INSIGHTS_PORTAL_URL}" target="_blank">Insights Portal</a></li>')
    if SALES_DASHBOARD_URL:
        _links.append(f'<li><a href="{SALES_DASHBOARD_URL}" target="_blank">Sales Dashboard</a></li>')
    if _links:
        st.markdown(f"""
        <div style='text-align: center;'>
            <ul style='display: inline-block; text-align: left; margin: 0;'>
                {''.join(_links)}
            </ul>
        </div>
        """, unsafe_allow_html=True)
    st.markdown("---")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display all messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        render_message(message["content"])

# Accept user input
if prompt := st.chat_input("Ask me anything!"):
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display ONLY the new user message (history already displayed above)
    with st.chat_message("user"):
        render_message(prompt)
    
    # Get and display assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # Show loading
        with message_placeholder.container():
            with st.status("Thinking...", expanded=False):
                st.write("Processing your request...")
                time.sleep(2)
                st.write("Orchestrating to the right agent...")
                time.sleep(1)
                st.write("Formulating the final response...")
                
                # Query the endpoint (limit to last 10 messages to manage context length)
                assistant_response = query_endpoint(
                    endpoint_name=SERVING_ENDPOINT,
                    messages=st.session_state.messages[-10:],
                )["content"]
        
        # Replace loading with response
        render_message(assistant_response)
        
        # Add to history
        st.session_state.messages.append({"role": "assistant", "content": assistant_response})

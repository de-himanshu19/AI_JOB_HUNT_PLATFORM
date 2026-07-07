"""Static local styling for the dashboard."""

import streamlit as st


CSS = """
<style>
:root {
  --ink: #17211d;
  --muted: #5d6861;
  --paper: #f7f3e9;
  --card: #fffdf7;
  --line: #d9d1bf;
  --accent: #0d7165;
  --warm: #c86432;
}
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 88% 8%, rgba(200,100,50,.11), transparent 24rem),
    linear-gradient(135deg, #f7f3e9 0%, #f1eee5 55%, #e8f0eb 100%);
  color: var(--ink);
}
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #17211d 0%, #21332b 100%);
}
[data-testid="stSidebar"] * { color: #f7f3e9; }
h1, h2, h3 { font-family: Georgia, 'Times New Roman', serif; letter-spacing: -.02em; }
p, label, button, input, textarea, [data-testid="stDataFrame"] {
  font-family: 'Aptos', 'Trebuchet MS', sans-serif;
}
.block-container { max-width: 1500px; padding-top: 2.2rem; }
.eyebrow {
  color: var(--accent); text-transform: uppercase; letter-spacing: .16em;
  font-size: .74rem; font-weight: 750; margin-bottom: .35rem;
}
.page-lede { color: var(--muted); max-width: 58rem; font-size: 1.02rem; }
[data-testid="stMetric"] {
  background: rgba(255,253,247,.84); border: 1px solid var(--line);
  border-radius: 4px; padding: .9rem 1rem;
  box-shadow: 0 8px 24px rgba(23,33,29,.06);
}
[data-testid="stExpander"], [data-testid="stForm"] {
  background: rgba(255,253,247,.72); border-color: var(--line);
}
.status-note {
  border-left: 4px solid var(--accent); background: rgba(255,253,247,.82);
  padding: .75rem 1rem; margin: .5rem 0 1rem;
}
a:focus-visible, button:focus-visible, input:focus-visible {
  outline: 3px solid #e3a43b !important; outline-offset: 2px;
}
@media (max-width: 720px) {
  .block-container { padding: 1rem .8rem; }
}
</style>
"""


def apply_styles() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


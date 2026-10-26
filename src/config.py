"""Read API keys: Streamlit secrets first (works locally and on Streamlit Cloud), then env vars."""
import os


def get_secret(name):
    try:
        import streamlit as st

        return st.secrets[name]
    except Exception:
        return os.environ.get(name)

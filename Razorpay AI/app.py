"""
AI Finance Controller - Web Application Entry Point.
Run directly via:
    python app.py
or
    py app.py
"""

from src.web_app import start_server

if __name__ == "__main__":
    start_server(port=5000, open_browser=True)

# run_dashboard.py
"""Launch the demo dashboard:  py -3 run_dashboard.py  ->  http://127.0.0.1:8000"""
import uvicorn

from server.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

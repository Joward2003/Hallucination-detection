"""Persistent, real-provider desktop workbench entry point."""
from credit_review.workbench.app import create_workbench_app

app = create_workbench_app()

def run():
    import uvicorn
    uvicorn.run('credit_review.api.server:app', host='127.0.0.1', port=8000, reload=False)

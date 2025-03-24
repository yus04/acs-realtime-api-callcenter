import uvicorn
from fastapi import FastAPI, WebSocket
from contextlib import asynccontextmanager
from config import *
from clients import *
from job_router import init_job_router_state
from call_handler import router as call_handler_router
from websocket_handler import websocket_endpoint as ws_handler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Attach shared state to app.state
    app.state.conversation_states = {}
    app.state.job_id_to_call_id = {}
    # Initialize the Job Router state (queues, policies, workers, etc.)
    await init_job_router_state(app)
    yield

app = FastAPI(lifespan=lifespan)

# Include REST endpoints (incoming call and callbacks)
app.include_router(call_handler_router)

# Setup the WebSocket endpoint for handling AI conversation
@app.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await ws_handler(websocket, call_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)

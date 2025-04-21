import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from state_manager import ConversationStateManager, RealtimeManager
from job_router import JobRouter
from router import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.conversation_state_manager = ConversationStateManager()
    app.state.realtime_manager = RealtimeManager()
    app.state.job_router = JobRouter()
    await app.state.job_router.init()
    yield

app = FastAPI(lifespan = lifespan)
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host = "0.0.0.0", port = 8080)

"""FastAPI application factory and router registration."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.routers.threads import router as threads_router

configure_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(
    title="AI-Powered Zoho Project Chatbot",
    version="1.0.0",
    description="Conversational AI chatbot that connects to Zoho Projects via its REST API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(threads_router)

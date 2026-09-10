from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.connection import init_db
from api.routes_invoices import router as invoices_router
from api.routes_payment_page import router as payment_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="BluPal Card-to-Card Payment Platform",
        description="Automated card-to-card payment gateway powered by BluBank active sessions",
        version="1.0.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(invoices_router)
    app.include_router(payment_router)

    @app.get("/")
    async def root():
        return {
            "name": "BluPal Automated Gateway API",
            "status": "online",
            "documentation": "/docs"
        }

    return app

app = create_app()

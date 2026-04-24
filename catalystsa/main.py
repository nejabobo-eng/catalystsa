from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from catalystsa.database import Base, engine
from catalystsa.routes import orders, payments, webhooks, admin, public, products_admin, migrate
from catalystsa.routes.test_orders import router_test

app = FastAPI()

# Configure CORS
origins = [
    "http://localhost:3000",
    "https://catalystsa-frontend.vercel.app",
    "https://catalystsa-admin-fyd5.vercel.app",  # Admin panel
    "https://catalystsa-admin-fyd5-git-main-nejabobo-engs-projects.vercel.app",  # Admin git preview
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}

# Product routes (admin + public)
app.include_router(products_admin.router, prefix="", tags=["Products"])
app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(webhooks.router, prefix="/yoco", tags=["Webhooks"])
app.include_router(public.router, prefix="", tags=["Public"])
app.include_router(admin.router, prefix="", tags=["Admin"])
app.include_router(migrate.router, prefix="", tags=["Migration"])
app.include_router(router_test, prefix="", tags=["Testing"])


@app.get("/")
def root():
    return {
        "message": "CatalystSA API running",
        "version": "2.0-products-admin",
        "timestamp": "2024-01-15T12:00:00Z"
    }


@app.get("/__version")
def version():
    return {
        "version": "NEW-PRODUCTS-ADMIN-V1",
        "routes_loaded": "products_admin with x1.6 markup"
    }

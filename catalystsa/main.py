from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from catalystsa.database import Base, engine
from catalystsa.routes import products, orders, payments, webhooks

app = FastAPI()

# Configure CORS
origins = [
    "http://localhost:3000",
    "https://catalystsa-frontend.vercel.app",
    "https://*.vercel.app",  # Allow all Vercel preview deployments
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(webhooks.router, prefix="/yoco", tags=["Webhooks"])


@app.get("/")
def root():
    return {"message": "CatalystSA API running"}

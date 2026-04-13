from fastapi import FastAPI
from catalystsa.database import Base, engine
from catalystsa.routes import products, orders, payments

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])


@app.get("/")
def root():
    return {"message": "CatalystSA API running"}

from fastapi import FastAPI
from database import Base, engine
from routes import products, orders

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(orders.router, prefix="/orders", tags=["Orders"])


@app.get("/")
def root():
    return {"message": "CatalystSA API running"}

from fastapi import FastAPI

app = FastAPI(title="Microservice Observability Dashboard")


@app.get("/health")
def health() -> dict[str, str]:
	return {"status": "ok"}

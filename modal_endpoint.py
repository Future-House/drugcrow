import json
import os
from typing import Dict

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from modal import Image, Secret, Stub, asgi_app

stub = Stub("drugcrow")
web_app = FastAPI()
auth_scheme = HTTPBearer()

image = (
    Image.debian_slim(python_version="3.11")
    .pip_install(
            "langchain==0.1.16",
            "pandas",
            "numpy",
            "scipy",
            "matplotlib"
        )
)
with image.imports():
    print("Hello")


@stub.function(image=image, gpu="a100")
def answer():
    return {"success": True, "data": "HELLLOOOOOOOOO! I am from modal!"}

@web_app.post("/answer")
async def endpoint(token: HTTPAuthorizationCredentials = Depends(auth_scheme),
                   ):
    if token.credentials != os.environ["AUTH_TOKEN"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    blob = await answer.remote.aio()
    return json.dumps({"data": blob})


@web_app.get("/")
async def root():
    return {"message": "Hi there! I am DrugCrow!"}


@stub.function(secrets=[Secret.from_name("agihack-token")])
@asgi_app()
def app():
    return web_app

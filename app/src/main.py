import asyncio, requests, os, docker
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .database import SessionLocal, engine
import pika
import json  # Assuming you're sending JSON data
from fastapi.encoders import jsonable_encoder


# # RabbitMQ connection details
# credentials = pika.PlainCredentials("guest", "guest")  # Replace with actual credentials
# parameters = pika.ConnectionParameters("rabbitmq", 5672, "/", credentials)

client = docker.from_env()
models.Base.metadata.create_all(bind=engine)


def consume():
    # connection = pika.BlockingConnection(
    #     pika.ConnectionParameters(
    #         "rabbitmq", 5672, "/", pika.PlainCredentials("guest", "guest")
    #     )
    # )
    connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    channel = connection.channel()
    channel.queue_declare(queue="task_queue", durable=True)  # Declare the queue

    def callback(ch, method, properties, body):
        # data = json.loads(body)
        data = {"data": f"{body} processed by FastAPI"}
        response = requests.post("http://localhost:8000/process_data", json=data)
        if response.status_code == 200:
            print("Message processed successfully")
        else:
            print("Error processing message:", response.text)
        print("Received message:", data)
        # Do something with the message data
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue="task_queue", on_message_callback=callback)
    channel.start_consuming()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    # Run the consumer in a separate thread or process
    loop.run_in_executor(None, consume)
    yield
    os._exit(0)


app = FastAPI(lifespan=lifespan)


# def send_output_to_rabbitmq(output_data):
#     with pika.BlockingConnection(pika.ConnectionParameters("localhost")) as connection:
#         channel = connection.channel()

#         channel.queue_declare(queue="output_queue")  # Declare the queue

#         channel.basic_publish(
#             exchange="", routing_key="output_queue", body=json.dumps(output_data)
#         )

#         print("Sent message:", output_data)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    response = Response("Internal server error", status_code=500)
    try:
        request.state.db = SessionLocal()
        response = await call_next(request)
    finally:
        request.state.db.close()
    return response


# Dependency
def get_db(request: Request):
    return request.state.db


def trigger_container_with_env(container_name, env_vars):
    client.containers.run(image=container_name, environment=env_vars)


@app.post("/trigger")
async def trigger_action(action: str, container_name: str, custom_input: str):
    env_vars = {"CUSTOM_INPUT": custom_input}
    trigger_container_with_env(container_name, env_vars)
    return {"message": "Container triggered with input"}


@app.post("/process_data")
async def process_data(data: dict):
    # Simulate processing (replace with your actual logic)
    print("Processing data:", data)
    return {"message": "Data processing initiated"}


@app.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = crud.create_user(db=db, user=user)
    serialized_user = jsonable_encoder(new_user)
    # send_output_to_rabbitmq(serialized_user)
    return new_user


@app.get("/users/", response_model=list[schemas.User])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    users = crud.get_users(db, skip=skip, limit=limit)
    return users


@app.get("/users/{user_id}", response_model=schemas.User)
def read_user(user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@app.post("/users/{user_id}/items/", response_model=schemas.Item)
def create_item_for_user(
    user_id: int, item: schemas.ItemCreate, db: Session = Depends(get_db)
):
    return crud.create_user_item(db=db, item=item, user_id=user_id)


@app.get("/items/", response_model=list[schemas.Item])
def read_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = crud.get_items(db, skip=skip, limit=limit)
    return items


@app.get("/")
def read_root():
    return {"Hello": "World"}

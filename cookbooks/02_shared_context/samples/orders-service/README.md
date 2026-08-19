# orders-service

Takes orders over HTTP and writes them to Postgres.

## Endpoints

- `POST /orders` create an order
- `GET /orders/{id}` fetch one order

## Configuration

See `config.toml`. `DATABASE_URL` is required.

## CLI

`orders --port 8080` starts the service.

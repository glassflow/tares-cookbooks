# billing-service

Charges customers for orders. Reads orders from orders-service over HTTP.

## Endpoints

- `POST /invoices` create an invoice for an order

## Configuration

See `config.toml`. `ORDERS_URL` points at orders-service.

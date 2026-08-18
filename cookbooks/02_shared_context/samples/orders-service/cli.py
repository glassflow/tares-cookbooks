"""orders CLI: `orders --port 8080`."""
import argparse


def main():
    p = argparse.ArgumentParser(prog="orders")
    p.add_argument("--port", type=int, default=8080, help="port to listen on")
    args = p.parse_args()
    print(f"orders-service listening on {args.port}")


if __name__ == "__main__":
    main()

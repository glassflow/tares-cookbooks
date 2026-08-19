"""billing CLI: `billing --port 8090`."""
import argparse


def main():
    p = argparse.ArgumentParser(prog="billing")
    p.add_argument("--port", type=int, default=8090)
    args = p.parse_args()
    print(f"billing-service listening on {args.port}")


if __name__ == "__main__":
    main()

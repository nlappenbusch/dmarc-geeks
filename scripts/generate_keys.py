"""Generate values for SECRET_KEY and FERNET_KEY. Run once, paste into .env."""
import secrets

from cryptography.fernet import Fernet


def main() -> None:
    print("# Add to .env:")
    print(f"SECRET_KEY={secrets.token_urlsafe(64)}")
    print(f"FERNET_KEY={Fernet.generate_key().decode()}")


if __name__ == "__main__":
    main()

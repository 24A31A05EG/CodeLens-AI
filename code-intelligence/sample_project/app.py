from auth import login
from database import connect_database


def start_application():
    connect_database()
    print("Application started")


if __name__ == "__main__":
    start_application()
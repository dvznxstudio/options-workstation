from app.collector import collect_all
from app.database import init_db

if __name__ == "__main__":
    init_db()
    result = collect_all()
    print(result)

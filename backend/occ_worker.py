from app.database import init_db
from app.occ_importer import import_latest_occ

if __name__ == "__main__":
    init_db()
    print(import_latest_occ())

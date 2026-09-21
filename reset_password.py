import sqlite3
from passlib.context import CryptContext

# --- عدّل القيم دي ---
EMAIL = "bassem.sheta@acu.edu.eg"
NEW_PASSWORD = "YourNewPass123!"   # اختار باسورد جديد قوي هنا
DB_PATH = "efdp.db"
# ----------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
hashed = pwd_context.hash(NEW_PASSWORD)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
# نتأكد كمان إن الحساب Active
cur.execute("UPDATE employees SET hashed_password = ?, employment_status = 'ACTIVE' WHERE email = ?", (hashed, EMAIL))
conn.commit()
print(f"Rows updated: {cur.rowcount}")
conn.close()
from db import get_connection

def migrate():
    conn = get_connection()
    cur = conn.cursor()
    try:
        print("Altering students table...")
        cur.execute("ALTER TABLE students ADD COLUMN current_semester INT DEFAULT 1")
        conn.commit()
        print("Success: Added current_semester column.")
    except Exception as e:
        print(f"Error (might already exist): {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()

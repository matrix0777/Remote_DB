from database import SessionLocal
from models import User
from main import get_password_hash

db = SessionLocal()

try:
    # Check if admin already exists
    admin_user = db.query(User).filter(User.username == "admin").first()

    if not admin_user:
        # Create default admin user
        hashed_pwd = get_password_hash("admin")

        # Check your models.py field name: 'hashed_password' or 'password_hash'
        new_admin = User(
            username="admin",
            hashed_password=hashed_pwd,
            role="admin"
        )
        db.add(new_admin)
        db.commit()
        print("Admin user created successfully!")
    else:
        print("Admin user already exists in the database.")

except Exception as e:
    db.rollback()
    print(f"Error creating admin user: {e}")

finally:
    db.close()
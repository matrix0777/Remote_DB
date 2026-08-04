from database import SessionLocal, engine, Base
import models
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Check if admin already exists
existing_admin = db.query(models.User).filter(models.User.username == "admin").first()

if not existing_admin:
    admin_user = models.User(
        username="admin",
        hashed_password=pwd_context.hash("admin123"),  # Change password as needed
        role="admin"
    )
    db.add(admin_user)
    db.commit()
    print("✅ Initial admin account created successfully!")
    print("   Username: admin")
    print("   Password: admin123")
else:
    print("⚠️ Admin account already exists.")

db.close()
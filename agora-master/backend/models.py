from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    is_active = Column(Boolean, default=False)
    verification_code = Column(String, nullable=True)
    university = Column(String, nullable=True)
    course = Column(Integer, nullable=True)
    bio = Column(String, nullable=True)
    telegram = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    privacy_settings = Column(String, default='{"email": false, "bio": true, "uni": true, "tg": true}')
    fav_categories = Column(String, default='[]')
    created_at = Column(DateTime, default=datetime.utcnow)

    materials = relationship("Material", back_populates="author")
    tasks = relationship("Task", back_populates="user")


class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text, nullable=True)
    category = Column(String, index=True)
    material_type = Column(String)
    course = Column(Integer)
    is_private = Column(Boolean, default=False)
    likes_count = Column(Integer, default=0)
    downloads_count = Column(Integer, default=0)
    views_count = Column(Integer, default=0)
    ai_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    author_id = Column(Integer, ForeignKey("users.id"))
    author = relationship("User", back_populates="materials")

    # ВОТ ЭТА СТРОКА ВАЖНА (Связь с файлами)
    files = relationship("MaterialFile", back_populates="material", cascade="all, delete-orphan")


class MaterialFile(Base):
    __tablename__ = "material_files"
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"))
    filename = Column(String)
    file_path = Column(String)
    file_size = Column(String)

    # ВОТ ЭТОЙ СТРОКИ У ТЕБЯ НЕ ХВАТАЛО 👇
    material = relationship("Material", back_populates="files")


class UserLike(Base):
    __tablename__ = "user_likes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))


class UserAI(Base):
    __tablename__ = "user_ai"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))
    summary_text = Column(Text)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String)
    subject = Column(String, nullable=True)
    deadline = Column(DateTime, nullable=True)
    is_urgent = Column(Boolean, default=False)
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="tasks")


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    description = Column(Text, nullable=True)


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))
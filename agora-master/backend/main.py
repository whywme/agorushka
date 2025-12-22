import shutil
import os
import uuid
import json
import bcrypt
import random
from typing import List  # <--- ВАЖНО: Добавили List для мульти-загрузки
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from gigachat import GigaChat
import PyPDF2
import docx
from dotenv import load_dotenv

load_dotenv()

from backend.database import get_db, engine
from backend import models

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

if not os.path.exists("uploads"):
    os.makedirs("uploads")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="uploads"), name="static")

templates = Jinja2Templates(directory="/app/backend/templates")

# почта
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),  # Порт должен быть числом
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "Agora"),
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

html_email_template = """
<!DOCTYPE html>
<html>
    <body style="background-color: #f3f4f6; padding: 40px; font-family: sans-serif;">
        <div style="max-width: 500px; margin: 0 auto; background-color: white; padding: 40px; border-radius: 20px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.05);">
            <h1 style="color: #007EC6; margin-bottom: 10px;">Agora.</h1>
            <p style="color: #6b7280; font-size: 16px;">Ваш код подтверждения:</p>
            <div style="background-color: #eff6ff; color: #1d4ed8; font-size: 36px; letter-spacing: 5px; font-weight: bold; padding: 20px; border-radius: 10px; margin: 20px 0;">
                {code}
            </div>
        </div>
    </body>
</html>
"""


# пароли
def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


async def send_verification_email(email: str, code: str):
    message = MessageSchema(
        subject="Код подтверждения Agora",
        recipients=[email],
        body=html_email_template.format(code=code),
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)


async def send_reset_email(email: str, code: str):
    html = f"Ваш код: {code}"
    message = MessageSchema(
        subject="Код сброса пароля",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)


# маршруты

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 1. РЕГИСТРАЦИЯ
@app.post("/register")
async def register_user(
        background_tasks: BackgroundTasks,
        name: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    if db.query(models.User).filter(models.User.email == email).first():
        return RedirectResponse(url="/", status_code=303)

    code = str(random.randint(1000, 9999))
    hashed_pw = get_password_hash(password)

    new_user = models.User(
        username=name, email=email, password_hash=hashed_pw, verification_code=code,
        is_active=False, university="Не указан", course=1, bio="", telegram="", age=None
    )
    db.add(new_user)
    db.commit()

    try:
        background_tasks.add_task(send_verification_email, email, code)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

    return RedirectResponse(url=f"/verify_page?email={email}", status_code=303)


# 2. ВВОД КОДА
@app.get("/verify_page")
def verify_page_view(request: Request, email: str):
    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


@app.post("/verify")
def verify_code_action(email: str = Form(...), code: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user: return RedirectResponse(url="/", status_code=303)

    if user.verification_code == code:
        user.is_active = True
        user.verification_code = None
        db.commit()
        return RedirectResponse(url=f"/dashboard?email={email}", status_code=303)
    else:
        return templates.TemplateResponse("verify.html", {"request": {}, "email": email, "error": "Неверный код!"})


# 3. ВХОД
@app.post("/login")
def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("index.html",
                                          {"request": request, "login_error": "Неверный email или пароль"})
    if not user.is_active:
        return RedirectResponse(url=f"/verify_page?email={email}", status_code=303)
    return RedirectResponse(url=f"/dashboard?email={email}", status_code=303)


# 4. ЛИЧНЫЙ КАБИНЕТ
@app.get("/dashboard")
def dashboard_page(request: Request, email: str = None, db: Session = Depends(get_db)):
    if email:
        user = db.query(models.User).filter(models.User.email == email).first()
    else:
        user = db.query(models.User).first()

    if not user: return RedirectResponse(url="/")

    avatar_link = f"/static/{user.avatar_url}" if user.avatar_url else None

    privacy_dict = {"email": False, "bio": True, "uni": True, "tg": True}
    if user.privacy_settings:
        try:
            privacy_dict = json.loads(user.privacy_settings)
        except:
            pass

    total_materials = len(user.materials)
    total_likes = sum(m.likes_count for m in user.materials)
    rating_val = 1.0 + (total_likes * 0.1)
    if rating_val > 5.0: rating_val = 5.0

    tasks_list = []
    sorted_tasks = sorted(user.tasks, key=lambda x: (x.is_done, not x.is_urgent))

    for t in sorted_tasks:
        tasks_list.append({
            "id": t.id,
            "text": t.text,
            "subject": t.subject,
            "urgent": t.is_urgent,
            "done": t.is_done,
            "deadline": t.deadline.strftime("%Y-%m-%d %H:%M") if t.deadline else None
        })

    user_data = {
        "id": user.id, "name": user.username, "email": user.email,
        "university": user.university or "Не указан", "course": str(user.course) if user.course else "1",
        "bio": user.bio or "Информация о себе не заполнена", "telegram": user.telegram or "",
        "age": user.age or "", "avatarUrl": avatar_link,
        "downloads": total_materials,
        "rating": f"{rating_val:.1f}",
        "privacy": privacy_dict,
        "favCats": json.loads(user.fav_categories) if user.fav_categories else [],
        "tasks": tasks_list
    }

    materials_db = db.query(models.Material).all()

    my_ai_entries = db.query(models.UserAI).filter(models.UserAI.user_id == user.id).all()
    ai_map = {entry.material_id: entry.summary_text for entry in my_ai_entries}

    my_likes = db.query(models.UserLike.material_id).filter(models.UserLike.user_id == user.id).all()
    my_likes_ids = [like[0] for like in my_likes]

    my_favs = db.query(models.UserFavorite.material_id).filter(models.UserFavorite.user_id == user.id).all()
    my_favs_ids = [fav[0] for fav in my_favs]  # Список ID избранных файлов

    materials_data = []
    for m in materials_db:
        author_name = m.author.username if m.author else "Неизвестный"
        personal_ai = ai_map.get(m.id)

        files_list = []
        for f in m.files:
            files_list.append({
                "id": f.id,
                "name": f.filename,
                "path": f.file_path,
                "size": f.file_size,
                "ext": f.filename.split('.')[-1].lower() if '.' in f.filename else 'file'
            })

        materials_data.append({
            "id": m.id, "title": m.title, "author": author_name, "authorId": m.author_id,
            "category": m.category, "date": m.created_at.strftime("%d.%m.%Y"),
            "type": m.material_type, "course": m.course, "likes": m.likes_count,
            "isLiked": m.id in my_likes_ids,
            "isFav": m.id in my_favs_ids,
            "ai": personal_ai, "aiStatus": "ready" if personal_ai else "none",
            "desc": m.description,
            "isPrivate": m.is_private,
            "downloads": m.downloads_count, "views": m.views_count,
            "files": files_list
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_json": json.dumps(user_data, ensure_ascii=False),
        "materials_json": json.dumps(materials_data, ensure_ascii=False)
    })


# 5. ЗАГРУЗКА МАТЕРИАЛОВ
@app.post("/upload")
def upload_material(
        title: str = Form(...),
        category: str = Form(...),
        course: int = Form(...),
        material_type: str = Form(...),
        description: str = Form(""),
        is_private: str = Form("false"),
        email: str = Form(...),
        files: List[UploadFile] = File(...),
        db: Session = Depends(get_db)
):

    title = title.strip()
    category = category.strip()

    if len(title) > 0:
        title = title[0].upper() + title[1:]

    if len(category) > 0:
        category = category[0].upper() + category[1:]


    author = db.query(models.User).filter(models.User.email == email).first()
    if not author: author = db.query(models.User).first()

    new_material = models.Material(
        title=title, category=category, course=course, material_type=material_type,
        description=description, is_private=(is_private == "true"), author_id=author.id
    )
    db.add(new_material)
    db.commit()
    db.refresh(new_material)

    for file in files:
        if not file.filename: continue

        unique_filename = f"{uuid.uuid4()}_{file.filename}"

        file.file.seek(0, 2)
        size_bytes = file.file.tell()
        file.file.seek(0)
        size_mb = f"{size_bytes / 1024 / 1024:.2f} MB"

        with open(f"uploads/{unique_filename}", "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)

        new_file = models.MaterialFile(
            material_id=new_material.id,
            filename=file.filename,
            file_path=unique_filename,
            file_size=size_mb
        )
        db.add(new_file)

    db.commit()
    return RedirectResponse(url=f"/dashboard?email={author.email}", status_code=303)


# 6. ВОССТАНОВЛЕНИЕ ПАРОЛЯ
@app.get("/forgot-password")
def forgot_password_page(request: Request): return templates.TemplateResponse("forgot.html", {"request": request})


@app.post("/forgot-password")
async def forgot_password_action(background_tasks: BackgroundTasks, email: str = Form(...),
                                 db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user: return templates.TemplateResponse("forgot.html", {"request": {}, "error": "Пользователь не найден"})
    code = str(random.randint(1000, 9999))
    user.verification_code = code
    db.commit()
    background_tasks.add_task(send_reset_email, email, code)
    return RedirectResponse(url=f"/reset-password?email={email}", status_code=303)


@app.get("/reset-password")
def reset_password_page(request: Request, email: str): return templates.TemplateResponse("reset.html",
                                                                                         {"request": request,
                                                                                          "email": email})


@app.post("/reset-password")
def reset_password_final(email: str = Form(...), code: str = Form(...), new_password: str = Form(...),
                         db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or user.verification_code != code: return templates.TemplateResponse("reset.html",
                                                                                     {"request": {}, "email": email,
                                                                                      "error": "Неверный код!"})
    user.password_hash = get_password_hash(new_password)
    user.verification_code = None
    db.commit()
    return RedirectResponse(url="/", status_code=303)


# 7. ОБНОВЛЕНИЕ ПРОФИЛЯ
@app.post("/update_profile")
def update_profile(
        name: str = Form(...), university: str = Form(""), course: int = Form(1),
        bio: str = Form(""), telegram: str = Form(""), age: str = Form(""),
        privacy: str = Form(''), avatar: UploadFile = File(None), email: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.username = name
    user.university = university
    user.course = course
    user.bio = bio
    user.telegram = telegram
    user.privacy_settings = privacy
    if age and age.isdigit():
        user.age = int(age)
    else:
        user.age = None

    if avatar:
        ext = avatar.filename.split('.')[-1]
        filename = f"avatar_{user.id}_{uuid.uuid4()}.{ext}"
        with open(f"uploads/{filename}", "wb+") as buffer: shutil.copyfileobj(avatar.file, buffer)
        user.avatar_url = filename

    db.commit()
    return {"status": "ok", "avatarUrl": user.avatar_url}


# 8. ПОЛУЧЕНИЕ ЧУЖОГО ПРОФИЛЯ
@app.get("/api/profile/{user_id}")
def get_public_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user: return {"error": "Пользователь не найден"}

    privacy = {"email": False, "bio": True, "uni": True, "tg": True}
    if user.privacy_settings:
        try:
            privacy = json.loads(user.privacy_settings)
        except:
            pass

    total_materials = len(user.materials)
    total_likes = sum(m.likes_count for m in user.materials)
    rating_val = 1.0 + (total_likes * 0.1)
    if rating_val > 5.0: rating_val = 5.0

    return {
        "id": user.id, "name": user.username,
        "avatarUrl": f"/static/{user.avatar_url}" if user.avatar_url else None,
        "university": user.university if privacy.get("uni") else "Скрыто",
        "course": str(user.course) if (user.course and privacy.get("uni")) else "",
        "bio": user.bio if privacy.get("bio") else "Информация скрыта пользователем",
        "telegram": user.telegram if privacy.get("tg") else ("Скрыто" if user.telegram else None),
        "downloads": total_materials, "rating": f"{rating_val:.1f}"
    }


# 9. СКАЧИВАНИЕ ФАЙЛА
@app.get("/download/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db)):
    file_record = db.query(models.MaterialFile).filter(models.MaterialFile.id == file_id).first()
    if not file_record: return RedirectResponse(url="/dashboard")

    if file_record.material:
        file_record.material.downloads_count += 1
        db.commit()

    file_location = f"uploads/{file_record.file_path}"
    return FileResponse(file_location, filename=file_record.filename, media_type='application/octet-stream')


# 10. УПРАВЛЕНИЕ ЛАЙКАМИ
@app.post("/toggle_like")
def toggle_like_action(material_id: int = Form(...), email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if not user or not material: return {"status": "error"}

    existing_like = db.query(models.UserLike).filter(models.UserLike.user_id == user.id,
                                                     models.UserLike.material_id == material.id).first()
    liked_now = False
    if existing_like:
        db.delete(existing_like)
        material.likes_count -= 1
        liked_now = False
    else:
        new_like = models.UserLike(user_id=user.id, material_id=material.id)
        db.add(new_like)
        material.likes_count += 1
        liked_now = True
    db.commit()
    return {"status": "ok", "likes": material.likes_count, "isLiked": liked_now}


# 11. УВЕЛИЧЕНИЕ ПРОСМОТРОВ
@app.post("/api/view/{material_id}")
def increment_view(material_id: int, db: Session = Depends(get_db)):
    material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if material:
        material.views_count += 1
        db.commit()
        return {"status": "ok", "views": material.views_count}
    return {"status": "error"}


# 12. УДАЛЕНИЕ МАТЕРИАЛА
@app.post("/api/material/delete")
def delete_material_action(material_id: int = Form(...), email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    material = db.query(models.Material).filter(models.Material.id == material_id).first()

    if not material or not user or material.author_id != user.id:
        return {"status": "error", "message": "Нет прав"}

    for f in material.files:
        try:
            if os.path.exists(f"uploads/{f.file_path}"): os.remove(f"uploads/{f.file_path}")
        except:
            pass

    db.query(models.UserLike).filter(models.UserLike.material_id == material_id).delete()
    db.query(models.UserAI).filter(models.UserAI.material_id == material_id).delete()
    db.delete(material)
    db.commit()
    return {"status": "ok"}


# 13. РЕДАКТИРОВАНИЕ
@app.post("/api/material/edit")
def edit_material_action(
        material_id: int = Form(...), title: str = Form(...), category: str = Form(...),
        course: int = Form(...), material_type: str = Form(...), description: str = Form(""),
        is_private: str = Form("false"), email: str = Form(...),
        files: List[UploadFile] = File(None),
        db: Session = Depends(get_db)
):

    title = title.strip()
    category = category.strip()

    if len(title) > 0:
        title = title[0].upper() + title[1:]

    if len(category) > 0:
        category = category[0].upper() + category[1:]
    user = db.query(models.User).filter(models.User.email == email).first()
    material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if not material or not user or material.author_id != user.id:
        return {"status": "error", "message": "Нет прав"}

    material.title = title
    material.category = category
    material.course = course
    material.material_type = material_type
    material.description = description
    material.is_private = (is_private == "true")

    if files and len(files) > 0 and files[0].filename:
        for old_f in material.files:
            if os.path.exists(f"uploads/{old_f.file_path}"): os.remove(f"uploads/{old_f.file_path}")
        db.query(models.MaterialFile).filter(models.MaterialFile.material_id == material_id).delete()

        for file in files:
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            file.file.seek(0, 2)
            size_bytes = file.file.tell()
            file.file.seek(0)
            size_mb = f"{size_bytes / 1024 / 1024:.2f} MB"

            with open(f"uploads/{unique_filename}", "wb+") as buffer:
                shutil.copyfileobj(file.file, buffer)

            new_file = models.MaterialFile(
                material_id=material.id, filename=file.filename,
                file_path=unique_filename, file_size=size_mb
            )
            db.add(new_file)

    db.commit()
    return {"status": "ok"}


# гигачат

def extract_text_from_file(file_path: str) -> str:
    text = ""
    try:
        if file_path.endswith(".pdf"):
            with open(f"uploads/{file_path}", "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages[:5]: text += page.extract_text() + "\n"
        elif file_path.endswith(".docx"):
            doc = docx.Document(f"uploads/{file_path}")
            for para in doc.paragraphs: text += para.text + "\n"
        elif file_path.endswith(".txt"):
            with open(f"uploads/{file_path}", "r", encoding="utf-8") as f:
                text = f.read()
    except Exception as e:
        print(f"Ошибка чтения файла: {e}")
    return text[:8000]


@app.post("/api/ai/analyze")
def analyze_material_ai(
        material_id: int = Form(...), email: str = Form(...), db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if not material or not user: return {"error": "Ошибка данных"}

    existing_ai = db.query(models.UserAI).filter(models.UserAI.user_id == user.id,
                                                 models.UserAI.material_id == material.id).first()
    if existing_ai: return {"status": "ok", "ai": existing_ai.summary_text}

    if not material.files: return {"error": "В материале нет файлов"}
    text_content = extract_text_from_file(material.files[0].file_path)

    if not text_content or len(text_content) < 50: return {"error": "Файл пустой или не читается"}

    CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")

    try:
        with GigaChat(credentials=CREDENTIALS, verify_ssl_certs=False) as giga:
            prompt = f"Сделай краткую выжимку (саммари). Текст: {text_content}"
            response = giga.chat(prompt)
            summary = response.choices[0].message.content

            new_user_ai = models.UserAI(user_id=user.id, material_id=material.id, summary_text=summary)
            db.add(new_user_ai)
            db.commit()
            return {"status": "ok", "ai": summary}
    except Exception as e:
        print(f"Ошибка GigaChat: {e}")
        return {"error": "Ошибка нейросети"}


# 14. УПРАВЛЕНИЕ ИЗБРАННЫМ
@app.post("/toggle_fav")
def toggle_fav_action(material_id: int = Form(...), email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    material = db.query(models.Material).filter(models.Material.id == material_id).first()
    if not user or not material: return {"status": "error"}

    existing_fav = db.query(models.UserFavorite).filter(models.UserFavorite.user_id == user.id,
                                                        models.UserFavorite.material_id == material.id).first()

    is_fav_now = False
    if existing_fav:
        db.delete(existing_fav)
        is_fav_now = False
    else:
        new_fav = models.UserFavorite(user_id=user.id, material_id=material.id)
        db.add(new_fav)
        is_fav_now = True

    db.commit()
    return {"status": "ok", "isFav": is_fav_now}


# 15. СОХРАНЕНИЕ ИЗБРАННЫХ КАТЕГОРИЙ
@app.post("/api/update_fav_cats")
def update_fav_cats(email: str = Form(...), categories: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user: return {"error": "Пользователь не найден"}

    # Сохраняем пришедший JSON-строку в базу
    user.fav_categories = categories
    db.commit()
    return {"status": "ok"}


# задачи
@app.post("/api/task/add")
def add_task(
        text: str = Form(...),
        subject: str = Form(""),
        date: str = Form(""),
        time: str = Form(""),
        is_urgent: str = Form("false"),
        email: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user: return {"status": "error", "message": "Пользователь не найден"}

    deadline_dt = None
    if date:
        try:
            if time:
                dt_str = f"{date} {time}"
                deadline_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            else:
                deadline_dt = datetime.strptime(date, "%Y-%m-%d")
        except Exception as e:
            print(f"Ошибка даты: {e}")

    new_task = models.Task(
        text=text,
        subject=subject,
        deadline=deadline_dt,
        is_urgent=(is_urgent == "true"),
        user_id=user.id
    )
    db.add(new_task)
    db.commit()
    return {"status": "ok"}


@app.post("/api/task/toggle_done")
def toggle_task_done(
        task_id: int = Form(...),
        email: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()

    if not user or not task or task.user_id != user.id:
        return {"status": "error"}

    task.is_done = not task.is_done
    db.commit()
    return {"status": "ok", "is_done": task.is_done}


@app.post("/api/task/delete")
def delete_task(
        task_id: int = Form(...),
        email: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()

    if not user or not task or task.user_id != user.id:
        return {"status": "error"}

    db.delete(task)
    db.commit()
    return {"status": "ok"}


@app.post("/api/task/edit")
def edit_task(
    task_id: int = Form(...),
    text: str = Form(...),
    subject: str = Form(""),
    date: str = Form(""),
    time: str = Form(""),
    is_urgent: str = Form("false"),
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()

    if not user or not task or task.user_id != user.id:
        return {"status": "error", "message": "Задача не найдена"}

    task.text = text
    task.subject = subject
    task.is_urgent = (is_urgent == "true")

    if date and date != "undefined" and date != "null":
        try:
            if time and time != "undefined":
                dt_str = f"{date} {time}"
                task.deadline = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            else:
                task.deadline = datetime.strptime(date, "%Y-%m-%d")
        except Exception as e:
            print(f"Ошибка сохранения даты: {e}")
    else:
        task.deadline = None

    db.commit()
    return {"status": "ok"}
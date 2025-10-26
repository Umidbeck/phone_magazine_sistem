# 📦 PHONE MAGAZINE SYSTEM - PRODUCTION DEPLOYMENT

## 🚀 TEZKOR BOSHLASH

### 1. Serverga ulanish
```bash
ssh user@your-server-ip
```

### 2. Docker o'rnatish
```bash
# Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Tekshirish
docker --version
docker-compose --version
```

### 3. Loyihani klonlash
```bash
git clone https://github.com/your-username/phone-magazine.git
cd phone-magazine
```

### 4. .env faylini sozlash
```bash
cp .env.example .env
nano .env
```

**.env** faylida o'zgartiring:
```env
DJANGO_SECRET_KEY=your-super-secret-key-HERE-random-50-chars
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,123.45.67.89

POSTGRES_DB=phone_magazine
POSTGRES_USER=postgres
POSTGRES_PASSWORD=STRONG-PASSWORD-HERE

DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@yourdomain.com
DJANGO_SUPERUSER_PASSWORD=STRONG-PASSWORD-HERE
```

### 5. Deploy qilish (bitta buyruq!)
```bash
make deploy
```

Yoki qo'lda:
```bash
docker-compose build
docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py collectstatic --noinput
```

### 6. Saytni ochish
```
http://your-server-ip
```

---

## 🔧 MAKEFILE BUYRUQLARI

### Asosiy buyruqlar
```bash
make setup          # Boshlang'ich sozlash
make build          # Docker image yaratish
make up             # Serverni ishga tushirish
make down           # Serverni to'xtatish
make restart        # Qayta ishga tushirish
make logs           # Loglarni ko'rish
make deploy         # To'liq deploy
```

### Database
```bash
make migrate            # Migration yuritish
make makemigrations     # Migration yaratish
make backup             # Database backup
make restore FILE=...   # Database restore
make dbshell            # Database shell
make createsuperuser    # Admin yaratish
```

### Static files
```bash
make collectstatic  # Static fayllarni yig'ish
```

### Monitoring
```bash
make ps         # Container holati
make logs       # Barcha loglar
make stats      # CPU/RAM ishlatish
make health     # Sog'liqni tekshirish
```

---

## 🔒 SSL SERTIFIKAT (HTTPS)

### 1. Domain sozlash
DNS settings'da A record qo'shing:
```
Type: A
Name: @
Value: YOUR_SERVER_IP

Type: A
Name: www
Value: YOUR_SERVER_IP
```

### 2. SSL olish
```bash
# nginx/conf.d/default.conf da domenni o'zgartiring
nano nginx/conf.d/default.conf

# SSL sertifikat olish
make ssl-setup

# HTTPS server blockni yoqish
nano nginx/conf.d/default.conf  # HTTPS qismini uncomment qiling

# Nginx qayta yuklash
docker-compose restart nginx
```

### 3. Auto-renewal
Certbot avtomatik yangilaydi har 12 soatda.

---

## 📊 MONITORING VA LOGS

### Loglarni ko'rish
```bash
# Barcha loglar
make logs

# Faqat web
make logs SERVICE=web

# Faqat nginx
make logs SERVICE=nginx

# Faqat database
make logs SERVICE=db

# Real-time
docker-compose logs -f --tail=100
```

### Container statistikasi
```bash
make stats
```

### Disk space
```bash
make disk
```

---

## 🔄 UPDATE VA REDEPLOY

### Code yangilash
```bash
git pull
make restart
```

### To'liq redeploy
```bash
make redeploy
```

### Database migration bilan yangilash
```bash
git pull
docker-compose build
docker-compose down
docker-compose up -d
make migrate
make collectstatic
```

---

## 💾 BACKUP VA RESTORE

### Database backup
```bash
# Avtomatik backup (hozirgi sana bilan)
make backup

# Manual
docker-compose exec -T db pg_dump -U postgres phone_magazine > backup.sql
```

### Database restore
```bash
make restore FILE=backups/backup_20240101_120000.sql
```

### Media files backup
```bash
make backup-media
```

### To'liq backup (database + media)
```bash
make backup
make backup-media
```

---

## 🛠️ MUAMMO YECHISH

### Container ishlamayapti
```bash
docker-compose ps
docker-compose logs web
```

### Database ulanish xatosi
```bash
# Database running ekanligini tekshirish
docker-compose exec db pg_isready -U postgres

# Database qayta ishga tushirish
docker-compose restart db
```

### Static files ko'rinmayapti
```bash
make collectstatic
docker-compose restart nginx
```

### Nginx 502 Bad Gateway
```bash
# Web container ishlayaptimi?
docker-compose ps web

# Web logs
make logs SERVICE=web

# Nginx logs
make logs SERVICE=nginx
```

### Port band
```bash
# 80 portni tekshirish
sudo lsof -i :80

# Portni bo'shatish
sudo systemctl stop apache2  # agar Apache ishlayotgan bo'lsa
```

### Disk to'lgan
```bash
# Disk space
df -h

# Docker cleanup
make clean

# Eski images o'chirish
docker system prune -a
```

---

## 🔐 XAVFSIZLIK

### 1. Firewall sozlash
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 2. SSH key authentication
```bash
# Local kompyuterdan
ssh-keygen -t ed25519
ssh-copy-id user@server-ip

# Serverda parol kirish o'chirish
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
sudo systemctl restart sshd
```

### 3. Database parol o'zgartirish
```bash
# .env da yangi parol
nano .env

# Container rebuild
docker-compose down
docker-compose up -d
```

### 4. Django SECRET_KEY yangilash
```bash
# Python shell'da yangi key yaratish
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# .env ga qo'shish
nano .env

# Restart
make restart
```

---

## 📈 PERFORMANCE OPTIMIZATION

### 1. Gunicorn workers sozlash
```bash
# .env ga qo'shish
GUNICORN_WORKERS=4  # CPU * 2 + 1
GUNICORN_THREADS=2
```

### 2. PostgreSQL tuning
```bash
# docker-compose.yml da
db:
  environment:
    POSTGRES_INITDB_ARGS: "-c shared_buffers=256MB -c max_connections=200"
```

### 3. Nginx cache
```bash
# nginx/conf.d/default.conf da cache sozlamalari mavjud
```

---

## 🎯 ENVIRONMENT SOZLAMALARI

### Development (local)
```env
DEBUG=True
USE_POSTGRESQL=False
USE_REDIS=False
```

### Production (server)
```env
DEBUG=False
USE_POSTGRESQL=True
USE_REDIS=True
SECURE_SSL_REDIRECT=True
```

---

## 📞 YORDAM

### Logs orqali muammo topish
```bash
# Web application logs
docker-compose logs web | grep ERROR

# Nginx access logs
docker-compose exec nginx cat /var/log/nginx/access.log

# Database logs
docker-compose logs db
```

### Database tekshirish
```bash
# Django shell
make shell

# Database shell
make dbshell
```

---

## ✅ CHECKLIST - PRODUCTION'GA O'TISHDAN OLDIN

- [ ] .env faylida DEBUG=False
- [ ] SECRET_KEY random va xavfsiz
- [ ] ALLOWED_HOSTS to'g'ri
- [ ] PostgreSQL parollari kuchli
- [ ] Firewall sozlangan
- [ ] SSL sertifikat o'rnatilgan
- [ ] Database backup sozlangan
- [ ] Monitoring ishga tushirilgan
- [ ] Static files to'plangan
- [ ] Media papka mavjud va ruxsatlar to'g'ri
- [ ] Superuser yaratilgan
- [ ] Email settings sozlangan (agar kerak bo'lsa)

---

## 🎉 TAYYOR!

Tizim ishga tushdi! Qo'shimcha savollar uchun:
- Documentation: `/docs`
- Admin panel: `http://yourdomain.com/admin`
- Support: support@yourdomain.com
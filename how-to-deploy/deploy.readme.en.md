# FPVSessions Deployment Guide (VPS)

This guide explains how to set up and deploy **FPVSessions** on a VPS using a dedicated system user, Python virtual environment, systemd, and optionally Nginx as a reverse proxy.

---

## 1. Create a System User

Log in as `root` and create a dedicated user and group:

```bash
useradd --system -s /usr/sbin/nologin FPVSession_user -m
sudo groupadd FPVSessiongroup
sudo usermod -aG FPVSessiongroup FPVSession_user
sudo usermod -aG FPVSessiongroup {your_main_vps_user}

sudo chgrp -R FPVSessiongroup /home/FPVSession_user \
  && sudo chmod -R 770 /home/FPVSession_user \
  && sudo chmod g+s /home/FPVSession_user
```

---

## 2. Copy Code to the Server

From your local machine, upload the project to the VPS:

```bash
scp -r ./FPVSession fpvsessions@<VPS-IP>:/home/FPVSession_user/
```

Replace `<VPS-IP>` with your server’s IP address.

---

## 3. Python Virtual Environment & Dependencies

On the VPS:

```bash
sudo apt update
sudo apt install python3-venv python3-pip -y

cd /home/FPVSession_user/FPVSession
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Exit the system user when done:

```bash
exit
```

---

## 4. Create a Systemd Service

Create `/etc/systemd/system/fpvsessions.service` with the following content:

```ini
[Unit]
Description=Gunicorn instance to service FPVSession
After=network.target

[Service]
User=FPVSession_user
Group=www-data
WorkingDirectory=/home/FPVSession_user/FPVSession
Environment="PATH=/home/FPVSession_user/FPVSession/venv/bin"
ExecStart=/home/FPVSession_user/FPVSession/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8007 wsgi:app

# Make print outputs visible in logs
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

## 5. Start & Enable the Service

Start and enable the service:

```bash
sudo systemctl start fpvsessions.service
sudo systemctl enable fpvsessions.service
```

Check logs:

```bash
sudo journalctl -u fpvsessions.service
```

---

## 6. (Optional) Reverse Proxy with Nginx

Create `/etc/nginx/sites-available/fpvsessions`:

```nginx
server {
    listen 80;
    listen [::]:80;

    server_name <VPS-IP>;

    location / {
        proxy_pass http://127.0.0.1:8007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and reload Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/fpvsessions /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 7. Useful Commands

### Fix Permissions

```bash
sudo chgrp -R FPVSessiongroup /home/FPVSession_user \
  && sudo chmod -R 770 /home/FPVSession_user \
  && sudo chmod g+s /home/FPVSession_user \
  && sudo systemctl restart fpvsessions.service
```

### Service Management

```bash
sudo journalctl -u gunicorn.my_fpv.service
```

```bash
sudo systemctl stop gunicorn.my_fpv.service
```

```bash
sudo systemctl start gunicorn.my_fpv.service
```

```bash
sudo systemctl restart gunicorn.my_fpv.service
```

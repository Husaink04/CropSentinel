# CropSentinel Kali Server Guide

This guide is for a beginner.

Goal:
- turn your Kali Linux machine into a server
- run CropSentinel on it
- test the app from another computer
- update the app automatically when you push code to GitHub

This guide uses:
- Docker
- GitHub
- a small auto-update script

If you follow this guide, your Kali machine will:
- keep the database safe in Docker volumes
- restart the app after reboot
- check GitHub every minute for new code
- rebuild and restart the app automatically when code changes

## 1. Before you start

You need:
- your Kali server IP address
- SSH access to the Kali machine
- your code pushed to GitHub
- your repo URL, for example: `https://github.com/yourname/CropSentinel.git`

If your code is only on your laptop and not on GitHub yet, do that first.

## 2. Connect to your Kali server

From your own computer:

```bash
ssh your_linux_username@YOUR_SERVER_IP
```

Example:

```bash
ssh husain@192.168.1.50
```

## 3. Install the basic tools

Run these commands on the Kali server:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates gnupg cron
```

## 4. Install Docker

Run these commands on the Kali server one by one:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Start Docker:

```bash
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
```

Now log out and log in again.

Then test Docker:

```bash
docker --version
docker compose version
```

## 5. Download your project on the server

Move to a good folder:

```bash
cd /opt
```

Clone the repo:

```bash
sudo git clone https://github.com/yourname/CropSentinel.git
sudo chown -R $USER:$USER /opt/CropSentinel
cd /opt/CropSentinel
```

If your repo is private, use the private GitHub clone URL or set up SSH access for GitHub.

## 6. Create the environment file

Copy the example file:

```bash
cp .env.example .env
```

Open it:

```bash
nano .env
```

Change these values:

```env
SECRET_KEY=put_a_long_random_value_here
POSTGRES_PASSWORD=choose_a_database_password
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=choose_a_strong_password
AGENT_API_KEY=choose_a_long_agent_key
CORS_ORIGINS=*
```

Simple rule:
- make every password long
- do not use sample passwords in real use

Quick way to create a random secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste that value into `SECRET_KEY`.

Save and exit in `nano`:
- press `Ctrl + O`
- press `Enter`
- press `Ctrl + X`

## 7. Start the app

Run:

```bash
docker compose up --build -d
```

This starts:
- database
- backend API
- frontend

Check if everything is running:

```bash
docker compose ps
```

See live logs:

```bash
docker compose logs -f
```

Stop the log view with:

```bash
Ctrl + C
```

## 8. Open the app in your browser

From your own computer, open:

```text
http://YOUR_SERVER_IP
```

Example:

```text
http://192.168.1.50
```

The frontend should open in the browser.

If it does not open, allow the firewall:

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw enable
```

Then check again.

## 9. Test the backend directly

Open this in your browser:

```text
http://YOUR_SERVER_IP:8000/docs
```

If this opens, the backend is working.

## 10. Set the agent to talk to the server

For your agent machines, point them to your new server:

```env
CROPPRO_SERVER=http://YOUR_SERVER_IP:8000
CROPPRO_AGENT_KEY=the_same_value_as_AGENT_API_KEY
```

Important:
- backend uses `AGENT_API_KEY`
- agent uses `CROPPRO_AGENT_KEY`
- these two values should match

## 11. Make updates automatic

This is the easiest beginner setup:
- you push code to GitHub from your laptop
- the Kali server checks GitHub every minute
- if there is new code, it pulls it and rebuilds the app

### Step A: make sure the server repo is on the right branch

Inside `/opt/CropSentinel`, run:

```bash
git branch
```

If needed, switch to your main branch:

```bash
git checkout main
```

### Step B: make the helper scripts executable

Run:

```bash
chmod +x tools/server-deploy/update.sh
chmod +x tools/server-deploy/install-cron.sh
```

### Step C: install the automatic update job

Run:

```bash
./tools/server-deploy/install-cron.sh
```

What this does:
- creates a cron job
- checks GitHub every minute
- only updates when new code exists
- writes logs to `/var/log/cropsentinel-update.log`

## 12. How your update flow will work

On your laptop:

```bash
git add .
git commit -m "my change"
git push origin main
```

Then wait about 1 minute.

The server will:
- detect the new commit
- pull the new code
- rebuild containers
- restart the app

## 13. How to check if auto-update worked

On the server:

```bash
tail -f /var/log/cropsentinel-update.log
```

You should see messages like:
- checking for updates
- new version found
- rebuilding containers
- update complete

## 14. Useful commands

Start app:

```bash
cd /opt/CropSentinel
docker compose up --build -d
```

Stop app:

```bash
cd /opt/CropSentinel
docker compose down
```

Restart app:

```bash
cd /opt/CropSentinel
docker compose up --build -d
```

See logs:

```bash
cd /opt/CropSentinel
docker compose logs -f
```

See running containers:

```bash
docker compose ps
```

## 15. If something breaks

### The app does not open

Check:

```bash
cd /opt/CropSentinel
docker compose ps
docker compose logs -f
```

### Auto-update does not run

Check:

```bash
crontab -l
tail -f /var/log/cropsentinel-update.log
```

### Docker command says permission denied

You probably need to log out and log in again after:

```bash
sudo usermod -aG docker $USER
```

### Backend starts but frontend is blank

Run:

```bash
cd /opt/CropSentinel
docker compose logs -f frontend
docker compose logs -f backend
```

## 16. Very important notes

- Do not do coding directly on the server.
- Make code changes on your laptop.
- Push code to GitHub.
- Let the server pull from GitHub automatically.

This keeps the server clean and makes updates easier.

- Do not delete Docker volumes unless you want to erase your database.
- The database is stored in Docker volumes, not inside your code folder.

## 17. Better setup later

This guide is good for testing and early deployment.

Later, we should improve it with:
- HTTPS with a domain name
- Nginx reverse proxy
- backup script for the database
- staging server and production server
- GitHub Actions deployment instead of cron polling

## 18. Recommended next step

Follow this guide once on the Kali server.

After that, I can help you with the next step:
- create HTTPS
- connect a domain
- add backups
- make production deployment safer

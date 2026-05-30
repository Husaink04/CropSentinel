# CropSentinel GitHub Guide for Beginners

This guide explains:
- how to create a GitHub repository
- which files to upload
- which files not to upload
- how to create branches
- how to push your code
- how to update your server from GitHub

This is written in simple language.

## 1. What GitHub is

GitHub is an online place where your code lives.

You will use it to:
- keep your project safe
- track changes
- go back if something breaks
- push new code to your server

## 2. What you need before starting

You need:
- a GitHub account
- Git installed on your laptop
- your CropSentinel project folder on your laptop

## 3. Create a new GitHub repository

### Step 1: log in to GitHub

Open:

[https://github.com](https://github.com)

Sign in to your account.

### Step 2: create the repo

Click:
- `+` at the top right
- `New repository`

### Step 3: fill the form

Use something like:
- Repository name: `CropSentinel`
- Description: `Context-aware endpoint monitoring and data protection platform`
- Visibility:
  - choose `Private` if this is your product code
  - choose `Public` only if you want everyone to see the code

Important:
- do not add `README`
- do not add `.gitignore`
- do not add a license

Why:
- your local project already has these files
- starting empty avoids conflicts

Then click:
- `Create repository`

## 4. Which files should go to GitHub

Upload the source code and project files.

These should go:
- `frontend/`
- `backend/`
- `agent/`
- `docs/`
- `tools/`
- `.github/`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- `.gitignore`

## 5. Which files should NOT go to GitHub

Do not upload:
- `.env`
- passwords
- API keys
- private keys
- database files
- build output
- big video files
- local test files
- installer output files unless you really want to version them

This project already has a `.gitignore` file.

That file helps Git skip unsafe and unnecessary files like:
- `.env`
- `node_modules`
- Python cache files
- videos
- secret folders

## 6. Check your project before upload

Open PowerShell in your project folder:

```powershell
cd C:\Users\husai\OneDrive\Desktop\CropSentinel
git status
```

If Git is not started yet, run:

```powershell
git init
```

## 7. Connect your local project to GitHub

After creating the empty repo on GitHub, GitHub will show commands.

You can use these commands in PowerShell:

```powershell
cd C:\Users\husai\OneDrive\Desktop\CropSentinel
git init
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/CropSentinel.git
```

Replace:
- `YOUR_USERNAME` with your GitHub username

## 8. First upload to GitHub

Run:

```powershell
git add .
git commit -m "Initial project upload"
git push -u origin main
```

What this does:
- `git add .` = prepares your files
- `git commit` = saves a checkpoint
- `git push` = uploads to GitHub

If Git asks for login:
- sign in with your GitHub account
- or use GitHub Desktop if you find browser login easier

## 9. Best branch setup

Use this simple branch system:

- `main`
  - stable code
  - production or server should use this

- feature branches
  - for new work
  - example names:
    - `feature/dlp-upgrade`
    - `feature/ui-fixes`
    - `feature/live-view-fix`

- fix branches
  - for bugs
  - example names:
    - `fix/notification-isolation`
    - `fix/login-error-message`

This is enough for a small team or solo work.

## 10. How to create a new branch

Before starting new work:

```powershell
git checkout main
git pull origin main
git checkout -b feature/my-new-work
```

Example:

```powershell
git checkout -b feature/team-dashboard
```

Now your new work stays separate from `main`.

## 11. Daily workflow

Use this simple process every time:

### Step 1: get latest code

```powershell
git checkout main
git pull origin main
```

### Step 2: create a branch

```powershell
git checkout -b feature/my-change
```

### Step 3: make your code changes

Edit your files.

### Step 4: check what changed

```powershell
git status
```

### Step 5: save your work

```powershell
git add .
git commit -m "Describe what changed"
```

Example:

```powershell
git commit -m "Fix tenant notification isolation"
```

### Step 6: upload branch to GitHub

```powershell
git push -u origin feature/my-change
```

## 12. How to merge into main

There are 2 simple ways.

### Easy way for beginners: GitHub website

After pushing your branch:
- open your GitHub repo
- GitHub may show `Compare & pull request`
- click it
- create the pull request
- review the changes
- click `Merge`

Then update local main:

```powershell
git checkout main
git pull origin main
```

### Simple local way

Only do this if you are working alone and understand the change:

```powershell
git checkout main
git merge feature/my-change
git push origin main
```

## 13. Good commit message examples

Use short, clear messages.

Good examples:
- `Fix login validation message`
- `Add enterprise DLP policy APIs`
- `Improve platform light theme`
- `Add Kali deployment guide`

Avoid vague messages like:
- `update`
- `fix stuff`
- `changes`

## 14. How to see which files will be uploaded

Run:

```powershell
git status
```

If you want to see ignored files too:

```powershell
git status --ignored
```

This helps confirm:
- `.env` is not being uploaded
- secret files are not being uploaded

## 15. If you accidentally added a secret file

Example: you added `.env`

Run:

```powershell
git rm --cached .env
```

Then commit again:

```powershell
git commit -m "Remove .env from git tracking"
```

Important:
- if a secret was already pushed to GitHub, change that password/key immediately

## 16. If Git says remote already exists

Run:

```powershell
git remote -v
```

If the old URL is wrong, fix it:

```powershell
git remote set-url origin https://github.com/YOUR_USERNAME/CropSentinel.git
```

## 17. If Git says there are conflicts

This means:
- Git found overlapping changes

Simple beginner-safe steps:

```powershell
git status
```

Then stop and review before pushing.

If you want, I can help you solve conflicts step by step when that happens.

## 18. Recommended setup for your project

For CropSentinel, use:

- GitHub repo: `Private`
- default branch: `main`
- server deployment branch: `main`
- all new work: separate `feature/...` or `fix/...` branch

This works well with your auto-update server plan because:
- your server can watch `main`
- only approved code goes into `main`

## 19. Very simple branch naming rules

Use these patterns:

- new feature:
  - `feature/name`

- bug fix:
  - `fix/name`

- docs:
  - `docs/name`

Examples:
- `feature/team-monitoring`
- `fix/live-view-websocket`
- `docs/server-setup`

## 20. Suggested first-time setup commands

If you are starting from zero in this project:

```powershell
cd C:\Users\husai\OneDrive\Desktop\CropSentinel
git init
git branch -M main
git add .
git commit -m "Initial project upload"
git remote add origin https://github.com/YOUR_USERNAME/CropSentinel.git
git push -u origin main
```

## 21. After this, your normal workflow is only this

For each new task:

```powershell
git checkout main
git pull origin main
git checkout -b feature/my-task
```

After finishing:

```powershell
git add .
git commit -m "Describe the work"
git push -u origin feature/my-task
```

Then merge into `main`.

## 22. Final advice

Keep it simple:
- one private repo
- one stable branch called `main`
- one new branch per task
- never upload `.env`
- never work directly on the server

Make code changes on your laptop, push to GitHub, and let the server update from GitHub.

## 23. Recommended next step

Do these in order:

1. Create the private GitHub repo.
2. Push this project to `main`.
3. Create one test branch.
4. Follow the Kali deployment guide.
5. Connect the server to GitHub auto-update.

If you want, I can now give you:
- the exact commands for your Windows laptop
- the exact commands for your Kali server
- or help you create the GitHub repo step by step

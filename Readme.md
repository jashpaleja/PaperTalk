# AI Paper to NotebookLM Podcast Automator

An automated, zero-server workflow that scrapes the latest AI research papers from ArXiv, sends them to a Telegram bot for personal validation, and automatically converts approved papers into audio podcasts using Google's NotebookLM.

Built entirely on GitHub Actions to keep server costs at exactly $0.00.

## 🚀 Features

* **Zero-Server Architecture:** Utilizes Telegram's 24-hour offline queue and GitHub Actions cron jobs to eliminate the need for a 24/7 web server.
* **Duplicate Prevention:** Uses Git Scraping (`sent_papers.txt`) to remember previously sent papers, ensuring you never review the same paper twice.
* **Fire-and-Forget Generation:** Triggers NotebookLM podcast generation instantly and provides a direct web link, avoiding long-polling timeouts and saving GitHub compute minutes.
* **Native API Integration:** Uses Python's `notebooklm-py` and ArXiv's direct PDF links to bypass local downloading constraints.

## 🏗️ How It Works

This project is split into two lightweight, independent jobs:

1. **Morning Job (`fetch_and_notify.py`):** Runs once a day. Queries ArXiv for the newest `cs.AI` papers, checks them against the local history file, and pushes an interactive Telegram message with **Approve/Reject** buttons. It then automatically commits the updated history file back to the repository.
2. **Processing Job (`process_approvals.py`):** Runs three times a day. Wakes up, checks Telegram's offline queue for your button clicks, and processes your decision. If approved, it creates a new notebook in NotebookLM, attaches the paper, starts the podcast generation, and sends you a direct listening link.

## 📋 Prerequisites

Before pushing this code to GitHub, you need to gather three secret keys:

1. **TELEGRAM_BOT_TOKEN:** Create a new bot via [@BotFather](https://t.me/botfather) on Telegram.
2. **TELEGRAM_CHAT_ID:** Your personal (or group) Chat ID where the bot will send messages.
3. **NOTEBOOKLM_SESSION:** A `storage_state.json` file containing your Google authentication cookies.

## ⚙️ Setup Instructions

### Step 1: Get the Google Session State
Because Google does not have an official API, this tool uses browser automation. You must log in locally once to generate an authentication file.

1. Ensure you have Python 3.11 installed locally.
2. Run the following commands in your local terminal:
   ```bash
   pip install "notebooklm-py[browser]" --prefer-binary
   playwright install chromium
   notebooklm login
   ```
   The above steps will save a storage_state.json file in your local computer copy and paste that in secrets.NOTEBOOKLM_SESSION.

### Step 2: Create a Telegram Bot
1. Checkout a youtube tutorial: https://www.youtube.com/watch?v=UQrcOj63S2o. You should get the TELEGRAM_BOT_TOKEN.
2. You can go the bot you have created and enter /start. It will return you the TELEGRAM_CHAT_ID add that to the secrets.
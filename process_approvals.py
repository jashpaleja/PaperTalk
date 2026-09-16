import os
import time
import json
import datetime
import arxiv
import requests
import telebot
import asyncio
from notebooklm import NotebookLMClient

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = "paper_database.json"

class Paper:
    def __init__(self, title, pdf_url=None, source=None, local_file=None):
        self.title = title
        self.pdf_url = pdf_url
        self.source = source
        self.local_file = local_file

def load_db():
    if not os.path.exists(DB_FILE):
        return {"sent_papers": [], "pending_queue": {}, "date": str(datetime.date.today()), "daily_count": 0}
    with open(DB_FILE, "r") as f:
        db = json.load(f)
        
    # Auto-migrate old list format to new dictionary format
    if "approved_papers" in db:
        db["pending_queue"] = {}
        for item in db["approved_papers"]:
            db["pending_queue"][item] = {"type": "api", "attempts": 0, "last_attempt_date": ""}
        del db["approved_papers"]
        
    if "pending_queue" not in db:
        db["pending_queue"] = {}
        
    return db

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

async def build_podcast(paper):
    bot.send_message(CHAT_ID, f"⏳ Uploading '{paper.title}' to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print(f"Creating Notebook: {paper.title}")
            nb = await client.notebooks.create(paper.title)
            
            if paper.local_file:
                await client.sources.add_file(nb.id, paper.local_file, wait=True)
            elif paper.source == "arxiv" or (paper.pdf_url and "arxiv.org" in paper.pdf_url):
                final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
                await client.sources.add_url(nb.id, final_url, wait=True)
            else:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                pdf_response = requests.get(paper.pdf_url, headers=headers, stream=True)
                pdf_response.raise_for_status()
                
                local_filename = f"temp_{int(time.time())}.pdf"
                with open(local_filename, "wb") as f:
                    for chunk in pdf_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                await client.sources.add_file(nb.id, local_filename, wait=True)
                os.remove(local_filename)
            
            print("Triggering Podcast Generation...")
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await client.artifacts.generate_audio(nb.id)
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    if "rate limit" in error_str or "resource exhausted" in error_str or "429" in error_str:
                        if attempt < max_retries - 1:
                            wait_time = 60 * (attempt + 1)
                            bot.send_message(CHAT_ID, f"⚠️ Google requested a cooldown. Waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            # If it fails 3 times, return a specific global rate limit error
                            return "rate_limit"
                    else:
                        # Re-raise standard errors (like bad PDFs) to hit the main except block
                        raise e
            
            notebook_url = f"https://notebooklm.google.com/notebook/{nb.id}"
            message = (
                f"✅ Podcast Generation Started!\n\n"
                f"Title: {paper.title}\n\n"
                f"Google is building the audio in the background.\n\n"
                f"Link: {notebook_url}"
            )
            bot.send_message(CHAT_ID, message)
            return "success"
            
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {str(e)}")
        return "error"

def process_queue():
    db = load_db()
    today_str = str(datetime.date.today())
    
    if db.get("date") != today_str:
        db["date"] = today_str
        db["daily_count"] = 0
        save_db(db)
        
    updates = bot.get_updates()
    last_update_id = 0
    
    # 1. READ TELEGRAM QUEUE & INGEST INTO DATABASE
    if updates:
        for update in updates:
            last_update_id = update.update_id
            
            if update.callback_query:
                data = update.callback_query.data
                if data.startswith("approve_"):
                    job_id = data.replace("approve_", "")
                    if job_id not in db["pending_queue"]:
                        db["pending_queue"][job_id] = {"type": "api", "attempts": 0, "last_attempt_date": ""}
                        
            elif update.message:
                if update.message.document and update.message.document.mime_type == 'application/pdf':
                    job_id = f"pdf_{update.message.document.file_id}"
                    if job_id not in db["pending_queue"]:
                        db["pending_queue"][job_id] = {
                            "type": "pdf", 
                            "file_id": update.message.document.file_id,
                            "title": update.message.document.file_name or "Uploaded_Document.pdf",
                            "attempts": 0, 
                            "last_attempt_date": ""
                        }
                elif update.message.text and update.message.text.startswith('http'):
                    url = update.message.text.strip()
                    raw_name = url.split('/')[-1].split('?')[0]
                    title = f"Shared Link: {raw_name}" if len(raw_name) > 3 else "Shared Web Link"
                    job_id = f"link_{int(time.time())}"
                    db["pending_queue"][job_id] = {
                        "type": "link", "url": url, "title": title,
                        "attempts": 0, "last_attempt_date": ""
                    }

        bot.get_updates(offset=last_update_id + 1)
        save_db(db)

    # 2. PROCESS THE QUEUE
    # We iterate over a copy of keys so we can safely delete items from the actual dict
    for job_id in list(db["pending_queue"].keys()):
        job_data = db["pending_queue"][job_id]
        
        if db["daily_count"] >= 3:
            print("⚠️ Daily limit (3) reached. Halting pipeline for today.")
            break
            
        # Ensure we only try a paper once per day
        if job_data["last_attempt_date"] == today_str:
            print(f"Skipping {job_id} - already attempted today.")
            continue
            
        print(f"\nProcessing from Queue -> {job_id}")
        paper_obj = None
        
        try:
            # Reconstruct the Paper object based on its type
            if job_data["type"] == "api":
                source, paper_id = job_id.split("_", 1)
                if source == "openalex":
                    response = requests.get(f"https://api.openalex.org/works/{paper_id}")
                    response.raise_for_status()
                    data = response.json()
                    paper_obj = Paper(title=f"AI Paper: {data['title']}", pdf_url=data['open_access']['oa_url'], source=source)
                elif source == "arxiv":
                    search = arxiv.Search(id_list=[paper_id])
                    paper_data = next(arxiv.Client().results(search))
                    paper_obj = Paper(title=f"AI Paper: {paper_data.title}", pdf_url=paper_data.pdf_url, source=source)
                    
            elif job_data["type"] == "pdf":
                file_info = bot.get_file(job_data["file_id"])
                downloaded_file = bot.download_file(file_info.file_path)
                local_path = f"telegram_{job_data['file_id']}.pdf"
                with open(local_path, 'wb') as new_file:
                    new_file.write(downloaded_file)
                paper_obj = Paper(title=job_data["title"], local_file=local_path)
                
            elif job_data["type"] == "link":
                paper_obj = Paper(title=job_data["title"], pdf_url=job_data["url"], source='telegram_link')
                
            if paper_obj:
                status = asyncio.run(build_podcast(paper_obj))
                
                if paper_obj.local_file and os.path.exists(paper_obj.local_file):
                    os.remove(paper_obj.local_file)
                
                # Analyze the result
                if status == "success":
                    del db["pending_queue"][job_id]
                    db["daily_count"] += 1
                    save_db(db)
                    print("Cooling down for 60 seconds...")
                    time.sleep(60) 
                    
                elif status == "rate_limit":
                    print("Global rate limit hit. Halting pipeline.")
                    bot.send_message(CHAT_ID, "⚠️ Google NotebookLM rate limit reached. Pausing all processing until tomorrow.")
                    job_data["last_attempt_date"] = today_str
                    save_db(db)
                    break # Halt the entire pipeline loop
                    
                elif status == "error":
                    job_data["attempts"] += 1
                    job_data["last_attempt_date"] = today_str
                    
                    if job_data["attempts"] >= 5:
                        bot.send_message(CHAT_ID, f"❌ Gave up on '{paper_obj.title}' after 5 days of errors. Removing from queue.")
                        del db["pending_queue"][job_id]
                    
                    save_db(db)
                    
        except Exception as e:
            bot.send_message(CHAT_ID, f"❌ Pipeline Data Error for {job_id}: {e}")
            
    print("\nProcessing complete. Shutting down!")

if __name__ == "__main__":
    process_queue()
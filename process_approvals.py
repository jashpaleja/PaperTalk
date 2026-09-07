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
        return {"sent_papers": [], "approved_papers": [], "date": str(datetime.date.today()), "daily_count": 0}
    with open(DB_FILE, "r") as f:
        return json.load(f)

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
                await client.sources.add_file(nb.id, paper.local_file)
            elif paper.source == "arxiv" or (paper.pdf_url and "arxiv.org" in paper.pdf_url):
                final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
                await client.sources.add_url(nb.id, final_url)
            else:
                headers = {"User-Agent": "Mozilla/5.0"}
                pdf_response = requests.get(paper.pdf_url, headers=headers, stream=True)
                pdf_response.raise_for_status()
                
                local_filename = f"temp_{int(time.time())}.pdf"
                with open(local_filename, "wb") as f:
                    for chunk in pdf_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                await client.sources.add_file(nb.id, local_filename)
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
                            raise Exception("Google permanently rate-limited this request.")
                    else:
                        raise e
            
            notebook_url = f"https://notebooklm.google.com/notebook/{nb.id}"
            message = (
                f"✅ Podcast Generation Started!\n\n"
                f"Title: {paper.title}\n\n"
                f"Google is building the audio in the background.\n\n"
                f"Link: {notebook_url}"
            )
            bot.send_message(CHAT_ID, message)
            return True # Return True ONLY on total success
            
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {str(e)}")
        return False

def process_queue():
    db = load_db()
    today_str = str(datetime.date.today())
    
    # Reset daily limit if it's a new day
    if db.get("date") != today_str:
        db["date"] = today_str
        db["daily_count"] = 0
        save_db(db)
        
    updates = bot.get_updates()
    last_update_id = 0
    custom_jobs = []
    
    # 1. READ TELEGRAM QUEUE
    if updates:
        for update in updates:
            last_update_id = update.update_id
            
            # Button clicks go permanently into the JSON queue
            if update.callback_query:
                data = update.callback_query.data
                if data.startswith("approve_"):
                    # Store as "source_paperid" (e.g., "openalex_W12345")
                    source_and_id = data.replace("approve_", "")
                    if source_and_id not in db["approved_papers"]:
                        db["approved_papers"].append(source_and_id)
                        
            # Direct messages get processed immediately in the current run
            elif update.message:
                if update.message.document and update.message.document.mime_type == 'application/pdf':
                    custom_jobs.append({
                        'type': 'pdf', 'file_id': update.message.document.file_id,
                        'title': update.message.document.file_name or "Uploaded_Document.pdf"
                    })
                elif update.message.text and update.message.text.startswith('http'):
                    url = update.message.text.strip()
                    raw_name = url.split('/')[-1].split('?')[0]
                    title = f"Shared Link: {raw_name}" if len(raw_name) > 3 else "Shared Web Link"
                    custom_jobs.append({'type': 'link', 'url': url, 'title': title})

        # Advance the Telegram Queue pointer so we don't read these messages again
        bot.get_updates(offset=last_update_id + 1)
        save_db(db)

    # 2. PROCESS CUSTOM JOBS (Manual PDF Uploads & Links)
    for job in custom_jobs:
        if db["daily_count"] >= 3:
            bot.send_message(CHAT_ID, "⚠️ Daily limit (3) reached. Custom files/links are not queued. Please try again tomorrow!")
            break
            
        try:
            if job['type'] == 'pdf':
                file_info = bot.get_file(job['file_id'])
                downloaded_file = bot.download_file(file_info.file_path)
                local_path = f"telegram_{job['file_id']}.pdf"
                with open(local_path, 'wb') as new_file:
                    new_file.write(downloaded_file)
                
                paper_obj = Paper(title=job['title'], local_file=local_path)
                success = asyncio.run(build_podcast(paper_obj))
                os.remove(local_path)
                
            elif job['type'] == 'link':
                paper_obj = Paper(title=job['title'], pdf_url=job['url'], source='telegram_link')
                success = asyncio.run(build_podcast(paper_obj))
                
            if success:
                db["daily_count"] += 1
                save_db(db)
            print("Cooling down for 60 seconds...")
            time.sleep(60)
            
        except Exception as e:
            bot.send_message(CHAT_ID, f"❌ Failed to process custom message: {e}")

    # 3. PROCESS THE JSON DATABASE QUEUE (Automated Approvals)
    # We use list(db["approved_papers"]) to iterate safely over a copy while modifying the original
    for queued_item in list(db["approved_papers"]):
        if db["daily_count"] >= 3:
            bot.send_message(CHAT_ID, "⚠️ Daily NotebookLM limit (3) reached. Remaining approved papers are saved in the queue for tomorrow!")
            break
            
        source, approved_paper_id = queued_item.split("_", 1)
        print(f"\nProcessing from Queue -> Source: {source}, ID: {approved_paper_id}")
        paper_obj = None
        
        try:
            if source == "openalex":
                api_url = f"https://api.openalex.org/works/{approved_paper_id}"
                response = requests.get(api_url)
                response.raise_for_status()
                data = response.json()
                paper_obj = Paper(title=f"AI Paper: {data['title']}", pdf_url=data['open_access']['oa_url'], source=source)
                
            elif source == "arxiv":
                client = arxiv.Client()
                search = arxiv.Search(id_list=[approved_paper_id])
                paper_data = next(client.results(search))
                paper_obj = Paper(title=f"AI Paper: {paper_data.title}", pdf_url=paper_data.pdf_url, source=source)
                
            if paper_obj:
                success = asyncio.run(build_podcast(paper_obj))
                
                # ONLY delete from the queue if Google successfully started generating!
                if success:
                    db["approved_papers"].remove(queued_item)
                    db["daily_count"] += 1
                    save_db(db)
                    
                print("Cooling down for 60 seconds...")
                time.sleep(60) 
                
        except Exception as e:
            bot.send_message(CHAT_ID, f"❌ Failed to fetch paper data for {queued_item}: {e}")

    print("\nProcessing complete. Shutting down!")

if __name__ == "__main__":
    process_queue()
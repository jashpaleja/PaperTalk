import os
import time
import arxiv
import requests
import telebot
import asyncio
from notebooklm import NotebookLMClient

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)

class Paper:
    # Added local_file to support Telegram PDF downloads
    def __init__(self, title, pdf_url=None, source=None, local_file=None):
        self.title = title
        self.pdf_url = pdf_url
        self.source = source
        self.local_file = local_file

async def build_podcast(paper):
    # bot.send_message(CHAT_ID, f"⏳ Uploading '{paper.title}' to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print(f"Creating Notebook: {paper.title}")
            nb = await client.notebooks.create(paper.title)
            
            # SCENARIO 1: We already downloaded the PDF from Telegram
            if paper.local_file:
                print("Uploading pre-downloaded Telegram file...")
                await client.sources.add_file(nb.id, paper.local_file)
                
            # SCENARIO 2: It's an ArXiv link (fast Google fetch)
            elif paper.source == "arxiv" or (paper.pdf_url and "arxiv.org" in paper.pdf_url):
                print("Uploading ArXiv PDF link directly to NotebookLM...")
                final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
                await client.sources.add_url(nb.id, final_url)
                
            # SCENARIO 3: It's a Publisher link or custom URL
            else:
                print(f"Downloading PDF locally from URL ({paper.pdf_url})...")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
                pdf_response = requests.get(paper.pdf_url, headers=headers, stream=True)
                pdf_response.raise_for_status()
                
                local_filename = f"temp_{int(time.time())}.pdf"
                with open(local_filename, "wb") as f:
                    for chunk in pdf_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print("Uploading local PDF to NotebookLM...")
                await client.sources.add_file(nb.id, local_filename)
                os.remove(local_filename)
            
            print("Triggering Podcast Generation...")
            await client.artifacts.generate_audio(nb.id)
            
            notebook_url = f"https://notebooklm.google.com/notebook/{nb.id}"
            message = (
                f"✅ **Podcast Generation Started!**\n\n"
                f"**Title:** {paper.title}\n\n"
                f"Google is building the audio in the background. It will be ready in about 10-15 minutes.\n\n"
                f"[Click here to listen on NotebookLM]({notebook_url})"
            )
            bot.send_message(CHAT_ID, message)
            
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {str(e)}")

def process_queue():
    print("Checking Telegram's queue...")
    updates = bot.get_updates()
    
    if not updates:
        print("No buttons clicked or messages sent. Exiting.")
        return
        
    last_update_id = 0
    approved_papers = {}
    custom_jobs = []
    
    for update in updates:
        last_update_id = update.update_id
        
        # 1. Look for Button Clicks
        if update.callback_query:
            data = update.callback_query.data
            if data.startswith("approve_openalex_"):
                paper_id = data.replace("approve_openalex_", "")
                approved_papers[paper_id] = "openalex"
            elif data.startswith("approve_arxiv_"):
                paper_id = data.replace("approve_arxiv_", "")
                approved_papers[paper_id] = "arxiv"
                
        # 2. Look for Direct Messages (PDFs or URLs)
        elif update.message:
            # Did the user upload a PDF?
            if update.message.document and update.message.document.mime_type == 'application/pdf':
                custom_jobs.append({
                    'type': 'pdf',
                    'file_id': update.message.document.file_id,
                    'title': update.message.document.file_name or "Uploaded_Document.pdf"
                })
            # Did the user paste a link?
            elif update.message.text and update.message.text.startswith('http'):
                url = update.message.text.strip()
                # Parse the end of the URL for a clean title
                raw_name = url.split('/')[-1].split('?')[0]
                title = f"Shared Link: {raw_name}" if len(raw_name) > 3 else "Shared Web Link"
                custom_jobs.append({
                    'type': 'link',
                    'url': url,
                    'title': f'LINK_{title}'
                })

    # --- PROCESS AUTOMATED API APPROVALS ---
    if approved_papers:
        print(f"Found {len(approved_papers)} automated approvals to process!")
        for approved_paper_id, source in approved_papers.items():
            print(f"\nProcessing -> Source: {source}, ID: {approved_paper_id}")
            paper_obj = None
            try:
                if source == "openalex":
                    api_url = f"https://api.openalex.org/works/{approved_paper_id}"
                    response = requests.get(api_url)
                    response.raise_for_status()
                    data = response.json()
                    # Added "AI Paper: " prefix specifically for the automated ones
                    paper_obj = Paper(title=f"AI Paper: {data['title']}", pdf_url=data['open_access']['oa_url'], source=source)
                    
                elif source == "arxiv":
                    client = arxiv.Client()
                    search = arxiv.Search(id_list=[approved_paper_id])
                    paper_data = next(client.results(search))
                    paper_obj = Paper(title=f"AI Paper: {paper_data.title}", pdf_url=paper_data.pdf_url, source=source)
                    
                if paper_obj:
                    asyncio.run(build_podcast(paper_obj))
                    time.sleep(2) 
                    
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ Failed to route API paper: {e}")

    # --- PROCESS CUSTOM DIRECT UPLOADS/LINKS ---
    if custom_jobs:
        print(f"\nFound {len(custom_jobs)} direct messages to process!")
        for job in custom_jobs:
            try:
                if job['type'] == 'pdf':
                    print(f"Downloading custom PDF from Telegram: {job['title']}")
                    # Download the PDF from Telegram's servers
                    file_info = bot.get_file(job['file_id'])
                    downloaded_file = bot.download_file(file_info.file_path)
                    
                    local_path = f"telegram_{job['file_id']}.pdf"
                    with open(local_path, 'wb') as new_file:
                        new_file.write(downloaded_file)
                    
                    paper_obj = Paper(title=job['title'], local_file=local_path)
                    asyncio.run(build_podcast(paper_obj))
                    
                    # Clean up the file from GitHub Actions runner
                    os.remove(local_path)
                    
                elif job['type'] == 'link':
                    print(f"Processing custom link: {job['title']}")
                    paper_obj = Paper(title=job['title'], pdf_url=job['url'], source='telegram_link')
                    asyncio.run(build_podcast(paper_obj))
                    
                time.sleep(2)
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ Failed to process custom message '{job['title']}': {e}")

    # Advance the Telegram Queue pointer so we don't process these again
    bot.get_updates(offset=last_update_id + 1)
    print("\nQueue cleared. Shutting down!")

if __name__ == "__main__":
    process_queue()
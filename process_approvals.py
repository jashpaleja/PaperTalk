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
    def __init__(self, title, pdf_url, source):
        self.title = title
        self.pdf_url = pdf_url
        self.source = source

async def build_podcast(paper):
    # bot.send_message(CHAT_ID, f"Approval received! Sending '{paper.title}' to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print("Creating Notebook...")
            nb = await client.notebooks.create(f"AI Paper: {paper.title}")
            
            if paper.source == "arxiv":
                print("Uploading ArXiv PDF link directly to NotebookLM...")
                final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
                await client.sources.add_url(nb.id, final_url)
            else:
                print(f"Downloading Publisher PDF locally ({paper.pdf_url})...")
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
                }
                
                pdf_response = requests.get(paper.pdf_url, headers=headers, stream=True)
                pdf_response.raise_for_status()
                
                local_filename = f"temp_{paper.source}.pdf"
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
                f"**Paper:** {paper.title}\n\n"
                f"Google is building the audio in the background. It will be ready in about 10-15 minutes.\n\n"
                f"[Click here to listen on NotebookLM]({notebook_url})"
            )
            bot.send_message(CHAT_ID, message, parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {str(e)}")

def process_queue():
    print("Checking Telegram's queue...")
    updates = bot.get_updates()
    
    if not updates:
        print("No buttons clicked. Exiting.")
        return
        
    last_update_id = 0
    approved_papers = {}
    
    for update in updates:
        last_update_id = update.update_id
        if update.callback_query:
            data = update.callback_query.data
            
            if data.startswith("approve_openalex_"):
                paper_id = data.replace("approve_openalex_", "")
                approved_papers[paper_id] = "openalex"
            elif data.startswith("approve_arxiv_"):
                paper_id = data.replace("approve_arxiv_", "")
                approved_papers[paper_id] = "arxiv"
            elif data.startswith("approve_ss_"):
                bot.send_message(CHAT_ID, "⚠️ Semantic Scholar is no longer supported. Please approve a newer OpenAlex or ArXiv paper.")

    if not approved_papers:
         print("No valid approvals found in the queue.")
    else:
        print(f"Found {len(approved_papers)} approved papers to process!")
        
        for approved_paper_id, source in approved_papers.items():
            print(f"\nProcessing -> Source: {source}, ID: {approved_paper_id}")
            paper_obj = None
            
            try:
                if source == "openalex":
                    api_url = f"https://api.openalex.org/works/{approved_paper_id}"
                    response = requests.get(api_url)
                    response.raise_for_status()
                    data = response.json()
                    paper_obj = Paper(title=data['title'], pdf_url=data['open_access']['oa_url'], source=source)
                    
                elif source == "arxiv":
                    client = arxiv.Client()
                    search = arxiv.Search(id_list=[approved_paper_id])
                    paper_data = next(client.results(search))
                    paper_obj = Paper(title=paper_data.title, pdf_url=paper_data.pdf_url, source=source)
                    
                if paper_obj:
                    asyncio.run(build_podcast(paper_obj))
                    time.sleep(2) 
                    
            except Exception as e:
                error_msg = f"❌ Failed to route paper {approved_paper_id} from {source}: {e}"
                print(error_msg)
                bot.send_message(CHAT_ID, error_msg)

    bot.get_updates(offset=last_update_id + 1)
    print("\nQueue cleared. Shutting down!")

if __name__ == "__main__":
    process_queue()
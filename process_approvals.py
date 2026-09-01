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

# UPDATE 1: Added 'source' to the class so the podcast builder knows where it came from
class Paper:
    def __init__(self, title, pdf_url, source):
        self.title = title
        self.pdf_url = pdf_url
        self.source = source

async def build_podcast(paper):
    bot.send_message(CHAT_ID, f"Approval received! Sending '{paper.title}' to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print("Creating Notebook...")
            nb = await client.notebooks.create(f"AI Paper: {paper.title}")
            
            # UPDATE 2: Branching logic for URL vs Local Upload
            if paper.source == "arxiv":
                print("Uploading ArXiv PDF link directly to NotebookLM...")
                final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
                await client.sources.add_url(nb.id, final_url)
            else:
                print(f"Downloading Publisher PDF locally ({paper.pdf_url})...")
                # Use a standard browser User-Agent so publishers don't block the download
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
                }
                
                # Fetch the PDF bytes
                pdf_response = requests.get(paper.pdf_url, headers=headers, stream=True)
                pdf_response.raise_for_status()
                
                # Save it temporarily to the GitHub runner
                local_filename = f"temp_{paper.source}.pdf"
                with open(local_filename, "wb") as f:
                    for chunk in pdf_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print("Uploading local PDF to NotebookLM...")
                # The python API uses add_file for physical files
                await client.sources.add_file(nb.id, local_filename)
                
                # Clean up the file so we don't bloat the server
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
            
            if data.startswith("approve_ss_"):
                paper_id = data.replace("approve_ss_", "")
                approved_papers[paper_id] = "ss"
            elif data.startswith("approve_openalex_"):
                paper_id = data.replace("approve_openalex_", "")
                approved_papers[paper_id] = "openalex"
            elif data.startswith("approve_arxiv_"):
                paper_id = data.replace("approve_arxiv_", "")
                approved_papers[paper_id] = "arxiv"

    if not approved_papers:
         print("No approvals found in the queue (only rejections or ignores).")
    else:
        print(f"Found {len(approved_papers)} approved papers to process!")
        
        for approved_paper_id, source in approved_papers.items():
            print(f"\nProcessing -> Source: {source}, ID: {approved_paper_id}")
            paper_obj = None
            
            try:
                if source == "ss":
                    headers = {}
                    ss_api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
                    if ss_api_key:
                        headers['x-api-key'] = ss_api_key
                        
                    api_url = f"https://api.semanticscholar.org/graph/v1/paper/{approved_paper_id}"
                    response = requests.get(api_url, params={"fields": "title,openAccessPdf"}, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    # UPDATE 3: Passing the source to the Paper object
                    paper_obj = Paper(title=data['title'], pdf_url=data['openAccessPdf']['url'], source=source)
                    
                elif source == "openalex":
                    api_url = f"https://api.openalex.org/works/{approved_paper_id}"
                    response = requests.get(api_url)
                    response.raise_for_status()
                    data = response.json()
                    # UPDATE 3: Passing the source to the Paper object
                    paper_obj = Paper(title=data['title'], pdf_url=data['open_access']['oa_url'], source=source)
                    
                elif source == "arxiv":
                    client = arxiv.Client()
                    search = arxiv.Search(id_list=[approved_paper_id])
                    paper_data = next(client.results(search))
                    # UPDATE 3: Passing the source to the Paper object
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
import os
import arxiv
import requests
import telebot
import asyncio
from notebooklm import NotebookLMClient

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)

class Paper:
    def __init__(self, title, pdf_url):
        self.title = title
        self.pdf_url = pdf_url

async def build_podcast(paper):
    bot.send_message(CHAT_ID, f"Approval received! Sending '{paper.title}' to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print("Creating Notebook...")
            nb = await client.notebooks.create(f"AI Paper: {paper.title}")
            
            print("Uploading PDF to NotebookLM...")
            # NotebookLM expects a URL ending in .pdf
            final_url = paper.pdf_url if paper.pdf_url.endswith('.pdf') else f"{paper.pdf_url}.pdf"
            await client.sources.add_url(nb.id, final_url, wait=True)
            
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
    approved_paper_id = None
    source = None
    
    for update in updates:
        last_update_id = update.update_id
        if update.callback_query:
            data = update.callback_query.data
            if data.startswith("approve_ss_"):
                source = "ss"
                approved_paper_id = data.replace("approve_ss_", "")
            elif data.startswith("approve_openalex_"):
                source = "openalex"
                approved_paper_id = data.replace("approve_openalex_", "")
            elif data.startswith("approve_arxiv_"):
                source = "arxiv"
                approved_paper_id = data.replace("approve_arxiv_", "")
            elif data.startswith("reject_"):
                approved_paper_id = None
                source = None

    if approved_paper_id and source:
        print(f"Approval found. Source: {source}, ID: {approved_paper_id}")
        paper_obj = None
        
        # Route 1: Semantic Scholar
        if source == "ss":
            headers = {}
            ss_api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
            if ss_api_key:
                headers['x-api-key'] = ss_api_key
                
            api_url = f"https://api.semanticscholar.org/graph/v1/paper/{approved_paper_id}"
            response = requests.get(api_url, params={"fields": "title,openAccessPdf"}, headers=headers)
            data = response.json()
            paper_obj = Paper(title=data['title'], pdf_url=data['openAccessPdf']['url'])
            
        # Route 2: OpenAlex
        elif source == "openalex":
            api_url = f"https://api.openalex.org/works/{approved_paper_id}"
            response = requests.get(api_url)
            data = response.json()
            paper_obj = Paper(title=data['title'], pdf_url=data['open_access']['oa_url'])
            
        # Route 3: ArXiv
        elif source == "arxiv":
            client = arxiv.Client()
            search = arxiv.Search(id_list=[approved_paper_id])
            paper_data = next(client.results(search))
            paper_obj = Paper(title=paper_data.title, pdf_url=paper_data.pdf_url)
            
        if paper_obj:
            asyncio.run(build_podcast(paper_obj))
            
    else:
        bot.send_message(CHAT_ID, "Paper was rejected or ignored today. Skipping.")
        
    bot.get_updates(offset=last_update_id + 1)
    print("Queue cleared. Shutting down!")

if __name__ == "__main__":
    process_queue()
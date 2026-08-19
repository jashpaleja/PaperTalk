import os
import arxiv
import telebot
import asyncio
from notebooklm import NotebookLMClient

# Pull secrets from GitHub Actions environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)

async def build_podcast(paper):
    bot.send_message(CHAT_ID, "Approval received! Generating podcast in NotebookLM...")
    try:
        # Use the native Python API instead of terminal commands
        async with await NotebookLMClient.from_storage() as client:
            print("Creating Notebook...")
            nb = await client.notebooks.create(f"AI Paper: {paper.title}")
            
            print("Uploading PDF to NotebookLM...")
            # We append .pdf to the ArXiv URL so Google's servers fetch it natively!
            # Example: https://arxiv.org/pdf/1234.56789v1.pdf
            await client.sources.add_url(nb.id, f"{paper.pdf_url}.pdf", wait=True)
            
            print("Generating Podcast (this takes a few minutes)...")
            status = await client.artifacts.generate_audio(nb.id)
            
            # Wait for Google to finish generating the audio
            await client.artifacts.wait_for_completion(nb.id, status.task_id)
            
            bot.send_message(CHAT_ID, f"✅ Podcast successfully generated for: {paper.title}")
            
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {str(e)}")

def process_queue():
    print("Checking Telegram's 24-hour queue for button clicks...")
    updates = bot.get_updates()
    
    if not updates:
        print("No buttons clicked since the last run. Exiting.")
        return
        
    last_update_id = 0
    approved_paper_id = None
    
    for update in updates:
        last_update_id = update.update_id
        if update.callback_query:
            data = update.callback_query.data
            if data.startswith("approve_"):
                approved_paper_id = data.replace("approve_", "")
            elif data.startswith("reject_"):
                approved_paper_id = None 

    if approved_paper_id:
        print(f"Approval found for ArXiv ID: {approved_paper_id}")
        client = arxiv.Client()
        search = arxiv.Search(id_list=[approved_paper_id])
        paper = next(client.results(search))
        
        # Run the robust async Python process
        asyncio.run(build_podcast(paper))
            
    else:
        bot.send_message(CHAT_ID, "Paper was rejected or ignored today. Skipping.")
        
    # Clear the queue so we don't process it again
    bot.get_updates(offset=last_update_id + 1)
    print("Telegram queue cleared. Shutting down!")
    
if __name__ == "__main__":
    process_queue()
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
    bot.send_message(CHAT_ID, "Approval received! Sending to NotebookLM...")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print("Creating Notebook...")
            nb = await client.notebooks.create(f"AI Paper: {paper.title}")
            
            print("Uploading PDF to NotebookLM...")
            await client.sources.add_url(nb.id, f"{paper.pdf_url}.pdf", wait=True)
            
            print("Triggering Podcast Generation...")
            # We trigger the audio generation, but we DO NOT wait for it.
            await client.artifacts.generate_audio(nb.id)
            
            # Construct the direct URL to your new notebook
            notebook_url = f"https://notebooklm.google.com/notebook/{nb.id}"
            
            message = (
                f"✅ **Podcast Generation Started!**\n\n"
                f"**Paper:** {paper.title}\n\n"
                f"Google is building the audio in the background. It will be ready in about 10-15 minutes.\n\n"
                f"[Click here to listen on NotebookLM]({notebook_url})"
            )
            
            # Send the instant link and shut down!
            bot.send_message(CHAT_ID, message, parse_mode="Markdown")
            
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
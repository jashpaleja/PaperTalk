import os
import arxiv
import subprocess
import telebot

# Pull secrets from GitHub Actions environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)

def process_queue():
    print("Checking Telegram's 24-hour queue for button clicks...")
    
    # Fetch all offline messages and button clicks that happened since the last run
    updates = bot.get_updates()
    
    if not updates:
        print("No buttons clicked since the last run. Exiting.")
        return
        
    last_update_id = 0
    approved_paper_id = None
    
    # Loop through the events to find the most recent button you clicked
    for update in updates:
        last_update_id = update.update_id
        
        if update.callback_query:
            data = update.callback_query.data
            
            # If you clicked approve, then changed your mind and clicked reject, 
            # this loop ensures it respects your final choice.
            if data.startswith("approve_"):
                approved_paper_id = data.replace("approve_", "")
            elif data.startswith("reject_"):
                approved_paper_id = None 

    if approved_paper_id:
        print(f"Approval found for ArXiv ID: {approved_paper_id}")
        bot.send_message(CHAT_ID, "Approval received! Generating podcast in NotebookLM...")
        
        # Look up the specific paper you approved using the ID passed via the button
        client = arxiv.Client()
        search = arxiv.Search(id_list=[approved_paper_id])
        paper = next(client.results(search))
        
        try:
            # NEW: Download the PDF locally to the GitHub server first
            print("Downloading PDF from ArXiv...")
            paper.download_pdf(filename="paper.pdf")
            
            # 1. Create a new notebook
            print("Creating Notebook...")
            subprocess.run(["notebooklm", "create", f"AI Paper: {paper.title}"], check=True)
            
            # 2. Upload the local physical file instead of the URL
            print("Uploading PDF to NotebookLM...")
            subprocess.run(["notebooklm", "source", "add", "paper.pdf"], check=True)
            
            # 3. Generate the audio podcast and wait for it to finish
            print("Generating Podcast (this takes a few minutes)...")
            subprocess.run(["notebooklm", "generate", "audio", "--wait"], check=True)
            
            bot.send_message(CHAT_ID, f"✅ Podcast successfully generated for: {paper.title}")
        except subprocess.CalledProcessError as e:
            bot.send_message(CHAT_ID, f"❌ NotebookLM Error: {e}")
            
    else:
        bot.send_message(CHAT_ID, "Paper was rejected or ignored today. Skipping.")
        
    # CRITICAL STEP: Passing the offset tells Telegram we have successfully 
    # processed these updates. Telegram will now delete them from the queue 
    # so we don't accidentally process the same paper again tomorrow.
    bot.get_updates(offset=last_update_id + 1)
    print("Telegram queue cleared. Shutting down!")
    
if __name__ == "__main__":
    process_queue()
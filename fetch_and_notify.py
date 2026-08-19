import os
import arxiv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Pull secrets from GitHub Actions environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)

def fetch_and_send():
    print("Fetching the latest AI paper from ArXiv...")
    
    # Query ArXiv for the newest submission in the Computer Science AI category
    client = arxiv.Client()
    search = arxiv.Search(
        query="cat:cs.AI",
        max_results=1,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    paper = next(client.results(search))
    
    # Extract the ArXiv ID to pass to the processing script later
    arxiv_id = paper.get_short_id()
    
    # Create Telegram inline buttons
    markup = InlineKeyboardMarkup()
    
    # We embed the arxiv_id directly into the button's callback data.
    # This allows the second script to know exactly which paper to process 
    # without needing a database to store the state.
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{arxiv_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{arxiv_id}")
    )
    
    message_text = (
        f"📄 **New AI Paper Review**\n\n"
        f"**Title:** {paper.title}\n"
        f"**Authors:** {', '.join([a.name for a in paper.authors[:3]])}\n"
        f"**Link:** {paper.pdf_url}\n\n"
        f"Approve this before the processing job runs to generate a NotebookLM podcast."
    )
    
    # Send the message to your Telegram app
    bot.send_message(CHAT_ID, message_text, reply_markup=markup, parse_mode="Markdown")
    print(f"Sent paper {arxiv_id} to Telegram. Shutting down!")

if __name__ == "__main__":
    fetch_and_send()
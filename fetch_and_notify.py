import os
import arxiv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)
STATE_FILE = "sent_papers.txt"

def get_sent_papers():
    # If the file doesn't exist yet, return an empty set
    if not os.path.exists(STATE_FILE):
        return set()
    # Read the file and get all previously sent IDs
    with open(STATE_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_sent_paper(paper_id):
    # Append the new ID to the text file
    with open(STATE_FILE, "a") as f:
        f.write(f"{paper_id}\n")

def fetch_and_send():
    print("Fetching recent AI papers from ArXiv...")
    sent_papers = get_sent_papers()
    
    client = arxiv.Client()
    search = arxiv.Search(
        query="cat:cs.AI",
        max_results=15, # Grab the last 15 to guarantee we find a new one
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    
    new_paper = None
    for paper in client.results(search):
        arxiv_id = paper.get_short_id()
        # Check if we have already sent this one
        if arxiv_id not in sent_papers:
            new_paper = paper
            break
            
    if not new_paper:
        print("No new papers published today. Shutting down!")
        return

    arxiv_id = new_paper.get_short_id()
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{arxiv_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{arxiv_id}")
    )
    
    message_text = (
        f"📄 **New AI Paper Review**\n\n"
        f"**Title:** {new_paper.title}\n"
        f"**Authors:** {', '.join([a.name for a in new_paper.authors[:3]])}\n"
        f"**Link:** {new_paper.pdf_url}\n\n"
        f"Approve this before the processing job runs to generate a NotebookLM podcast."
    )
    
    bot.send_message(CHAT_ID, message_text, reply_markup=markup, parse_mode="Markdown")
    print(f"Sent paper {arxiv_id} to Telegram.")
    
    # Save the new ID to our text file so we skip it tomorrow
    save_sent_paper(arxiv_id)

if __name__ == "__main__":
    fetch_and_send()
import os
import arxiv
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

bot = telebot.TeleBot(BOT_TOKEN)
STATE_FILE = "sent_papers.txt"

def get_sent_papers():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_sent_paper(paper_id):
    with open(STATE_FILE, "a") as f:
        f.write(f"{paper_id}\n")

def fetch_semantic_scholar(sent_papers):
    print("Checking Semantic Scholar for peer-reviewed papers...")
    api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": "artificial intelligence OR machine learning",
        "publicationTypes": "JournalArticle,Conference",
        "openAccessPdf": "true",
        "fields": "paperId,title,authors,openAccessPdf,venue,year",
        "year": "2026",
        "limit": 15
    }
    
    try:
        response = requests.get(api_url, params=params)
        papers = response.json().get('data', [])
        
        for p in papers:
            if p['paperId'] not in sent_papers:
                authors = [a['name'] for a in p.get('authors', [])[:3]]
                return {
                    "source": "ss",
                    "id": p['paperId'],
                    "title": p['title'],
                    "authors": ", ".join(authors),
                    "venue": f"{p.get('venue') or 'Peer-Reviewed Venue'} ({p.get('year')})",
                    "pdf_url": p['openAccessPdf']['url']
                }
    except Exception as e:
        print(f"Semantic Scholar API failed: {e}")
    return None

def fetch_arxiv(sent_papers):
    print("Checking ArXiv for recent preprints...")
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query="cat:cs.AI",
            max_results=15,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        
        for p in client.results(search):
            arxiv_id = p.get_short_id()
            if arxiv_id not in sent_papers:
                authors = [a.name for a in p.authors[:3]]
                return {
                    "source": "arxiv",
                    "id": arxiv_id,
                    "title": p.title,
                    "authors": ", ".join(authors),
                    "venue": "ArXiv Preprint",
                    "pdf_url": p.pdf_url
                }
    except Exception as e:
        print(f"ArXiv API failed: {e}")
    return None

def fetch_and_send():
    sent_papers = get_sent_papers()
    
    # Strategy: Try Semantic Scholar first, fallback to ArXiv
    paper_info = fetch_semantic_scholar(sent_papers)
    if not paper_info:
        print("No new peer-reviewed papers. Falling back to ArXiv...")
        paper_info = fetch_arxiv(sent_papers)
        
    if not paper_info:
        print("No new papers found from either source today. Shutting down!")
        return

    # Prefix the callback data so the Night script knows which API to use
    prefix = paper_info['source']
    paper_id = paper_info['id']
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{prefix}_{paper_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_ignore")
    )
    
    message_text = (
        f"📄 **New AI Paper Review**\n\n"
        f"**Title:** {paper_info['title']}\n"
        f"**Authors:** {paper_info['authors']}\n"
        f"**Published In:** {paper_info['venue']}\n"
        f"**Link:** {paper_info['pdf_url']}\n\n"
        f"Approve this to generate a NotebookLM podcast."
    )
    
    bot.send_message(CHAT_ID, message_text, reply_markup=markup, parse_mode="Markdown")
    print(f"Sent paper from {prefix} to Telegram.")
    
    save_sent_paper(paper_id)

if __name__ == "__main__":
    fetch_and_send()
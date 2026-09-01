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

def fetch_openalex(sent_papers):
    print("1. Checking OpenAlex for peer-reviewed papers...")
    api_url = "https://api.openalex.org/works"
    params = {
        "search": "artificial intelligence OR machine learning",
        "filter": "has_fulltext:true,is_oa:true,type:article,publication_year:2026",
        "per-page": "15"
    }
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        papers = response.json().get('results', [])
        
        for p in papers:
            paper_id = p['id'].split('/')[-1] 
            if paper_id not in sent_papers and p.get('open_access', {}).get('oa_url'):
                authors = [a['author']['display_name'] for a in p.get('authorships', [])[:3]]
                venue = "Peer-Reviewed Journal"
                if p.get('primary_location') and p['primary_location'].get('source'):
                    venue = p['primary_location']['source'].get('display_name', venue)
                return {
                    "source": "openalex",
                    "id": paper_id,
                    "title": p['title'],
                    "authors": ", ".join(authors),
                    "venue": venue,
                    "url": p.get('id'),
                    "pdf_url": p['open_access']['oa_url']
                }
    except Exception as e:
        print(f"OpenAlex API failed: {e}")
    return None

def fetch_arxiv(sent_papers):
    print("2. OpenAlex failed. Falling back to ArXiv...")
    try:
        client = arxiv.Client()
        search = arxiv.Search(query="cat:cs.AI", max_results=15, sort_by=arxiv.SortCriterion.SubmittedDate)
        for p in client.results(search):
            arxiv_id = p.get_short_id()
            if arxiv_id not in sent_papers:
                return {
                    "source": "arxiv",
                    "id": arxiv_id,
                    "title": p.title,
                    "authors": ", ".join([a.name for a in p.authors[:3]]),
                    "venue": "ArXiv Preprint",
                    "url": p.entry_id,
                    "pdf_url": p.pdf_url
                }
    except Exception as e:
        print(f"ArXiv API failed: {e}")
    return None

def fetch_and_send():
    sent_papers = get_sent_papers()
    
    
    paper_info = fetch_arxiv(sent_papers)
    if not paper_info:
        paper_info = fetch_openalex(sent_papers)    

    if not paper_info:
        print("No papers found from any source today. Shutting down!")
        return

    prefix = paper_info['source']
    paper_id = paper_info['id']
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{prefix}_{paper_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_ignore")
    )
    
    message_text = (
        f"**Title:** {paper_info['title']}\n"
        f"**Source:** {prefix.upper()}\n"
        f"**Authors:** {paper_info['authors']}\n"
        f"**Published In:** {paper_info['venue']}\n"
        f"**Link:** {paper_info['url']}\n"
        f"**PDF:** {paper_info['pdf_url']}"
    )
    
    bot.send_message(CHAT_ID, message_text, reply_markup=markup, parse_mode="Markdown")
    print(f"Sent {prefix} paper to Telegram.")
    save_sent_paper(paper_id)

if __name__ == "__main__":
    fetch_and_send()
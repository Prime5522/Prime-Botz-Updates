import re
import hashlib
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, TMDB_API
from database.ia_filterdb import save_file
from utils import get_poster, get_status, temp

CAPTION_LANGUAGES = ["Bhojpuri", "Hindi", "Bengali", "Tamil", "English", "Bangla", "Telugu", "Malayalam", "Kannada", "Marathi", "Punjabi", "Bengoli", "Gujrati", "Korean", "Gujarati", "Spanish", "French", "German", "Chinese", "Arabic", "Portuguese", "Russian", "Japanese", "Odia", "Assamese", "Urdu"]

notified_movies = set()
user_reactions = {}
reaction_counts = {}

media_filter = filters.document | filters.video | filters.audio

@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media:
            break
    else:
        return
    media.file_type = file_type
    media.caption = message.caption
    success, result = await save_file(bot, media)
    try:
        if success and result == 1 and await get_status(bot.me.id):
            await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
    except Exception as e:
        print(f"Error In Movie Update - {e}")
        pass

async def send_movie_update(bot, file_name, caption):
    try:
        file_name = await movie_name_format(file_name)
        caption = await movie_name_format(caption)
        year_match = re.search(r"\b(19|20)\d{2}\b", caption)
        year = year_match.group(0) if year_match else None      
        season_match = re.search(r"(?i)(?:s|season)0*(\d{1,2})", caption) or re.search(r"(?i)(?:s|season)0*(\d{1,2})", file_name)
        if year:
            file_name = file_name[:file_name.find(year) + 4]
        elif season_match:
            season = season_match.group(1)
            file_name = file_name[:file_name.find(season) + 1]

        quality = await get_qualities(caption) or "HDRip"
        language = ", ".join([lang for lang in CAPTION_LANGUAGES if lang.lower() in caption.lower()]) or "Not Idea"

        if file_name in notified_movies:
            return 
        notified_movies.add(file_name)

        imdb_data = await get_imdb_details(file_name)
        title = imdb_data.get("title", file_name)
        kind = imdb_data.get("kind", "").strip().upper().replace(" ", "_") if imdb_data else None
        poster = await fetch_movie_poster(title, year)        
        search_movie = file_name.replace(" ", "-")
        unique_id = generate_unique_id(search_movie)

        reaction_counts[unique_id] = {"❤️": 0, "👍": 0, "👎": 0, "🔥": 0}
        user_reactions[unique_id] = {}

        caption_template = "<b>#Added ✅\n\nName: {}\nQuality: {}\nAudio: {}</b>"
        full_caption = caption_template.format(file_name, quality, language)
        if kind:
            full_caption += f"\n<b>#{kind}</b>"

        buttons = [[
            InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_{search_movie}_heart"),                
            InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_{search_movie}_like"),
            InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_{search_movie}_dislike"),
            InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_{search_movie}_fire")
        ],[
            InlineKeyboardButton('Get File', url=f'https://telegram.me/{temp.U_NAME}?start=getfile-{search_movie}')
        ]]

        image_url = poster or "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"
        await bot.send_photo(chat_id=MOVIE_UPDATE_CHANNEL, photo=image_url, caption=full_caption, reply_markup=InlineKeyboardMarkup(buttons))    
    except Exception as e:
        print(f"Error in send_movie_update: {e}")

@Client.on_callback_query(filters.regex(r"^r_"))
async def reaction_handler(client, query):
    try:
        data = query.data.split("_")
        if len(data) != 4:
            return        
        unique_id = data[1]
        search_movie = data[2]
        new_reaction = data[3]
        user_id = query.from_user.id
        emoji_map = {"heart": "❤️", "like": "👍", "dislike": "👎", "fire": "🔥"}

        if new_reaction not in emoji_map:
            return

        new_emoji = emoji_map[new_reaction]       

        if unique_id not in reaction_counts:
            return

        if user_id in user_reactions[unique_id]:
            old_emoji = user_reactions[unique_id][user_id]
            if old_emoji == new_emoji:
                return 
            else:
                reaction_counts[unique_id][old_emoji] -= 1

        user_reactions[unique_id][user_id] = new_emoji
        reaction_counts[unique_id][new_emoji] += 1

        updated_buttons = [[
            InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_{search_movie}_heart"),                
            InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_{search_movie}_like"),
            InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_{search_movie}_dislike"),
            InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_{search_movie}_fire")
        ],[
            InlineKeyboardButton('Get File', url=f'https://telegram.me/{temp.U_NAME}?start=getfile-{search_movie}')
        ]]

        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(updated_buttons))
    except Exception as e:
        print("Reaction error:", e)

async def get_imdb_details(name):
    try:
        formatted_name = await movie_name_format(name)
        imdb = await get_poster(formatted_name)
        if not imdb:
            return {}
        return {
            "title": imdb.get("title", formatted_name),
            "kind": imdb.get("kind", "Movie"),
            "year": imdb.get("year")
        }
    except Exception as e:
        print(f"IMDB fetch error: {e}")
        return {}

async def fetch_movie_poster(title, year=None):
    try:
        params = {"api_key": TMDB_API, "query": title}
        if year:
            params["year"] = year
        res = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
        data = res.json().get("results", [])
        if not data:
            return None
        movie_id = data[0].get("id")
        if not movie_id:
            return None
        img_res = requests.get(f"https://api.themoviedb.org/3/movie/{movie_id}/images?api_key={TMDB_API}", timeout=10)
        backdrops = img_res.json().get("backdrops", [])
        return f"https://image.tmdb.org/t/p/original{backdrops[0]['file_path']}" if backdrops else None
    except Exception as e:
        print(f"Poster fetch error: {e}")
        return None

def generate_unique_id(movie_name):
    return hashlib.md5(movie_name.encode('utf-8')).hexdigest()[:5]

async def get_qualities(text):
    qualities = ["ORG", "HDCAM", "HQ", "HDRip", "CAMRip", "WEB-DL", "HDTC", "HDTS", "DVDScr", "DVDRip"]
    return ", ".join([q for q in qualities if q.lower() in text.lower()])

async def movie_name_format(file_name):
    clean_filename = re.sub(r'http\S+', '', re.sub(r'@\w+|#\w+', '', file_name).replace('_', ' ').replace('[', '').replace(']', '').replace('(', '').replace(')', '').replace('{', '').replace('}', '').replace('.', ' ').replace('@', '').replace(':', '').replace(';', '').replace("'", '').replace('-', '').replace('!', '')).strip()
    return clean_filename
    

import discord
from discord.ext import commands
import hashlib
import time
import sqlite3
import aiohttp
import json
import asyncio
import ssl
import os
from datetime import datetime
from requests.adapters import HTTPAdapter, Retry
import logging

# Setup Logging
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG for more detailed logs
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
# Define Emoji-to-Language Mapping Globally
EMOJI_LANGUAGE_MAP = {
    '🇺🇸': 'EN',  # English
    '🇲🇽': 'ES',  # Spanish
    # Add more mappings as needed, for example:
    # '🇫🇷': 'FR',  # French
    # '🇩🇪': 'DE',  # German
    # '🇯🇵': 'JA',  # Japanese
}

# Configuration Constants
DB_FILE = 'gift_db.sqlite'
SETTINGS_FILE = 'settings.txt'

# Role prefixes for primary roles
ROLE_PREFIXES = {
    1285275744284577852: "[SBZ] ",  # Prefix for SBZ role
    1285278313107165228: "[PuP] ",  # Prefix for PVP role
    1285279147848892509: "[PuP] ",  # Prefix for SIN role
    1285280176850210857: "[WPA] ",  # Prefix for WPA role
    1285279928203481180: "[Wrk] ",  # Prefix for Wrk role
    1285284446928502804: "[WTF] ",  # Prefix for WTF role
    1285286816290836592: "[JaA] ",  # Prefix for JaA role
    1285284966074155048: "[CHL] ",  # Prefix for CHL role
    1299860203965255701: "[T] "     # Prefix for Newbie role
}

# Secondary role prefixes (added after primary prefixes)
SECONDARY_PREFIXES = {
    1264549669627891763: "[R4] ",   # Prefix for R4 role
    1264549766692339814: "[R5] "    # Prefix for R5 role
}

# URLs and Configurations for API calls
wos_player_info_url = "https://wos-giftcode-api.centurygame.com/api/player"
wos_giftcode_url = "https://wos-giftcode-api.centurygame.com/api/gift_code"
wos_encrypt_key = "tB87#kPtkxqOS2"

# Retry configuration for requests
retry_config = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429],
    allowed_methods=["POST"]
)

# Load Settings from File
def load_settings():
    default_settings = {
        'BOT_TOKEN': '',
        'SECRET': 'tB87#kPtkxqOS2',
        'CHANNEL_ID': '',
        'WELCOME_CHANNEL_ID': '',
        'ALLIANCE_NAME': '',
        'DEEPL_API_KEY': ''
    }
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f:
            for key, value in default_settings.items():
                f.write(f"{key}={value}\n")
        print("Settings file created. Please fill in and restart.")
        exit()
    with open(SETTINGS_FILE, 'r') as f:
        return dict(line.strip().split('=') for line in f if '=' in line)

settings = load_settings()
BOT_TOKEN = settings['BOT_TOKEN']
SECRET = settings['SECRET']
CHANNEL_ID = int(settings['CHANNEL_ID'])
WELCOME_CHANNEL_ID = int(settings['WELCOME_CHANNEL_ID'])
ALLIANCE_NAME = settings['ALLIANCE_NAME']
DEEPL_API_KEY = settings['DEEPL_API_KEY']

# Initialize Discord Bot
intents = discord.Intents.default()
intents.message_content, intents.members = True, True
bot = commands.Bot(command_prefix='/', intents=intents)

# Database Context Manager
class Database:
    def __enter__(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.conn.commit()
        self.conn.close()

# Database Initialization
def initialize_db():
    with Database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS users (
                          fid INTEGER PRIMARY KEY,
                          nickname TEXT,
                          furnace_lv INTEGER DEFAULT 0,
                          discord_id INTEGER UNIQUE)''')
        
        db.execute('''CREATE TABLE IF NOT EXISTS gift_code_history (
                          fid INTEGER,
                          giftcode TEXT,
                          redeemed_at TIMESTAMP,
                          PRIMARY KEY(fid, giftcode))''')

initialize_db()

# Prefix Handling Utility
def clean_nickname(nickname):
    prefixes = list(ROLE_PREFIXES.values()) + list(SECONDARY_PREFIXES.values())
    for prefix in prefixes:
        if nickname.startswith(prefix):
            nickname = nickname[len(prefix):].strip()
    return nickname


# Helper to Update Nickname Based on Roles
async def update_member_nickname(member):
    # Clean the existing nickname to remove any prefixes
    base_nickname = clean_nickname(member.nick or member.name)
    
    # Determine the new prefix based on roles
    primary_prefix = next(
        (prefix for role_id, prefix in ROLE_PREFIXES.items() if member.get_role(role_id)),
        ""
    )
    secondary_prefix = next(
        (prefix for role_id, prefix in SECONDARY_PREFIXES.items() if member.get_role(role_id)),
        ""
    )
    
    # Construct the new nickname
    new_nickname = f"{primary_prefix}{secondary_prefix}{base_nickname}"
    
    # Update the member's nickname if it has changed
    if member.nick != new_nickname:
        try:
            await member.edit(nick=new_nickname)
            print(f"Updated nickname for {member.name} to {new_nickname}")
        except discord.Forbidden:
            print(f"Permission denied: Cannot change nickname for {member.name}")
        except discord.HTTPException as e:
            print(f"HTTP Exception while changing nickname for {member.name}: {e}")

# Event Listeners
@bot.event
async def on_member_update(before, after):
    await update_member_nickname(after)

@bot.event
async def on_member_join(member):
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        await welcome_channel.send(f"Welcome, {member.mention}! Please select your alliance and review the guidelines.")

@bot.command(name='update_all_nicknames')
@commands.has_permissions(administrator=True)  # Ensure only admins can run this
async def update_all_nicknames(ctx):
    await ctx.send("Starting to update all member nicknames...")
    for member in ctx.guild.members:
        await update_member_nickname(member)
    await ctx.send("Finished updating all member nicknames.")


# API Request Helpers
import requests

# Helper Functions

DEEPL_SUPPORTED_LANGUAGES = {
    'EN': 'English',
    'ES': 'Spanish',
    'DE': 'German',
    'FR': 'French',
    'IT': 'Italian',
    'NL': 'Dutch',
    'PL': 'Polish',
    'PT': 'Portuguese',
    'RU': 'Russian',
    'ZH': 'Chinese',
    # Add more languages as needed
}

# Helper Functions

def get_language_name(lang_code: str) -> str:
    """
    Returns the full language name for a given language code.

    :param lang_code: The language code (e.g., 'EN', 'ES').
    :return: The full language name or the code itself if not found.
    """
    return DEEPL_SUPPORTED_LANGUAGES.get(lang_code.upper(), lang_code.upper())

async def translate_text(text: str, target_lang: str) -> str:
    """
    Translates the given text into the target language using DeepL API.

    :param text: The text to translate.
    :param target_lang: The target language code (e.g., 'EN', 'ES').
    :return: The translated text or None if an error occurred.
    """
    if not DEEPL_API_KEY:
        logging.error("DEEPL_API_KEY is not set in settings.txt")
        return None

    url = "https://api.deepl.com/v2/translate"
    data = {
        'auth_key': DEEPL_API_KEY,
        'text': text,
        'target_lang': target_lang.upper(),
        'source_lang': 'auto'  # Let DeepL detect the source language
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=data) as response:
                if response.status != 200:
                    logging.error(f"DeepL API error: {response.status} {response.reason}")
                    return None
                result = await response.json()
        except aiohttp.ClientError as e:
            logging.error(f"Client error during translation: {e}")
            return None

    # Extract the translated text
    try:
        translated_text = result['translations'][0]['text']
        return translated_text
    except (KeyError, IndexError):
        logging.error("Unexpected response format from DeepL API.")
        return None

@bot.event
async def on_reaction_add(reaction, user):
    # Prevent the bot from responding to its own reactions
    if user == bot.user:
        return

    # Check if the reaction emoji is one we are tracking
    if str(reaction.emoji) not in EMOJI_LANGUAGE_MAP:
        return  # Ignore other emojis

    target_language = EMOJI_LANGUAGE_MAP[str(reaction.emoji)]

    # Get the message that was reacted to
    message = reaction.message

    # Prevent translating bot messages to avoid loops or unnecessary translations
    if message.author == bot.user:
        return

    # Fetch the message content
    original_text = message.content

    # Prevent empty messages from being translated
    if not original_text.strip():
        try:
            await user.send("❌ The message you're trying to translate is empty.")
        except discord.Forbidden:
            await message.channel.send(
                f"{user.mention}, I couldn't send you a DM. Please enable DMs to receive translations."
            )
        return

    # Translate the message
    translated_text = await translate_text(original_text, target_language)

    if translated_text is None:
        # Translation failed; notify the user
        try:
            await user.send("❌ Failed to translate the message. Please try again later.")
        except discord.Forbidden:
            await message.channel.send(
                f"{user.mention}, I couldn't send you a DM. Please enable DMs to receive translations."
            )
        return

    # Create an embed for better presentation
    embed = discord.Embed(
        title="🔄 Translation",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Original Message", value=original_text, inline=False)
    embed.add_field(
        name=f"Translated ({get_language_name(target_language)})",
        value=translated_text,
        inline=False
    )
    embed.set_footer(
        text=f"Requested by {user}",
        icon_url=user.avatar.url if user.avatar else None
    )

    # Send the translated message to the user via DM
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        # If the user has DMs disabled
        await message.channel.send(
            f"{user.mention}, I couldn't send you a DM. Please enable DMs to receive translations."
        )

    # Optionally, remove the user's reaction to keep the channel clean
    try:
        await reaction.remove(user)
    except discord.Forbidden:
        # If the bot lacks permissions to remove reactions
        pass
    except discord.HTTPException:
        # Failed to remove reaction
        pass

@bot.command(name='languages')
async def list_languages(ctx):
    """Lists all supported language codes and their corresponding languages."""
    embed = discord.Embed(
        title="🌐 Supported Languages",
        description="List of supported language codes and their corresponding languages.",
        color=discord.Color.green()
    )
    languages_per_field = 10
    language_items = list(DEEPL_SUPPORTED_LANGUAGES.items())
    for i in range(0, len(language_items), languages_per_field):
        chunk = language_items[i:i + languages_per_field]
        field_name = ", ".join([code.upper() for code, _ in chunk])
        field_value = ", ".join([language for _, language in chunk])
        embed.add_field(name=field_name, value=field_value, inline=False)

    await ctx.send(embed=embed)


def encode_data(data):
    secret = SECRET
    sorted_keys = sorted(data.keys())
    encoded_data = "&".join(
        [
            f"{key}={json.dumps(data[key]) if isinstance(data[key], dict) else data[key]}"
            for key in sorted_keys
        ]
    )
    sign = hashlib.md5(f"{encoded_data}{secret}".encode()).hexdigest()
    return {"sign": sign, **data}


async def fetch_player_info(session, player_id):
    data = encode_data({"fid": player_id, "time": int(datetime.now().timestamp())})
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "origin": wos_giftcode_url,
    }
    async with session.post(wos_player_info_url, data=data, headers=headers) as response:
        return await response.json()



# Helper function for color assignment based on alliance
def get_alliance_color(alliance):
    color_mapping = {
        "SBZ": discord.Color.yellow(),
        "PVP": discord.Color.orange(),
        "SIN": discord.Color.red(),
        "WPA": discord.Color.green(),
        "Wrk": discord.Color.pink(),
        "WTF": discord.Color.blue(),
        "JaA": discord.Color.magenta(),
        "CHL": discord.Color.purple(),
        "T": discord.Color.light_grey(),
        "None": discord.Color.greyple(),
    }
    return color_mapping.get(alliance.upper().strip(), discord.Color.greyple())

def create_profile_embed(ctx, member, fid, nickname, alliance, rank, furnace_display, avatar_url, color):
    """Creates and returns an embed for the given member's profile with improved formatting."""

    # Add alliance prefix to the nickname, based on ROLE_PREFIXES dictionary
    alliance_prefix = next(
        (prefix.replace("[", "").replace("]", "") for role_id, prefix in ROLE_PREFIXES.items() if member.get_role(role_id)),
        ""
    )
    full_nickname = f"**{nickname}**"

    embed = discord.Embed(
        title=full_nickname,  # Use the alliance-prefixed nickname without "Profile" at the end
        color=color,
        timestamp=datetime.now()
    )
    # Set the person's avatar as the top-right thumbnail
    embed.set_thumbnail(url=avatar_url)

 # Divider for visual separation
    embed.add_field(
        name="\u200B",
        value="— — — — — — — — — — —",
        inline=False
    )

    # Game ID and Furnace Level fields
    embed.add_field(
        name="Game ID",
        value=f"`{fid}`",
        inline=False
    )
    embed.add_field(
        name="Furnace Level",
        value=f"`{furnace_display}`",
        inline=False
    )

    # Divider for visual separation
    embed.add_field(
        name="\u200B",
        value="— — — — — — — — — — —",
        inline=False
    )

    # Alliance and Rank Info
    embed.add_field(
        name="Alliance Info",
        value=f"**Alliance**: `{alliance}` | **Rank**: `{rank}`",
        inline=False
    )

    # Game logo in bottom-left as footer icon
    embed.set_footer(text="WOS State #1454", icon_url="attachment://game_logo.png")

    # Return embed and the game logo file for attachment
    return embed, discord.File("game_logo.png", filename="game_logo.png")

def claim_giftcode_rewards_wos(player_id, giftcode):
    """Handles the gift code redemption request for Whiteout Survival."""
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry_config))

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "origin": wos_giftcode_url,
    }

    # First, fetch player info to establish the session
    data_to_encode = {
        "fid": f"{player_id}",
        "time": f"{int(datetime.now().timestamp())}",
    }
    data = encode_data(data_to_encode)

    response_player_info = session.post(wos_player_info_url, headers=headers, data=data)
    player_info_json = response_player_info.json()

    if player_info_json.get("msg") != "success":
        print(f"Error fetching player info for {player_id}: {player_info_json.get('msg')}")
        return "NOT_LOGIN_FAILED"

    # Now, proceed to redeem the gift code using the same session
    data_to_encode = {
        "fid": f"{player_id}",
        "cdk": giftcode,
        "time": f"{int(datetime.now().timestamp())}",
    }
    data = encode_data(data_to_encode)

    response_giftcode = session.post(wos_giftcode_url, headers=headers, data=data)
    response_json = response_giftcode.json()

    # Process the response as before
    if response_json.get("msg") == "SUCCESS":
        return "SUCCESS"
    elif response_json.get("msg") == "RECEIVED." and response_json.get("err_code") == 40008:
        return "ALREADY_RECEIVED"
    elif response_json.get("msg") == "SAME TYPE EXCHANGE." and response_json.get("err_code") == 40011:
        return "ALREADY_REDEEMED_SIMILAR_CODE"
    elif response_json.get("msg") == "NOT LOGIN":
        print(f"Player {player_id} encountered 'NOT LOGIN' error.")
        return "NOT_LOGIN_FAILED"
    else:
        error_msg = response_json.get("msg", "Unknown error")
        print(f"Error redeeming gift code for {player_id}: {error_msg}")
        return "ERROR"

@bot.command(name='user')
async def user_info(ctx, *, search_term: str):
    try:
        fid = int(search_term)
        search_by = "id"
    except ValueError:
        fid = None
        search_by = "nickname"

    with Database() as db:
        if search_by == "id":
            db.execute("SELECT fid, nickname, discord_id FROM users WHERE fid=?", (fid,))
        else:
            db.execute("SELECT fid, nickname, discord_id FROM users WHERE nickname=?", (search_term,))
        user = db.fetchone()

    if user is None:
        await ctx.send(f"No user found with {search_by} '{search_term}'.")
        return

    fid, nickname, discord_id = user

    # Fetch in-game data
    async with aiohttp.ClientSession() as session:
        player_data = await fetch_player_info(session, fid)

    if not player_data or "data" not in player_data:
        await ctx.send(f"Could not retrieve data for user ID '{fid}' from the game API.")
        return

    player_info = player_data["data"]
    in_game_nickname = player_info.get("nickname", "Unknown")
    furnace_lv = player_info.get("stove_lv", 0)
    avatar_url = player_info.get("avatar_image")  # Ensure the correct key is used

    # Update nickname and furnace level in the database
    with Database() as db:
        db.execute("UPDATE users SET nickname=?, furnace_lv=? WHERE fid=?", (in_game_nickname, furnace_lv, fid))
        db.execute("SELECT discord_id FROM users WHERE fid=?", (fid,))
        row = db.fetchone()
        discord_id = row[0] if row else None

    # Attempt to get the Discord member using the linked discord_id
    target_member = ctx.guild.get_member(discord_id) if discord_id else None

    # Determine alliance and rank from roles if member is found
    if target_member:
        # Fetch primary prefix based on the member's roles
        primary_prefix = next(
            (prefix for role_id, prefix in ROLE_PREFIXES.items() if target_member.get_role(role_id)),
            ""
        )
        # Fetch secondary prefix based on the member's roles
        secondary_prefix = next(
            (prefix for role_id, prefix in SECONDARY_PREFIXES.items() if target_member.get_role(role_id)),
            ""
        )
        alliance = primary_prefix.strip("[] ") if primary_prefix else "None"
        rank = secondary_prefix.strip("[] ") if secondary_prefix else "Member"
        color = get_alliance_color(alliance)
    else:
        alliance = "None"
        rank = "Member"
        color = discord.Color.greyple()
        primary_prefix = ""
        secondary_prefix = ""

    # Clean the in-game nickname to remove any existing prefixes
    cleaned_nickname = clean_nickname(in_game_nickname)

    # Construct full nickname with prefixes
    full_nickname = f"{primary_prefix}{secondary_prefix}{cleaned_nickname}"

    # Handle Furnace Level Display with "FC-"
    if 35 <= furnace_lv <= 39:
        furnace_display = "FC-1"
    elif 40 <= furnace_lv <= 44:
        furnace_display = "FC-2"
    elif furnace_lv >= 45:
        furnace_display = "FC-3"
    else:
        furnace_display = str(furnace_lv)

    # Create the embed with in-game and Discord information
    embed, file = create_profile_embed(
        ctx,
        target_member,
        fid,
        full_nickname,
        alliance,
        rank,
        furnace_display,
        avatar_url,
        color
    )

    # Send the embed along with the game logo file
    await ctx.send(embed=embed, file=file)


# Remove User Command
@bot.command(name='removeuser')
async def remove_user(ctx, fid: int):
    with Database() as db:
        db.execute("DELETE FROM users WHERE fid=?", (fid,))
    await ctx.send(f"User with ID {fid} has been removed from the database.")

@bot.command(name='profile')
async def show_profile(ctx, fid: int = None):
    # If no fid is provided, try to get it from the linked Discord account
    if fid is None:
        discord_id = ctx.author.id
        with Database() as db:
            db.execute("SELECT fid FROM users WHERE discord_id=?", (discord_id,))
            result = db.fetchone()
        if result:
            fid = result[0]
        else:
            await ctx.send("You haven't linked your account yet. Use `/link [in-game ID]` to link your account.")
            return

    # Fetch in-game data from the game API
    async with aiohttp.ClientSession() as session:
        player_data = await fetch_player_info(session, fid)

    if not player_data or "data" not in player_data:
        await ctx.send(f"Could not retrieve data for user ID '{fid}' from the game API.")
        return

    player_info = player_data["data"]
    in_game_nickname = player_info.get("nickname", "Unknown")
    furnace_lv = player_info.get("stove_lv", 0)
    avatar_url = player_info.get("avatar_image")  # Use the correct key

    # Update nickname and furnace level in the database
    with Database() as db:
        db.execute("UPDATE users SET nickname=?, furnace_lv=? WHERE fid=?", (in_game_nickname, furnace_lv, fid))
        db.execute("SELECT discord_id FROM users WHERE fid=?", (fid,))
        row = db.fetchone()
        discord_id = row[0] if row else None

    # Attempt to get the Discord member using the linked discord_id
    target_member = ctx.guild.get_member(discord_id) if discord_id else None

    # Determine alliance and rank from roles if member is found
    if target_member:
        # Fetch primary prefix based on the member's roles
        primary_prefix = next(
            (prefix for role_id, prefix in ROLE_PREFIXES.items() if discord.utils.get(target_member.roles, id=role_id)),
            ""
        )
        # Fetch secondary prefix based on the member's roles
        secondary_prefix = next(
            (prefix for role_id, prefix in SECONDARY_PREFIXES.items() if discord.utils.get(target_member.roles, id=role_id)),
            ""
        )
        color = get_alliance_color(primary_prefix.strip("[] "))
    else:
        primary_prefix = ""
        secondary_prefix = ""
        color = discord.Color.greyple()

    # Clean the in-game nickname to remove any existing prefixes
    cleaned_nickname = clean_nickname(in_game_nickname)

    # Construct full nickname with prefixes
    full_nickname = f"{primary_prefix}{secondary_prefix}{cleaned_nickname}"

    # Handle Furnace Level Display with "FC-"
    if 35 <= furnace_lv <= 39:
        furnace_display = "FC-1"
    elif 40 <= furnace_lv <= 44:
        furnace_display = "FC-2"
    elif furnace_lv >= 45:
        furnace_display = "FC-3"
    else:
        furnace_display = str(furnace_lv)

    # Create the embed with in-game and Discord information
    embed, file = create_profile_embed(
        ctx,
        target_member,
        fid,
        full_nickname,
        primary_prefix.strip("[] ") or "None",
        secondary_prefix.strip("[] ") or "Member",
        furnace_display,
        avatar_url,
        color
    )

    # Send the embed along with the game logo file
    await ctx.send(embed=embed, file=file)

@bot.command(name='giftredeem')
async def use_giftcode(ctx, giftcode: str):
    await ctx.message.delete()
    notify_message = await ctx.send(
        content="Alliance list is being checked for Gift Code usage. The process will be completed in approximately 10 minutes."
    )

    # Fetch all users from the database
    with Database() as db:
        db.execute("SELECT fid, nickname, furnace_lv FROM users")
        users = db.fetchall()

    # Initialize result lists
    success_results = []
    received_results = []
    error_results = []
    similar_code_results = []
    login_errors = []  # Track 'NOT LOGIN' errors

    for user in users:
        fid, nickname, furnace_lv = user
        try:
            # Call the claim_giftcode_rewards_wos function and capture the response status
            response_status = claim_giftcode_rewards_wos(player_id=fid, giftcode=giftcode)

            # Process the response based on its status
            if response_status == "SUCCESS":
                with Database() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO gift_code_history (fid, giftcode, redeemed_at) VALUES (?, ?, ?)",
                        (fid, giftcode, datetime.now().isoformat())
)
                success_results.append(nickname)
            elif response_status == "ALREADY_RECEIVED":
                received_results.append(nickname)
            elif response_status == "ALREADY_REDEEMED_SIMILAR_CODE":
                similar_code_results.append(nickname)
            elif response_status == "NOT_LOGIN_FAILED":
                login_errors.append(nickname)
            else:
                error_results.append(nickname)
        except Exception as e:
            print(f"Exception for {fid} - {nickname}: {e}")
            error_results.append(nickname)

    # Delete the notification message
    await notify_message.delete()

    # Send summaries for each result category as separate embeds
    if success_results:
        success_embed = discord.Embed(
            title=f"{giftcode} Gift Code - Successfully Redeemed",
            description=", ".join(success_results),
            color=discord.Color.green()
        )
        success_embed.set_footer(text="These users have successfully redeemed the gift code.")
        await ctx.send(embed=success_embed)

    if received_results:
        received_embed = discord.Embed(
            title=f"{giftcode} Gift Code - Already Redeemed",
            description=", ".join(received_results),
            color=discord.Color.orange()
        )
        received_embed.set_footer(text="These users have already redeemed this gift code.")
        await ctx.send(embed=received_embed)

    if similar_code_results:
        similar_embed = discord.Embed(
            title=f"{giftcode} Gift Code - Already Redeemed Similar Code",
            description=", ".join(similar_code_results),
            color=discord.Color.yellow()
        )
        similar_embed.set_footer(text="These users have already redeemed a similar type of code.")
        await ctx.send(embed=similar_embed)

    if login_errors:
        login_embed = discord.Embed(
            title=f"{giftcode} Gift Code - Login Required",
            description=", ".join(login_errors),
            color=discord.Color.red()
        )
        login_embed.set_footer(text="These users encountered a login issue during gift code redemption.")
        await ctx.send(embed=login_embed)

    if error_results:
        error_embed = discord.Embed(
            title=f"{giftcode} Gift Code - Errors",
            description=", ".join(error_results),
            color=discord.Color.red()
        )
        error_embed.set_footer(text="Errors occurred for these users during gift code redemption.")
        await ctx.send(embed=error_embed)


@bot.command(name='useradd')
async def add_user(ctx, ids: str):
    added = []
    already_exists = []
    async with aiohttp.ClientSession() as session:
        for fid in ids.split(','):
            fid = fid.strip()
            if not fid:
                already_exists.append(f"{fid} - Empty ID provided")
                continue
            response = await fetch_player_info(session, fid)
            if not response['data']:
                already_exists.append(f"{fid} - No data found")
                continue
            player_info = response['data']
            nickname = player_info.get('nickname', 'Unknown')
            furnace_lv = player_info.get('stove_lv', 0)
            with Database() as db:
                db.execute("SELECT * FROM users WHERE fid=?", (fid,))
                if db.fetchone() is None:
                    db.execute("INSERT INTO users (fid, nickname, furnace_lv) VALUES (?, ?, ?)", (fid, nickname, furnace_lv))
                    added.append(nickname)
                else:
                    already_exists.append(nickname)

    #Embed for useradd
    embed = discord.Embed(title="User Addition Results")
    if added: embed.add_field(name="Added Users", value="\n".join(added), inline=False)
    if already_exists: embed.add_field(name="Already Exists", value="\n".join(already_exists), inline=False)
    await ctx.send(embed=embed)

@bot.command(name='link')
async def link_account(ctx, fid: int):
    discord_id = ctx.author.id
    async with aiohttp.ClientSession() as session:
        player_data = await fetch_player_info(session, fid)
    if not player_data or "data" not in player_data:
        await ctx.send(f"Could not retrieve data for user ID '{fid}' from the game API.")
        return

    player_info = player_data["data"]
    nickname = player_info.get("nickname", "Unknown")
    furnace_lv = player_info.get("stove_lv", 0)

    with Database() as db:
        db.execute("SELECT * FROM users WHERE fid=?", (fid,))
        user = db.fetchone()
        if user:
            # Update the discord_id and nickname in case they have changed
            db.execute("UPDATE users SET discord_id=?, nickname=?, furnace_lv=? WHERE fid=?", (discord_id, nickname, furnace_lv, fid))
            await ctx.send(f"Successfully linked your Discord account to in-game ID {fid}.")
        else:
            # Insert new user
            db.execute("INSERT INTO users (fid, nickname, furnace_lv, discord_id) VALUES (?, ?, ?, ?)", (fid, nickname, furnace_lv, discord_id))
            await ctx.send(f"Successfully linked your Discord account to in-game ID {fid}.")

@bot.command(name='adminlink')
@commands.has_permissions(administrator=True)  # Restricts command to administrators
async def admin_link(ctx, member: discord.Member, fid: int):
    """
    Admin command to link a Discord member to an in-game ID (fid).
    
    Usage:
    /adminlink @Member fid
    """
    # Log the command usage
    logging.info(f"Admin {ctx.author} is attempting to link {member} to fid {fid}.")

    # Fetch in-game data
    async with aiohttp.ClientSession() as session:
        player_data = await fetch_player_info(session, fid)

    # Validate player data
    if not player_data or "data" not in player_data:
        await ctx.send(f"❌ Could not retrieve data for user ID `{fid}` from the game API.")
        logging.error(f"Failed to fetch data for fid {fid}.")
        return

    player_info = player_data["data"]
    in_game_nickname = player_info.get("nickname", "Unknown")
    furnace_lv = player_info.get("stove_lv", 0)
    avatar_url = player_info.get("avatar_image")  # Ensure this key is correct

    # Check if the fid is already linked to another Discord user
    with Database() as db:
        db.execute("SELECT discord_id FROM users WHERE fid=?", (fid,))
        existing_link = db.fetchone()
        if existing_link:
            existing_discord_id = existing_link[0]
            if existing_discord_id is not None and existing_discord_id != member.id:
                existing_member = bot.get_user(existing_discord_id)
                if existing_member:
                    existing_member_mention = existing_member.mention
                else:
                    existing_member_mention = 'another user'
                await ctx.send(f"❌ The in-game ID `{fid}` is already linked to {existing_member_mention}.")
                logging.warning(f"Attempt to link fid {fid} to {member} but it's already linked to {existing_discord_id}.")
                return

        # Check if the Discord member is already linked to another fid
        db.execute("SELECT fid FROM users WHERE discord_id=?", (member.id,))
        existing_fid = db.fetchone()
        if existing_fid:
            existing_fid = existing_fid[0]
            await ctx.send(f"❌ {member.mention} is already linked to in-game ID `{existing_fid}`.")
            logging.warning(f"Attempt to link {member} to fid {fid}, but they are already linked to fid {existing_fid}.")
            return

        # Proceed to link the member
        try:
            db.execute("""
                INSERT INTO users (fid, nickname, furnace_lv, discord_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(fid) DO UPDATE SET
                    nickname=excluded.nickname,
                    furnace_lv=excluded.furnace_lv,
                    discord_id=excluded.discord_id
            """, (fid, in_game_nickname, furnace_lv, member.id))
            logging.info(f"Linked {member} to fid {fid} successfully.")
        except sqlite3.IntegrityError as e:
            await ctx.send(f"❌ Database error: {e}")
            logging.error(f"Database error while linking: {e}")
            return

    # Determine alliance and rank based on roles
    primary_prefix = next(
        (prefix for role_id, prefix in ROLE_PREFIXES.items() if member.get_role(role_id)),
        ""
    )
    secondary_prefix = next(
        (prefix for role_id, prefix in SECONDARY_PREFIXES.items() if member.get_role(role_id)),
        ""
    )
    alliance = primary_prefix.strip("[] ") if primary_prefix else "None"
    rank = secondary_prefix.strip("[] ") if secondary_prefix else "Member"
    color = get_alliance_color(alliance)

    # Clean the in-game nickname to remove any existing prefixes
    cleaned_nickname = clean_nickname(in_game_nickname)

    # Construct full nickname with prefixes
    full_nickname = f"{primary_prefix}{secondary_prefix}{cleaned_nickname}"

    # Handle Furnace Level Display with "FC-"
    if 35 <= furnace_lv <= 39:
        furnace_display = "FC-1"
    elif 40 <= furnace_lv <= 44:
        furnace_display = "FC-2"
    elif furnace_lv >= 45:
        furnace_display = "FC-3"
    else:
        furnace_display = str(furnace_lv)

    # Create the embed with in-game and Discord information
    embed, file = create_profile_embed(
        ctx,
        member,
        fid,
        full_nickname,
        alliance,
        rank,
        furnace_display,
        avatar_url,
        color
    )

    # Send the embed along with the game logo file
    await ctx.send(embed=embed, file=file)

    # Optionally, notify the user via DM
    try:
        await member.send(f"✅ Your Discord account has been linked to in-game ID `{fid}`.")
    except discord.Forbidden:
        logging.warning(f"Could not send DM to {member}. They might have DMs disabled.")

@bot.command(name='adminunlink')
@commands.has_permissions(administrator=True)  # Restricts command to administrators
async def admin_unlink(ctx, member: discord.Member):
    """
    Admin command to unlink a Discord member from their in-game ID (fid).
    
    Usage:
    /adminunlink @Member
    """
    # Log the command usage
    logging.info(f"Admin {ctx.author} is attempting to unlink {member} from their fid.")

    # Check if the member is linked in the database
    with Database() as db:
        db.execute("SELECT fid FROM users WHERE discord_id=?", (member.id,))
        user = db.fetchone()

    if not user:
        await ctx.send(f"❌ {member.mention} is not linked to any in-game ID.")
        logging.warning(f"Attempt to unlink {member} who is not linked to any fid.")
        return

    fid = user[0]

    # Remove the link from the database
    try:
        with Database() as db:
            db.execute("DELETE FROM users WHERE fid=?", (fid,))
            logging.info(f"Unlinked {member} from fid {fid}.")
    except sqlite3.Error as e:
        await ctx.send(f"❌ Database error: {e}")
        logging.error(f"Database error while unlinking: {e}")
        return

    # Optionally, reset the member's nickname to remove prefixes
    base_nickname = clean_nickname(member.nick or member.name)
    try:
        await member.edit(nick=base_nickname)
        logging.info(f"Reset nickname for {member} to {base_nickname}.")
    except discord.Forbidden:
        logging.error(f"Permission denied: Cannot reset nickname for {member}.")
        await ctx.send(f"❌ Failed to reset nickname for {member.mention}. Permission denied.")
        return
    except discord.HTTPException as e:
        logging.error(f"HTTP Exception while resetting nickname for {member}: {e}")
        await ctx.send(f"❌ Failed to reset nickname for {member.mention}.")
        return

    # Inform the admin of the successful unlinking
    await ctx.send(f"✅ Successfully unlinked {member.mention} from in-game ID `{fid}`.")

    # Optionally, notify the user via DM
    try:
        await member.send(f"✅ Your Discord account has been unlinked from in-game ID `{fid}`.")
    except discord.Forbidden:
        logging.warning(f"Could not send DM to {member}. They might have DMs disabled.")

@bot.command(name='viewlist')
async def show_users(ctx):
    with Database() as db:
        db.execute("SELECT fid, nickname, furnace_lv FROM users ORDER BY nickname ASC")
        users = db.fetchall()
    
    user_count = len(users)
    embed_title = f"{ALLIANCE_NAME} Members ({user_count})"
    user_info, part_number = "", 1

    for user in users:
        fid, nickname, furnace_lv = user
        line = f"**{nickname}** | Furnace Level: {furnace_lv} | ID: {fid}\n"
        if len(user_info) + len(line) > 2000:
            await ctx.send(embed=discord.Embed(title=embed_title if part_number == 1 else f"{embed_title} (Part {part_number})", description=user_info, color=discord.Color.blue()))
            user_info, part_number = "", part_number + 1
        user_info += line

    if user_info:
        await ctx.send(embed=discord.Embed(title=embed_title if part_number == 1 else f"{embed_title} (Part {part_number})", description=user_info, color=discord.Color.blue()))

@bot.command(name='giftcodehistory')
async def gift_code_history(ctx, fid: int):
    with Database() as db:
        db.execute("SELECT giftcode, redeemed_at FROM gift_code_history WHERE fid=?", (fid,))
        history = db.fetchall()
    embed = discord.Embed(title=f"Gift Code Redemption History for ID {fid}", color=discord.Color.blue())
    if history:
        for giftcode, redeemed_at in history:
            embed.add_field(name=giftcode, value=f"Redeemed on {redeemed_at.strftime('%Y-%m-%d %H:%M:%S')}", inline=False)
    else:
        embed.description = "No gift codes have been redeemed."
    await ctx.send(embed=embed)


@bot.command(name='sync')
@commands.is_owner()  
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("Commands have been synced.")

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot is online as {bot.user} and commands are synced.")

# Run the bot with the token
bot.run(BOT_TOKEN)

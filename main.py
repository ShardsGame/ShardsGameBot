import os
import math
import time
import boto3
import base58
import random
import asyncio
import logging
import aiomysql
import warnings
import threading
import json
import aiofiles
import datetime
import pymysql.cursors
from dotenv import load_dotenv
from transfer import send_sol, send_sol_e, send_sol_e_r
from balance import get_balance
from spl_balance import get_solana_token_amount
from sendSPL import send_spl
from solders.keypair import Keypair
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext, ContextTypes
from telegram.error import TimedOut, BadRequest

from dbcalls import (
    get_user_id,
    get_wallet_address_by_user_id,
    get_game_wallet,
    generate_wallet_if_needed,
    save_wallet_address_new,
    get_wallet_address,
    get_total_users,
    save_wallet_address,
    decrement_user_credit_balance
)

warnings.simplefilter("ignore")
load_dotenv('.env')
logging.basicConfig(level=logging.ERROR)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DB_NAME = os.getenv('DATABASE_NAME')
DB_HOST = os.getenv('DATABASE_HOST')
DB_USER = os.getenv('DATABASE_USER')
DB_PASSWORD = os.getenv('DATABASE_PASSWORD')
CHANNELID = int(os.getenv('TELEGRAM_CHANNEL_ID'))
bot = Bot(token=TOKEN)

user_last_start_time = {}
START_COMMAND_COOLDOWN = 3
MAX_START_COMMAND_COOLDOWN = 30
user_spam_count = {}
user_notified = {}
filename1 = 'glimmer.mp4'
filename2 = 'radiant.mp4'

GAME_CONFIG = {
    "grid": {"size": 5, "entry_fee": 0.03, "nft_count": 1, "token_count": 5, "token_prize": 25000}
}

CURRENT_GAME_ID = None
TOKEN_ACTIVE = False

TOKEN_PRIZE_OPTIONS = [50000, 25000, 12500, 5000, 5000]

async def load_config():
    try:
        async with aiofiles.open('config.json', 'r') as f:
            content = await f.read()
            config = json.loads(content)
            return config.get('token_active', False)
    except FileNotFoundError:
        config = {'token_active': False}
        async with aiofiles.open('config.json', 'w') as f:
            await f.write(json.dumps(config, indent=2))
        return False

async def get_latest_game_id():
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    try:
        async with pool.acquire() as conn:
            await conn.select_db(DB_NAME)
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT MAX(game_id) FROM game_entries")
                result = await cursor.fetchone()
                return result[0] if result[0] is not None else 1000
    except Exception as e:
        logging.error(f"Error fetching latest game_id: {e}")
        return 1000
    finally:
        pool.close()
        await pool.wait_closed()

async def setup_database():
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
            await cursor.execute(f"USE {DB_NAME}")
            await cursor.execute(f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'%'")
            await cursor.execute("FLUSH PRIVILEGES")
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    user_id BIGINT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    earned DOUBLE DEFAULT 0,
                    referrer_id BIGINT,
                    credit_balance DOUBLE DEFAULT 0,
                    FOREIGN KEY (referrer_id) REFERENCES players(user_id)
                )
            ''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS game_grid (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    wallet_address TEXT NOT NULL,
                    round DOUBLE DEFAULT 0,
                    entries JSON
                )
            ''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS game_entries (
                    game_id BIGINT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    user_wallet TEXT NOT NULL,
                    choice TEXT NOT NULL,
                    grid JSON NOT NULL,
                    reward_success BOOLEAN DEFAULT FALSE,
                    prize_amount DOUBLE DEFAULT 0,
                    prize_type VARCHAR(10),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS affiliate_rewards (
                    referrer_id BIGINT,
                    referral_count INT DEFAULT 0,
                    shard_rewards DOUBLE DEFAULT 0,
                    PRIMARY KEY (referrer_id),
                    FOREIGN KEY (referrer_id) REFERENCES players(user_id)
                )
            ''')
            await asyncio.shield(generate_wallet_if_needed(cursor, "game_grid"))
    pool.close()
    await pool.wait_closed()

async def private_chat_only(update: Update, context: CallbackContext):
    return update.effective_chat.type == 'private'

async def increment_referral_count(referrer_id):
    global TOKEN_ACTIVE
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute(
                '''
                INSERT INTO affiliate_rewards (referrer_id, referral_count)
                VALUES (%s, 1)
                ON DUPLICATE KEY UPDATE referral_count = referral_count + 1
                ''',
                (referrer_id,)
            )
            await cursor.execute("SELECT referral_count FROM affiliate_rewards WHERE referrer_id = %s", (referrer_id,))
            result = await cursor.fetchone()
            referral_count = result[0] if result else 0
            if referral_count % 10 == 0:
                shard_reward = 10000
                if TOKEN_ACTIVE:
                    await cursor.execute(
                        '''
                        UPDATE affiliate_rewards
                        SET shard_rewards = shard_rewards + %s
                        WHERE referrer_id = %s
                        ''',
                        (shard_reward, referrer_id)
                    )
                else:
                    await update_credit_balance(referrer_id, shard_reward)
                await bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 Congrats! You've earned {shard_reward} $SHARD {'tokens' if TOKEN_ACTIVE else 'credits'} for reaching {referral_count} referrals (pre-launch bonus)!"
                )
    pool.close()
    await pool.wait_closed()

async def update_credit_balance(user_id, amount):
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute(
                '''
                UPDATE players
                SET credit_balance = credit_balance + %s
                WHERE user_id = %s
                ''',
                (amount, user_id)
            )
    pool.close()
    await pool.wait_closed()

async def get_referral_info(user_id):
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute(
                "SELECT referral_count, shard_rewards FROM affiliate_rewards WHERE referrer_id = %s",
                (user_id,)
            )
            result = await cursor.fetchone()
            referral_count = result[0] if result else 0
            shard_rewards = result[1] if result else 0
            return referral_count, shard_rewards
    pool.close()
    await pool.wait_closed()

async def get_credit_balance(user_id):
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT credit_balance FROM players WHERE user_id = %s", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0
    pool.close()
    await pool.wait_closed()

async def get_jackpot_balance():
    game_wallet = await get_game_wallet("game_grid")
    return await get_balance(game_wallet)

async def create_start_task(update: Update, context: CallbackContext):
    if not await private_chat_only(update, context):
        return
    user_id = update.effective_user.id
    current_time = time.time()
    if user_id in user_last_start_time and (current_time - user_last_start_time[user_id]) < START_COMMAND_COOLDOWN:
        user_spam_count[user_id] = user_spam_count.get(user_id, 0) + 1
        cooldown_time = min(START_COMMAND_COOLDOWN + (user_spam_count[user_id] * 3), MAX_START_COMMAND_COOLDOWN)
        if user_id not in user_notified:
            user_notified[user_id] = True
            await update.message.reply_text(f"Please wait {cooldown_time} seconds before trying again.")
        return
    else:
        user_spam_count[user_id] = 0
        user_notified[user_id] = False
    user_last_start_time[user_id] = current_time
    asyncio.create_task(start(update, context, user_id))

async def start(update: Update, context: Application, user_id: int = None):
    if not await private_chat_only(update, context):
        return
    user_id = user_id or update.effective_user.id
    await asyncio.sleep(2.5)
    wallet_address = await asyncio.shield(get_wallet_address(user_id))
    referrer_id = context.args[0] if context.args else None
    if wallet_address:
        balance = await asyncio.shield(get_balance(wallet_address))
        balance_formatted = f"{math.floor(balance * 1000) / 1000:.3f}"
        spl_balance = await asyncio.shield(get_solana_token_amount(wallet_address))
        spl_balance_formatted = round(spl_balance)
        credit_balance = await get_credit_balance(user_id)
    else:
        wallet_address = "NEW_WALLET_ADDRESS"
        credit_balance = 0
        await asyncio.shield(save_wallet_address_new(user_id, wallet_address, 0, None, 0, referrer_id, credit_balance))
        balance_formatted = "0.000"
        spl_balance_formatted = "0"
        if referrer_id:
            await increment_referral_count(referrer_id)
    jackpot_balance = await get_jackpot_balance()
    jackpot_formatted = f"{math.floor(jackpot_balance / 2 * 1000) / 1000:.3f}"
    welcome_message = (
        f"💎 *Welcome to SHARDS!* 💎\n\n"
        f"A 5x5 grid of shards with hidden prizes!\n\n"
        f"🎮 *How It Works:*\n"
        f"• Grid Example:\n"
        f"```\n"
        f"    A B C D E\n"
        f"  1 - - - - -\n"
        f"  2 - - - - -\n"
        f"  3 - - - - -\n"
        f"  4 - - - - -\n"
        f"  5 - - - - -\n"
        f"```\n"
        f"• Pay 0.03 SOL to break a shard 💎 (e.g., A1, E5)\n"
        f"• Prizes: 20% chance of Jackpot appearing, 5 Token wins (5k-50k SHARDS), or Nothing\n"
        f"• Current *Jackpot*: {jackpot_formatted} SOL\n\n"
        f"💰 *Your Info:*\n"
        f"• *Sol Balance:* {balance_formatted} Sol\n"
        f"• *Token Balance:* {spl_balance_formatted}\n"
        f"• *Token Credits:* {credit_balance}\n"
        f"• *Wallet:* `{wallet_address}`\n\n"
        f"✨ *Ready to break some shards?*"
    )
    keyboard = await build_grid_keyboard(user_id)
    keyboard.append([InlineKeyboardButton("---", callback_data="noop")])
    keyboard.append([
        InlineKeyboardButton("How to Play?", callback_data='info'),
        InlineKeyboardButton("Wallet", callback_data='wallet')
    ])
    keyboard.append([
        InlineKeyboardButton("Redeem Credits", callback_data='withdraw'),
        InlineKeyboardButton("Referral", callback_data='refer'),
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="markdown")
    elif update.callback_query:
        await context.bot.send_message(chat_id=user_id, text=welcome_message, reply_markup=reply_markup, parse_mode="markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=welcome_message, reply_markup=reply_markup, parse_mode="markdown")

async def create_grid(size, nft_count, token_count):
    grid = [['-' for _ in range(size)] for _ in range(size)]
    positions = [(i, j) for i in range(size) for j in range(size)]
    random.shuffle(positions)
    include_jackpot = random.random() < 0.2
    jackpot_pos = None
    if include_jackpot and nft_count > 0:
        jackpot_pos = positions.pop()
        grid[jackpot_pos[0]][jackpot_pos[1]] = 'N'
    token_positions = positions[:token_count] if len(positions) >= token_count else positions
    for pos in token_positions:
        grid[pos[0]][pos[1]] = 'T'
    return grid, jackpot_pos, token_positions

async def build_grid_keyboard(user_id, grid_state=None, active=True, selected_pos=None):
    config = GAME_CONFIG["grid"]
    keyboard = []
    for i in range(config["size"]):
        row = []
        for j in range(config["size"]):
            if grid_state and grid_state[i][j] != '-':
                emoji = '🎰' if grid_state[i][j] == 'N' else '🪙' if grid_state[i][j] == 'T' else '✖️'
                label = f"({emoji})" if selected_pos and selected_pos == (i, j) else emoji
            else:
                label = "💎" if active else "✖️"
            callback = f"grid_{user_id},{i},{j}" if active else "noop"
            row.append(InlineKeyboardButton(label, callback_data=callback))
        keyboard.append(row)
    return keyboard

async def format_grid_result(grid, user_choice):
    cols = ['A', 'B', 'C', 'D', 'E']
    result = "  A B C D E\n"
    for i in range(len(grid)):
        row = f"{i+1} " + " ".join(
            grid[i][j] if (i, j) == user_choice else 'X' if grid[i][j] == '-' else grid[i][j]
            for j in range(len(grid[0]))
        )
        result += row + "\n"
    return result

async def store_entry(game_id, user_id, user_wallet, choice, grid, reward_success, prize_amount=0, prize_type=None):
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute(
                '''
                INSERT INTO game_entries (game_id, user_id, user_wallet, choice, grid, reward_success, prize_amount, prize_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (game_id, user_id, user_wallet, choice, json.dumps(grid), reward_success, prize_amount, prize_type)
            )
    pool.close()
    await pool.wait_closed()

async def get_entry(game_id):
    pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
    async with pool.acquire() as conn:
        await conn.select_db(DB_NAME)
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM game_entries WHERE game_id = %s", (game_id,))
            result = await cursor.fetchone()
    pool.close()
    await pool.wait_closed()
    return result

async def result(update: Update, context: Application):
    if not await private_chat_only(update, context):
        return
    try:
        game_id = int(context.args[0])
        entry = await get_entry(game_id)
        if not entry:
            await update.message.reply_text(f"No entry found for Game ID {game_id}.")
            return
        game_id, user_id, user_wallet, choice, grid_json, reward_success, prize_amount, prize_type, timestamp = entry
        grid = json.loads(grid_json)
        cols = ['A', 'B', 'C', 'D', 'E']
        grid_display = "   A  B  C  D  E\n"
        for i in range(len(grid)):
            row = f"{i+1} " + " ".join(
                "✖️" if grid[i][j] == '-' else "🪙" if grid[i][j] == 'T' else "🎰" if grid[i][j] == 'N' else grid[i][j]
                for j in range(len(grid[0]))
            )
            grid_display += row + "\n"
        prize_display = f"{prize_amount:.3f} SOL" if prize_type == 'SOL' else f"{int(prize_amount)} SHARDS" if prize_type == 'SHARD' else "None"
        result_message = (
            f"*Game Result - ID {game_id}*\n\n"
            f"• *User ID*: {user_id}\n"
            f"• *Wallet*: `{user_wallet}`\n"
            f"• *Choice*: {choice}\n"
            f"• *Grid*:\n```\n{grid_display}\n```\n"
            f"• *Prize*: {prize_display}\n"
            f"• *Reward Sent*: {'Yes' if reward_success else 'No'}\n"
            f"• *Timestamp*: {timestamp}"
        )
        await update.message.reply_text(result_message, parse_mode="markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /result <game_id> (e.g., /result 1001)")

async def button(update: Update, context: Application):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    async def handle_query():
        global CURRENT_GAME_ID, TOKEN_ACTIVE
        if query.data == 'info':
            await query.edit_message_text(
                f"💎 *SHARDS - How to Play* 💎\n\n"
                f"Break open shards to win prizes on a 5x5 grid!\n\n"
                f"• Grid Example:\n"
                f"```\n"
                f"    A B C D E\n"
                f"  1 - - - - -\n"
                f"  2 - - - - -\n"
                f"  3 - - - - -\n"
                f"  4 - - - - -\n"
                f"  5 - - - - -\n"
                f"```\n"
                f"• Pay 0.03 SOL to break a shard 💎 (e.g., A1, E5)\n"
                f"• Prizes: 20% chance of Jackpot appearing, 5 Token wins (5k-50k SHARDS), or Nothing\n"
                f"• Jackpot winners get 50% of the pool\n\n"
                f"*How the Jackpot Works:*\n"
                f"• 80% of entry fees go to the Jackpot pool (90% if no referral)\n"
                f"• 10% goes to the team\n"
                f"• 10% for referrals (if applicable)\n\n"
                f"*Referrals:*\n"
                f"• Earn 10% of your referrals’ entry fees\n"
                f"• For every 10 referrals, get 10,000 $SHARD tokens (pre-launch only)\n\n"
                f"*Redeem Credits:*\n"
                f"• Post-launch, redeem $SHARD tokens at a 1:1 rate",
                parse_mode='Markdown'
            )
            await start(update, context, user_id=user_id)
        elif query.data == 'noop':
            return
        elif query.data.startswith('grid_'):
            config = GAME_CONFIG["grid"]
            _, coords = query.data.split('_', 1)
            _, row, col = map(int, coords.split(','))
            cols = ['A', 'B', 'C', 'D', 'E']
            choice_label = f"{cols[col]}{row+1}"
            processing_msg = await context.bot.send_message(
                chat_id=user_id,
                text=f"Processing Payment. Please wait..."
            )
            user_wallet = await get_wallet_address(user_id)
            balance = await get_balance(user_wallet)
            if balance < config["entry_fee"]:
                await processing_msg.edit_text("Insufficient SOL balance. Need at least 0.031 SOL.")
                await start(update, context, user_id=user_id)
                return
            game_wallet = await get_game_wallet("game_grid")
            pool = await aiomysql.create_pool(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
            async with pool.acquire() as conn:
                await conn.select_db(DB_NAME)
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT referrer_id FROM players WHERE user_id = %s", (user_id,))
                    result = await cursor.fetchone()
                    referrer_id = result[0] if result else None
                    if referrer_id:
                        referrer_wallet = await get_wallet_address(referrer_id)
                        payment_result = await send_sol_e_r(game_wallet, user_wallet, referrer_wallet, None, config["entry_fee"])
                        if payment_result["success"]:
                            await cursor.execute(
                                "UPDATE players SET earned = earned + %s WHERE user_id = %s",
                                (config["entry_fee"] * 0.1, referrer_id)
                            )
                    else:
                        payment_result = await send_sol_e(game_wallet, user_wallet, None, config["entry_fee"])
            if not payment_result.get("success"):
                await processing_msg.edit_text("Payment failed. Try again.")
                await start(update, context, user_id=user_id)
                return
            await processing_msg.edit_text(f"Breaking shard {choice_label}...")
            processing_msg2 = await context.bot.send_message(
                chat_id=user_id,
                text=f"Checking your prize..."
            )
            session_key = f"grid_{user_id}"
            if session_key not in context.user_data:
                grid, jackpot_pos, token_positions = await create_grid(config["size"], config["nft_count"], config["token_count"])
                context.user_data[session_key] = {
                    'grid': grid,
                    'jackpot_pos': jackpot_pos,
                    'token_positions': token_positions
                }
            grid_data = context.user_data[session_key]
            grid = grid_data['grid']
            jackpot_pos = grid_data['jackpot_pos']
            token_positions = grid_data['token_positions']
            user_choice = (row, col)
            result = grid[row][col]
            reward_success = False
            prize_amount = 0
            prize_type = None
            if result == 'N':
                jackpot_balance = await get_jackpot_balance()
                prize_amount = jackpot_balance * 0.5
                prize_result = await send_sol(user_wallet, game_wallet, None, prize_amount)
                if prize_result["success"]:
                    prize_msg = f"🎉 *You won the Jackpot!* {choice_label}\nPrize: {prize_amount:.3f} SOL\nTX: [View on Solscan](https://solscan.io/tx/{prize_result['result']})"
                    reward_success = True
                    prize_type = 'SOL'
                    group_msg = f"🎉 *Someone won the Jackpot!* {choice_label}\nPrize: {prize_amount:.3f} SOL\nTX: [View on Solscan](https://solscan.io/tx/{prize_result['result']})"
                else:
                    prize_msg = f"🎉 *You won the Jackpot!* {choice_label} (Prize transfer failed, contact support)"
                    reward_success = False
                    group_msg = f"🎉 *Someone won the Jackpot!* {choice_label}\nPrize: {prize_amount:.3f} SOL"
            elif result == 'T':
                prize = random.choice(TOKEN_PRIZE_OPTIONS)
                prize_amount = prize
                if TOKEN_ACTIVE:
                    user_shard_balance = await get_solana_token_amount(user_wallet)
                    if user_shard_balance >= 1:
                        try:
                            prize_result = await send_spl(user_wallet, game_wallet, None, prize)
                            if prize_result["success"]:
                                prize_msg = f"🎉 *You won {prize} SHARDS!* {choice_label}\nTX: [View on Solscan](https://solscan.io/tx/{prize_result['result']})"
                                reward_success = True
                                prize_type = 'SHARD'
                                group_msg = f"🎉 *Someone won {prize} SHARDS!* {choice_label}\nTX: [View on Solscan](https://solscan.io/tx/{prize_result['result']})"
                            else:
                                prize_msg = f"🎉 *You won {prize} SHARDS!* {choice_label} (Transfer failed, contact support)"
                                reward_success = False
                                group_msg = f"🎉 *Someone won {prize} SHARDS!* {choice_label}\n"
                        except Exception as e:
                            logging.error(f"Failed to send SHARDS: {e}")
                            prize_msg = f"🎉 *You won {prize} SHARDS!* {choice_label} (Transfer failed due to token account issue, contact support)"
                            reward_success = False
                            group_msg = f"🎉 *Someone won {prize} SHARDS!* {choice_label}\n"
                    else:
                        prize_msg = f"🎉 *You won {prize} SHARDS!* {choice_label}\nYou need at least 1 SHARD token in your wallet to receive tokens. Credited {prize} SHARDS to your account."
                        await update_credit_balance(user_id, prize)
                        reward_success = True
                        prize_type = 'SHARD'
                        group_msg = f"🎉 *Someone won {prize} SHARDS!* {choice_label}\n"
                else:
                    prize_msg = f"🎉 *You won {prize} SHARDS credits!* {choice_label}"
                    await update_credit_balance(user_id, prize)
                    reward_success = True
                    prize_type = 'SHARD'
                    group_msg = f"🎉 *Someone won {prize} SHARDS!* {choice_label}\n"
            else:
                prize_msg = f"😔 *No prize this time.* {choice_label}"
                grid[row][col] = 'X'
                reward_success = False
            await processing_msg2.edit_text(f"Opening shard {choice_label}...")
            await asyncio.sleep(2)
            game_id = CURRENT_GAME_ID
            CURRENT_GAME_ID += 1
            await store_entry(game_id, user_id, user_wallet, choice_label, grid, reward_success, prize_amount, prize_type)
            keyboard = await build_grid_keyboard(user_id, grid_state=grid, active=False, selected_pos=user_choice)
            await query.edit_message_text(
                f"{prize_msg}\n\nGame ID: {game_id}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            if group_msg:
                video_file = filename2 if "Jackpot" in group_msg else filename1
                try:
                    await bot.send_video(
                        chat_id=CHANNELID,
                        video=open(video_file, 'rb'),
                        caption=group_msg,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Failed to send group video: {e}")
            await context.bot.delete_message(chat_id=user_id, message_id=processing_msg.message_id)
            await context.bot.delete_message(chat_id=user_id, message_id=processing_msg2.message_id)
            context.user_data.pop(session_key, None)
            await start(update, context, user_id=user_id)
        elif query.data == 'refer':
            referral_count, shard_rewards = await get_referral_info(user_id)
            referral_link = f"https://t.me/ShardsGameBot?start={user_id}"
            await query.edit_message_text(
                f"💎 *Your Referral Info* 💎\n\n"
                f"• *Referral Link*: `{referral_link}`\n"
                f"• *Referrals*: {referral_count}\n"
                f"• *Earned $SHARD Rewards*: {shard_rewards}\n\n"
                f"Share your link to earn 10% of your referrals’ entry fees and 10,000 $SHARD tokens for every 10 referrals (pre-launch only)!",
                parse_mode='Markdown'
            )
            await start(update, context, user_id=user_id)
        elif query.data == 'wallet':
            keyboard = [
                [InlineKeyboardButton("Import Wallet", callback_data='import_wallet')],
                [InlineKeyboardButton("Cancel", callback_data='cancel_button')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Wallet options:", reply_markup=reply_markup)
        elif query.data == 'import_wallet':
            keyboard = [
                [InlineKeyboardButton("Yes", callback_data='yes_wallet')],
                [InlineKeyboardButton("No", callback_data='cancel_button')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "*Are you sure you want to update your wallet?*\n\n"
                "Please ensure you have:\n- Backed up your previous wallet.\n- Transferred any SOL and tokens out.\n\n*Note: We do not store wallet data*",
                parse_mode="Markdown"
            )
        elif query.data == 'yes_wallet':
            await query.edit_message_text("Please reply with your wallet address to import your wallet")
            handler = MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                lambda update, context: import_wallet(update, context, user_id, handler)
            )
            context.application.add_handler(handler)
        elif query.data == 'no_wallet' or query.data == 'cancel_button':
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
            await start(update, context, user_id=user_id)
        elif query.data == 'withdraw':
            keyboard = [
                [InlineKeyboardButton("Yes", callback_data='yes_withdraw')],
                [InlineKeyboardButton("No", callback_data='cancel_button')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            public_key = await get_wallet_address(user_id)
            await query.edit_message_text(
                f"This function will redeem your credits to $SHARDS Tokens\n\nWould you like to proceed?",
                reply_markup=reply_markup
            )
        elif query.data == 'yes_withdraw':
            await query.edit_message_text("Checking... Please wait!")
            await initiate_withdraw(update, context, query, user_id)
    asyncio.create_task(handle_query())

async def import_wallet(update: Update, context: Application, user_id: int, handler: MessageHandler):
    if update.message.chat.type != "private" or update.message.from_user.id != user_id:
        return
    wallet_address = update.message.text.strip()
    try:
        await save_wallet_address(user_id, wallet_address=wallet_address, private_key=None)
        await update.message.reply_text(f"Your wallet {wallet_address} has been successfully imported!")
    except ValueError:
        await update.message.reply_text("Invalid wallet address format")
        return
    try:
        await context.bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
    except Exception as e:
        print(f"Failed to delete message: {e}")
    context.application.remove_handler(handler)
    await start(update, context)

async def initiate_withdraw(update, context, query, user_id):
    withdraw_amount = await get_credit_balance(user_id)
    withdraw_float = float(withdraw_amount)
    if withdraw_float <= 999:
        message = (
            f"You do not have enough credits to make a withdrawal. Minimum required: 1000 credits."
        )
        await context.bot.send_message(chat_id=user_id, text=message)
        await start(update, context, user_id=user_id)
        return
    token_active = await load_config()
    if not token_active:
        message = (
            f"The token is not active yet."
        )
        await context.bot.send_message(chat_id=user_id, text=message)
        await start(update, context, user_id=user_id)
        return
    user_wallet = await get_wallet_address_by_user_id(user_id)
    user_shard_balance = await get_solana_token_amount(user_wallet)
    if user_shard_balance < 1:
        message = (
            f"You need at least 1 SHARD token in your wallet to redeem credits to $SHARDS. Your current balance: {user_shard_balance} SHARDS."
        )
        await context.bot.send_message(chat_id=user_id, text=message)
        await start(update, context, user_id=user_id)
        return
    message = (
        f"Withdrawal in progress...\n\n"
        f"Redeeming {withdraw_float} Credits to $SHARDS\n\n"
        f"Please wait :)"
    )
    progress_message = await context.bot.send_message(chat_id=user_id, text=message)
    table = "game_grid"
    wallet = await get_game_wallet(table)
    transfer_spl = await send_spl(user_wallet, wallet, None, withdraw_amount)
    if transfer_spl['success']:
        await decrement_user_credit_balance(user_id, withdraw_amount)
        message = (
            f"Your transaction is successful!\n\n"
            f"Loading start menu"
        )
        await context.bot.send_message(chat_id=user_id, text=message)
    else:
        await context.bot.send_message(chat_id=user_id, text="Withdrawal failed. Please contact support.")
    await start(update, context, user_id=user_id)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", create_start_task))
    application.add_handler(CommandHandler("result", result))
    application.add_handler(CallbackQueryHandler(button))
    threading.Thread(target=async_init, daemon=True).start()
    time.sleep(1)
    application.run_polling()

def async_init():
    async def initialize():
        global CURRENT_GAME_ID, TOKEN_ACTIVE
        await setup_database()
        CURRENT_GAME_ID = await get_latest_game_id() + 1
        TOKEN_ACTIVE = await load_config()
    asyncio.run(initialize())

if __name__ == '__main__':
    main()
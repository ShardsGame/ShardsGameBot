# ShardsBot

ShardsBot is a Telegram bot that offers an engaging Solana-based game where players break virtual shards on a 5x5 grid to win prizes, such as SOL jackpots and $SHARD tokens. Built with Python, the bot integrates with the Solana blockchain for wallet management, token transfers, and game transactions, providing a fun experience with referral rewards and credit redemption features.

## Features

- **Gameplay**: Pay 0.03 SOL to break a shard on a 5x5 grid, revealing hidden prizes:
  - **Jackpot**: 20% chance to appear, awarding 50% of the jackpot pool in SOL.
  - **Tokens**: 5 token wins per grid, ranging from 5,000 to 50,000 $SHARD tokens.
  - **Nothing**: Some shards are empty, adding strategic depth.
- **Wallet Integration**: Link a Solana wallet to manage SOL and $SHARD balances.
- **Referral System**: Earn 10% of referred users’ entry fees and 10,000 $SHARD tokens for every 10 referrals (pre-launch bonus).
- **Credit Redemption**: Convert $SHARD credits to tokens post-launch (requires 1+ $SHARD in wallet, minimum 1,000 credits).
- **Game History**: View past games with the `/result <game_id>` command.
- **Interactive UI**: Inline keyboards guide players through gameplay, wallet options, and referrals.

## How It Works

1. **Start the Bot**: Send `/start` (or `/start <referrer_id>` for referrals) to access the main menu.
2. **Play the Game**: Choose a shard (e.g., A1, E5) to break for 0.03 SOL, revealing a jackpot, tokens, or nothing.
3. **Manage Wallet**: View balances or import a Solana wallet address.
4. **Refer Friends**: Share a referral link to earn rewards.
5. **Redeem Credits**: Convert $SHARD credits to tokens when the token is active.

## Prerequisites

- Python 3.8+
- MySQL database for storing user data, game entries, and referrals
- Solana RPC node (e.g., QuickNode, Alchemy, or public mainnet)
- Telegram bot token from [BotFather](https://t.me/BotFather)
- Media files: `glimmer.mp4` and `radiant.mp4` for group announcements (optional)

## Installation

### Clone the Repository

```bash
git clone https://github.com/yourusername/shardsbot.git
cd shardsbot

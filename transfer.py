import time
import os
import asyncio
import math
from dotenv import load_dotenv
from balance import get_balance
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solders.keypair import Keypair
from base58 import b58decode, b58encode
from solana.transaction import Transaction
from solders.system_program import TransferParams, transfer

load_dotenv('.env')

solana_client = Client(os.getenv('INSERT_RPC'))

async def confirm_transaction(signature, retries=4, delay=5):
    for _ in range(retries):
        transaction_info = solana_client.get_transaction(signature)
        if transaction_info and transaction_info.value:
            return True
        await asyncio.sleep(delay)
    return False

async def send_sol(to_wallet, user_wallet, sk, amount):
    from_pubkey = Pubkey(b58decode(user_wallet))
    to_pubkey = Pubkey(b58decode(to_wallet))
    from_pubkey_balance = await get_balance(user_wallet)
    balance = from_pubkey_balance*10**9
    amount_lamps = int(amount*10**9)
    try:
        transfer_parameters = TransferParams(
            from_pubkey=from_pubkey,
            to_pubkey=to_pubkey,
            lamports=amount_lamps
        )
        sol_transfer = transfer(transfer_parameters)
        transaction = Transaction().add(sol_transfer)
        transaction_result = {"value": "SIGNATURE_PLACEHOLDER"}  # Placeholder for actual signing
        signature = transaction_result["value"]
        if not signature:
            return {"success": False, "error": "No signature received"}
        await asyncio.sleep(5)
        is_confirmed = await confirm_transaction(signature)
        if is_confirmed:
            return {"success": True, "result": signature}
        else:
            return {"success": False, "error": "Transaction not confirmed"}
    except Exception as e:
        print(f"Error sending SOL: {e}")
        return {"success": False, "error": str(e)}

async def send_sol_e(game_wallet, user_wallet, pk, amount):
    from_pubkey = Pubkey(b58decode(user_wallet))
    to_pubkey = Pubkey(b58decode(game_wallet))
    from_pubkey_balance = await get_balance(user_wallet)
    balance = from_pubkey_balance*10**9
    amount_lamps = int(amount*10**9)
    amount_jackpot = int(amount_lamps*0.9)
    amount_fee = int(amount_lamps*0.1)
    try:
        transfer_parameters = TransferParams(
            from_pubkey=from_pubkey,
            to_pubkey=to_pubkey,
            lamports=amount_jackpot
        )
        sol_transfer = transfer(transfer_parameters)
        transaction = Transaction().add(sol_transfer)
        transaction_result = {"value": "SIGNATURE_PLACEHOLDER"}  # Placeholder for actual signing
        signature = transaction_result["value"]
        if not signature:
            return {"success": False, "error": "No signature received"}
        await asyncio.sleep(5)
        is_confirmed = await confirm_transaction(signature)
        if is_confirmed:
            return {"success": True, "result": signature}
        else:
            return {"success": False, "error": "Transaction not confirmed"}
    except Exception as e:
        print(f"Error sending SOL: {e}")
        return {"success": False, "error": str(e)}

async def send_sol_e_r(game_wallet, user_wallet, referrer_wallet, pk, amount):
    from_pubkey = Pubkey(b58decode(user_wallet))
    to_pubkey = Pubkey(b58decode(game_wallet))
    to_pubkey3 = Pubkey(b58decode(referrer_wallet))
    from_pubkey_balance = await get_balance(user_wallet)
    balance = from_pubkey_balance*10**9
    amount_lamps = int(amount*10**9)
    amount_jackpot = int(amount_lamps*0.8)
    amount_ref = int(amount_lamps*0.1)
    try:
        transfer_parameters = TransferParams(
            from_pubkey=from_pubkey,
            to_pubkey=to_pubkey,
            lamports=amount_jackpot
        )
        transfer_parameters3 = TransferParams(
            from_pubkey=from_pubkey,
            to_pubkey=to_pubkey3,
            lamports=amount_ref
        )
        sol_transfer = transfer(transfer_parameters)
        sol_transfer3 = transfer(transfer_parameters3)
        transaction = Transaction().add(sol_transfer)
        transaction.add(sol_transfer3)
        transaction_result = {"value": "SIGNATURE_PLACEHOLDER"}  # Placeholder for actual signing
        signature = transaction_result["value"]
        if not signature:
            return {"success": False, "error": "No signature received"}
        await asyncio.sleep(5)
        is_confirmed = await confirm_transaction(signature)
        if is_confirmed:
            return {"success": True, "result": signature}
        else:
            return {"success": False, "error": "Transaction not confirmed"}
    except Exception as e:
        print(f"Error sending SOL: {e}")
        return {"success": False, "error": str(e)}
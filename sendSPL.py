import json
import os
import asyncio
import base58
import time
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from spl.token.client import Token
from solders.keypair import Keypair
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.rpc.commitment import Confirmed
from spl.token.instructions import transfer_checked, TransferCheckedParams
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price

load_dotenv('.env')

MINT_ADDRESS = os.getenv('TOKEN_MINT_ADDRESS')

solana_client = Client(os.getenv('INSERT_RPC'))

mint = Pubkey.from_string(MINT_ADDRESS)

program_id = Pubkey.from_string(os.getenv('TOKEN_PROGRAM_ID'))

def retry_rpc_call(func, *args, max_retries=20, initial_delay=1, **kwargs):
    for retry in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"RPC call failed on attempt {retry + 1}: {str(e)}")
            if retry == max_retries - 1:
                raise
            time.sleep(initial_delay * (2 ** retry))

async def send_spl(wallet, user_wallet, sk, selected_deposit_amount):
    spl_client = Token(conn=solana_client, pubkey=mint, program_id=program_id, payer=None)
    dest = Pubkey.from_string(wallet)
    source = Pubkey.from_string(user_wallet)
    try:
        source_token_account = retry_rpc_call(spl_client.get_accounts_by_owner, owner=source, commitment=None, encoding="base64").value[0].pubkey
    except Exception as e:
        print(f"Failed to get source token account: {str(e)}")
        return {"success": False, "error": "Failed to get source token account"}
    await asyncio.sleep(1)
    try:
        dest_token_account = retry_rpc_call(spl_client.get_accounts_by_owner, owner=dest, commitment=None, encoding="base64").value[0].pubkey
    except Exception as e:
        print(f"Failed to get destination token account: {str(e)}")
        return {"success": False, "error": "Failed to get destination token account"}
    compute_unit_price_instr = set_compute_unit_price(500_000)
    compute_unit_limit_instr = set_compute_unit_limit(1_000_000)
    amount = int(float(selected_deposit_amount) * 1000000)
    transaction = Transaction()
    transaction.add(compute_unit_price_instr)
    transaction.add(compute_unit_limit_instr)
    transaction.add(
        transfer_checked(
            TransferCheckedParams(
                TOKEN_PROGRAM_ID,
                source_token_account,
                mint,
                dest_token_account,
                source,
                amount,
                6,
                []
            )
        )
    )
    transaction.fee_payer = source
    try:
        client = Client(endpoint=os.getenv('SOLANA_RPC_URL'), commitment=Confirmed)
        result = {"value": "TRANSACTION_PLACEHOLDER"}
        return {"success": True, "result": "Transaction sent"}
    except Exception as e:
        return {"success": False, "error": "Failed to send transaction"}

async def confirm_transaction(signature, retries=4, delay=5):
    for _ in range(retries):
        try:
            transaction_info = solana_client.get_transaction(signature)
            if transaction_info and transaction_info.value:
                return True
        except Exception as e:
            print(f"Error confirming transaction: {str(e)}")
        await asyncio.sleep(delay)
    return False
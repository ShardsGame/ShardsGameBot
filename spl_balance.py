import os
import requests
from dotenv import load_dotenv

load_dotenv('.env')

MINT_ADDRESS = os.getenv('TOKEN_MINT_ADDRESS')

solana_client = os.getenv('INSERT_RPC')

headers = {"accept": "application/json", "content-type": "application/json"}

async def get_solana_token_amount(wallet_address):
    url = solana_client
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": MINT_ADDRESS},
            {"encoding": "jsonParsed"},
        ],
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if "result" in result and "value" in result["result"] and len(result["result"]["value"]) > 0:
            token_amount = result["result"]["value"][0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
            return token_amount
        else:
            return 0.0
    except requests.exceptions.RequestException as e:
        print(f"Error while fetching token balance: {e}")
        return None
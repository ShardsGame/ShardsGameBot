import os
import requests
from dotenv import load_dotenv
load_dotenv('.env')

RPC_URL2 = os.getenv('INSERT_RPC')


async def get_balance(wallet_address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address]
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(RPC_URL2, json=payload, headers=headers)
    if response.ok:
        lamports = response.json()["result"]["value"]
        sol_balance = lamports / 1000000000
        return sol_balance
    else:
        sol_balance = 0
        print("Error:", response.status_code, response.text)
        return sol_balance


